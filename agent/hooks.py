"""
Hooks: shell commands that run around the agent's tool calls.

Configured under "hooks" in ~/.deimos/settings.json or a project's
.deimos/settings.json:

    "hooks": {
      "pre_tool":  [{"command": "python scripts/guard.py", "tools": ["run_command"]}],
      "post_edit": ["ruff format $DEIMOS_FILES"],
      "post_tool": [],
      "on_stop":   [{"command": "npm run lint", "timeout": 120}]
    }

An entry is a command string or {"command", "tools" (optional filter), "timeout"}.

  pre_tool   before a tool runs (after it's approved). Non-zero exit blocks the
             tool and its output is sent to the agent as the reason.
  post_tool  after a tool runs. Non-zero exit adds its output to the tool result.
  post_edit  like post_tool, but only after file edits; DEIMOS_FILES lists them.
  on_stop    when the agent is about to finish a turn. Non-zero exit sends the
             output back and the agent keeps working (a few times at most).

Each hook gets DEIMOS_EVENT, DEIMOS_TOOL, DEIMOS_TOOL_INPUT (JSON) and
DEIMOS_FILES in its environment, and the same as JSON on stdin.

Hooks from your own ~/.deimos/settings.json always run. Commands a project
defines (hooks and verify.commands) run only after you approve them once;
the approval is remembered until those commands change.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass

from config import LOCAL_DIR
from settings import load_layers

EVENTS = ("pre_tool", "post_tool", "post_edit", "on_stop")
DEFAULT_TIMEOUT = 60
OUTPUT_LIMIT = 4000
TRUST_FILE = LOCAL_DIR / "trusted_projects.json"


@dataclass
class Hook:
    command: str
    tools: list[str] | None = None
    timeout: int = DEFAULT_TIMEOUT
    source: str = "user"  # "user" or "project"

    def matches(self, tool_name: str | None) -> bool:
        return not self.tools or tool_name in self.tools


@dataclass
class HookResult:
    hook: Hook
    code: int
    output: str

    @property
    def failed(self) -> bool:
        return self.code != 0

    def describe(self) -> str:
        return f"`{self.hook.command}` exited with {self.code}:\n{self.output}".rstrip()


def _parse(entries, source: str) -> list[Hook]:
    hooks = []
    for entry in entries or []:
        if isinstance(entry, str) and entry.strip():
            hooks.append(Hook(entry.strip(), source=source))
        elif isinstance(entry, dict) and str(entry.get("command", "")).strip():
            tools = entry.get("tools")
            hooks.append(Hook(
                str(entry["command"]).strip(),
                tools=[str(t) for t in tools] if isinstance(tools, list) else None,
                timeout=int(entry.get("timeout", DEFAULT_TIMEOUT)),
                source=source,
            ))
    return hooks


def project_commands(project: dict) -> list[str]:
    """Every shell command a project's settings would run automatically."""
    commands = []
    for event in EVENTS:
        commands += [h.command for h in _parse((project.get("hooks") or {}).get(event), "project")]
    commands += [str(c) for c in (project.get("verify") or {}).get("commands") or []]
    return commands


class HookRunner:
    def __init__(self, ui=None, cwd: str | None = None, trust_file=TRUST_FILE):
        self.ui = ui
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.trust_file = trust_file
        user, project, self.project_file = load_layers(self.cwd)
        self._user = user
        self._project = project
        self.project_trusted: bool | None = None if project_commands(project) else True
        self.hooks: dict[str, list[Hook]] = {}
        self._build()

    # ── Trust ────────────────────────────────────────────────────────────────

    def ensure_trust(self) -> bool:
        """Ask once whether this project's commands may run; remembered per project."""
        if self.project_trusted is not None:
            return self.project_trusted
        commands = project_commands(self._project)
        digest = hashlib.sha256(json.dumps(commands).encode("utf-8")).hexdigest()
        trusted = self._load_trust()
        if trusted.get(self.cwd) == digest:
            self.project_trusted = True
        elif self.ui is None:
            self.project_trusted = False
        else:
            detail = [f"$ {c}" for c in commands]
            answer, _ = self.ui.ask_permission(
                "Project commands", detail,
                question=f"{self.project_file} runs these commands automatically. Allow them for this project?",
            )
            self.project_trusted = answer in ("y", "a")
            if self.project_trusted:
                trusted[self.cwd] = digest
                self._save_trust(trusted)
        self._build()
        return self.project_trusted

    def _load_trust(self) -> dict:
        try:
            return json.loads(self.trust_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_trust(self, data: dict):
        try:
            self.trust_file.parent.mkdir(parents=True, exist_ok=True)
            self.trust_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _build(self):
        user_hooks = self._user.get("hooks") or {}
        project_hooks = (self._project.get("hooks") or {}) if self.project_trusted else {}
        self.hooks = {
            event: _parse(user_hooks.get(event), "user") + _parse(project_hooks.get(event), "project")
            for event in EVENTS
        }

    def verify_commands(self) -> list[str] | None:
        """Configured verify commands (project ones only if trusted), or None to auto-detect."""
        if self.project_trusted and (self._project.get("verify") or {}).get("commands"):
            return [str(c) for c in self._project["verify"]["commands"]]
        if (self._user.get("verify") or {}).get("commands"):
            return [str(c) for c in self._user["verify"]["commands"]]
        return None

    # ── Running ──────────────────────────────────────────────────────────────

    def run(self, event: str, tool_name: str | None = None, inputs: dict | None = None,
            files: list[str] | None = None, result: str | None = None) -> list[HookResult]:
        if self.project_trusted is None:
            # Project hooks stay out of self.hooks until approved, so ask before
            # selecting when the project defines one for this call.
            project_hooks = _parse((self._project.get("hooks") or {}).get(event), "project")
            if any(h.matches(tool_name) for h in project_hooks):
                self.ensure_trust()
        hooks = [h for h in self.hooks.get(event, []) if h.matches(tool_name)]
        if not hooks:
            return []
        payload = {"event": event, "tool": tool_name, "inputs": inputs or {}, "files": files or [],
                   "result": (result or "")[:OUTPUT_LIMIT]}
        env = dict(os.environ,
                   DEIMOS_EVENT=event,
                   DEIMOS_TOOL=tool_name or "",
                   DEIMOS_TOOL_INPUT=json.dumps(inputs or {}),
                   DEIMOS_FILES=" ".join(_quote(f) for f in files or []))
        results = []
        for hook in hooks:
            results.append(self._run_one(hook, payload, env))
            if event == "pre_tool" and results[-1].failed:
                break  # the first blocking hook decides
        return results

    def _run_one(self, hook: Hook, payload: dict, env: dict) -> HookResult:
        try:
            proc = subprocess.run(hook.command, shell=True, cwd=self.cwd, env=env,
                                  input=json.dumps(payload), capture_output=True, text=True,
                                  timeout=hook.timeout)
            output = (proc.stdout + proc.stderr).strip()
            code = proc.returncode
        except subprocess.TimeoutExpired:
            output, code = f"timed out after {hook.timeout}s", 124
        except OSError as e:
            output, code = str(e), 127
        if len(output) > OUTPUT_LIMIT:
            output = output[:OUTPUT_LIMIT // 2] + "\n[...]\n" + output[-OUTPUT_LIMIT // 2:]
        return HookResult(hook, code, output)


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path
