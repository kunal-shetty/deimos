import re
import subprocess
from .base import BaseTool

TIMEOUT_SECONDS = 60

# Patterns that indicate a potentially destructive/irreversible command.
# Checked by agent/core.py BEFORE dispatching, so the user can confirm.
DANGEROUS_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f",   # rm -rf, rm -fr, rm -Rf, etc.
    r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r",
    r"\brm\s+--recursive",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
    r"\bdd\s+if=",
    r"\bmkfs",
    r">\s*/dev/sd",
    r"\bchmod\s+-R\s+777\s+/",
    r"\bchown\s+-R.*\s+/",
    r"\bgit\s+push\s+.*(-f\b|--force)",
    r"\bgit\s+reset\s+--hard",
    r"\bgit\s+clean\s+-[a-zA-Z]*d[a-zA-Z]*f",  # git clean -df, -fdx, etc.
    r"\btruncate\s+-s\s*0",
    r"\bDROP\s+(TABLE|DATABASE)\b",
    r"\bsudo\s+rm\b",
    r">\s*/etc/",
]

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]


def is_dangerous(command: str) -> bool:
    """Return True if the command matches a known destructive pattern."""
    return any(p.search(command) for p in _compiled_patterns)


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Execute a shell command and return its stdout + stderr output. "
        "Use for running scripts, compilers, package managers (npm, pip, cargo), "
        "git operations, and any other terminal command. "
        "Destructive commands (rm -rf, force pushes, etc.) will prompt the user "
        "for confirmation before running."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory to run the command in (optional).",
            },
        },
        "required": ["command"],
    }

    def run(self, command: str, cwd: str = None) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=cwd or None,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                return f"[exit {result.returncode}]\n{output}" if output else f"[exit {result.returncode}]"
            return output if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {TIMEOUT_SECONDS}s"
        except Exception as e:
            return f"Error running command: {e}"