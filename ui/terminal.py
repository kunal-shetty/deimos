import sys
import os
import re
import difflib
import random
import threading
import subprocess
import time
import json

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style as PTStyle

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
FAINT      = "\033[38;5;240m"   # #585858  rules, hints
WHITE      = "\033[97m"
BOLD       = "\033[1m"
DIM        = "\033[2m"
ITALIC     = "\033[3m"
RESET      = "\033[0m"
ADD_BG     = "\033[48;5;22m"    # dark green bar behind added lines
DEL_BG     = "\033[48;5;52m"    # dark red bar behind removed lines

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _fit(s: str, width: int, pad: bool = True) -> str:
    """Truncate a string with ANSI codes to `width` visible chars (with …), optionally padding."""
    overflow = len(_strip_ansi(s)) > width
    out, visible = [], 0
    for m in re.finditer(r"\033\[[0-9;]*m|.", s, re.DOTALL):
        tok = m.group(0)
        if tok.startswith("\033"):
            out.append(tok)
            continue
        if overflow and visible == width - 1:
            out.append("…" + RESET)
            visible += 1
            break
        out.append(tok)
        visible += 1
    text = "".join(out)
    return text + " " * (width - visible) if pad and visible < width else text


# Box-drawing helpers
def _box_top(label: str, width: int, colour: str) -> str:
    label_str = f" {label} " if label else ""
    line = "─" * max(0, width - len(_strip_ansi(label_str)) - 3)
    return f"{colour}╭─{RESET}{label_str}{colour}{line}╮{RESET}"

def _box_bot(width: int, colour: str) -> str:
    return f"{colour}╰{'─' * (width - 2)}╯{RESET}"

def _box_row(content: str, width: int, colour: str) -> str:
    return f"{colour}│{RESET} {_fit(content, width - 4)} {colour}│{RESET}"


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
) + "\n"

PT_STYLE = PTStyle.from_dict({
    "prompt":                           "fg:#5fd7ff bold",
    "rule":                             "fg:#585858",
    "completion-menu.completion":       "bg:#1c1c1c fg:#c0c0c0",
    "completion-menu.completion.current":"bg:#003a5c fg:#5fd7ff bold",
    "completion-menu.meta.completion":  "bg:#1c1c1c fg:#767676",
    "completion-menu.meta.completion.current": "bg:#003a5c fg:#5fafff",
    "scrollbar.background":             "bg:#1c1c1c",
    "scrollbar.button":                 "bg:#005f87",
    "bottom-toolbar":                   "noreverse bg:default fg:#6c6c6c",
    "bottom-toolbar.hint":              "fg:#6c6c6c",
    "bottom-toolbar.value":             "fg:#8a8a8a",
    "bottom-toolbar.warn":              "fg:#ffd75f",
    "bottom-toolbar.danger":            "fg:#ff5f5f",
    "bottom-toolbar.info":              "fg:#5fafff",
})

# Display names for tool calls, e.g. "Read(agent/core.py)"
TOOL_LABELS = {
    "read_file":       "Read",
    "write_file":      "Write",
    "edit_file":       "Update",
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
    "delegate":        "Delegate",
}

# Result strings starting with any of these are rendered as failures
_FAIL_PREFIXES = ("Error", "[exit", "Git error", "GitHub CLI error",
                  "Web search failed", "Web read failed", "Unexpected error",
                  "Denied", "User declined")

THINKING_WORDS = ["Thinking", "Working", "Reasoning", "Considering", "Pondering", "Figuring"]

# Mode indicator shown under the input box, and the order Shift+Tab cycles through
MODE_FOOTER = {
    "ask":       ("", ""),
    "auto-edit": ("▸▸ auto-edit on", "warn"),
    "auto":      ("▸▸ auto on", "danger"),
    "read-only": ("▸▸ read-only", "info"),
}


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
        return max(40, os.get_terminal_size().columns)
    except OSError:
        return default


def stdin_is_terminal() -> bool:
    """
    True when a person can type at stdin. On Windows isatty() is also true
    for the NUL device, so ask the console API whether it's a real console.
    """
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_uint()
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:
        return False


def _interactive() -> bool:
    try:
        return stdin_is_terminal() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name.replace("_", " ").capitalize())


