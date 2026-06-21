import os
import re
import shutil
import subprocess
from .base import BaseTool

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".pytest_cache", ".mypy_cache",
}

MAX_MATCHES = 100
MAX_FILE_SIZE = 1_000_000  # skip files larger than ~1MB
RG_TIMEOUT = 20

# Detected once at import time — ripgrep is dramatically faster on large repos
# and respects .gitignore automatically, so we prefer it when available.
_RG_PATH = shutil.which("rg")


class SearchCodebaseTool(BaseTool):
    name = "search_codebase"
    description = (
        "Search for a text pattern (plain text or regex) across files in a "
        "directory tree, like grep -r. Returns matching file paths, line "
        "numbers, and the matching line. Use this to find where something "
        "is defined or used before editing it. Uses ripgrep when available "
        "for speed on large codebases, with a Python fallback otherwise."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text or regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to the current directory.",
            },
            "file_extension": {
                "type": "string",
                "description": (
                    "Only search files with this extension, e.g. 'py' or 'php' "
                    "(without the dot). Omit to search all text files."
                ),
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the search is case-sensitive. Defaults to false.",
            },
        },
        "required": ["pattern"],
    }

    def run(self, pattern: str, path: str = ".", file_extension: str = None,
            case_sensitive: bool = False) -> str:
        root = os.path.abspath(path)
        if not os.path.exists(root):
            return f"Error: Path not found: {path}"

        if _RG_PATH:
            result = self._search_ripgrep(pattern, root, file_extension, case_sensitive)
            if result is not None:
                return result
            # fall through to python backend if ripgrep itself errored unexpectedly

        return self._search_python(pattern, root, file_extension, case_sensitive)

    # ── ripgrep backend ──────────────────────────────────────────────────────

    def _search_ripgrep(self, pattern: str, root: str, file_extension: str | None,
                         case_sensitive: bool) -> str | None:
        cmd = [_RG_PATH, "--line-number", "--no-heading", "--color=never",
               "--max-count", str(MAX_MATCHES)]

        if not case_sensitive:
            cmd.append("--ignore-case")
        if file_extension:
            cmd.extend(["--type-add", f"custom:*.{file_extension.lstrip('.')}", "--type", "custom"])

        cmd.extend([pattern, root])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=RG_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"Error: ripgrep search timed out after {RG_TIMEOUT}s"
        except Exception:
            return None  # let python fallback handle it

        # rg exit code 1 = no matches (not an error), 2 = real error
        if proc.returncode == 2:
            return None  # fall back to python on genuine rg errors (bad regex, etc.)

        output = proc.stdout.strip()
        if not output:
            return f"No matches found for pattern: {pattern}"

        lines = output.splitlines()
        formatted = []
        for line in lines[:MAX_MATCHES]:
            # rg output: /abs/path:line_num:content
            try:
                file_path, line_num, content = line.split(":", 2)
                rel_path = os.path.relpath(file_path, root)
                formatted.append(f"{rel_path}:{line_num}: {content.strip()}")
            except ValueError:
                formatted.append(line)

        result = "\n".join(formatted)
        if len(lines) >= MAX_MATCHES:
            result += f"\n... (truncated at {MAX_MATCHES} matches)"
        return result

    # ── python fallback backend ──────────────────────────────────────────────

    def _search_python(self, pattern: str, root: str, file_extension: str | None,
                        case_sensitive: bool) -> str:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        ext_suffix = f".{file_extension.lstrip('.')}" if file_extension else None
        matches = []

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]

            for filename in filenames:
                if ext_suffix and not filename.endswith(ext_suffix):
                    continue

                full_path = os.path.join(dirpath, filename)
                try:
                    if os.path.getsize(full_path) > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, start=1):
                            if regex.search(line):
                                rel_path = os.path.relpath(full_path, root)
                                matches.append(f"{rel_path}:{line_num}: {line.strip()}")
                                if len(matches) >= MAX_MATCHES:
                                    break
                except (UnicodeDecodeError, PermissionError):
                    continue

                if len(matches) >= MAX_MATCHES:
                    break
            if len(matches) >= MAX_MATCHES:
                break

        if not matches:
            return f"No matches found for pattern: {pattern}"

        result = "\n".join(matches)
        if len(matches) >= MAX_MATCHES:
            result += f"\n... (truncated at {MAX_MATCHES} matches)"
        return result