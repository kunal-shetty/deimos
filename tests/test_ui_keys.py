"""Drive the real prompt_toolkit prompt and approval menu with simulated keystrokes."""

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

import ui.terminal as terminal
from ui.terminal import TerminalUI

DOWN, ESC, SHIFT_TAB = "\x1b[B", "\x1b", "\x1b[Z"


@pytest.fixture
def keys(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal, "INPUT_HISTORY_FILE", tmp_path / "history")
    monkeypatch.setattr(terminal, "LOCAL_DIR", tmp_path)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        yield pipe


def _ui():
    ui = TerminalUI()
    ui.setup_input([("help", "Show all available commands")])
    return ui


def test_prompt_returns_submitted_text(keys):
    ui = _ui()
    keys.send_text("hello deimos\r")
    assert ui.prompt() == "hello deimos"


def test_backslash_enter_inserts_a_newline(keys):
    ui = _ui()
    keys.send_text("line one\\\rline two\r")
    assert ui.prompt() == "line one\nline two"


def test_shift_tab_cycles_mode(keys):
    ui = _ui()
    calls = []
    ui.set_mode_cycler(lambda: calls.append("cycled"))
    keys.send_text(SHIFT_TAB + SHIFT_TAB + "x\r")
    assert ui.prompt() == "x" and calls == ["cycled", "cycled"]


def test_toolbar_shows_mode_and_context(keys):
    ui = _ui()
    ui.set_status_provider(lambda: {"mode": "auto-edit", "model": "m1", "context": 0.75, "plan_pending": True})
    text = "".join(t for _, t in ui._toolbar())
    assert "▸▸ auto-edit on" in text and "m1" in text and "75%" in text and "plan awaiting confirmation" in text


@pytest.mark.parametrize("typed, expected", [
    ("\r", ("y", None)),                 # enter on the default "Yes"
    (DOWN + "\r", ("a", None)),          # arrow down to "don't ask again"
    ("2", ("a", None)),                  # digit shortcut
    (ESC, ("n", None)),                  # escape declines without asking for feedback
])
def test_approval_menu_keys(keys, monkeypatch, typed, expected):
    monkeypatch.setattr(terminal, "_interactive", lambda: True)
    ui = TerminalUI()
    keys.send_text(typed)
    assert ui.ask_permission("Run command", ["$ pytest"], always_label="`pytest` commands") == expected


def test_approval_menu_no_then_feedback(keys, monkeypatch):
    monkeypatch.setattr(terminal, "_interactive", lambda: True)
    ui = TerminalUI()
    keys.send_text("3")
    keys.send_text("run only the unit tests\r")
    assert ui.ask_permission("Run command", ["$ pytest"], always_label="`pytest` commands") == (
        "n", "run only the unit tests")
