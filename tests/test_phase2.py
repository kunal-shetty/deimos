import os
from unittest.mock import MagicMock

import pytest

from agent.checkpoints import CheckpointStore
from agent.core import Agent
from agent.permissions import Permissions
from llm.decide import DecisionError
from tools.base import FileChange
from tools.registry import ToolRegistry
from ui.terminal import MarkdownStream, _strip_ansi, diff_headline, render_diff, tool_summary


# ── #5 checkpoints ───────────────────────────────────────────────────────────

def test_undo_restores_edited_and_deletes_created_files(tmp_path):
    edited, created = tmp_path / "a.txt", tmp_path / "new" / "b.txt"
    edited.write_text("original", encoding="utf-8")
    store = CheckpointStore(cwd=str(tmp_path))

    store.begin("change things")
    store.snapshot([str(edited), str(created)])
    edited.write_text("changed", encoding="utf-8")
    store.snapshot([str(edited)])  # second snapshot in the same turn keeps the original
    edited.write_text("changed again", encoding="utf-8")
    created.parent.mkdir()
    created.write_text("agent made this", encoding="utf-8")

    result = store.undo()

    assert edited.read_text(encoding="utf-8") == "original"
    assert not created.exists()
    assert result.restored == [str(edited)] and result.deleted == [str(created)]
    assert store.undo() is None