def tool_summary(name: str, inputs: dict) -> str:
    """One-line description of a tool call's arguments."""
    inputs = inputs or {}
    if name == "read_file":
        s = inputs.get("path", "")
        if inputs.get("offset") or inputs.get("limit"):
            start = int(inputs.get("offset") or 1)
            s += f", lines {start}-{start + int(inputs['limit']) - 1}" if inputs.get("limit") else f", from line {start}"
        return s
    if name == "write_file":
        lines = str(inputs.get("content", "")).count(chr(10)) + 1
        return f"{inputs.get('path', '')}, {lines} line{'s' if lines != 1 else ''}"
    if name == "delegate":
        tasks = [t for t in inputs.get("tasks") or [] if isinstance(t, dict)]
        ids = ", ".join(str(t.get("id") or f"t{i}") for i, t in enumerate(tasks, 1))
        return f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}: {ids}"
    if name == "run_command":
        cwd = f"  (in {inputs['cwd']})" if inputs.get("cwd") else ""
        return f"{inputs.get('command', '')}{cwd}"
    if name == "list_directory":
        return inputs.get("path") or "."
    if name in ("git_branch", "github_pr"):
        rest = inputs.get("branch_name") or inputs.get("title") or inputs.get("pr_number") or ""
        return f"{inputs.get('action', '')} {rest}".strip()
    for key in ("path", "pattern", "query", "url", "message", "paths", "skill_name", "output_path"):
        if inputs.get(key):
            return str(inputs[key])
    return "  ".join(f"{k}={json.dumps(v)}" for k, v in inputs.items())


