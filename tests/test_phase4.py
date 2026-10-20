import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

import settings
from agent.core import Agent
from agent.hooks import HookRunner
from agent.permissions import Permissions
from agent.subagent import PromptBroker
from agent.verify import detect_commands
from tools.registry import ToolRegistry

PY = f'"{sys.executable}"'


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return f'{PY} "{path}"'


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated ~/.deimos and project dir; returns a writer for user/project settings."""
    user_dir, project = tmp_path / "home", tmp_path / "project"
    user_dir.mkdir()
    (project / ".deimos").mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_DIR", user_dir)
    monkeypatch.chdir(project)
    settings.reload_settings()

    def write(user=None, proj=None):
        if user is not None:
            (user_dir / "settings.json").write_text(json.dumps(user), encoding="utf-8")
        if proj is not None:
            (project / ".deimos" / "settings.json").write_text(json.dumps(proj), encoding="utf-8")
        settings.reload_settings()

    write.user_dir, write.project = user_dir, project
    yield write
    settings.reload_settings()


class AnswerUI:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def ask_permission(self, title, detail=None, change=None, danger=False, always_label=None, question=None):
        self.asked.append(title)
        return self.answers.pop(0) if self.answers else ("n", None)


# ── #10 hooks ────────────────────────────────────────────────────────────────

def test_pre_tool_hook_blocks_and_post_edit_hook_reports(home, tmp_path):
    guard = _script(tmp_path, "guard.py", "import sys; print('no rm here'); sys.exit(1)")
    fmt = _script(tmp_path, "fmt.py", "import os, sys; print('formatted', os.environ['DEIMOS_FILES']); sys.exit(3)")
    home(user={"hooks": {"pre_tool": [{"command": guard, "tools": ["run_command"]}], "post_edit": [fmt]}})
    hooks = HookRunner(ui=AnswerUI(), cwd=str(home.project))

    blocked = hooks.run("pre_tool", "run_command", {"command": "rm x"})
    assert blocked[0].failed and "no rm here" in blocked[0].output
    assert hooks.run("pre_tool", "read_file", {"path": "x"}) == []  # filtered by "tools"

    edited = hooks.run("post_edit", "edit_file", files=["a.py"])
    assert edited[0].code == 3 and "formatted a.py" in edited[0].output


def test_hook_gets_payload_on_stdin(home, tmp_path):
    echo = _script(tmp_path, "echo.py", "import sys, json; d = json.load(sys.stdin); print(d['tool'], d['inputs']['path']); sys.exit(1)")
    home(user={"hooks": {"post_tool": [echo]}})
    result = HookRunner(cwd=str(home.project)).run("post_tool", "read_file", {"path": "f.py"})
    assert result[0].output == "read_file f.py"


def test_project_hooks_need_approval_once(home, tmp_path):
    marker = tmp_path / "ran.txt"
    hook = _script(tmp_path, "mark.py", f"open(r'{marker}', 'a').write('x')")
    home(proj={"hooks": {"post_tool": [hook]}})
    trust = home.user_dir / "trusted.json"

    declined = HookRunner(ui=AnswerUI(("n", None)), cwd=str(home.project), trust_file=trust)
    declined.run("post_tool", "read_file")
    assert not marker.exists() and not trust.exists()

    ui = AnswerUI(("y", None))
    allowed = HookRunner(ui=ui, cwd=str(home.project), trust_file=trust)
    allowed.run("post_tool", "read_file")
    assert marker.read_text() == "x" and ui.asked == ["Project commands"]

    again = AnswerUI()
    HookRunner(ui=again, cwd=str(home.project), trust_file=trust).run("post_tool", "read_file")
    assert again.asked == [] and marker.read_text() == "xx"  # remembered

    home(proj={"hooks": {"post_tool": [hook + " --changed"]}})
    changed = AnswerUI(("n", None))
    HookRunner(ui=changed, cwd=str(home.project), trust_file=trust).run("post_tool", "read_file")
    assert changed.asked == ["Project commands"]  # new commands need a new approval


def test_verify_commands_from_untrusted_project_are_ignored(home):
    home(user={"verify": {"commands": ["user-check"]}}, proj={"verify": {"commands": ["project-check"]}})
    hooks = HookRunner(ui=AnswerUI(("n", None)), cwd=str(home.project), trust_file=home.user_dir / "t.json")
    hooks.ensure_trust()
    assert hooks.verify_commands() == ["user-check"]


# ── #7 verification ──────────────────────────────────────────────────────────

def test_detect_commands(tmp_path):
    assert detect_commands(str(tmp_path)) == []
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detect_commands(str(tmp_path)) == ["python -m pytest -q -x", "npm test --silent"]


def _tool_call(name, inputs, cid):
    return {"stop_reason": "tool_use", "text": None, "tool_calls": [{"id": cid, "name": name, "inputs": inputs}],
            "raw_content": {"role": "assistant", "content": None, "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(inputs)}}]}}


def _reply(text):
    return {"stop_reason": "end_turn", "text": text, "tool_calls": [], "raw_content": {"role": "assistant", "content": text}}


def _scripted_llm(*responses):
    llm = MagicMock()
    llm.total_input_tokens = llm.total_output_tokens = 0
    llm.complete_stream.side_effect = list(responses)
    return llm


def _agent(llm, mode="auto"):
    memory = MagicMock()
    memory.build_memory_context.return_value = None
    memory.load_resumed_messages.return_value = []
    memory.recall.return_value = None
    ui = MagicMock()
    agent = Agent(ui=ui, llm=llm, tools=ToolRegistry(), system_prompt="s", memory=memory,
                  plan_mode=False, permissions=Permissions(ui, mode=mode, decider=MagicMock(yes_no=MagicMock(return_value=0.0))))
    return agent


def test_failed_check_is_sent_back_and_the_agent_fixes_it(home, tmp_path, monkeypatch):
    target = home.project / "calc.py"
    target.write_text("ANSWER = 1\n", encoding="utf-8")
    check = _script(tmp_path, "check.py",
                    f"import sys; ok = 'ANSWER = 42' in open(r'{target}').read(); print('ok' if ok else 'expected 42'); sys.exit(0 if ok else 1)")
    home(user={"verify": {"commands": [check], "max_attempts": 2}})
    monkeypatch.setattr("agent.core.needs_verification", lambda files, request: True)

    llm = _scripted_llm(
        _tool_call("edit_file", {"path": "calc.py", "old_text": "ANSWER = 1", "new_text": "ANSWER = 41"}, "c1"),
        _reply("Done."),                       # tries to finish; the check fails
        _tool_call("edit_file", {"path": "calc.py", "old_text": "ANSWER = 41", "new_text": "ANSWER = 42"}, "c2"),
        _reply("Fixed, checks pass."),         # check passes this time
    )
    agent = _agent(llm)
    agent.run("set the answer to 42")

    assert target.read_text(encoding="utf-8") == "ANSWER = 42\n"
    feedback = [m["content"] for m in agent.ctx.messages if m["role"] == "user" and isinstance(m["content"], str)
                and "verification failed" in m["content"]]
    assert len(feedback) == 1 and "expected 42" in feedback[0]
    agent.ui.success.assert_any_call(f"Checks passed: {check}")
    assert llm.complete_stream.call_count == 4


def test_checks_stop_after_max_attempts(home, tmp_path, monkeypatch):
    (home.project / "f.py").write_text("x = 1\n", encoding="utf-8")
    home(user={"verify": {"commands": [_script(tmp_path, "fail.py", "import sys; sys.exit(1)")], "max_attempts": 1}})
    monkeypatch.setattr("agent.core.needs_verification", lambda files, request: True)
    llm = _scripted_llm(
        _tool_call("edit_file", {"path": "f.py", "old_text": "x = 1", "new_text": "x = 2"}, "c1"),
        _reply("Done."),
        _reply("Still done."),
    )
    agent = _agent(llm)
    agent.run("change x")
    agent.ui.error.assert_any_call("Checks still failing after 1 attempts; stopping here.")
    assert llm.complete_stream.call_count == 3


def test_turns_without_edits_skip_checks(home, tmp_path):
    home(user={"verify": {"commands": [_script(tmp_path, "boom.py", "raise SystemExit(1)")]}})
    llm = _scripted_llm(_reply("Just answering."))
    agent = _agent(llm)
    agent.run("what is this repo?")
    assert llm.complete_stream.call_count == 1


def test_on_stop_hook_keeps_the_agent_working(home, tmp_path):
    flag = tmp_path / "flag"
    hook = _script(tmp_path, "stop.py", f"import os, sys; sys.exit(0 if os.path.exists(r'{flag}') else 1)")
    home(user={"hooks": {"on_stop": [hook]}, "verify": {"enabled": False}})
    llm = _scripted_llm(
        _reply("Done."),
        _tool_call("write_file", {"path": str(flag), "content": "ok"}, "c1"),
        _reply("Now really done."),
    )
    agent = _agent(llm)
    agent.run("do the thing")
    assert flag.exists() and llm.complete_stream.call_count == 3


# ── #8 sub-agents ────────────────────────────────────────────────────────────

class FakeSubLLM:
    """Writes one file, then reports. Records which threads it ran on."""
    threads = set()
    barrier = None

    def __init__(self, model=None):
        self.total_input_tokens = 10
        self.total_output_tokens = 5
        self.model = model
        self.calls = 0

    def complete(self, system, messages, tools):
        FakeSubLLM.threads.add(threading.get_ident())
        self.calls += 1
        task = messages[0]["content"]
        target = task.split("write ")[1].strip()
        if self.calls == 1:
            if FakeSubLLM.barrier:
                FakeSubLLM.barrier.wait(timeout=5)  # proves both run at the same time
            return _tool_call("write_file", {"path": target, "content": task}, f"w-{target}")
        return _reply(f"Wrote {target}.")


def test_delegate_runs_tasks_in_parallel_and_reports(home, monkeypatch):
    home(user={"subagents": {"max_parallel": 2}, "permission_mode": "auto"})
    FakeSubLLM.threads, FakeSubLLM.barrier = set(), threading.Barrier(2)
    monkeypatch.setattr("llm.client.LLMClient", FakeSubLLM)
    agent = _agent(_scripted_llm(), mode="auto")
    agent.llm.model = "m"

    report = agent.delegate([{"id": "s1", "task": "please write a.txt"}, {"id": "s2", "task": "please write b.txt"}])

    assert (home.project / "a.txt").read_text() == "please write a.txt"
    assert (home.project / "b.txt").read_text() == "please write b.txt"
    assert "## s1: done" in report and "Wrote a.txt." in report and "## s2: done" in report
    assert len(FakeSubLLM.threads) == 2
    assert agent.llm.total_input_tokens == 20  # sub-agent usage counted in the session
    assert {p.lower() for p in agent._turn_edits} >= {str(home.project / "a.txt").lower()}


def test_sub_agents_cannot_edit_the_same_file(home, monkeypatch):
    home(user={"permission_mode": "auto"})
    agent = _agent(_scripted_llm(), mode="auto")
    from agent.subagent import FileClaims
    agent.claims = FileClaims()
    first = agent._execute_tool("write_file", {"path": "shared.txt", "content": "1"}, ui=MagicMock(), owner="s1")
    second = agent._execute_tool("write_file", {"path": "shared.txt", "content": "2"}, ui=MagicMock(), owner="s2")
    assert first.startswith("Written") and second.startswith("Error: ") and "sub-agent s1" in second
    assert (home.project / "shared.txt").read_text() == "1"


def test_prompt_broker_runs_worker_prompts_on_the_main_thread():
    broker, main = PromptBroker(), threading.get_ident()
    seen = []

    def prompt(x):
        seen.append(threading.get_ident())
        return x * 2

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(broker.ask, prompt, n) for n in (1, 2)]
        broker.serve(futures)
        assert sorted(f.result() for f in futures) == [2, 4]
    assert seen == [main, main]
