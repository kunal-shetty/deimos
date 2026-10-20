import sys
import os
import re
import difflib
import threading
import itertools
import subprocess
import time
import json

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from pygments.util import ClassNotFound

from config import INPUT_HISTORY_FILE, LOCAL_DIR

# Enable ANSI escapes on legacy Windows consoles (no-op elsewhere)
if os.name == "nt":
    os.system("")

# Ensure stdout/stderr can encode Unicode (box-drawing, symbols) even when the
# console codepage is not UTF-8 (e.g. cp1252) or output is piped/redirected.
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ── Colour palette (cyan/blue brand theme) ───────────────────────────────────
ACCENT     = "\033[38;5;81m"    # #5fd7ff  primary brand colour (cyan)
ACCENT_DIM = "\033[38;5;67m"    # #5f87af  dimmer blue: borders, gutters
BLUE       = "\033[38;5;75m"    # #5fafff  secondary accent
GREEN      = "\033[38;5;114m"   # #87d787  success, additions
RED        = "\033[38;5;203m"   # #ff5f5f  errors, deletions, danger
YELLOW     = "\033[38;5;221m"   # #ffd75f  approvals, warnings
GREY       = "\033[38;5;245m"   # #8a8a8a  secondary text
WHITE      = "\033[97m"
BOLD       = "\033[1m"
DIM        = "\033[2m"
ITALIC     = "\033[3m"
RESET      = "\033[0m"

# Box-drawing helpers
def _box_top(label: str, width: int, colour: str) -> str:
    label_str = f" {label} " if label else ""
    line = "─" * (width - len(label_str) - 2)
    return f"{colour}╭{label_str}{line}╮{RESET}"

def _box_bot(width: int, colour: str) -> str:
    return f"{colour}╰{'─' * (width - 2)}╯{RESET}"

def _box_row(content: str, width: int, colour: str) -> str:
    pad = width - len(_strip_ansi(content)) - 4
    pad = max(pad, 0)
    return f"{colour}│{RESET} {content}{' ' * pad} {colour}│{RESET}"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)

# Gradient sweep for the logo: magenta → purple → blue → cyan (256-colour)
_LOGO_COLOURS = ["\033[38;5;213m", "\033[38;5;176m", "\033[38;5;140m",
                 "\033[38;5;105m", "\033[38;5;75m", "\033[38;5;81m"]
_LOGO_LINES = [
    "  ██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗",
    "  ██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝",
    "  ██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗",
    "  ██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║",
    "  ██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║",
    "  ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝",
]
LOGO = "\n" + "\n".join(
    f"{c}{BOLD}{line}{RESET}" for line, c in zip(_LOGO_LINES, _LOGO_COLOURS)
) + f"""
{GREY}  autonomous coding agent  ·  type {ACCENT}/{RESET}{GREY} for commands{RESET}
"""

PT_STYLE = PTStyle.from_dict({
    "prompt":                           "fg:#5fd7ff bold",
    "completion-menu.completion":       "bg:#1c1c1c fg:#c0c0c0",
    "completion-menu.completion.current":"bg:#003a5c fg:#5fd7ff bold",
    "completion-menu.meta.completion":  "bg:#1c1c1c fg:#767676",
    "completion-menu.meta.completion.current": "bg:#003a5c fg:#5fafff",
    "scrollbar.background":             "bg:#1c1c1c",
    "scrollbar.button":                 "bg:#005f87",
    "bottom-toolbar":                   "noreverse bg:default fg:#6c6c6c",
    "bottom-toolbar.key":               "fg:#6c6c6c",
    "bottom-toolbar.value":             "fg:#a8a8a8",
    "bottom-toolbar.warn":              "fg:#ffd75f bold",
    "bottom-toolbar.danger":            "fg:#ff5f5f bold",
})

# Short verbs shown for each tool call, e.g. "Read  agent/core.py"
TOOL_LABELS = {
    "read_file":       "Read",
    "write_file":      "Write",
    "edit_file":       "Edit",
    "run_command":     "Run",
    "list_directory":  "List",
    "search_codebase": "Search",
    "list_skills":     "Skills",
    "read_skill":      "Skill",
    "create_docx":     "Document",
    "web_search":      "Web search",
    "web_read":        "Web read",
    "fetch_url":       "Fetch",
    "git_status":      "Git status",
    "git_add":         "Git add",
    "git_commit":      "Git commit",
    "git_push":        "Git push",
    "git_branch":      "Git branch",
    "github_pr":       "GitHub PR",
}

