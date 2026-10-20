"""
Layered settings for behaviour that varies per user or per project.

Precedence (later wins): built-in defaults < ~/.deimos/settings.json
< <project>/.deimos/settings.json. Nested objects are merged key by key,
so a project file only needs the keys it changes. Secrets stay in .env.
"""

import copy
import json
import os
import sys
from pathlib import Path

from config import LOCAL_DIR

DEFAULTS = {
    "permission_mode": "ask",       # ask | auto-edit | read-only
    "models": {"fast": None},       # None -> LLM_MODEL_FAST from .env
    "jev": {"enabled": True},       # needs TYPESAFE_API_KEY; falls back to Groq
    "tool_output_limit": 8000,      # characters kept inline per tool result
    "hooks": {"pre_tool": [], "post_tool": [], "post_edit": [], "on_stop": []},
    "verify": {"enabled": True, "commands": [], "max_attempts": 2},
    "subagents": {"max_parallel": 2},
}

_cache: dict[str, dict] = {}


def load_settings(cwd: str | None = None) -> dict:
    """Return the merged settings for a project directory (cached per directory)."""
    root = os.path.abspath(cwd or os.getcwd())
    if root not in _cache:
        merged = copy.deepcopy(DEFAULTS)
        for path in (LOCAL_DIR / "settings.json", Path(root) / ".deimos" / "settings.json"):
            _deep_merge(merged, _read(path))
        _cache[root] = merged
    return _cache[root]


def load_layers(cwd: str | None = None) -> tuple[dict, dict, Path]:
    """(user settings, project settings, project settings path), unmerged and without defaults."""
    project_file = Path(os.path.abspath(cwd or os.getcwd())) / ".deimos" / "settings.json"
    return _read(LOCAL_DIR / "settings.json"), _read(project_file), project_file


def reload_settings():
    """Forget cached settings so the next load re-reads the files."""
    _cache.clear()


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: ignoring invalid settings file {path}: {e}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"Warning: ignoring settings file {path}: top level must be an object", file=sys.stderr)
        return {}
    return data


def _deep_merge(base: dict, override: dict):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
