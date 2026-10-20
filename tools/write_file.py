import os
from .base import BaseTool, FileChange


class WriteFileTool(BaseTool):
    name = "write_file"
    kind = "edit"
    description = (
        "Write content to a file at the given path. "
        "Creates the file (and any parent directories) if it doesn't exist, "
        "or overwrites it if it does."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to write the file to.",
            },
            "content": {
                "type": "string",
                "description": "The content to write into the file.",
            },
        },
        "required": ["path", "content"],
    }

    def target_paths(self, path: str = "", **kwargs) -> list[str]:
        return [path] if path else []

    def preview(self, path: str = "", content: str = "", **kwargs) -> FileChange | str:
        if not path:
            return "Error: path is required"
        if not os.path.exists(path):
            return FileChange(path, None, content)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return FileChange(path, f.read(), content)
        except UnicodeDecodeError:
            return FileChange(path, "(binary file)\n", content)
        except Exception as e:
            return f"Error reading file: {e}"

    def run(self, path: str, content: str) -> str:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            lines = content.count("\n") + 1
            return f"Written: {path} ({lines} lines)"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {e}"
