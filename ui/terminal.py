import sys
import os
import json
import shutil
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


CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

LOGO = f"""{CYAN}{BOLD}
  ██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
  ██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
  ██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
  ██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
  ██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
{RESET}{DIM}  autonomous coding agent{RESET}
"""

CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

PT_STYLE = PTStyle.from_dict({
    "prompt": "fg:#00d7ff bold",
    "completion-menu.completion": "bg:#1c1c1c fg:#cccccc",
    "completion-menu.completion.current": "bg:#444444 fg:#ffffff bold",
    "completion-menu.meta.completion": "bg:#1c1c1c fg:#888888",
    "completion-menu.meta.completion.current": "bg:#444444 fg:#dddddd",
    "scrollbar.background": "bg:#1c1c1c",
    "scrollbar.button": "bg:#444444",
})


class SlashCommandCompleter(Completer):
    """Live dropdown completer for '/' commands."""

    def __init__(self, commands: list[tuple[str, str]]):
        # commands: list of (name, description)
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
                    display=f"/{name}",
                    display_meta=description,
                )


class Spinner:
    """Simple terminal spinner shown while the LLM is thinking."""

    def __init__(self, message="Thinking"):
        self._message = message
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        for frame in itertools.cycle(frames):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{CYAN}{frame}{RESET} {DIM}{self._message}...{RESET}")
            sys.stdout.flush()
            time.sleep(0.08)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join()
        sys.stdout.write("\r\033[K")  # Clear line
        sys.stdout.flush()


