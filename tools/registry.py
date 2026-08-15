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
    """
    Central registry that holds all available tools and dispatches calls.
    Supports dynamic registration/unregistration so MCP server tools can be
    added when a server connects and removed when it disconnects, without
    restarting the agent.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._mcp_tool_names: set[str] = set()  # tracks which tools came from MCP
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

    def register(self, tool: BaseTool, is_mcp: bool = False):
        self._tools[tool.name] = tool
        if is_mcp:
            self._mcp_tool_names.add(tool.name)

    def register_mcp_tools(self, tools: list[BaseTool]):
        """Register a batch of MCP-derived tools."""
        for tool in tools:
            self.register(tool, is_mcp=True)

    def unregister_mcp_tools(self):
        """Remove all currently-registered MCP tools (e.g. on /mcp disconnect)."""
        for name in list(self._mcp_tool_names):
            self._tools.pop(name, None)
        self._mcp_tool_names.clear()

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def all_schemas(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def mcp_tool_names(self) -> list[str]:
        return sorted(self._mcp_tool_names)

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