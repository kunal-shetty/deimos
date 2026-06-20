from .base import BaseTool


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Make a targeted edit to an existing file by replacing an exact text "
        "match with new text. Use this instead of write_file when changing "
        "part of a file — it's cheaper and safer because it doesn't touch the "
        "rest of the file. The 'old_text' must match the file content exactly "
        "(including whitespace/indentation) and must be unique within the file. "
        "Read the file first if you're not sure of its exact current content."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "old_text": {
                "type": "string",
                "description": "The exact text to find. Must appear exactly once in the file.",
            },
            "new_text": {
                "type": "string",
                "description": "The text to replace it with. Can be empty to delete old_text.",
            },
        },
        "required": ["path", "old_text", "new_text"],
    }

    def run(self, path: str, old_text: str, new_text: str = "") -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

        count = content.count(old_text)

        if count == 0:
            return (
                f"Error: old_text not found in {path}. "
                "Make sure it matches the file exactly, including whitespace/indentation. "
                "Read the file first to confirm its current content."
            )

        if count > 1:
            return (
                f"Error: old_text appears {count} times in {path}, but must be unique. "
                "Include more surrounding context to make the match unique."
            )

        new_content = content.replace(old_text, new_text, 1)

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {e}"

        old_lines = old_text.count("\n") + 1
        new_lines = new_text.count("\n") + 1
        return f"Edited: {path} ({old_lines} line(s) -> {new_lines} line(s))"