class TerminalUI:
    """Handles all terminal I/O for Deimos."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._spinner: Spinner | None = None
        self._session: PromptSession | None = None

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup_input(self, commands: list[tuple[str, str]]):
        """Initialize the prompt_toolkit session with a '/' command completer."""
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        self._session = PromptSession(
            completer=SlashCommandCompleter(commands),
            complete_while_typing=True,
            history=FileHistory(str(INPUT_HISTORY_FILE)),
            style=PT_STYLE,
        )

    def print_logo(self):
        print(LOGO)
        print(f"{DIM}  Type your task, or / for commands.{RESET}\n")

    def prompt(self) -> str:
        try:
            if self._session:
                return self._session.prompt(HTML("<prompt>›</prompt> ")).strip()
            return input("> ").strip()
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

    # ── Tool rendering ───────────────────────────────────────────────────────

    def tool_call(self, name: str, inputs: dict):
        self._stop_spinner()
        args_str = ", ".join(
            f"{k}={_truncate(json.dumps(v), 60)}" for k, v in inputs.items()
        )
        print(f"{CYAN}●{RESET} {BOLD}{name}{RESET}{DIM}({args_str}){RESET}")

    def tool_result(self, result: str):
        lines = result.strip().splitlines() or [""]
        first = _truncate(lines[0], 100)
        print(f"  {DIM}⎿  {first}{RESET}")

        if self.verbose and len(lines) > 1:
            for line in lines[1:6]:
                print(f"     {DIM}{_truncate(line, 100)}{RESET}")
            if len(lines) > 6:
                print(f"     {DIM}… ({len(lines) - 6} more lines){RESET}")

    # ── Agent response (typewriter prose + highlighted code blocks) ───────────

    def agent_response(self, text: str):
        self._stop_spinner()
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()

        pos = 0
        for match in CODE_BLOCK_RE.finditer(text):
            self._typewriter(text[pos:match.start()])
            lang = match.group(1)
            code = match.group(2)
            self._print_code_block(code, lang)
            pos = match.end()

        self._typewriter(text[pos:])
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    def _typewriter(self, text: str):
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            if char in ".!?":
                time.sleep(0.06)
            elif char == ",":
                time.sleep(0.03)
            else:
                time.sleep(0.012)

    def _print_code_block(self, code: str, lang: str):
        code = code.rstrip("\n")
        highlighted = _highlight_code(code, lang)

        sys.stdout.write("\n")
        label = lang or "code"
        sys.stdout.write(f"{DIM}╭─ {label}{RESET}\n")
        for line in highlighted.split("\n"):
            sys.stdout.write(f"{DIM}│{RESET} {line}\n")
        sys.stdout.write(f"{DIM}╰─{RESET}\n")
        sys.stdout.flush()

    # ── Status / info messages ──────────────────────────────────────────────

    def error(self, message: str):
        self._stop_spinner()
        print(f"\n{RED}✗ {message}{RESET}\n")

    def info(self, message: str):
        self._stop_spinner()
        print(f"{DIM}{message}{RESET}")

    def memory_loaded(self):
        print(f"{DIM}  ✓ Loaded memory from previous sessions{RESET}\n")

    def conversation_resumed(self, message_count: int):
        print(f"{DIM}  ✓ Resumed conversation ({message_count} messages){RESET}\n")

    def saving_memory(self):
        sys.stdout.write(f"{DIM}  Saving memory...{RESET}")
        sys.stdout.flush()

    def memory_saved(self, title: str | None = None):
        sys.stdout.write("\r\033[K")
        if title:
            print(f"{DIM}  ✓ Memory saved.{RESET} {CYAN}\"{title}\"{RESET}")
        else:
            print(f"{DIM}  ✓ Memory saved.{RESET}")

    def clear_screen(self):
        os.system("cls" if os.name == "nt" else "clear")

    # ── Structured displays ──────────────────────────────────────────────────

    def print_conversations(self, conversations: list[dict]):
        """Render a list of past conversations."""
        if not conversations:
            print(f"{DIM}No past conversations found.{RESET}\n")
            return

        print(f"\n{BOLD}Past conversations:{RESET}\n")
        for i, conv in enumerate(conversations, 1):
            title = conv.get("title") or "(untitled)"
            started = conv.get("started_at", "")[:16].replace("T", " ")
            count = conv.get("message_count", 0)
            full_id = conv["id"]

            print(
                f"  {CYAN}{i:>2}.{RESET} {BOLD}{title}{RESET}\n"
                f"      {DIM}{started}  ·  {count} messages  ·  id: {full_id}{RESET}"
            )
        print()

    def print_help(self, commands):
        """Render the list of all available slash commands."""
        print(f"\n{BOLD}Available commands:{RESET}\n")
        width = max(len(c.usage) for c in commands) + 2
        for c in commands:
            print(f"  {CYAN}{c.usage:<{width}}{RESET} {DIM}{c.description}{RESET}")
        print()

    def print_facts(self, facts: list[dict]):
        """Render semantic memory facts about the user."""
        if not facts:
            print(f"{DIM}No facts stored yet.{RESET}\n")
            return

        print(f"\n{BOLD}What Deimos remembers about you:{RESET}\n")
        key_width = max(len(f["key"]) for f in facts) + 2
        for f in facts:
            confidence = f.get("confidence", 0)
            freq = f.get("frequency", 1)
            print(
                f"  {CYAN}{f['key']:<{key_width}}{RESET} {f['value']}"
                f"  {DIM}(confidence {confidence}, seen {freq}x){RESET}"
            )
        print()

    def print_status(self, info: dict):
        """Render a key/value status panel."""
        print(f"\n{DIM}╭─ status{RESET}")
        key_width = max(len(k) for k in info.keys()) + 2
        for key, value in info.items():
            print(f"{DIM}│{RESET} {BOLD}{key:<{key_width}}{RESET} {value}")
        print(f"{DIM}╰─{RESET}\n")


# ── helpers ──────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _highlight_code(code: str, lang: str) -> str:
    """Return ANSI-highlighted code using pygments, falling back gracefully."""
    try:
        if lang:
            lexer = get_lexer_by_name(lang, stripall=True)
        else:
            lexer = guess_lexer(code)
    except ClassNotFound:
        try:
            lexer = get_lexer_by_name("text")
        except Exception:
            return code

    try:
        formatter = Terminal256Formatter(style="monokai")
        result = highlight(code, lexer, formatter)
        return result.rstrip("\n")
    except Exception:
        return code