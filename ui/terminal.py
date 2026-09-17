import sys
import os
import json
import math
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

# Enable ANSI escapes on legacy Windows consoles (no-op elsewhere)
if os.name == "nt":
    os.system("")

# Ensure stdout/stderr can encode Unicode (box-drawing, emoji) even when the
# console codepage is not UTF-8 (e.g. cp1252) or output is piped/redirected.
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ── Colour palette (cyan/blue brand theme) ───────────────────────────────────
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
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")

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
{GREY}  autonomous coding agent  ·  type {AMBER}/{RESET}{GREY} for commands{RESET}
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
    "list_skills":     "🧰",
    "read_skill":      "📕",
    "create_docx":     "📄",
    "web_search":      "🌐",
    "web_read":        "📖",
    "fetch_url":       "🌍",
    "git_status":      "🌿",
    "git_add":         "➕",
    "git_commit":      "📝",
    "git_push":        "🚀",
    "git_branch":      "🌱",
    "github_pr":       "🔀",
}

# Result strings starting with any of these are rendered as failures
_FAIL_PREFIXES = ("Error", "[exit", "Git error", "GitHub CLI error",
                  "Web search failed", "Web read failed", "Unexpected error")


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


def _style_inline(text: str) -> str:
    """Bold + inline-code styling for a single line of markdown text."""
    parts = INLINE_CODE_RE.split(text)  # odd indices are inline code spans
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(f"{AMBER}{part}{RESET}")
        else:
            out.append(BOLD_RE.sub(lambda m: f"{BOLD}{WHITE}{m.group(1)}{RESET}", part))
    return "".join(out)


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
        self._start = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            elapsed = time.time() - self._start
            sys.stdout.write(
                f"\r{AMBER}{frame}{RESET} {GREY}{self._message}…{RESET} "
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
        self._stream_active = False
        self._stream_buffer = ""

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

    def print_workdir(self, path: str, model: str | None = None, plan_mode: bool | None = None):
        """Claude-Code-style context header: dir, branch, model, plan mode."""
        bits = [f"{GREY}dir:{RESET} {AMBER}{path}{RESET}"]
        branch = _git_branch()
        if branch:
            bits.append(f"{GREY}branch:{RESET} {WHITE}{branch}{RESET}")
        if model:
            bits.append(f"{GREY}model:{RESET} {WHITE}{model}{RESET}")
        if plan_mode is not None:
            bits.append(f"{GREY}plan mode:{RESET} {WHITE}{'on' if plan_mode else 'off'}{RESET}")
        print(f"  {'  ·  '.join(bits)}\n")

    def prompt(self) -> str:
        # Safety net: never sit at the prompt with a spinner still ticking.
        self._stop_spinner()
        try:
            if self._session:
                return self._session.prompt(HTML(f"<prompt>❯</prompt> ")).strip()
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
        """
        After streaming completes, erase the raw streamed text and re-render
        it as styled markdown (headers, bullets, highlighted code blocks).
        """
        self._stream_active = False
        raw = getattr(self, "_stream_buffer", "")
        if not raw.strip():
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            return

        # Estimate how many visual lines the streamed text occupies so we can
        # move the cursor back up and cleanly replace it with rendered output.
        lines_up = 0
        try:
            width = max(os.get_terminal_size().columns - 2, 20)
        except OSError:
            width = 78
        segments = raw.split("\n")
        for i, seg in enumerate(segments):
            prefix = 2 if i == 0 else 0  # "◆ " shares the first line
            lines_up += max(1, math.ceil((len(seg) + prefix) / width))
        lines_up = max(lines_up - 1, 0)

        try:
            sys.stdout.write(f"\033[{lines_up}A\r\033[J")
            sys.stdout.write(f"\n{GREEN}◆{RESET} ")
            self._print_markdown(raw)
            sys.stdout.write("\n\n")
        except Exception:
            sys.stdout.write("\n\n")
        sys.stdout.flush()

    # ── Non-streaming agent response (markdown rendered) ─────────────────────

    def agent_response(self, text: str):
        self._stop_spinner()
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()
        self._print_markdown(text)
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    def _print_markdown(self, text: str):
        """Render markdown: headers, bullets, rules, inline styles, code blocks."""
        pos = 0
        for match in CODE_BLOCK_RE.finditer(text):
            self._print_md_text(text[pos:match.start()])
            self._print_code_block(match.group(2), match.group(1))
            pos = match.end()
        self._print_md_text(text[pos:])

    def _print_md_text(self, text: str):
        if not text:
            return
        for line in text.rstrip("\n").split("\n"):
            stripped = line.strip()
            if re.match(r"^#{1,6}\s", stripped):
                level = len(stripped) - len(stripped.lstrip("#"))
                label = stripped.lstrip("#").strip()
                colour = AMBER if level <= 2 else WHITE
                print(f"{BOLD}{colour}{label}{RESET}")
            elif stripped in ("---", "***", "___"):
                print(f"{GREY}{'─' * 40}{RESET}")
            elif re.match(r"^[-*]\s+", stripped):
                content = _style_inline(re.sub(r"^[-*]\s+", "", stripped))
                print(f"{CYAN}  •{RESET} {content}")
            elif re.match(r"^\d+\.\s+", stripped):
                m = re.match(r"^(\d+)\.\s+(.*)", stripped)
                print(f"  {AMBER}{m.group(1)}.{RESET} {_style_inline(m.group(2))}")
            elif stripped.startswith(">"):
                print(f"{GREY}{ITALIC}  {stripped}{RESET}")
            elif not stripped:
                print()
            else:
                print(_style_inline(line))

    def _print_code_block(self, code: str, lang: str):
        code = code.rstrip("\n")
        highlighted = _highlight_code(code, lang)
        label = f"✱ {lang or 'code'}"
        lines = highlighted.split("\n")
        width = min(max((max(len(_strip_ansi(l)) for l in lines) + 4), 40), 100)

        sys.stdout.write("\n")
        sys.stdout.write(f"{AMBER_DIM}╭─ {label}{'─' * max(1, width - len(label) - 3)}╮{RESET}\n")
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
        failed = result.startswith(_FAIL_PREFIXES)
        marker = f"{RED}✗{RESET}" if failed else f"{GREEN}✓{RESET}"
        lines = result.strip().splitlines() or [""]
        preview = _truncate(lines[0], 90)
        print(f"     {GREY}⎿{RESET} {marker} {GREY if failed else ''}{preview}{RESET}")
        if self.verbose and len(lines) > 1:
            shown = 0
            for line in lines[1:]:
                if line.startswith(("+++", "---", "@@")) or line.startswith("```"):
                    continue
                if line.startswith("+"):
                    print(f"       {GREEN}{_truncate(line, 90)}{RESET}")
                elif line.startswith("-"):
                    print(f"       {RED}{_truncate(line, 90)}{RESET}")
                else:
                    print(f"       {DIM}{_truncate(line, 90)}{RESET}")
                shown += 1
                if shown >= 5:
                    break
            remaining = len(lines) - 1 - shown
            if remaining > 0:
                print(f"       {DIM}… ({remaining} more lines){RESET}")

    def tool_skipped(self, name: str):
        print(f"  {RED}✗{RESET}  {GREY}{name} — skipped by user{RESET}")

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
            print(f"  {GREY}{'─' * 6} {' · '.join(bits)} {'─' * 6}{RESET}")

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

    # ── Plan mode displays ───────────────────────────────────────────────────

    def print_plan(self, plan):
        """Pretty-print a pending Plan object awaiting confirmation."""
        self._stop_spinner()
        rows = []
        for i, step in enumerate(plan.steps, 1):
            dep = f"  {GREY}(after {', '.join(step.dependencies)}){RESET}" if step.dependencies else ""
            rows.append(f"{AMBER}{i}{RESET}  {step.description}{dep}")
        title = f"✻ Plan — {plan.title}"
        widest = max([len(_strip_ansi(r)) for r in rows] + [len(title) + 2])
        width = min(widest + 6, 96)

        print(f"\n  {_box_top(title, width, AMBER_DIM)}")
        for r in rows:
            print(f"  {_box_row(r, width, AMBER_DIM)}")
        print(f"  {_box_bot(width, AMBER_DIM)}")
        print(f"  {GREY}Send any message to confirm & run  ·  {RED}/plan-reject{GREY} to cancel{RESET}\n")

    def plan_confirmed(self):
        self._stop_spinner()
        print(f"  {GREEN}✓{RESET} {GREY}Plan confirmed — executing…{RESET}")

    def plan_rejected(self):
        self._stop_spinner()
        print(f"  {RED}✗{RESET} {GREY}Plan rejected.{RESET}")

    def print_plans(self, plans: list[dict]):
        if not plans:
            print(f"\n  {GREY}No plans found in this project (.deimos/plans).{RESET}\n")
            return
        print(f"\n  {AMBER}{BOLD}Plans{RESET}\n")
        for p in plans:
            title = p.get("title", "untitled")
            status = p.get("status", "?")
            pid = p.get("id", "?")
            created = (p.get("created_at") or "")[:16].replace("T", " ")
            n_steps = len(p.get("steps", []))
            status_colour = GREEN if status == "completed" else (RED if status == "rejected" else AMBER)
            print(f"  {AMBER}✻{RESET} {BOLD}{WHITE}{title}{RESET}")
            print(f"      {GREY}{pid}  ·  {status_colour}{status}{RESET}{GREY}  ·  {created}  ·  {n_steps} steps{RESET}")
        print()

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
        key_w = max(len(k) for k in info) + 1
        inner_w = max(len(_strip_ansi(f"{k:<{key_w}}  {v}")) for k, v in info.items())
        width = inner_w + 8
        print(f"\n  {_box_top('status', width, AMBER_DIM)}")
        for key, val in info.items():
            key_str = f"{AMBER}{key:<{key_w}}{RESET}"
            val_str = f"{WHITE}{val}{RESET}"
            print(f"  {_box_row(f'{key_str}  {val_str}', width, AMBER_DIM)}")
        print(f"  {_box_bot(width, AMBER_DIM)}\n")


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
