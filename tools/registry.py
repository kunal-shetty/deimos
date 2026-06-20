from typing import Optional
from .base import BaseTool
from .read_file import ReadFileTool
from .write_file import WriteFileTool
from .run_command import RunCommandTool
from .list_directory import ListDirectoryTool
from .search_codebase import SearchCodebaseTool
from .edit_file import EditFileTool
from .list_skills import ListSkillsTool
from .read_skill import ReadSkillTool
from .create_docx import CreateDocxTool


class ToolRegistry:
    """Central registry that holds all available tools and dispatches calls."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self):
        for tool in [
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            RunCommandTool(),
            ListDirectoryTool(),
            SearchCodebaseTool(),
            ListSkillsTool(),
            ReadSkillTool(),
            CreateDocxTool(),
        ]:
            self.register(tool)

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def all_schemas(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def dispatch(self, name: str, inputs: dict) -> str:
        tool = self.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        inputs = inputs or {}
        try:
            return tool.run(**inputs)
        except TypeError as e:
            return f"Error: Bad tool inputs for '{name}': {e}"
        except Exception as e:
            return f"Error running tool '{name}': {e}"