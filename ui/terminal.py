import sys
import json
import threading
import itertools
import time


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

    def print_logo(self):
        print(LOGO)
        print(f"{DIM}  Type your task, or 'exit' to quit.{RESET}\n")

    def prompt(self) -> str:
        try:
            return input(f"{CYAN}{BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def thinking(self):
        self._spinner = Spinner("Thinking")
        self._spinner.start()

    def _stop_spinner(self):
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    def tool_call(self, name: str, inputs: dict):
        self._stop_spinner()
        args_str = ", ".join(
            f"{k}={json.dumps(v)[:60]!r}" for k, v in inputs.items()
        )
        print(f"  {YELLOW}⚙{RESET}  {BOLD}{name}{RESET}{DIM}({args_str}){RESET}")

    def tool_result(self, result: str):
        if self.verbose:
            preview = result[:200] + ("…" if len(result) > 200 else "")
            print(f"  {DIM}   → {preview}{RESET}")

    def agent_response(self, text: str):
        self._stop_spinner()
        sys.stdout.write(f"\n{GREEN}◆{RESET} ")
        sys.stdout.flush()
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            # Slight pause after punctuation for a more natural rhythm
            if char in ".!?:":
                time.sleep(0.7)
            elif char == ",":
                time.sleep(0.3)
            else:
                time.sleep(0.012)
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    def error(self, message: str):
        self._stop_spinner()
        print(f"\n{RED}✗ {message}{RESET}\n")

    def info(self, message: str):
        self._stop_spinner()
        print(f"{DIM}{message}{RESET}")