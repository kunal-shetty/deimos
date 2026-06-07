import os
from .base import BaseTool


class WriteFileTool(BaseTool):
    name = "write_file"
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