# Result strings starting with any of these are rendered as failures
_FAIL_PREFIXES = ("Error", "[exit", "Git error", "GitHub CLI error",
                  "Web search failed", "Web read failed", "Unexpected error",
                  "Denied", "User declined")


def _git_branch() -> str:
    """Current git branch name, or '' outside a repo. Cached for 30s."""
    cached = getattr(_git_branch, "_cache", None)
    if cached and time.time() - cached[0] < 30:
        return cached[1]
    branch = ""
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        ).strip()
    except Exception:
        branch = ""
    _git_branch._cache = (time.time(), branch)
    return branch


def _fmt_tokens(n: int | None) -> str:
    if n is None:
        return "0"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _term_width(default: int = 100) -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name.replace("_", " ").capitalize())


def tool_summary(name: str, inputs: dict) -> str:
    """One-line description of a tool call's arguments."""
    inputs = inputs or {}
    if name == "read_file":
        s = inputs.get("path", "")
        if inputs.get("offset") or inputs.get("limit"):
            start = int(inputs.get("offset") or 1)
            s += f"  lines {start}-{start + int(inputs['limit']) - 1}" if inputs.get("limit") else f"  from line {start}"
        return s
    if name == "write_file":
        return f"{inputs.get('path', '')}  ({str(inputs.get('content', '')).count(chr(10)) + 1} lines)"
    if name == "run_command":
        cwd = f"  in {inputs['cwd']}" if inputs.get("cwd") else ""
        return f"$ {inputs.get('command', '')}{cwd}"
    if name == "list_directory":
        return inputs.get("path") or "."
    if name in ("git_branch", "github_pr"):
        rest = inputs.get("branch_name") or inputs.get("title") or inputs.get("pr_number") or ""
        return f"{inputs.get('action', '')} {rest}".strip()
    for key in ("path", "pattern", "query", "url", "message", "paths", "skill_name", "output_path"):
        if inputs.get(key):
            return str(inputs[key])
    return "  ".join(f"{k}={json.dumps(v)}" for k, v in inputs.items())


# ── Streaming markdown ───────────────────────────────────────────────────────

_MARKER_PREFIX_RE = re.compile(r"#{1,6}|[-*+]|>|`{1,2}|\d{1,3}\.?|-{2,3}|\*{2,3}|_{1,3}")
_HEADING_RE = re.compile(r"(#{1,6}) (.*)", re.DOTALL)
_BULLET_RE = re.compile(r"[-*+] (.*)", re.DOTALL)
_NUMBERED_RE = re.compile(r"(\d{1,3})\. (.*)", re.DOTALL)
_QUOTE_RE = re.compile(r"> ?(.*)", re.DOTALL)


