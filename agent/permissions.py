"""
Permission modes: what the agent may do without asking.

                read     edit (files)      exec (commands, git)   dangerous
  ask           allow    ask, with diff    ask                    ask
  auto-edit     allow    allow             ask                    ask
  auto          allow    allow             allow (not outward)    ask
  read-only     allow    deny              deny                   deny

"Dangerous" means a shell command matching a destructive pattern, or one the
safety check (Jev/Groq yes-no) judges likely to destroy data or reach outside
the project. Dangerous commands are always confirmed and can never be granted
"always". Outward tools (git push, PRs) are confirmed even in auto mode.

Answering "a" (always) grants that kind of action for the rest of the
session: all file edits, one tool, or one command program (e.g. pytest).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llm.decide import DecisionError, get_decider
from tools.run_command import is_dangerous

MODES = ("ask", "auto-edit", "auto", "read-only")
MODE_DESCRIPTIONS = {
    "ask": "ask before file edits and commands",
    "auto-edit": "apply file edits automatically, ask before commands",
    "auto": "apply edits and run commands automatically (dangerous ones still ask)",
    "read-only": "only read; no edits or commands",
}

DANGER_QUESTION = (
    "Could running this shell command irreversibly destroy or overwrite important data, "
    "or affect systems outside the project directory (e.g. deleting source files or home "
    "directories, force-pushing, dropping databases, changing system configuration)? "
    "Removing build artifacts, caches or dependencies that can be reinstalled is not dangerous."
)
DANGER_THRESHOLD = 0.6

# Shell syntax that chains or redirects commands: no "always allow" for these
_COMPOUND_RE = re.compile(r"&&|\|\||[;|<>`]|\$\(")


@dataclass
class Verdict:
    allowed: bool
    message: str | None = None  # returned to the agent when not allowed
    prompted: bool = False      # the user was asked (so the diff was already shown)


class Permissions:
    def __init__(self, ui, mode: str = "ask", decider=None):
        if mode not in MODES:
            mode = "ask"
        self.ui = ui
        self.mode = mode
        self._decider = decider
        self._grants: set[str] = set()
        self._danger_cache: dict[str, tuple[bool, str | None]] = {}

    def cycle_mode(self) -> str:
        """Advance to the next mode (Shift+Tab)."""
        self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        return self.mode

    def set_mode(self, mode: str):
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode!r}; choose one of: {', '.join(MODES)}")
        self.mode = mode

    def reset_grants(self):
        self._grants.clear()

    # ── Decision ─────────────────────────────────────────────────────────────

    def check(self, tool, inputs: dict, change=None, ui=None) -> Verdict:
        """Decide whether a tool call may run. `ui` overrides where prompts go (sub-agents)."""
        return self._check(tool, inputs, change, ui or self.ui)

    def _check(self, tool, inputs: dict, change, ui) -> Verdict:
        if tool.kind == "read":
            return Verdict(True)
        if self.mode == "read-only":
            return Verdict(False, (
                f"Denied: Deimos is in read-only mode, so {tool.name} cannot run. "
                "Describe the change you would make instead, or ask the user to switch modes with /mode."
            ))

        if tool.name == "run_command":
            command = inputs.get("command", "")
            dangerous, reason = self.command_danger(command)
            if dangerous:
                return self._ask(ui, tool, inputs, change, danger=True, reason=reason, grant=None)

        if tool.kind == "edit":
            if self.mode in ("auto-edit", "auto") or "edit" in self._grants:
                return Verdict(True)
            return self._ask(ui, tool, inputs, change, grant=("edit", "file edits"))

        grant = self._exec_grant(tool, inputs)
        if self.mode == "auto" and not tool.outward:
            return Verdict(True)
        if grant and grant[0] in self._grants:
            return Verdict(True)
        return self._ask(ui, tool, inputs, change, grant=grant)

    def command_danger(self, command: str) -> tuple[bool, str | None]:
        """Regex first, then the structured safety check. Cached per command."""
        if command in self._danger_cache:
            return self._danger_cache[command]
        result: tuple[bool, str | None] = (False, None)
        if is_dangerous(command):
            result = (True, "matches a known destructive pattern")
        else:
            try:
                p = (self._decider or get_decider()).yes_no(command, DANGER_QUESTION)
                if p >= DANGER_THRESHOLD:
                    result = (True, f"safety check rates it likely destructive ({p:.0%})")
            except DecisionError:
                pass  # regex-only when no decision backend is reachable
        self._danger_cache[command] = result
        return result

    # ── Internals ────────────────────────────────────────────────────────────

    def _exec_grant(self, tool, inputs: dict) -> tuple[str, str] | None:
        """(grant key, what "don't ask again" covers), or None when it can't be granted."""
        if tool.name != "run_command":
            return (f"tool:{tool.name}", tool.name)
        command = inputs.get("command", "").strip()
        if not command or _COMPOUND_RE.search(command):
            return None
        program = command.split()[0]
        return (f"cmd:{program}", f"`{program}` commands")

    def _ask(self, ui, tool, inputs, change, grant, danger: bool = False, reason: str | None = None) -> Verdict:
        from ui.terminal import tool_summary, WHITE, YELLOW, RED, RESET

        detail = []
        if change is None or tool.kind != "edit":
            prompt = "$ " if tool.name == "run_command" else ""
            detail.append(f"{WHITE}{prompt}{tool_summary(tool.name, inputs)}{RESET}")
        if reason:
            detail.append(f"{RED if danger else YELLOW}Flagged: {reason}{RESET}")

        if tool.kind == "edit":
            target = (tool.target_paths(**inputs) or ["this file"])[0]
            title = "Create file" if change is not None and change.old is None else "Edit file"
            question = f"Do you want to make this edit to {target}?"
        elif tool.name == "run_command":
            title = "Potentially destructive command" if danger else "Run command"
            question = "Do you want to run this command?"
        else:
            title = tool.name.replace("_", " ").capitalize()
            question = "Do you want to proceed?"

        answer, feedback = ui.ask_permission(
            title, detail, change=change if tool.kind == "edit" else None,
            danger=danger, always_label=grant[1] if grant else None, question=question,
        )
        if answer == "a" and grant:
            self._grants.add(grant[0])
        if answer in ("y", "a"):
            return Verdict(True, prompted=True)
        message = f"User declined this {tool.name} call."
        message += f" They said: {feedback}" if feedback else " Ask them how to proceed or try a different approach."
        return Verdict(False, message, prompted=True)
