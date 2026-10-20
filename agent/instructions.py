"""
DEIMOS.md: user- and project-level instructions loaded into the system prompt.

Files are read from ~/.deimos/DEIMOS.md, then from every directory between
the filesystem root and the working directory, so the closest file comes
last and wins when instructions conflict.
"""

import os
from pathlib import Path

from config import LOCAL_DIR

INSTRUCTIONS_FILE = "DEIMOS.md"
MAX_FILE_CHARS = 20000


def instruction_files(cwd: str | None = None) -> list[Path]:
    here = Path(os.path.abspath(cwd or os.getcwd()))
    candidates = [LOCAL_DIR / INSTRUCTIONS_FILE]
    candidates += [d / INSTRUCTIONS_FILE for d in reversed([here, *here.parents])]
    seen, found = set(), []
    for path in candidates:
        key = os.path.normcase(str(path.resolve())) if path.exists() else None
        if key and key not in seen and path.is_file():
            seen.add(key)
            found.append(path)
    return found


def load_instructions(cwd: str | None = None) -> str | None:
    """Return a system-prompt block with all DEIMOS.md contents, or None."""
    sections = []
    for path in instruction_files(cwd):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n[... truncated ...]"
        sections.append(f"### {path}\n{text}")
    if not sections:
        return None
    return (
        "## Project instructions (DEIMOS.md)\n"
        "Follow these instructions from the user and project. Later files are "
        "closer to the working directory and take precedence.\n\n"
        + "\n\n".join(sections)
    )
