from .base import BaseTool


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file at the given path. "
        "Returns the file content as a string. For long files, pass offset "
        "(1-based start line) and limit (number of lines) to read part of it."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the file to read.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line to start reading from (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return (optional).",
            },
        },
        "required": ["path"],
    }

    def run(self, path: str, offset: int | None = None, limit: int | None = None) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

        if not content:
            return "(empty file)"
        if offset is None and limit is None:
            return content

        lines = content.splitlines(keepends=True)
        start = max(1, int(offset or 1))
        end = len(lines) if limit is None else min(len(lines), start - 1 + max(1, int(limit)))
        if start > len(lines):
            return f"Error: offset {start} is past the end of the file ({len(lines)} lines)"
        return f"[lines {start}-{end} of {len(lines)}]\n" + "".join(lines[start - 1:end])
