"""CLI entry points used by an installed copy: argument defaults, setup, optional memory."""

from unittest.mock import MagicMock

import pytest

import main
from commands import setup
from memory.null import NullMemory


@pytest.mark.parametrize("argv, command", [
    ([], "assemble"),
    (["--mode", "auto"], "assemble"),
    (["-v"], "assemble"),
    (["assemble", "--no-plan"], "assemble"),
    (["setup"], "setup"),
    (["update"], "update"),
])
def test_plain_deimos_starts_the_agent(argv, command):
    assert main.parse_args(argv).command == command


def test_assemble_flags_work_without_the_subcommand():
    args = main.parse_args(["--mode", "read-only", "--no-plan"])
    assert args.mode == "read-only" and args.no_plan


def _answers(monkeypatch, *values):
    for key, *_ in setup.FIELDS:  # don't offer the developer's real keys as defaults
        monkeypatch.delenv(key, raising=False)
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    monkeypatch.setattr(setup, "getpass", lambda prompt="": next(it))
    monkeypatch.setattr("ui.terminal.stdin_is_terminal", lambda: True)
    monkeypatch.setattr(setup, "_groq_key_works", lambda key: key != "bad-key")


def test_setup_saves_keys_and_skips_memory_questions_without_supabase(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    # groq (rejected, then accepted), tavily, typesafe, supabase url (skipped)
    _answers(monkeypatch, "bad-key", "gsk-good", "", "ts-key", "")
    assert setup.run_setup(env)
    text = env.read_text()
    assert "GROQ_API_KEY=gsk-good" in text and "TYPESAFE_API_KEY=ts-key" in text
    assert "TAVILY" not in text and "SUPABASE" not in text


def test_setup_keeps_existing_values_on_enter(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=old-key\nOTHER=keep\n")
    _answers(monkeypatch, "", "", "", "https://x.supabase.co", "anon", "user-1")
    assert setup.run_setup(env)
    text = env.read_text()
    assert "GROQ_API_KEY=old-key" in text and "OTHER=keep" in text
    assert "SUPABASE_URL=https://x.supabase.co" in text and "DEIMOS_USER_ID=user-1" in text


def test_setup_requires_a_groq_key(tmp_path, monkeypatch):
    def no_more(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_more)
    monkeypatch.setattr(setup, "getpass", no_more)
    assert not setup.run_setup(tmp_path / ".env")
    assert not (tmp_path / ".env").exists()


def test_memory_is_off_without_supabase(monkeypatch):
    monkeypatch.setattr(main, "SUPABASE_URL", None)
    memory = main.open_memory(MagicMock(), "user-1")
    assert isinstance(memory, NullMemory) and not memory.enabled


def test_memory_falls_back_when_supabase_is_unreachable(monkeypatch):
    monkeypatch.setattr(main, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(main, "SUPABASE_KEY", "anon")
    monkeypatch.setattr(main, "MemoryManager", MagicMock(side_effect=ConnectionError("offline")))
    ui = MagicMock()
    memory = main.open_memory(ui, "user-1")
    assert isinstance(memory, NullMemory) and "offline" in memory.reason
    ui.error.assert_called_once()


def test_null_memory_supports_the_agent(tmp_path, monkeypatch):
    from agent.core import Agent
    from agent.permissions import Permissions
    monkeypatch.chdir(tmp_path)
    agent = Agent(ui=MagicMock(), llm=MagicMock(), tools=MagicMock(), system_prompt="s",
                  memory=NullMemory(), plan_mode=False, permissions=Permissions(MagicMock()))
    agent.memory.save_message("user", "hi")
    assert agent.memory.end_session(agent.ctx.messages) is None
