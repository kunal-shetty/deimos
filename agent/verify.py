"""
Verification: after a turn that edited files, run the project's checks and
send failures back to the agent so it fixes them before finishing.

Commands come from "verify.commands" in settings, or are detected from the
project (pytest, npm test, cargo test, go test). Edits that only touch docs
skip verification; otherwise a yes/no decision (Jev or the Groq fallback)
judges whether the change could affect what the checks cover.
"""

from __future__ import annotations

import json
import os

from llm.decide import DecisionError, get_decider

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
NEEDS_CHECK_QUESTION = (
    "A coding agent just changed these files to carry out the request. Could the change "
    "affect behaviour that the project's automated tests or checks cover? Pure documentation, "
    "comment or formatting changes do not."
)
SKIP_BELOW = 0.3


def detect_commands(cwd: str | None = None) -> list[str]:
    """Best guess at the project's test command(s), or [] if none is evident."""
    root = os.path.abspath(cwd or os.getcwd())

    def exists(*names):
        return any(os.path.exists(os.path.join(root, n)) for n in names)

    commands = []
    if exists("pytest.ini", "conftest.py", "tests/conftest.py") or (
            exists("tests", "test") and exists("pyproject.toml", "setup.py", "setup.cfg")):
        commands.append("python -m pytest -q -x")
    if exists("package.json"):
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                test = (json.load(f).get("scripts") or {}).get("test", "")
            if test and "no test specified" not in test:
                commands.append("npm test --silent")
        except (OSError, ValueError):
            pass
    if exists("Cargo.toml"):
        commands.append("cargo test --quiet")
    if exists("go.mod"):
        commands.append("go test ./...")
    return commands


def needs_verification(files: list[str], request: str, decider=None) -> bool:
    if not files:
        return False
    if all(os.path.splitext(f)[1].lower() in DOC_EXTENSIONS for f in files):
        return False
    state = f"Request: {request[:1000]}\nChanged files:\n" + "\n".join(f"- {f}" for f in files[:50])
    try:
        return (decider or get_decider()).yes_no(state, NEEDS_CHECK_QUESTION) >= SKIP_BELOW
    except DecisionError:
        return True  # when unsure, check


def failure_message(command: str, result: str, attempt: int, max_attempts: int) -> str:
    tail = "\n".join(result.strip().splitlines()[-60:])
    return (
        f"[System: verification failed after your changes (attempt {attempt}/{max_attempts}).\n"
        f"$ {command}\n{tail}\n"
        "Fix the cause of the failure (not the check itself, unless the check is wrong), "
        "then finish your answer.]"
    )
