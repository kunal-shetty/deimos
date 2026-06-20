import sys
import os
import json
import threading
import itertools
import time
import re

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML

from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import Terminal256Formatter
from pygments.util import ClassNotFound

from config import INPUT_HISTORY_FILE, LOCAL_DIR

# ── Colour palette (blue/cyan theme) ─────────────────────────────────────────
AMBER     = "\033[38;5;81m"    # #5fd7ff  primary brand colour (cyan)
AMBER_DIM = "\033[38;5;67m"    # #5f87af  dimmer blue
ORANGE    = "\033[38;5;75m"    # #5fafff  accent
GREEN     = "\033[38;5;114m"   # #87d787  success / agent response
RED       = "\033[38;5;203m"   # #ff5f5f  errors / danger
CYAN      = "\033[38;5;81m"    # #5fd7ff  info highlights
GREY      = "\033[38;5;245m"   # #8a8a8a  dim text
WHITE     = "\033[97m"
BOLD      = "\033[1m"
DIM       = "\033[2m"
ITALIC    = "\033[3m"
RESET     = "\033[0m"

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

CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

LOGO = f"""
{AMBER}{BOLD}  ██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
  ██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
  ██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
  ██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
  ██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝{RESET}
{GREY}  autonomous coding agent  ·  type {AMBER}/{RESET}{GREY}help to get started{RESET}
"""

PT_STYLE = PTStyle.from_dict({
    "prompt":                           "fg:#5fd7ff bold",
    "completion-menu.completion":       "bg:#1c1c1c fg:#c0c0c0",
    "completion-menu.completion.current":"bg:#003a5c fg:#5fd7ff bold",
    "completion-menu.meta.completion":  "bg:#1c1c1c fg:#767676",
    "completion-menu.meta.completion.current": "bg:#003a5c fg:#5fafff",
    "scrollbar.background":             "bg:#1c1c1c",
    "scrollbar.button":                 "bg:#005f87",
})

TOOL_ICONS = {
    "read_file":       "📄",
    "write_file":      "✏️ ",
    "edit_file":       "🔧",
    "run_command":     "⚡",
    "list_directory":  "📁",
    "search_codebase": "🔍",
}


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
                    display=HTML(f"<ansibrightmagenta>/{name}</ansibrightmagenta>"),
                    display_meta=description,
                )


class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message="Thinking"):
        self._message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{AMBER}{frame}{RESET} {GREY}{self._message}…{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)

    def start(self): self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


