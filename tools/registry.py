import os
import re
import time
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
from .web_tools import WebSearchTool, WebReadTool
from .web_fetch import FetchUrlTool
from .git_tools import GitStatusTool, GitAddTool, GitCommitTool, GitPushTool, GitBranchTool, GitHubPRTool



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
            WebSearchTool(),
            WebReadTool(),
            FetchUrlTool(),
            GitStatusTool(),
            GitAddTool(),
            GitCommitTool(),
            GitPushTool(),
            GitBranchTool(),
            GitHubPRTool(),
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
            result = tool.run(**inputs)
        except TypeError as e:
            return f"Error: Bad tool inputs for '{name}': {e}"
        except Exception as e:
            return f"Error running tool '{name}': {e}"
        return limit_output(name, result if isinstance(result, str) else str(result))


OUTPUT_DIR_NAME = os.path.join(".deimos", "outputs")
KEEP_OUTPUT_FILES = 50


def limit_output(tool_name: str, result: str, limit: int | None = None, cwd: str | None = None) -> str:
    """
    Keep tool results from flooding the context window. Results longer than
    the limit keep their head and tail inline; the full text is saved under
    .deimos/outputs/ so the agent can page through it with read_file.
    """
    if limit is None:
        from settings import load_settings
        limit = int(load_settings()["tool_output_limit"])
    if limit <= 0 or len(result) <= limit:
        return result

    path = _save_full_output(tool_name, result, cwd)
    head = result[: int(limit * 0.6)]
    tail = result[-int(limit * 0.4):]
    omitted = len(result) - len(head) - len(tail)
    where = (
        f"Full output ({result.count(chr(10)) + 1} lines) saved to {path}; "
        "use read_file with offset/limit to view specific lines."
        if path else "Full output could not be saved."
    )
    return f"{head}\n\n[... {omitted} characters omitted. {where} ...]\n\n{tail}"


def _save_full_output(tool_name: str, result: str, cwd: str | None) -> str | None:
    try:
        out_dir = os.path.join(cwd or os.getcwd(), OUTPUT_DIR_NAME)
        os.makedirs(out_dir, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", tool_name)
        path = os.path.join(out_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}-{safe}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(result)
        _prune(out_dir)
        return os.path.relpath(path, cwd or os.getcwd())
    except OSError:
        return None


def _prune(out_dir: str):
    files = sorted(
        (os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".txt")),
        key=os.path.getmtime,
    )
    for old in files[:-KEEP_OUTPUT_FILES]:
        try:
            os.remove(old)
        except OSError:
            pass