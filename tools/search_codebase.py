import os
import re
from .base import BaseTool

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".pytest_cache", ".mypy_cache",
}

MAX_MATCHES = 100
MAX_FILE_SIZE = 1_000_000  # skip files larger than ~1MB


class SearchCodebaseTool(BaseTool):
    name = "search_codebase"
    description = (
        "Search for a text pattern (plain text or regex) across files in a "
        "directory tree, like grep -r. Returns matching file paths, line "
        "numbers, and the matching line. Use this to find where something "
        "is defined or used before editing it."
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