from .base import BaseTool


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file at the given path. "
        "Returns the file content as a string."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the file to read.",
            }
        },
        "required": ["path"],
    }

    def run(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return content if content else "(empty file)"
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"
