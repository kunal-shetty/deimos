"""
Runs eval tasks against the real Deimos Agent in an isolated sandbox.

Each task gets a fresh temp directory (its "project"), a private HOME-style
settings directory so a developer's ~/.deimos config can't leak in, and
stubbed safety/verification deciders so no network call is needed to decide
whether a command is dangerous or a change needs testing.

The agent works relative to the process working directory, so runs are
serialised behind a lock and chdir into the sandbox.
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
import threading
import time
import traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from evals.checks import RunContext, evaluate
from evals.recording import RecordingUI, Trace, TracingLLM
from evals.scripted_llm import ScriptedLLM
from evals.tasks import SUITE, Task

_RUN_LOCK = threading.Lock()
_IGNORED_DIRS = {".deimos", "__pycache__", ".pytest_cache", ".git"}
_MAX_DIFF_CHARS = 4000
FALLBACK_SYSTEM_PROMPT = "You are Deimos, an autonomous coding agent. Use the tools to complete the task."


def _stub_decider(p: float):
    decider = MagicMock()
    decider.yes_no.return_value = p
    return decider


def _system_prompt() -> str:
    from config import PROMPTS_DIR
    try:
        return (PROMPTS_DIR / "system.txt").read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_SYSTEM_PROMPT


def _snapshot(root: Path) -> dict[str, str]:
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
    return files


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        status = "created" if old is None else "deleted" if new is None else "modified"
        diff = "".join(difflib.unified_diff(
            (old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        ))
        changes.append({"path": path, "status": status, "diff": diff[:_MAX_DIFF_CHARS]})
    return changes


def _clip(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit * 5 // 8] + "\n[... clipped for the trace ...]\n" + text[-limit * 3 // 8:]


def _write_files(root: Path, files: dict[str, str]):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def make_llm(task: Task, mode: str, model: str | None):
    if mode == "scripted":
        return ScriptedLLM(task.script or [], repairs=task.repairs, repeat_last=task.repeat_last)
    from llm.client import LLMClient
    return LLMClient(model=model)


def live_available() -> bool:
    from config import LLM_API_KEY
    return bool(LLM_API_KEY)


def run_task(task: Task, mode: str = "scripted", model: str | None = None, keep_workdir: bool = False) -> dict:
    """Run one task and return a JSON-serialisable result."""
    base = {
        "task_id": task.id, "name": task.name, "category": task.category, "mode": mode,
        "checks": [], "metrics": {}, "trace": [], "tool_calls": [], "changed_files": [],
        "final_text": "", "error": None, "workdir": None,
    }
    if mode == "scripted" and not task.scripted:
        return {**base, "status": "skipped", "error": "live-only task (no script)"}
    if mode == "live" and not live_available():
        return {**base, "status": "skipped", "error": "GROQ_API_KEY is not set"}

    with _RUN_LOCK:
        return _run_locked(task, mode, model, keep_workdir, base)


def _run_locked(task: Task, mode: str, model: str | None, keep_workdir: bool, base: dict) -> dict:
    import agent.core as core
    import agent.instructions as instructions
    import settings as settings_mod
    from agent.checkpoints import CheckpointStore
    from agent.core import Agent
    from agent.hooks import HookRunner
    from agent.permissions import Permissions
    from memory.null import NullMemory
    from tools.registry import ToolRegistry

    original_cwd = os.getcwd()
    sandbox = Path(tempfile.mkdtemp(prefix=f"deimos-eval-{task.id}-"))
    project, home = sandbox / "project", sandbox / "home"
    project.mkdir()
    home.mkdir()
    _write_files(project, task.files)
    initial = _snapshot(project)

    trace = Trace()
    ui = RecordingUI(trace, approve=task.approve)
    tool_calls: list[dict] = []
    result = {**base, "workdir": str(project) if keep_workdir else None}
    started = time.perf_counter()
    inner = None
    final_text = ""
    status, error = "error", None

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(settings_mod, "LOCAL_DIR", home))
            stack.enter_context(patch.object(instructions, "LOCAL_DIR", home))
            stack.enter_context(patch("agent.verify.get_decider", lambda: _stub_decider(1.0)))
            stack.enter_context(patch.object(core.requests, "post", lambda *a, **k: None))
            # Scripted edits land within the same second at the same size, which makes
            # Python reuse a stale .pyc (mtime has 1s resolution). Never write bytecode.
            stack.enter_context(patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}))
            if task.max_iterations:
                stack.enter_context(patch.object(core, "MAX_ITERATIONS", task.max_iterations))
            settings_mod.reload_settings()
            os.chdir(project)

            inner = make_llm(task, mode, model)
            llm = TracingLLM(inner, trace)
            agent = Agent(
                ui=ui, llm=llm, tools=ToolRegistry(), system_prompt=_system_prompt(),
                memory=NullMemory(), plan_mode=False,
                permissions=Permissions(ui, mode=task.permission_mode, decider=_stub_decider(0.0)),
            )
            agent.checkpoints = CheckpointStore(cwd=str(project))
            agent.hooks = HookRunner(ui, cwd=str(project), trust_file=home / "trusted_projects.json")

            real_execute = agent._execute_tool

            def traced_execute(name, inputs, *args, **kwargs):
                t0 = time.perf_counter()
                out = real_execute(name, inputs, *args, **kwargs)
                out_text = str(out)
                ok = not out_text.startswith(("Error", "[exit", "Denied", "User declined"))
                duration = round((time.perf_counter() - t0) * 1000, 1)
                # Checks read the full result; the trace keeps head and tail for display
                tool_calls.append({"name": name, "inputs": inputs, "result": out_text, "ok": ok,
                                   "duration_ms": duration})
                trace.add("tool", name=name, inputs=inputs, ok=ok, duration_ms=duration,
                          result=_clip(out_text))
                return out

            agent._execute_tool = traced_execute

            try:
                agent.handle_input(task.prompt)
                for action in task.after:
                    if action == "undo":
                        agent.undo_last_turn()
                status = "ran"
            except Exception as e:  # the agent crashed: that is a result, not a harness failure
                error = f"{type(e).__name__}: {e}"
                trace.add("crash", message=error, traceback=traceback.format_exc()[-2000:])

            assistant = trace.of("assistant")
            final_text = assistant[-1]["text"] if assistant else ""
            if not final_text:
                final_text = next((e["text"] for e in reversed(trace.of("llm")) if e.get("text")), "")

            ctx = RunContext(
                workdir=project, trace=trace, initial_files=initial, final_text=final_text,
                script_exhausted=bool(getattr(inner, "exhausted", False)), tool_calls=tool_calls,
            )
            checks = [evaluate(c, ctx) for c in task.checks]
            changed = _changed_files(initial, _snapshot(project))
            if status == "ran":
                status = "passed" if all(c.passed for c in checks) else "failed"
            else:
                checks = checks or []
            result.update(checks=[c.to_dict() for c in checks], changed_files=changed)
    except Exception as e:  # harness failure (setup, imports)
        error = f"{type(e).__name__}: {e}"
        trace.add("harness_error", message=error, traceback=traceback.format_exc()[-2000:])
    finally:
        os.chdir(original_cwd)
        settings_mod.reload_settings()
        if not keep_workdir:
            shutil.rmtree(sandbox, ignore_errors=True)

    llm_events = [e for e in trace.of("llm") if e["kind"] != "json"]
    turns = trace.of("turn_end")
    result.update(
        status=status, error=error, final_text=final_text, trace=trace.events,
        tool_calls=[{**c, "result": _clip(c["result"])} for c in tool_calls],
        metrics={
            "duration_s": round(time.perf_counter() - started, 3),
            "llm_calls": len(llm_events),
            "input_tokens": getattr(inner, "total_input_tokens", 0) if inner else 0,
            "output_tokens": getattr(inner, "total_output_tokens", 0) if inner else 0,
            "tool_calls": len(tool_calls),
            "tool_errors": sum(1 for c in tool_calls if not c["ok"]),
            "iterations": turns[-1]["stats"].get("turns") if turns else None,
            "llm_latency_ms": round(sum(e["latency_ms"] for e in llm_events), 1),
        },
    )
    return result


def summarize(results: list[dict]) -> dict:
    ran = [r for r in results if r["status"] != "skipped"]
    passed = [r for r in ran if r["status"] == "passed"]
    return {
        "total": len(results),
        "ran": len(ran),
        "passed": len(passed),
        "failed": sum(1 for r in ran if r["status"] == "failed"),
        "errors": sum(1 for r in ran if r["status"] == "error"),
        "skipped": len(results) - len(ran),
        "pass_rate": round(len(passed) / len(ran), 3) if ran else None,
        "input_tokens": sum(r["metrics"].get("input_tokens", 0) for r in ran),
        "output_tokens": sum(r["metrics"].get("output_tokens", 0) for r in ran),
        "duration_s": round(sum(r["metrics"].get("duration_s", 0) for r in ran), 2),
    }


def run_suite(task_ids: list[str] | None = None, mode: str = "scripted", model: str | None = None,
              on_result=None) -> list[dict]:
    tasks = [t for t in SUITE if not task_ids or t.id in task_ids]
    results = []
    for task in tasks:
        result = run_task(task, mode=mode, model=model)
        results.append(result)
        if on_result:
            on_result(result)
    return results
