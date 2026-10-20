import functools
import os
from unittest.mock import MagicMock

import agent.instructions as instructions
from agent.context import Context
from agent.core import SESSION_SUMMARY_HEADER, SESSION_SUMMARY_KEY, Agent
from tools.read_file import ReadFileTool
from tools.registry import limit_output


# ── #2 tool output limit ─────────────────────────────────────────────────────

def test_short_output_is_untouched(tmp_path):
    assert limit_output("run_command", "hello", limit=100, cwd=str(tmp_path)) == "hello"
    assert not (tmp_path / ".deimos").exists()


def test_long_output_keeps_head_and_tail_and_saves_full_text(tmp_path):
    text = "\n".join(f"line {i}" for i in range(2000))
    out = limit_output("run_command", text, limit=1000, cwd=str(tmp_path))

    assert len(out) < 1300
    assert out.startswith("line 0\n") and out.endswith("line 1999")
    assert "characters omitted" in out
    saved = list((tmp_path / ".deimos" / "outputs").iterdir())
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == text
    assert os.path.join(".deimos", "outputs") in out


def test_read_file_line_ranges(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("".join(f"{i}\n" for i in range(1, 11)), encoding="utf-8")
    tool = ReadFileTool()

    assert tool.run(str(f), offset=3, limit=2) == "[lines 3-4 of 10]\n3\n4\n"
    assert tool.run(str(f), offset=9).endswith("9\n10\n")
    assert tool.run(str(f), offset=50).startswith("Error:")
    assert tool.run(str(f)) == f.read_text(encoding="utf-8")


# ── #1 compaction ────────────────────────────────────────────────────────────

def test_truncate_always_keeps_latest_message():
    ctx = Context("s")
    ctx.add_user("x" * 4000)
    ctx.add_user("y" * 4000)
    removed = ctx.truncate(limit_tokens=10)
    assert len(removed) == 1
    assert ctx.messages[0]["content"].startswith("y")


def _agent():
    memory = MagicMock()
    memory.build_memory_context.return_value = None
    memory.load_resumed_messages.return_value = []
    return Agent(ui=MagicMock(), llm=MagicMock(), tools=MagicMock(), system_prompt="base",
                 memory=memory, plan_mode=False)


def test_compaction_folds_trimmed_messages_into_session_summary():
    agent = _agent()
    agent.ctx.truncate = functools.partial(agent.ctx.truncate, limit_tokens=150)
    agent.memory.summarize_segment.side_effect = ["first summary", "merged summary"]

    for i in range(3):
        agent.ctx.add_user(f"message {i} " + "z" * 300)
    agent._compact_if_needed()
    assert agent.ctx.get_transient(SESSION_SUMMARY_KEY) == SESSION_SUMMARY_HEADER + "first summary"
    agent.memory.save_segment_summary.assert_called_once_with("first summary")

    agent.ctx.add_user("another " + "z" * 300)
    agent._compact_if_needed()
    _, kwargs = agent.memory.summarize_segment.call_args
    assert kwargs["prior_summary"] == "first summary"
    assert agent.ctx.system_prompt.endswith("merged summary")


# ── #6 DEIMOS.md ─────────────────────────────────────────────────────────────

def test_instructions_load_user_then_outer_then_inner(tmp_path, monkeypatch):
    home, outer = tmp_path / "home", tmp_path / "repo"
    inner = outer / "pkg"
    inner.mkdir(parents=True)
    home.mkdir()
    (home / "DEIMOS.md").write_text("user prefs", encoding="utf-8")
    (outer / "DEIMOS.md").write_text("repo rules", encoding="utf-8")
    (inner / "DEIMOS.md").write_text("pkg rules", encoding="utf-8")
    monkeypatch.setattr(instructions, "LOCAL_DIR", home)

    block = instructions.load_instructions(str(inner))

    assert block.index("user prefs") < block.index("repo rules") < block.index("pkg rules")


def test_no_instructions_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(instructions, "LOCAL_DIR", tmp_path / "nohome")
    assert instructions.load_instructions(str(tmp_path)) is None