class MarkdownStream:
    """
    Renders markdown incrementally as text arrives, so streamed replies are
    styled in place and never need to be erased and redrawn.

    Line-level syntax (headings, bullets, numbered lists, quotes, rules, code
    fences) is decided from the first few characters of each line; inline
    `code` and **bold** are toggled as their markers arrive. Code blocks are
    buffered one line at a time so each line can be syntax-highlighted.
    """

    def __init__(self, write):
        self._write = write
        self.ended_with_newline = True
        self._line_start = True
        self._pending = ""
        self._line_style = ""
        self._bold = False
        self._code_span = False
        self._held_star = False
        self._in_code = False
        self._code_lang = ""
        self._code_line = ""

    def feed(self, text: str):
        for ch in text:
            self._char(ch)

    def finish(self):
        if self._pending:
            self._classify(final=True)
        if self._in_code:
            if self._code_line and not self._code_line.strip().startswith("```"):
                self._emit_code_line(self._code_line)
            self._out(f"{ACCENT_DIM}  ╰─{RESET}\n")
            self._in_code = False
        if self._held_star:
            self._out("*")
            self._held_star = False
        self._out(RESET)

    # ── internals ────────────────────────────────────────────────────────────

    def _out(self, s: str):
        if s:
            self._write(s)
            visible = _strip_ansi(s)
            if visible:
                self.ended_with_newline = visible.endswith("\n")

    def _char(self, ch: str):
        if self._in_code:
            if ch != "\n":
                self._code_line += ch
                return
            line, self._code_line = self._code_line, ""
            if line.strip().startswith("```"):
                self._in_code = False
                self._out(f"{ACCENT_DIM}  ╰─{RESET}\n")
            else:
                self._emit_code_line(line)
            return
        if self._line_start:
            self._pending += ch
            self._classify(final=False)
            return
        self._inline(ch)

    def _classify(self, final: bool):
        raw = self._pending
        newline = raw.endswith("\n")
        body = raw[:-1] if newline else raw
        indent = len(body) - len(body.lstrip(" "))
        s = body.lstrip(" ")
        if not newline and not final:
            if s == "" or s.startswith("```") or _MARKER_PREFIX_RE.fullmatch(s):
                return  # could still become a marker; wait for more characters
        self._pending = ""
        self._line_start = False

        if s.startswith("```"):
            self._code_lang = s[3:].strip()
            self._in_code = True
            self._line_start = True
            self._out(f"{ACCENT_DIM}  ╭─ {self._code_lang or 'code'}{RESET}\n")
            return
        if s in ("---", "***", "___") and (newline or final):
            self._out(f"{GREY}{'─' * min(40, _term_width() - 4)}{RESET}")
            if newline:
                self._inline("\n")
            return

        rest = body
        if m := _HEADING_RE.fullmatch(s):
            self._line_style = BOLD + (ACCENT if len(m.group(1)) <= 2 else WHITE)
            self._out(self._line_style)
            rest = m.group(2)
        elif m := _BULLET_RE.fullmatch(s):
            self._out(f"{' ' * indent}{ACCENT}  •{RESET} ")
            rest = m.group(1)
        elif m := _NUMBERED_RE.fullmatch(s):
            self._out(f"{' ' * indent}  {ACCENT}{m.group(1)}.{RESET} ")
            rest = m.group(2)
        elif m := _QUOTE_RE.fullmatch(s):
            self._line_style = GREY + ITALIC
            self._out(f"{ACCENT_DIM}  ┃ {RESET}{self._line_style}")
            rest = m.group(1)

        for c in rest:
            self._inline(c)
        if newline:
            self._inline("\n")

    def _inline(self, ch: str):
        if ch == "\n":
            if self._held_star:
                self._out("*")
                self._held_star = False
            self._bold = self._code_span = False
            self._line_style = ""
            self._out(RESET + "\n")
            self._line_start = True
            return
        if self._held_star:
            self._held_star = False
            if ch == "*" and not self._code_span:
                self._bold = not self._bold
                self._out(self._style())
                return
            self._out("*")
        if ch == "*" and not self._code_span:
            self._held_star = True
            return
        if ch == "`":
            self._code_span = not self._code_span
            self._out(self._style())
            return
        self._out(ch)

    def _style(self) -> str:
        return RESET + self._line_style + (BOLD + WHITE if self._bold else "") + (ACCENT if self._code_span else "")

    def _emit_code_line(self, line: str):
        self._out(f"{ACCENT_DIM}  │{RESET} {_highlight_code(line, self._code_lang)}{RESET}\n")


# ── Diffs ────────────────────────────────────────────────────────────────────

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def render_diff(change, max_lines: int = 40) -> list[str]:
    """Coloured, line-numbered diff lines for a FileChange (header first)."""
    new_lines = change.new.splitlines()
    if change.old is None:
        out = [f"{BOLD}{change.path}{RESET}  {GREEN}new file, {len(new_lines)} lines{RESET}"]
        for i, line in enumerate(new_lines[:max_lines], 1):
            out.append(f"{GREY}{i:>4}{RESET} {GREEN}+ {line}{RESET}")
        if len(new_lines) > max_lines:
            out.append(f"{GREY}     ... {len(new_lines) - max_lines} more lines{RESET}")
        return out

    old_lines = change.old.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))[2:]
    added = sum(1 for d in diff if d.startswith("+"))
    removed = sum(1 for d in diff if d.startswith("-"))
    if not diff:
        return [f"{BOLD}{change.path}{RESET}  {GREY}no changes{RESET}"]

    out = [f"{BOLD}{change.path}{RESET}  {GREEN}+{added}{RESET} {RED}-{removed}{RESET}"]
    old_no = new_no = 0
    shown = 0
    for d in diff:
        if m := _HUNK_RE.match(d):
            old_no, new_no = int(m.group(1)), int(m.group(2))
            if shown:
                out.append(f"{GREY}   ...{RESET}")
            continue
        if shown >= max_lines:
            remaining = sum(1 for x in diff[diff.index(d):] if not x.startswith("@@"))
            out.append(f"{GREY}     ... {remaining} more diff lines{RESET}")
            break
        if d.startswith("+"):
            out.append(f"{GREY}{new_no:>4}{RESET} {GREEN}+ {d[1:]}{RESET}")
            new_no += 1
        elif d.startswith("-"):
            out.append(f"{GREY}{old_no:>4}{RESET} {RED}- {d[1:]}{RESET}")
            old_no += 1
        else:
            out.append(f"{GREY}{new_no:>4}   {d[1:]}{RESET}")
            old_no += 1
            new_no += 1
        shown += 1
    return out


