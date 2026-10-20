"""
Deterministic checks that grade a finished task run.

A check is a plain dict so tasks stay JSON-serialisable:

    {"type": "file_contains", "path": "app.py", "text": "return 'hello'"}

Paths are relative to the task's sandbox directory and can't escape it.
"""

from __future__ import annotations

import glob
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from evals.recording import Trace


@dataclass
class RunContext:
    workdir: Path
    trace: Trace
    initial_files: dict[str, str]
    final_text: str = ""
    script_exhausted: bool = False
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def llm_calls(self) -> list[dict]:
        return self.trace.of("llm")

    @property
    def permissions(self) -> list[dict]:
        return self.trace.of("permission")

    @property
    def ui_errors(self) -> list[dict]:
        return self.trace.of("error")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


class CheckError(Exception):
    pass


def _resolve(ctx: RunContext, rel: str) -> Path:
    root = ctx.workdir.resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise CheckError(f"path escapes the sandbox: {rel}")
    return path


def _read(ctx: RunContext, rel: str) -> str | None:
    path = _resolve(ctx, rel)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _calls(ctx: RunContext, name: str | None) -> list[dict]:
    return [c for c in ctx.tool_calls if name is None or c["name"] == name]


# Each check returns (passed, detail)

def _file_exists(ctx, c):
    ok = _resolve(ctx, c["path"]).exists()
    return ok, "" if ok else f"{c['path']} does not exist"


def _file_missing(ctx, c):
    ok = not _resolve(ctx, c["path"]).exists()
    return ok, "" if ok else f"{c['path']} exists but should not"


def _file_contains(ctx, c):
    text = _read(ctx, c["path"])
    if text is None:
        return False, f"{c['path']} does not exist"
    ok = c["text"] in text
    return ok, "" if ok else f"{c['path']} does not contain {c['text']!r}"


def _file_not_contains(ctx, c):
    text = _read(ctx, c["path"])
    if text is None:
        return False, f"{c['path']} does not exist"
    ok = c["text"] not in text
    return ok, "" if ok else f"{c['path']} still contains {c['text']!r}"


def _file_equals(ctx, c):
    text = _read(ctx, c["path"])
    if text is None:
        return False, f"{c['path']} does not exist"
    ok = text == c["text"]
    return ok, "" if ok else f"{c['path']} differs from the expected content"


def _file_unchanged(ctx, c):
    original = ctx.initial_files.get(c["path"])
    if original is None:
        return False, f"{c['path']} was not part of the initial files"
    text = _read(ctx, c["path"])
    ok = text == original
    return ok, "" if ok else f"{c['path']} was modified"


def _glob_exists(ctx, c):
    root = ctx.workdir.resolve()
    matches = glob.glob(str(root / c["pattern"]), recursive=True)
    ok = bool(matches)
    return ok, "" if ok else f"nothing matches {c['pattern']}"


def _tool_called(ctx, c):
    n, low = len(_calls(ctx, c["name"])), c.get("min", 1)
    ok = n >= low
    return ok, f"{c['name']} called {n} time(s), expected at least {low}"


def _tool_not_called(ctx, c):
    n = len(_calls(ctx, c["name"]))
    return n == 0, f"{c['name']} called {n} time(s), expected none"


def _tool_result_contains(ctx, c):
    results = [x["result"] for x in _calls(ctx, c.get("name"))]
    ok = any(c["text"] in r for r in results)
    return ok, "" if ok else f"no {c.get('name') or 'tool'} result contains {c['text']!r}"


def _max_tool_calls(ctx, c):
    n = len(ctx.tool_calls)
    return n <= c["n"], f"{n} tool calls, limit {c['n']}"


def _max_llm_calls(ctx, c):
    n = len([e for e in ctx.llm_calls if e["kind"] != "json"])
    return n <= c["n"], f"{n} model calls, limit {c['n']}"


def _llm_calls_of_kind(ctx, c):
    n = len([e for e in ctx.llm_calls if e["kind"] == c["kind"]])
    return n == c["n"], f"{n} {c['kind']} call(s), expected {c['n']}"


def _final_text_contains(ctx, c):
    ok = c["text"].lower() in ctx.final_text.lower()
    return ok, "" if ok else f"final answer does not mention {c['text']!r}"


def _ui_error_contains(ctx, c):
    ok = any(c["text"].lower() in e["message"].lower() for e in ctx.ui_errors)
    return ok, "" if ok else f"no error containing {c['text']!r} was raised"


def _no_ui_errors(ctx, c):
    n = len(ctx.ui_errors)
    return n == 0, f"{n} error(s): " + "; ".join(e["message"][:80] for e in ctx.ui_errors[:3]) if n else ""


def _permission_requests(ctx, c):
    n = len(ctx.permissions)
    return n == c["n"], f"{n} permission request(s), expected {c['n']}"


def _permission_request(ctx, c):
    want_danger = c.get("danger")
    ok = any(want_danger is None or p["danger"] == want_danger for p in ctx.permissions)
    return ok, "" if ok else "no matching permission request"


def _script_completed(ctx, c):
    return not ctx.script_exhausted, "the model ran out of scripted turns" if ctx.script_exhausted else ""


def _command_passes(ctx, c):
    try:
        proc = subprocess.run(c["command"], shell=True, cwd=ctx.workdir, capture_output=True,
                              text=True, timeout=c.get("timeout", 60))
    except subprocess.TimeoutExpired:
        return False, f"`{c['command']}` timed out"
    out = (proc.stdout + proc.stderr).strip()
    tail = "\n".join(out.splitlines()[-8:])
    return proc.returncode == 0, f"`{c['command']}` exited {proc.returncode}\n{tail}" if proc.returncode else ""


CHECKS = {
    "file_exists": _file_exists,
    "file_missing": _file_missing,
    "file_contains": _file_contains,
    "file_not_contains": _file_not_contains,
    "file_equals": _file_equals,
    "file_unchanged": _file_unchanged,
    "glob_exists": _glob_exists,
    "tool_called": _tool_called,
    "tool_not_called": _tool_not_called,
    "tool_result_contains": _tool_result_contains,
    "max_tool_calls": _max_tool_calls,
    "max_llm_calls": _max_llm_calls,
    "llm_calls_of_kind": _llm_calls_of_kind,
    "final_text_contains": _final_text_contains,
    "ui_error_contains": _ui_error_contains,
    "no_ui_errors": _no_ui_errors,
    "permission_requests": _permission_requests,
    "permission_request": _permission_request,
    "script_completed": _script_completed,
    "command_passes": _command_passes,
}


def describe(check: dict) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in check.items() if k != "type")
    return f"{check['type']}({args})"


def evaluate(check: dict, ctx: RunContext) -> CheckResult:
    name = describe(check)
    fn = CHECKS.get(check.get("type"))
    if fn is None:
        return CheckResult(name, False, f"unknown check type {check.get('type')!r}")
    try:
        passed, detail = fn(ctx, check)
    except (CheckError, KeyError, OSError) as e:
        return CheckResult(name, False, f"check could not run: {type(e).__name__}: {e}")
    return CheckResult(name, bool(passed), "" if passed else detail)