class TerminalUI:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._spinner: Spinner | None = None
        self._session: PromptSession | None = None
        self._stream_active = False

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup_input(self, commands: list[tuple[str, str]]):
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        self._session = PromptSession(
            completer=SlashCommandCompleter(commands),
            complete_while_typing=True,
            history=FileHistory(str(INPUT_HISTORY_FILE)),
            style=PT_STYLE,
        )

    def print_logo(self):
        print(LOGO)

    def print_workdir(self, path: str):
        print(f"  {GREY}working in{RESET}  {AMBER}{path}{RESET}\n")

    def prompt(self) -> str:
        try:
            if self._session:
                return self._session.prompt(HTML(f"<prompt>❯</prompt> ")).strip()
            return input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"

    # ── Spinner ──────────────────────────────────────────────────────────────

    def thinking(self):
        self._spinner = Spinner("Thinking")
        self._spinner.start()

    def _stop_spinner(self):
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    # ── Streaming output ─────────────────────────────────────────────────────

    def stream_start(self):
        self._stop_spinner()
        self._stream_active = True
        self._stream_buffer = ""
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()

    def stream_chunk(self, text: str):
        """Write a streaming text chunk directly — no typewriter delay."""
        self._stream_buffer += text
        sys.stdout.write(text)
        sys.stdout.flush()

    def stream_end(self):
        """Called after streaming completes — render any code blocks found."""
        self._stream_active = False
        raw = getattr(self, "_stream_buffer", "")

        # If there were code blocks, re-render with syntax highlighting
        # (we already wrote the raw text so we need a newline either way)
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    # ── Non-streaming agent response (typewriter + code highlight) ────────────

    def agent_response(self, text: str):
        self._stop_spinner()
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()

        pos = 0
        for match in CODE_BLOCK_RE.finditer(text):
            self._typewriter(text[pos:match.start()])
            self._print_code_block(match.group(2), match.group(1))
            pos = match.end()
        self._typewriter(text[pos:])
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    def _typewriter(self, text: str):
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            if char in ".!?": time.sleep(0.055)
            elif char == ",": time.sleep(0.025)
            else:             time.sleep(0.010)

    def _print_code_block(self, code: str, lang: str):
        code = code.rstrip("\n")
        highlighted = _highlight_code(code, lang)
        label = lang or "code"
        lines = highlighted.split("\n")
        width = min(max((max(len(_strip_ansi(l)) for l in lines) + 4), 40), 100)

        sys.stdout.write("\n")
        sys.stdout.write(f"{AMBER_DIM}╭─ {label}{'─' * (width - len(label) - 3)}╮{RESET}\n")
        for line in lines:
            pad = width - len(_strip_ansi(line)) - 4
            sys.stdout.write(f"{AMBER_DIM}│{RESET} {line}{' ' * max(0, pad)} {AMBER_DIM}│{RESET}\n")
        sys.stdout.write(f"{AMBER_DIM}╰{'─' * (width - 2)}╯{RESET}\n")
        sys.stdout.flush()

    # ── Tool rendering ───────────────────────────────────────────────────────

    def tool_call(self, name: str, inputs: dict):
        self._stop_spinner()
        icon = TOOL_ICONS.get(name, "●")
        inputs = inputs or {}
        args_str = "  ".join(
            f"{GREY}{k}{RESET}={AMBER}{_truncate(json.dumps(v), 55)}{RESET}"
            for k, v in inputs.items()
        )
        print(f"  {ORANGE}{icon}{RESET} {BOLD}{AMBER}{name}{RESET}  {args_str}")

    def tool_result(self, result: str):
        lines = result.strip().splitlines() or [""]
        preview = _truncate(lines[0], 90)
        print(f"     {GREY}⎿  {preview}{RESET}")
        if self.verbose and len(lines) > 1:
            for line in lines[1:5]:
                print(f"       {DIM}{_truncate(line, 90)}{RESET}")
            if len(lines) > 5:
                print(f"       {DIM}… ({len(lines) - 5} more lines){RESET}")

    def tool_skipped(self, name: str):
        print(f"  {RED}✗{RESET}  {GREY}{name} — skipped by user{RESET}")

    # ── Safety guardrail ─────────────────────────────────────────────────────

    def confirm_dangerous(self, command: str) -> bool:
        self._stop_spinner()
        term_width = os.get_terminal_size().columns if hasattr(os, 'get_terminal_size') else 80
        w = min(term_width - 4, 80)

        print()
        print(f"  {RED}╭─ ⚠  Potentially destructive command {'─' * (w - 35)}╮{RESET}")
        cmd_lines = _wrap(command, w - 4)
        for line in cmd_lines:
            pad = w - len(line) - 4
            print(f"  {RED}│{RESET}  {WHITE}{line}{RESET}{' ' * pad}  {RED}│{RESET}")
        print(f"  {RED}╰{'─' * (w - 2)}╯{RESET}")
        print()

        try:
            answer = input(f"  {AMBER}Run this command? {GREY}[y/N]{RESET} ").strip().lower()
            print()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    # ── Status messages ──────────────────────────────────────────────────────

    def error(self, message: str):
        self._stop_spinner()
        print(f"\n  {RED}✗  {message}{RESET}\n")

    def info(self, message: str):
        self._stop_spinner()
        print(f"  {GREY}{message}{RESET}")

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
            print(f"  {GREY}✓ Memory saved  {AMBER_DIM}·{RESET}  {ITALIC}{AMBER}\"{title}\"{RESET}")
        else:
            print(f"  {GREY}✓ Memory saved{RESET}")

    def clear_screen(self):
        os.system("cls" if os.name == "nt" else "clear")

    # ── Structured displays ──────────────────────────────────────────────────

    def print_conversations(self, conversations: list[dict]):
        if not conversations:
            print(f"\n  {GREY}No past conversations found.{RESET}\n")
            return

        print(f"\n  {AMBER}{BOLD}Past conversations{RESET}\n")
        for i, conv in enumerate(conversations, 1):
            title = conv.get("title") or "(untitled)"
            started = conv.get("started_at", "")[:16].replace("T", " ")
            count = conv.get("message_count", 0)
            full_id = conv["id"]
            bullet = f"{AMBER_DIM}{i:>2}.{RESET}"
            print(f"  {bullet}  {BOLD}{WHITE}{title}{RESET}")
            print(f"        {GREY}{started}  ·  {count} messages{RESET}")
            print(f"        {DIM}{full_id}{RESET}")
            print()

    def print_help(self, commands):
        print(f"\n  {AMBER}{BOLD}Commands{RESET}\n")
        width = max(len(c.usage) for c in commands)
        for c in commands:
            print(f"  {AMBER}{c.usage:<{width + 2}}{RESET} {GREY}{c.description}{RESET}")
        print()

    def print_facts(self, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts stored yet.{RESET}\n")
            return
        print(f"\n  {AMBER}{BOLD}User memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            conf = f.get("confidence", 0)
            freq = f.get("frequency", 1)
            bar = _conf_bar(conf)
            print(f"  {AMBER}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
            print(f"  {' ' * key_w} {GREY}{bar}  conf {conf:.2f}  ·  seen {freq}×{RESET}")
        print()

    def print_projects(self, projects: list[str]):
        print(f"\n  {AMBER}{BOLD}Known projects{RESET}\n")
        for p in projects:
            print(f"  {AMBER}·{RESET}  {WHITE}{p}{RESET}")
        print()

    def print_project_facts(self, project_name: str, facts: list[dict]):
        if not facts:
            print(f"\n  {GREY}No facts found for project '{project_name}'.{RESET}\n")
            return
        print(f"\n  {AMBER}{BOLD}{project_name}{RESET}{GREY} — project memory{RESET}\n")
        key_w = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            print(f"  {AMBER}{f['key']:<{key_w}}{RESET} {WHITE}{f['value']}{RESET}")
        print()

    def print_status(self, info: dict):
        print(f"\n  {AMBER_DIM}╭─ status {'─' * 30}╮{RESET}")
        key_w = max(len(k) for k in info) + 1
        for key, val in info.items():
            key_str = f"{AMBER}{key:<{key_w}}{RESET}"
            val_str = f"{WHITE}{val}{RESET}"
            inner = f"{key_str}  {val_str}"
            pad = 36 - len(_strip_ansi(f"{key:<{key_w}}  {val}"))
            print(f"  {AMBER_DIM}│{RESET}  {inner}{' ' * max(0, pad)}  {AMBER_DIM}│{RESET}")
        print(f"  {AMBER_DIM}╰{'─' * 40}╯{RESET}\n")


# ── helpers ──────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"

def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines or [text]

def _conf_bar(conf: float, width: int = 10) -> str:
    filled = int(round(conf * width))
    return "█" * filled + "░" * (width - filled)

def _highlight_code(code: str, lang: str) -> str:
    try:
        lexer = get_lexer_by_name(lang, stripall=True) if lang else guess_lexer(code)
    except ClassNotFound:
        return code
    try:
        return highlight(code, lexer, Terminal256Formatter(style="monokai")).rstrip("\n")
    except Exception:
        return code