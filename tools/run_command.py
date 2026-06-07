import subprocess
from .base import BaseTool

TIMEOUT_SECONDS = 60


class RunCommandTool(BaseTool):
    name = "run_command"
    description = (
        "Execute a shell command and return its stdout + stderr output. "
        "Use for running scripts, compilers, package managers (npm, pip, cargo), "
        "git operations, and any other terminal command."
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
