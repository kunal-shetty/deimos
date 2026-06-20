import os
from .base import BaseTool

# Directories to always skip when walking a tree
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".pytest_cache", ".mypy_cache",
}

MAX_ENTRIES = 500


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = (
        "List files and folders under a directory, recursively, as a tree. "
        "Use this to explore project structure before reading or editing files. "
        "Common noise directories (.git, node_modules, __pycache__, venv, dist, "
        "build) are skipped automatically."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list. Defaults to the current directory.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to recurse (default 3).",
            },
        },
        "required": [],
    }

    def run(self, path: str = ".", max_depth: int = 3) -> str:
        root = os.path.abspath(path)
        if not os.path.exists(root):
            return f"Error: Path not found: {path}"
        if not os.path.isdir(root):
            return f"Error: Not a directory: {path}"

        lines = [f"{path}/"]
        count = [0]
        self._walk(root, prefix="", depth=0, max_depth=max_depth, lines=lines, count=count)

        if count[0] >= MAX_ENTRIES:
            lines.append(f"... (truncated at {MAX_ENTRIES} entries)")

        return "\n".join(lines)

    def _walk(self, current_dir, prefix, depth, max_depth, lines, count):
        if depth >= max_depth or count[0] >= MAX_ENTRIES:
            return

        try:
            entries = sorted(os.listdir(current_dir))
        except PermissionError:
            return

        entries = [e for e in entries if e not in IGNORE_DIRS and not e.startswith(".")]

        # Directories first, then files
        dirs = [e for e in entries if os.path.isdir(os.path.join(current_dir, e))]
        files = [e for e in entries if not os.path.isdir(os.path.join(current_dir, e))]
        ordered = dirs + files

        for i, entry in enumerate(ordered):
            if count[0] >= MAX_ENTRIES:
                return

            full_path = os.path.join(current_dir, entry)
            is_last = i == len(ordered) - 1
            connector = "└── " if is_last else "├── "
            is_dir = os.path.isdir(full_path)

            lines.append(f"{prefix}{connector}{entry}{'/' if is_dir else ''}")
            count[0] += 1

            if is_dir:
                extension = "    " if is_last else "│   "
                self._walk(full_path, prefix + extension, depth + 1, max_depth, lines, count)