def test_undo_walks_back_one_turn_at_a_time(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("v1", encoding="utf-8")
    store = CheckpointStore(cwd=str(tmp_path))
    for version in ("v2", "v3"):
        store.begin(f"make {version}")
        store.snapshot([str(f)])
        f.write_text(version, encoding="utf-8")

    assert [cp.label for cp in store.list()] == ["make v3", "make v2"]
    store.undo()
    assert f.read_text(encoding="utf-8") == "v2"
    store.undo()
    assert f.read_text(encoding="utf-8") == "v1"


def test_turns_without_edits_leave_no_checkpoint(tmp_path):
    store = CheckpointStore(cwd=str(tmp_path))
    store.begin("just a question")
    assert store.list() == [] and not (tmp_path / ".deimos").exists()


# ── #4 permission modes ──────────────────────────────────────────────────────

class FakeUI:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def ask_permission(self, title, detail=None, change=None, danger=False, always_label=None, question=None):
        self.asked.append({"title": title, "danger": danger, "always": always_label, "change": change,
                           "question": question})
        return self.answers.pop(0)


def _safe_decider(p=0.0):
    d = MagicMock()
    d.yes_no.return_value = p
    return d


TOOLS = ToolRegistry()
READ, EDIT, RUN, PUSH = (TOOLS.get(n) for n in ("read_file", "edit_file", "run_command", "git_push"))


@pytest.mark.parametrize("mode, tool, inputs, expect_ask", [
    ("ask", READ, {"path": "x"}, False),
    ("ask", EDIT, {"path": "x"}, True),
    ("ask", RUN, {"command": "pytest"}, True),
    ("auto-edit", EDIT, {"path": "x"}, False),
    ("auto-edit", RUN, {"command": "pytest"}, True),
    ("auto", RUN, {"command": "pytest"}, False),
    ("auto", PUSH, {}, True),  # outward: confirmed even in auto
])
def test_mode_table(mode, tool, inputs, expect_ask):
    ui = FakeUI(("y", None))
    verdict = Permissions(ui, mode=mode, decider=_safe_decider()).check(tool, inputs)
    assert verdict.allowed
    assert bool(ui.asked) == expect_ask


def test_read_only_denies_without_asking():
    ui = FakeUI()
    perms = Permissions(ui, mode="read-only", decider=_safe_decider())
    assert perms.check(READ, {"path": "x"}).allowed
    verdict = perms.check(EDIT, {"path": "x"})
    assert not verdict.allowed and "read-only" in verdict.message and not ui.asked


def test_dangerous_command_always_asks_and_cannot_be_granted():
    ui = FakeUI(("y", None))
    verdict = Permissions(ui, mode="auto", decider=_safe_decider()).check(RUN, {"command": "rm -rf /tmp/x"})
    assert verdict.allowed and ui.asked[0]["danger"] and ui.asked[0]["always"] is None


def test_safety_check_flags_commands_the_regex_misses():
    ui = FakeUI(("n", None))
    perms = Permissions(ui, mode="auto", decider=_safe_decider(0.9))
    verdict = perms.check(RUN, {"command": "find . -delete"})
    assert not verdict.allowed and ui.asked[0]["danger"]


def test_safety_check_failure_falls_back_to_regex_only():
    decider = MagicMock()
    decider.yes_no.side_effect = DecisionError("offline")
    assert Permissions(FakeUI(), mode="auto", decider=decider).check(RUN, {"command": "ls"}).allowed


def test_always_grants_a_program_but_not_compound_commands():
    ui = FakeUI(("a", None))
    perms = Permissions(ui, mode="ask", decider=_safe_decider())
    assert perms.check(RUN, {"command": "pytest -q"}).allowed
    assert perms.check(RUN, {"command": "pytest tests/test_x.py"}).allowed
    assert len(ui.asked) == 1

    ui.answers.append(("y", None))
    perms.check(RUN, {"command": "pytest && rm build"})
    assert ui.asked[-1]["always"] is None


def test_decline_with_feedback_is_passed_to_the_agent():
    ui = FakeUI(("n", "use ruff instead"))
    verdict = Permissions(ui, mode="ask", decider=_safe_decider()).check(RUN, {"command": "flake8"})
    assert not verdict.allowed and "use ruff instead" in verdict.message


# ── Agent tool gate ──────────────────────────────────────────────────────────

def _agent(tmp_path, monkeypatch, mode, *answers):
    monkeypatch.chdir(tmp_path)
    memory = MagicMock()
    memory.build_memory_context.return_value = None
    memory.load_resumed_messages.return_value = []
    ui = MagicMock()
    fake = FakeUI(*answers)
    ui.ask_permission.side_effect = fake.ask_permission
    agent = Agent(ui=ui, llm=MagicMock(), tools=ToolRegistry(), system_prompt="s", memory=memory,
                  plan_mode=False, permissions=Permissions(ui, mode=mode, decider=_safe_decider()))
    agent.checkpoints.begin("test turn")
    return agent, fake


def test_declined_edit_is_not_applied(tmp_path, monkeypatch):
    agent, ui = _agent(tmp_path, monkeypatch, "ask", ("n", None))
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")

    result = agent._execute_tool("edit_file", {"path": "f.py", "old_text": "x = 1", "new_text": "x = 2"})

    assert result.startswith("User declined")
    assert (tmp_path / "f.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(ui.asked[0]["change"], FileChange)
    assert ui.asked[0]["title"] == "Edit file"
    assert ui.asked[0]["question"] == "Do you want to make this edit to f.py?"
    assert ui.asked[0]["always"] == "file edits"


def test_auto_edit_applies_shows_diff_and_can_be_undone(tmp_path, monkeypatch):
    agent, _ = _agent(tmp_path, monkeypatch, "auto-edit")
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")

    result = agent._execute_tool("edit_file", {"path": "f.py", "old_text": "x = 1", "new_text": "x = 2"})

    assert result.startswith("Edited")
    agent.ui.show_change.assert_called_once()
    agent.undo_last_turn()
    assert (tmp_path / "f.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "/undo" in agent.ctx.messages[-2]["content"]


def test_failing_edit_reports_error_without_asking(tmp_path, monkeypatch):
    agent, ui = _agent(tmp_path, monkeypatch, "ask")
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    result = agent._execute_tool("edit_file", {"path": "f.py", "old_text": "nope", "new_text": "y"})
    assert result.startswith("Error: old_text not found") and not ui.asked


# ── UI rendering ─────────────────────────────────────────────────────────────

MARKDOWN = (
    "## Summary\n"
    "Changed **two** files in `agent/`:\n"
    "- first item\n"
    "1. numbered\n"
    "> a quote\n"
    "---\n"
    "```python\n"
    "x = 1\n"
    "```\n"
    "2 * 3 = 6 and *not bold*"
)


def _render(chunks):
    out = []
    stream = MarkdownStream(out.append)
    for c in chunks:
        stream.feed(c)
    stream.finish()
    return _strip_ansi("".join(out))


@pytest.mark.parametrize("size", [1, 2, 3, 7, len(MARKDOWN)])
def test_markdown_stream_is_independent_of_chunking(size):
    whole = _render([MARKDOWN])
    assert _render([MARKDOWN[i:i + size] for i in range(0, len(MARKDOWN), size)]) == whole


def test_markdown_stream_renders_structure():
    lines = _render([MARKDOWN]).splitlines()
    assert lines[0] == "Summary"
    assert "Changed two files in agent/:" in lines
    assert "• first item" in lines and "1. numbered" in lines
    assert "┃ a quote" in lines and any(l.startswith("─" * 10) for l in lines)
    assert "╭─ python" in lines and "│ x = 1" in lines and "╰─" in lines
    assert lines[-1] == "2 * 3 = 6 and *not bold*"


def test_markdown_stream_indents_lines_after_the_first():
    out = []
    stream = MarkdownStream(out.append, indent="  ")
    stream.feed("first\n- item\nlast")
    stream.finish()
    assert _strip_ansi("".join(out)).splitlines() == ["first", "  • item", "  last"]


def test_render_diff_numbers_lines_and_pads_bars():
    change = FileChange("f.py", "a\nb\nc\n", "a\nB\nc\nd\n")
    assert diff_headline(change) == "Update f.py with 2 additions and 1 removal"
    lines = [_strip_ansi(l) for l in render_diff(change, width=20)]
    assert "   2 - b".ljust(20) in lines and "   2 + B".ljust(20) in lines and "   4 + d".ljust(20) in lines
    assert "   1   a" in lines


def test_render_diff_new_file():
    change = FileChange("n.py", None, "one\ntwo")
    assert diff_headline(change) == "Create n.py (2 lines)"
    assert [_strip_ansi(l) for l in render_diff(change)] == ["   1 + one", "   2 + two"]


def test_fit_truncates_by_visible_width_and_keeps_colour_codes():
    from ui.terminal import GREEN, RESET, _fit
    s = f"{GREEN}hello world{RESET}"
    assert _strip_ansi(_fit(s, 8)) == "hello w…"
    assert _strip_ansi(_fit("hi", 5)) == "hi   "
    assert _fit(s, 50, pad=False) == s


def test_result_summaries():
    from ui.terminal import result_lines
    assert result_lines("read_file", "[lines 3-4 of 10]\n3\n4\n")[0] == "Read lines 3-4 of 10"
    assert result_lines("read_file", "a\nb\nc")[0] == "Read 3 lines"
    head, detail, hidden = result_lines("run_command", "[exit 1]\n" + "\n".join(f"l{i}" for i in range(10)))
    assert head == "[exit 1]" and detail == ["l7", "l8", "l9"] and hidden == 7
    head, detail, hidden = result_lines("run_command", "one\ntwo")
    assert head == "one" and detail == ["two"] and hidden == 0


def test_permission_panel_typed_fallback(monkeypatch, capsys):
    from ui.terminal import TerminalUI
    monkeypatch.setattr("ui.terminal._interactive", lambda: False)
    ui = TerminalUI()
    monkeypatch.setattr("builtins.input", lambda prompt="": "use ruff instead")
    answer = ui.ask_permission("Run command", ["$ flake8"], always_label="`flake8` commands",
                               question="Do you want to run this command?")
    out = _strip_ansi(capsys.readouterr().out)
    assert answer == ("n", "use ruff instead")
    assert "Run command" in out and "Do you want to run this command?" in out
    assert "2. Yes, and don't ask again for `flake8` commands this session" in out

    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert ui.ask_permission("Run command", always_label="`flake8` commands") == ("a", None)


def test_tool_summaries():
    assert tool_summary("run_command", {"command": "pytest -q"}) == "pytest -q"
    assert tool_summary("read_file", {"path": "a.py", "offset": 10, "limit": 5}) == "a.py, lines 10-14"
    assert tool_summary("write_file", {"path": "a.py", "content": "1\n2"}) == "a.py, 2 lines"
    assert tool_summary("write_file", {"path": "a.py", "content": "1"}) == "a.py, 1 line"
    assert tool_summary("delegate", {"tasks": [{"id": "s2", "task": "x"}, {"task": "y"}]}) == "2 tasks: s2, t2"