def result_lines(name: str, result: str, verbose: bool = False) -> tuple[str, list[str], int]:
    """
    Summarize a tool result for display: (headline, detail lines, hidden count).
    Reads and listings collapse to a count; command output shows its first lines.
    """
    lines = [l.rstrip() for l in result.strip().splitlines()]
    nonblank = [l for l in lines if l.strip()]
    if not nonblank:
        return "(no output)", [], 0
    failed = result.startswith(_FAIL_PREFIXES)
    keep = 20 if verbose else 3

    if not failed and name == "read_file":
        m = re.match(r"\[lines (\d+)-(\d+) of (\d+)\]", lines[0])
        return (f"Read lines {m.group(1)}-{m.group(2)} of {m.group(3)}" if m
                else f"Read {len(lines)} line{'s' if len(lines) != 1 else ''}"), [], 0
    if not failed and name in ("list_directory", "list_skills"):
        return f"Listed {len(nonblank)} entr{'ies' if len(nonblank) != 1 else 'y'}", [], 0
    if not failed and name in ("web_read", "fetch_url"):
        return f"Fetched {len(result):,} characters", [], 0

    head, rest = nonblank[0], nonblank[1:]
    if result.startswith("[exit") and rest:
        # exit code, then the end of the output, which usually holds the summary
        return head, rest[-keep:], max(0, len(rest) - keep)
    return head, rest[:keep], max(0, len(rest) - keep)


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
    Every line after the first is prefixed with `indent`.
    """

    def __init__(self, write, indent: str = ""):
        self._write = write
        self._indent = indent
        self._first_line = True
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
            self._out(f"{self._lead()}{ACCENT_DIM}╰─{RESET}\n")
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

    def _lead(self) -> str:
        """Indent for a new output line (the first line sits after the bullet)."""
        if self._first_line:
            self._first_line = False
            return ""
        return self._indent

    def _char(self, ch: str):
        if self._in_code:
            if ch != "\n":
                self._code_line += ch
                return
            line, self._code_line = self._code_line, ""
            if line.strip().startswith("```"):
                self._in_code = False
                self._out(f"{self._lead()}{ACCENT_DIM}╰─{RESET}\n")
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
            self._out(f"{self._lead()}{ACCENT_DIM}╭─ {self._code_lang or 'code'}{RESET}\n")
            return
        lead = "" if (not s and newline) else self._lead()
        if s in ("---", "***", "___") and (newline or final):
            self._out(f"{lead}{FAINT}{'─' * min(40, _term_width() - 8)}{RESET}")
            if newline:
                self._inline("\n")
            return

        rest = body
        if m := _HEADING_RE.fullmatch(s):
            self._line_style = BOLD + (WHITE if len(m.group(1)) <= 2 else GREY)
            self._out(lead + self._line_style)
            rest = m.group(2)
        elif m := _BULLET_RE.fullmatch(s):
            self._out(f"{lead}{' ' * indent}{GREY}•{RESET} ")
            rest = m.group(1)
        elif m := _NUMBERED_RE.fullmatch(s):
            self._out(f"{lead}{' ' * indent}{GREY}{m.group(1)}.{RESET} ")
            rest = m.group(2)
        elif m := _QUOTE_RE.fullmatch(s):
            self._line_style = GREY + ITALIC
            self._out(f"{lead}{FAINT}┃ {RESET}{self._line_style}")
            rest = m.group(1)
        else:
            self._out(lead)

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
        self._out(f"{self._lead()}{ACCENT_DIM}│{RESET} {_highlight_code(line, self._code_lang)}{RESET}\n")


# ── Diffs ────────────────────────────────────────────────────────────────────

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def diff_headline(change) -> str:
    if change.old is None:
        return f"Create {change.path} ({_plural(len(change.new.splitlines()), 'line')})"
    diff = list(difflib.unified_diff(change.old.splitlines(), change.new.splitlines(), lineterm="", n=0))[2:]
    added = sum(1 for d in diff if d.startswith("+"))
    removed = sum(1 for d in diff if d.startswith("-"))
    if not added and not removed:
        return f"No changes to {change.path}"
    parts = [p for p in (_plural(added, "addition") if added else "", _plural(removed, "removal") if removed else "") if p]
    return f"Update {change.path} with {' and '.join(parts)}"


def render_diff(change, max_lines: int = 40, width: int | None = None) -> list[str]:
    """
    Line-numbered diff lines for a FileChange. Added and removed lines get a
    coloured background bar, padded to `width` when given.
    """
    def bar(bg: str, fg: str, text: str) -> str:
        body = _fit(text, width) if width else text
        return f"{bg}{fg}{body}{RESET}"

    new_lines = change.new.splitlines()
    if change.old is None:
        out = [bar(ADD_BG, WHITE, f"{i:>4} + {line}") for i, line in enumerate(new_lines[:max_lines], 1)]
        if len(new_lines) > max_lines:
            out.append(f"{GREY}     ... {len(new_lines) - max_lines} more lines{RESET}")
        return out

    diff = list(difflib.unified_diff(change.old.splitlines(), new_lines, lineterm="", n=2))[2:]
    out = []
    old_no = new_no = 0
    shown = 0
    for i, d in enumerate(diff):
        if m := _HUNK_RE.match(d):
            old_no, new_no = int(m.group(1)), int(m.group(2))
            if shown:
                out.append(f"{FAINT}   ...{RESET}")
            continue
        if shown >= max_lines:
            remaining = sum(1 for x in diff[i:] if not x.startswith("@@"))
            out.append(f"{GREY}     ... {remaining} more diff lines{RESET}")
            break
        if d.startswith("+"):
            out.append(bar(ADD_BG, WHITE, f"{new_no:>4} + {d[1:]}"))
            new_no += 1
        elif d.startswith("-"):
            out.append(bar(DEL_BG, WHITE, f"{old_no:>4} - {d[1:]}"))
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
        if not text.startswith("/") or "\n" in text:
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
    """Animated status line: a pulsing glyph and a highlight sweeping across the message."""

    FRAMES = ["·", "✢", "✶", "✻", "✽", "✻", "✶", "✢"]

    def __init__(self, message="Thinking", prefix: str = ""):
        self._message = message
        self._prefix = prefix
        self._start = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        tick = 0
        width = len(self._message) + 6
        while not self._stop.is_set():
            frame = self.FRAMES[(tick // 2) % len(self.FRAMES)]
            pos = tick % (width + 8) - 4
            text = "".join(
                (WHITE if abs(i - pos) <= 1 else ACCENT) + ch for i, ch in enumerate(self._message + "…")
            )
            elapsed = time.time() - self._start
            sys.stdout.write(
                f"\r{self._prefix}{ACCENT}{frame}{RESET} {text}{RESET} "
                f"{GREY}({elapsed:.0f}s · ctrl+c to interrupt){RESET}\033[K"
            )
            sys.stdout.flush()
            tick += 1
            time.sleep(0.09)

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
        self._mode_cycler = None
        self._need_gap = False  # print a blank line before the next block (response, tool call, input)
        self._tool_header: tuple[str, str] | None = None  # (label, summary) of the open tool line
        self._tool_header_clean = False  # nothing printed since the tool line

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup_input(self, commands: list[tuple[str, str]]):
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        self._session = PromptSession(
            completer=SlashCommandCompleter(commands),
            complete_while_typing=True,
            history=FileHistory(str(INPUT_HISTORY_FILE)),
            style=PT_STYLE,
            bottom_toolbar=self._toolbar,
            key_bindings=self._key_bindings(),
            prompt_continuation=lambda width, line_number, wrap_count: "  ",
            erase_when_done=True,
            reserve_space_for_menu=6,
        )

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("s-tab")
        def _(event):
            if self._mode_cycler:
                self._mode_cycler()
                event.app.invalidate()

        @kb.add("escape", "enter")  # alt+enter: new line
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("enter")
        def _(event):
            buf = event.current_buffer
            if buf.complete_state and buf.complete_state.current_completion:
                buf.apply_completion(buf.complete_state.current_completion)
                return
            if buf.document.text_before_cursor.endswith("\\"):  # backslash + enter: new line
                buf.delete_before_cursor(1)
                buf.insert_text("\n")
                return
            buf.validate_and_handle()

        return kb

    def set_status_provider(self, provider):
        """
        `provider()` returns a dict for the footer under the input box:
        mode, model, context (0-1), plan_pending.
        """
        self._status_provider = provider

    def set_mode_cycler(self, cycler):
        """`cycler()` advances the permission mode (bound to Shift+Tab)."""
        self._mode_cycler = cycler

    def _prompt_message(self):
        return [("class:rule", "─" * _term_width() + "\n"), ("class:prompt", "> ")]

    def _toolbar(self):
        width = _term_width()
        parts = [("class:rule", "─" * width + "\n")]
        status = {}
        if self._status_provider:
            try:
                status = self._status_provider() or {}
            except Exception:
                status = {}

        left = []
        mode_text, mode_level = MODE_FOOTER.get(status.get("mode", "ask"), ("", ""))
        if mode_text:
            left.append((f"class:bottom-toolbar.{mode_level}", mode_text))
            left.append(("class:bottom-toolbar.hint", " (shift+tab to cycle)"))
        else:
            left.append(("class:bottom-toolbar.hint", "/ for commands · shift+tab to change mode · \\ + enter for a new line"))
        if status.get("plan_pending"):
            left.append(("class:bottom-toolbar.hint", "  ·  "))
            left.append(("class:bottom-toolbar.warn", "plan awaiting confirmation"))

        right = []
        if status.get("model"):
            right.append(("class:bottom-toolbar.value", status["model"]))
        if "context" in status:
            used = status["context"]
            level = "danger" if used > 0.9 else ("warn" if used > 0.7 else "value")
            right.append(("class:bottom-toolbar.hint", "  ·  context "))
            right.append((f"class:bottom-toolbar.{level}", f"{used:.0%}"))

        used_width = sum(len(t) for _, t in left + right) + 2
        gap = max(2, width - used_width)
        return parts + [("", " ")] + left + [("", " " * gap)] + right

    def print_logo(self):
        print(LOGO)

    def print_workdir(self, path: str, model: str | None = None, plan_mode: bool | None = None,
                      mode: str | None = None):
        """Welcome box: name, how to get started, and the session's context."""
        width = min(_term_width() - 4, 72)
        branch = _git_branch()
        rows = [
            f"{ACCENT}✻{RESET} {BOLD}Welcome to Deimos{RESET}",
            "",
            f"  {GREY}/help for commands, /init to write a DEIMOS.md for this project{RESET}",
            "",
            f"  {GREY}cwd:{RESET}    {path}" + (f"  {GREY}({branch}){RESET}" if branch else ""),
        ]
        if model:
            rows.append(f"  {GREY}model:{RESET}  {model}")
        if mode or plan_mode is not None:
            bits = []
            if mode:
                bits.append(f"{_mode_colour(mode)}{mode}{RESET}")
            if plan_mode is not None:
                bits.append(f"plan mode {'on' if plan_mode else 'off'}")
            rows.append(f"  {GREY}mode:{RESET}   " + f"{GREY} · {RESET}".join(bits))
        print(f"  {_box_top('', width, ACCENT_DIM)}")
        for r in rows:
            print(f"  {_box_row(r, width, ACCENT_DIM)}")
        print(f"  {_box_bot(width, ACCENT_DIM)}\n")

    def prompt(self) -> str:
        # Safety net: never sit at the prompt with a spinner still ticking.
        self._stop_spinner()
        self._gap()
        self._tool_header = None
        try:
            if self._session:
                text = self._session.prompt(self._prompt_message).strip()
            else:
                text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"
        if text and self._session:
            self._echo_user(text)
        return text

    def _echo_user(self, text: str):
        """Leave the submitted message in the scrollback as a quiet '> message' block."""
        lines = text.splitlines() or [""]
        print(f"{GREY}> {lines[0]}{RESET}")
        for line in lines[1:]:
            print(f"{GREY}  {line}{RESET}")
        self._need_gap = True

    def _gap(self):
        if self._need_gap:
            print()
            self._need_gap = False

    # ── Spinner ──────────────────────────────────────────────────────────────

    def thinking(self, message: str | None = None):
        # Stop any spinner that's already running first. Overwriting
        # self._spinner without stopping it would orphan the old thread,
        # which then spins forever and corrupts the prompt.
        self._stop_spinner()
        if message is None:
            message = random.choice(THINKING_WORDS)
        if not self._stream:
            self._gap()
        self._spinner = Spinner(message)
        self._spinner.start()

    def _stop_spinner(self):
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    def _mark_dirty(self):
        """Something was printed after the open tool line, so it can't be recoloured in place."""
        self._stop_spinner()
        self._tool_header_clean = False

    # ── Agent responses (markdown rendered as it streams) ────────────────────

    def stream_start(self):
        self._mark_dirty()
        self._gap()
        sys.stdout.write(f"{WHITE}●{RESET} ")
        sys.stdout.flush()
        self._stream = MarkdownStream(self._write, indent="  ")

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
        self._need_gap = False  # the reply already ends with a blank line

    def agent_response(self, text: str):
        self.stream_start()
        self.stream_chunk(text)
        self.stream_end()

    @staticmethod
    def _write(s: str):
        sys.stdout.write(s)
        sys.stdout.flush()

    # ── Tool rendering ───────────────────────────────────────────────────────

    def _tool_line(self, bullet_colour: str) -> str:
        label, summary = self._tool_header
        room = max(10, _term_width() - len(label) - 8)
        return f"{bullet_colour}●{RESET} {BOLD}{label}{RESET}{GREY}({_fit(summary, room, pad=False)}){RESET}"

    def tool_call(self, name: str, inputs: dict):
        self._stop_spinner()
        self._gap()
        self._tool_header = (tool_label(name), tool_summary(name, inputs))
        self._tool_name = name
        print(self._tool_line(GREY))
        self._tool_header_clean = True

    def tool_running(self, name: str):
        self._stop_spinner()
        self._spinner = Spinner("Running", prefix=f"  {FAINT}⎿{RESET}  ")
        self._spinner.start()

    def tool_result(self, result: str):
        self._stop_spinner()
        failed = result.startswith(_FAIL_PREFIXES)
        if self._tool_header and self._tool_header_clean:
            # Recolour the tool's bullet now that we know how it went
            sys.stdout.write(f"\033[1A\r\033[K{self._tool_line(RED if failed else GREEN)}\n")
        self._tool_header_clean = False

        head, detail, hidden = result_lines(getattr(self, "_tool_name", ""), result, self.verbose)
        width = _term_width() - 8
        colour = RED if failed else GREY
        print(f"  {FAINT}⎿{RESET}  {colour}{_fit(head, width, pad=False)}{RESET}")
        for line in detail:
            print(f"     {GREY}{_fit(line, width, pad=False)}{RESET}")
        if hidden:
            print(f"     {FAINT}… +{hidden} lines{RESET}")
        self._need_gap = True

    def tool_skipped(self, name: str):
        self._mark_dirty()
        print(f"  {FAINT}⎿{RESET}  {RED}{tool_label(name)} skipped by user{RESET}")

    def show_change(self, change, max_lines: int = 20):
        """Print the diff of an edit that was applied without asking."""
        self._mark_dirty()
        width = min(_term_width() - 6, 120)
        print(f"  {FAINT}⎿{RESET}  {diff_headline(change)}")
        for line in render_diff(change, max_lines=max_lines, width=width):
            print(f"     {line}")

    # ── Approvals ────────────────────────────────────────────────────────────

    def ask_permission(self, title: str, detail: list[str] | None = None, change=None,
                       danger: bool = False, always_label: str | None = None,
                       question: str | None = None) -> tuple[str, str | None]:
        """
        Ask the user to approve an action in a bordered panel. Returns
        (answer, feedback): "y", "a" (yes and don't ask again for
        `always_label` this session) or "n", with optional feedback text.
        Interactive terminals get an arrow-key menu; otherwise a typed answer.
        """
        self._mark_dirty()
        colour = RED if danger else YELLOW
        width = min(_term_width() - 4, 120)
        inner = width - 4

        body = []
        if change is not None:
            body.append(f"{BOLD}{diff_headline(change)}{RESET}")
            body.extend(render_diff(change, width=inner))
            body.append("")
        for line in detail or []:
            body.append(line)
        if detail:
            body.append("")
        body.append(question or "Do you want to proceed?")

        options = ["Yes"]
        if always_label:
            options.append(f"Yes, and don't ask again for {always_label} this session")
        options.append("No, and tell Deimos what to do differently")

        panel = [_box_top(f"{colour}{BOLD}{title}{RESET}", width, colour)]
        panel += [_box_row(line, width, colour) for line in body]

        if _interactive():
            choice = self._select_option(panel, options, width, colour)
        else:
            choice = self._typed_option(panel, options, width, colour)

        if choice is None or choice == len(options) - 1:
            feedback = self._ask_feedback() if choice is not None else None
            print(f"  {FAINT}⎿{RESET}  {RED}Declined{RESET}" + (f"{GREY}: {feedback}{RESET}" if feedback else ""))
            return "n", feedback
        if always_label and choice == 1:
            print(f"  {FAINT}⎿{RESET}  {GREEN}Allowed{RESET}{GREY} for {always_label} this session{RESET}")
            return "a", None
        print(f"  {FAINT}⎿{RESET}  {GREEN}Allowed{RESET}")
        return "y", None

    def _select_option(self, panel: list[str], options: list[str], width: int, colour: str) -> int | None:
        """Arrow keys or digits choose, enter confirms, esc declines. Returns index or None."""
        selected = [0]

        def render():
            rows = list(panel) + [_box_row("", width, colour)]
            for i, opt in enumerate(options):
                if i == selected[0]:
                    rows.append(_box_row(f"{ACCENT}❯ {i + 1}. {opt}{RESET}", width, colour))
                else:
                    rows.append(_box_row(f"{GREY}  {i + 1}. {opt}{RESET}", width, colour))
            rows.append(_box_bot(width, colour))
            rows.append(f"  {FAINT}↑/↓ or 1-{len(options)} to choose · enter to confirm · esc to decline{RESET}")
            return ANSI("\n".join("  " + r for r in rows))

        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            selected[0] = (selected[0] - 1) % len(options)

        @kb.add("down")
        @kb.add("tab")
        def _(event):
            selected[0] = (selected[0] + 1) % len(options)

        @kb.add("enter")
        def _(event):
            event.app.exit(result=selected[0])

        @kb.add("escape")
        @kb.add("c-c")
        def _(event):
            event.app.exit(result=None)

        for i in range(len(options)):
            @kb.add(str(i + 1))
            def _(event, i=i):
                event.app.exit(result=i)

        app = Application(
            layout=Layout(Window(FormattedTextControl(render), dont_extend_height=True)),
            key_bindings=kb, style=PT_STYLE, erase_when_done=True, full_screen=False,
        )
        print()
        try:
            choice = app.run()
        except (EOFError, KeyboardInterrupt):
            choice = None
        # Keep a static copy of the panel (without the menu) in the scrollback
        for row in panel + [_box_bot(width, colour)]:
            print("  " + row)
        return choice

    def _typed_option(self, panel: list[str], options: list[str], width: int, colour: str) -> int | None:
        print()
        rows = list(panel) + [_box_row("", width, colour)]
        rows += [_box_row(f"{GREY}{i + 1}. {opt}{RESET}", width, colour) for i, opt in enumerate(options)]
        rows.append(_box_bot(width, colour))
        for row in rows:
            print("  " + row)
        try:
            answer = input(f"  {colour}>{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in ("1", "y", "yes"):
            return 0
        if len(options) == 3 and answer in ("2", "a", "always"):
            return 1
        if answer in ("", str(len(options)), "n", "no"):
            return len(options) - 1
        self._typed_feedback = answer  # free text declines and becomes the feedback
        return len(options) - 1

    def _ask_feedback(self) -> str | None:
        typed = getattr(self, "_typed_feedback", None)
        if typed is not None:
            self._typed_feedback = None
            return typed
        if not _interactive():
            return None
        try:
            session = PromptSession(style=PT_STYLE, erase_when_done=True)
            text = session.prompt(HTML(
                "  <ansibrightblack>What should Deimos do instead? (enter to skip)</ansibrightblack>\n"
                "  <prompt>&gt;</prompt> "
            )).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return text or None

    def confirm_dangerous(self, command: str) -> bool:
        answer, _ = self.ask_permission("Potentially destructive command", [f"{WHITE}$ {command}{RESET}"],
                                        danger=True, question="Do you want to run this command?")
        return answer == "y"

    # ── Per-turn summary footer ──────────────────────────────────────────────

    def turn_end(self, stats: dict):
        self._mark_dirty()
        bits = []
        turns = stats.get("turns")
        if turns:
            bits.append(f"{turns} step{'s' if turns != 1 else ''}")
        ti, to = stats.get("input_tokens"), stats.get("output_tokens")
        if ti is not None:
            bits.append(f"↑ {_fmt_tokens(ti)} ↓ {_fmt_tokens(to or 0)} tokens")
        secs = stats.get("seconds")
        if secs is not None:
            bits.append(f"{secs:.1f}s")
        if bits:
            print(f"  {FAINT}{' · '.join(bits)}{RESET}")
        self._need_gap = True

    # ── Status messages ──────────────────────────────────────────────────────

    def error(self, message: str):
        self._mark_dirty()
        print(f"\n  {RED}✗ {message}{RESET}\n")
        self._need_gap = False

    def info(self, message: str):
        self._mark_dirty()
        print(f"  {GREY}{message}{RESET}")

    def success(self, message: str):
        self._mark_dirty()
        print(f"  {GREEN}✓{RESET} {message}")

    def memory_loaded(self):
        print(f"  {GREY}✓ Memory loaded from previous sessions{RESET}")

    def conversation_resumed(self, message_count: int):
        print(f"  {GREY}✓ Resumed conversation ({message_count} messages){RESET}")

    def saving_memory(self):
        self._mark_dirty()
        sys.stdout.write(f"\n  {GREY}Saving memory…{RESET}")
        sys.stdout.flush()

    def memory_saved(self, title: str | None = None):
        sys.stdout.write("\r\033[K")
        if title:
            print(f"  {GREY}✓ Memory saved · {RESET}{ITALIC}{ACCENT}\"{title}\"{RESET}")
        else:
            print(f"  {GREY}✓ Memory saved{RESET}")

    def clear_screen(self):
        os.system("cls" if os.name == "nt" else "clear")

    # ── Plan mode displays ───────────────────────────────────────────────────

    def print_plan(self, plan):
        """Pretty-print a pending Plan object awaiting confirmation."""
        self._mark_dirty()
        width = min(_term_width() - 4, 100)
        rows = []
        for i, step in enumerate(plan.steps, 1):
            dep = f"  {FAINT}after {', '.join(step.dependencies)}{RESET}" if step.dependencies else ""
            rows.append(f"{GREY}{i}.{RESET} {step.description}{dep}")
        print()
        print(f"  {_box_top(f'{BOLD}Plan: {plan.title}{RESET}', width, ACCENT_DIM)}")
        for r in rows:
            print(f"  {_box_row(r, width, ACCENT_DIM)}")
        print(f"  {_box_bot(width, ACCENT_DIM)}")
        print(f"  {FAINT}Send any message to run this plan · /plan-reject to cancel{RESET}\n")

    def plan_confirmed(self):
        self._mark_dirty()
        print(f"  {GREEN}✓{RESET} {GREY}Plan confirmed, executing…{RESET}")

    def plan_rejected(self):
        self._mark_dirty()
        print(f"  {RED}✗{RESET} {GREY}Plan rejected.{RESET}")

    def print_plans(self, plans: list[dict]):
        if not plans:
            print(f"\n  {GREY}No plans found in this project (.deimos/plans).{RESET}\n")
            return
        print(f"\n  {BOLD}Plans{RESET}\n")
        for p in plans:
            title = p.get("title", "untitled")
            status = p.get("status", "?")
            pid = p.get("id", "?")
            created = (p.get("created_at") or "")[:16].replace("T", " ")
            n_steps = len(p.get("steps", []))
            status_colour = GREEN if status == "completed" else (RED if status == "rejected" else ACCENT)
            print(f"  {GREY}●{RESET} {WHITE}{title}{RESET}")
            print(f"    {GREY}{pid} · {status_colour}{status}{RESET}{GREY} · {created} · {n_steps} steps{RESET}")
        print()

    def print_checkpoints(self, checkpoints: list):
        if not checkpoints:
            print(f"\n  {GREY}No checkpoints in this project yet (.deimos/checkpoints).{RESET}\n")
            return
        print(f"\n  {BOLD}Checkpoints{RESET}  {GREY}newest first · /undo restores the top one{RESET}\n")
        cwd = os.getcwd()
        for cp in checkpoints:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cp.created_at))
            print(f"  {GREY}●{RESET} {WHITE}{cp.label or '(untitled)'}{RESET}")
            files = ", ".join(_relpath(p, cwd) for p in cp.paths[:4])
            more = f" +{len(cp.paths) - 4} more" if len(cp.paths) > 4 else ""
            print(f"    {GREY}{when} · {_plural(len(cp.paths), 'file')}: {files}{more}{RESET}")
        print()

    # ── Structured displays ──────────────────────────────────────────────────

    def print_conversations(self, conversations: list[dict]):
        if not conversations:
            print(f"\n  {GREY}No past conversations found.{RESET}\n")
            return

        print(f"\n  {BOLD}Past conversations{RESET}\n")
        for i, conv in enumerate(conversations, 1):
            title = conv.get("title") or "(untitled)"
            started = conv.get("started_at", "")[:16].replace("T", " ")
            count = conv.get("message_count", 0)
            full_id = conv["id"]
            print(f"  {GREY}{i:>2}.{RESET} {WHITE}{title}{RESET}")
            print(f"      {GREY}{started} · {count} messages{RESET}")
            print(f"      {FAINT}{full_id}{RESET}")
        print()

    def print_help(self, commands):
        print(f"\n  {BOLD}Commands{RESET}\n")
        width = max(len(c.usage) for c in commands)
        for c in commands:
            print(f"  {ACCENT}{c.usage:<{width + 2}}{RESET} {GREY}{c.description}{RESET}")
        print(f"\n  {BOLD}Keys{RESET}\n")
        for keys, what in [("shift+tab", "cycle permission mode"), ("\\ + enter", "new line (or alt+enter)"),
                           ("ctrl+c", "interrupt the agent"), ("tab", "complete a /command")]:
            print(f"  {ACCENT}{keys:<{width + 2}}{RESET} {GREY}{what}{RESET}")
        print()

    def print_facts(self, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts stored yet.{RESET}\n")
            return
        print(f"\n  {BOLD}User memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            conf = f.get("confidence", 0)
            freq = f.get("frequency", 1)
            bar = _conf_bar(conf)
            print(f"  {ACCENT}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
            print(f"  {' ' * key_w} {GREY}{bar}  conf {conf:.2f} · seen {freq}×{RESET}")
        print()

    def print_projects(self, projects: list[str]):
        print(f"\n  {BOLD}Known projects{RESET}\n")
        for p in projects:
            print(f"  {GREY}●{RESET} {WHITE}{p}{RESET}")
        print()

    def print_project_facts(self, project_name: str, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts found for project '{project_name}'.{RESET}\n")
            return
        print(f"\n  {BOLD}{project_name}{RESET}{GREY} · project memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            print(f"  {ACCENT}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
        print()

    def print_status(self, info: dict):
        key_w = max(len(k) for k in info) + 1
        inner_w = max(len(_strip_ansi(f"{k:<{key_w}}  {v}")) for k, v in info.items())
        width = min(inner_w + 6, _term_width() - 4)
        print(f"\n  {_box_top(f'{BOLD}Status{RESET}', width, ACCENT_DIM)}")
        for key, val in info.items():
            print(f"  {_box_row(f'{GREY}{key:<{key_w}}{RESET} {val}', width, ACCENT_DIM)}")
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