class SlashCommandCompleter(Completer):
    def __init__(self, commands: list[tuple[str, str]]):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        word = text[1:]
        for name, description in self.commands:
            if name.startswith(word):
                yield Completion(
                    name,
                    start_position=-len(word),
                    display=HTML(f"<ansibrightcyan>/{name}</ansibrightcyan>"),
                    display_meta=description,
                )


class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message="Thinking"):
        self._message = message
        self._start = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            elapsed = time.time() - self._start
            sys.stdout.write(
                f"\r  {ACCENT}{frame}{RESET} {GREY}{self._message}…{RESET} "
                f"{GREY}({elapsed:.0f}s · ctrl-c to interrupt){RESET}   "
            )
            sys.stdout.flush()
            time.sleep(0.08)

    def start(self): self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


class TerminalUI:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._spinner: Spinner | None = None
        self._session: PromptSession | None = None
        self._stream: MarkdownStream | None = None
        self._status_provider = None
        self._last_was_tool = False

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup_input(self, commands: list[tuple[str, str]]):
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        self._session = PromptSession(
            completer=SlashCommandCompleter(commands),
            complete_while_typing=True,
            history=FileHistory(str(INPUT_HISTORY_FILE)),
            style=PT_STYLE,
            bottom_toolbar=self._toolbar,
        )

    def set_status_provider(self, provider):
        """
        `provider()` returns (label, value, level) tuples for the status bar
        under the prompt; level is "", "warn" or "danger".
        """
        self._status_provider = provider

    def _toolbar(self):
        if not self._status_provider:
            return ""
        try:
            items = self._status_provider()
        except Exception:
            return ""
        parts = [("class:bottom-toolbar", " ")]
        for i, (label, value, level) in enumerate(items):
            if i:
                parts.append(("class:bottom-toolbar.key", "  ·  "))
            parts.append(("class:bottom-toolbar.key", f"{label} "))
            parts.append((f"class:bottom-toolbar.{level or 'value'}", str(value)))
        return parts

    def print_logo(self):
        print(LOGO)

    def print_workdir(self, path: str, model: str | None = None, plan_mode: bool | None = None,
                      mode: str | None = None):
        """Context header: dir, branch, model, permission and plan mode."""
        bits = [f"{GREY}dir{RESET} {ACCENT}{path}{RESET}"]
        branch = _git_branch()
        if branch:
            bits.append(f"{GREY}branch{RESET} {WHITE}{branch}{RESET}")
        if model:
            bits.append(f"{GREY}model{RESET} {WHITE}{model}{RESET}")
        if mode:
            bits.append(f"{GREY}mode{RESET} {_mode_colour(mode)}{mode}{RESET}")
        if plan_mode is not None:
            bits.append(f"{GREY}plan{RESET} {WHITE}{'on' if plan_mode else 'off'}{RESET}")
        print(f"  {'   '.join(bits)}\n")

    def prompt(self) -> str:
        # Safety net: never sit at the prompt with a spinner still ticking.
        self._stop_spinner()
        self._last_was_tool = False
        try:
            if self._session:
                return self._session.prompt(HTML("<prompt>❯</prompt> ")).strip()
            return input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"

    # ── Spinner ──────────────────────────────────────────────────────────────

    def thinking(self, message: str = "Thinking"):
        # Stop any spinner that's already running first. Overwriting
        # self._spinner without stopping it would orphan the old thread,
        # which then spins forever and corrupts the prompt.
        self._stop_spinner()
        self._spinner = Spinner(message)
        self._spinner.start()

    def _stop_spinner(self):
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    # ── Agent responses (markdown rendered as it streams) ────────────────────

    def stream_start(self):
        self._stop_spinner()
        self._last_was_tool = False
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()
        self._stream = MarkdownStream(self._write)

    def stream_chunk(self, text: str):
        if self._stream is None:
            self.stream_start()
        self._stream.feed(text)

    def stream_end(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return
        stream.finish()
        sys.stdout.write("\n" if stream.ended_with_newline else "\n\n")
        sys.stdout.flush()
        self._last_was_tool = True  # a blank line was just written; tool lines can follow directly

    def agent_response(self, text: str):
        self.stream_start()
        self.stream_chunk(text)
        self.stream_end()

    @staticmethod
    def _write(s: str):
        sys.stdout.write(s)
        sys.stdout.flush()

    # ── Tool rendering ───────────────────────────────────────────────────────

    def tool_call(self, name: str, inputs: dict):
        self._stop_spinner()
        if not self._last_was_tool:
            print()
        self._last_was_tool = True
        summary = _truncate(tool_summary(name, inputs), max(30, _term_width() - len(tool_label(name)) - 10))
        print(f"  {ACCENT}●{RESET} {BOLD}{tool_label(name)}{RESET}  {GREY}{summary}{RESET}")

    def tool_running(self, name: str):
        self.thinking(f"Running {tool_label(name).lower()}")

    def tool_result(self, result: str):
        self._stop_spinner()
        failed = result.startswith(_FAIL_PREFIXES)
        lines = [l for l in result.strip().splitlines() if l.strip()] or [""]
        preview = lines[0]
        if result.startswith("[exit") and len(lines) > 1:
            preview += f"  {lines[-1].strip()}"  # exit code plus the last line, usually the summary
        preview = _truncate(preview, max(40, _term_width() - 12))
        colour = RED if failed else GREY
        more = f"  {DIM}(+{len(lines) - 1} lines){RESET}" if len(lines) > 1 and not self.verbose else ""
        print(f"    {ACCENT_DIM}⎿{RESET}  {colour}{preview}{RESET}{more}")
        if self.verbose and len(lines) > 1:
            for line in lines[1:9]:
                print(f"       {DIM}{_truncate(line, max(40, _term_width() - 10))}{RESET}")
            if len(lines) > 9:
                print(f"       {DIM}... {len(lines) - 9} more lines{RESET}")

    def tool_skipped(self, name: str):
        print(f"    {ACCENT_DIM}⎿{RESET}  {RED}{tool_label(name)} skipped by user{RESET}")

    def show_change(self, change, max_lines: int = 20):
        """Print the diff of an edit that was applied without asking."""
        for line in render_diff(change, max_lines=max_lines):
            print(f"      {line}")

    # ── Approvals ────────────────────────────────────────────────────────────

    def ask_permission(self, title: str, detail: list[str] | None = None, change=None,
                       danger: bool = False, always_label: str | None = None) -> tuple[str, str | None]:
        """
        Ask the user to approve an action. Returns (answer, feedback) where
        answer is "y", "a" (always, for the scope in always_label) or "n";
        typing anything else declines and passes the text on as feedback.
        """
        self._stop_spinner()
        colour = RED if danger else YELLOW
        print()
        print(f"  {colour}{BOLD}{title}{RESET}")
        for line in detail or []:
            print(f"    {line}")
        if change is not None:
            for line in render_diff(change):
                print(f"    {line}")
        options = [f"{GREEN}{BOLD}y{RESET} yes"]
        if always_label:
            options.append(f"{ACCENT}{BOLD}a{RESET} {always_label}")
        options.append(f"{RED}{BOLD}n{RESET} no")
        print(f"  {'   '.join(options)}   {GREY}or type what to do instead{RESET}")
        try:
            answer = input(f"  {colour}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "n", None
        lowered = answer.lower()
        if lowered in ("y", "yes"):
            return "y", None
        if always_label and lowered in ("a", "always"):
            return "a", None
        if lowered in ("", "n", "no"):
            return "n", None
        return "n", answer

    def confirm_dangerous(self, command: str) -> bool:
        answer, _ = self.ask_permission("Potentially destructive command", [f"{WHITE}$ {command}{RESET}"], danger=True)
        return answer == "y"

    # ── Per-turn summary footer ──────────────────────────────────────────────

    def turn_end(self, stats: dict):
        self._stop_spinner()
        bits = []
        turns = stats.get("turns")
        if turns:
            bits.append(f"{turns} turn{'s' if turns != 1 else ''}")
        ti, to = stats.get("input_tokens"), stats.get("output_tokens")
        if ti is not None:
            bits.append(f"↑{_fmt_tokens(ti)} ↓{_fmt_tokens(to or 0)} tok")
        secs = stats.get("seconds")
        if secs is not None:
            bits.append(f"{secs:.1f}s")
        if bits:
            print(f"  {GREY}{' · '.join(bits)}{RESET}\n")

    # ── Status messages ──────────────────────────────────────────────────────

    def error(self, message: str):
        self._stop_spinner()
        print(f"\n  {RED}✗  {message}{RESET}\n")

    def info(self, message: str):
        self._stop_spinner()
        print(f"  {GREY}{message}{RESET}")

    def success(self, message: str):
        self._stop_spinner()
        print(f"  {GREEN}✓{RESET} {message}")

    def memory_loaded(self):
        print(f"  {GREY}✓ Memory loaded from previous sessions{RESET}\n")

    def conversation_resumed(self, message_count: int):
        print(f"  {GREY}✓ Resumed conversation ({message_count} messages){RESET}\n")

    def saving_memory(self):
        sys.stdout.write(f"  {GREY}Saving memory…{RESET}")
        sys.stdout.flush()

    def memory_saved(self, title: str | None = None):
        sys.stdout.write("\r\033[K")
        if title:
            print(f"  {GREY}✓ Memory saved  {ACCENT_DIM}·{RESET}  {ITALIC}{ACCENT}\"{title}\"{RESET}")
        else:
            print(f"  {GREY}✓ Memory saved{RESET}")

    def clear_screen(self):
        os.system("cls" if os.name == "nt" else "clear")

    # ── Plan mode displays ───────────────────────────────────────────────────

    def print_plan(self, plan):
        """Pretty-print a pending Plan object awaiting confirmation."""
        self._stop_spinner()
        rows = []
        for i, step in enumerate(plan.steps, 1):
            dep = f"  {GREY}(after {', '.join(step.dependencies)}){RESET}" if step.dependencies else ""
            rows.append(f"{ACCENT}{i}{RESET}  {step.description}{dep}")
        title = f"Plan: {plan.title}"
        widest = max([len(_strip_ansi(r)) for r in rows] + [len(title) + 2])
        width = min(widest + 6, max(40, _term_width() - 4))

        print(f"\n  {_box_top(title, width, ACCENT_DIM)}")
        for r in rows:
            print(f"  {_box_row(r, width, ACCENT_DIM)}")
        print(f"  {_box_bot(width, ACCENT_DIM)}")
        print(f"  {GREY}Send any message to confirm and run  ·  {RED}/plan-reject{GREY} to cancel{RESET}\n")

    def plan_confirmed(self):
        self._stop_spinner()
        print(f"  {GREEN}✓{RESET} {GREY}Plan confirmed, executing…{RESET}")

    def plan_rejected(self):
        self._stop_spinner()
        print(f"  {RED}✗{RESET} {GREY}Plan rejected.{RESET}")

    def print_plans(self, plans: list[dict]):
        if not plans:
            print(f"\n  {GREY}No plans found in this project (.deimos/plans).{RESET}\n")
            return
        print(f"\n  {ACCENT}{BOLD}Plans{RESET}\n")
        for p in plans:
            title = p.get("title", "untitled")
            status = p.get("status", "?")
            pid = p.get("id", "?")
            created = (p.get("created_at") or "")[:16].replace("T", " ")
            n_steps = len(p.get("steps", []))
            status_colour = GREEN if status == "completed" else (RED if status == "rejected" else ACCENT)
            print(f"  {ACCENT}●{RESET} {BOLD}{WHITE}{title}{RESET}")
            print(f"      {GREY}{pid}  ·  {status_colour}{status}{RESET}{GREY}  ·  {created}  ·  {n_steps} steps{RESET}")
        print()

    def print_checkpoints(self, checkpoints: list):
        if not checkpoints:
            print(f"\n  {GREY}No checkpoints in this project yet (.deimos/checkpoints).{RESET}\n")
            return
        print(f"\n  {ACCENT}{BOLD}Checkpoints{RESET}  {GREY}newest first; /undo restores the top one{RESET}\n")
        cwd = os.getcwd()
        for cp in checkpoints:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cp.created_at))
            print(f"  {ACCENT}●{RESET} {BOLD}{WHITE}{cp.label or '(untitled)'}{RESET}")
            files = ", ".join(_relpath(p, cwd) for p in cp.paths[:4])
            more = f" +{len(cp.paths) - 4} more" if len(cp.paths) > 4 else ""
            print(f"      {GREY}{when}  ·  {len(cp.paths)} file{'s' if len(cp.paths) != 1 else ''}: {files}{more}{RESET}")
        print()

    # ── Structured displays ──────────────────────────────────────────────────

    def print_conversations(self, conversations: list[dict]):
        if not conversations:
            print(f"\n  {GREY}No past conversations found.{RESET}\n")
            return

        print(f"\n  {ACCENT}{BOLD}Past conversations{RESET}\n")
        for i, conv in enumerate(conversations, 1):
            title = conv.get("title") or "(untitled)"
            started = conv.get("started_at", "")[:16].replace("T", " ")
            count = conv.get("message_count", 0)
            full_id = conv["id"]
            bullet = f"{ACCENT_DIM}{i:>2}.{RESET}"
            print(f"  {bullet}  {BOLD}{WHITE}{title}{RESET}")
            print(f"        {GREY}{started}  ·  {count} messages{RESET}")
            print(f"        {DIM}{full_id}{RESET}")
            print()

    def print_help(self, commands):
        print(f"\n  {ACCENT}{BOLD}Commands{RESET}\n")
        width = max(len(c.usage) for c in commands)
        for c in commands:
            print(f"  {ACCENT}{c.usage:<{width + 2}}{RESET} {GREY}{c.description}{RESET}")
        print()

    def print_facts(self, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts stored yet.{RESET}\n")
            return
        print(f"\n  {ACCENT}{BOLD}User memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            conf = f.get("confidence", 0)
            freq = f.get("frequency", 1)
            bar = _conf_bar(conf)
            print(f"  {ACCENT}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
            print(f"  {' ' * key_w} {GREY}{bar}  conf {conf:.2f}  ·  seen {freq}×{RESET}")
        print()

    def print_projects(self, projects: list[str]):
        print(f"\n  {ACCENT}{BOLD}Known projects{RESET}\n")
        for p in projects:
            print(f"  {ACCENT}·{RESET}  {WHITE}{p}{RESET}")
        print()

    def print_project_facts(self, project_name: str, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts found for project '{project_name}'.{RESET}\n")
            return
        print(f"\n  {ACCENT}{BOLD}{project_name}{RESET}{GREY} · project memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            print(f"  {ACCENT}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
        print()

    def print_status(self, info: dict):
        key_w = max(len(k) for k in info) + 1
        inner_w = max(len(_strip_ansi(f"{k:<{key_w}}  {v}")) for k, v in info.items())
        width = inner_w + 8
        print(f"\n  {_box_top('status', width, ACCENT_DIM)}")
        for key, val in info.items():
            key_str = f"{ACCENT}{key:<{key_w}}{RESET}"
            val_str = f"{WHITE}{val}{RESET}"
            print(f"  {_box_row(f'{key_str}  {val_str}', width, ACCENT_DIM)}")
        print(f"  {_box_bot(width, ACCENT_DIM)}\n")


# ── helpers ──────────────────────────────────────────────────────────────────

def _mode_colour(mode: str) -> str:
    return {"read-only": BLUE, "auto": RED, "auto-edit": YELLOW}.get(mode, WHITE)

def _relpath(path: str, cwd: str) -> str:
    try:
        rel = os.path.relpath(path, cwd)
        return path if rel.startswith("..") else rel
    except ValueError:  # different drive on Windows
        return path

def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"

def _conf_bar(conf: float, width: int = 10) -> str:
    filled = int(round(conf * width))
    return "█" * filled + "░" * (width - filled)

def _highlight_code(code: str, lang: str) -> str:
    # Code is highlighted a line at a time while streaming, where guessing
    # the language is unreliable, so unlabelled blocks stay plain.
    if not code.strip() or not lang:
        return code
    try:
        lexer = get_lexer_by_name(lang, stripall=False)
    except ClassNotFound:
        return code
    try:
        return highlight(code, lexer, Terminal256Formatter(style="monokai")).rstrip("\n")
    except Exception:
        return code
