"""
MCP client support for Deimos.

Connects to external MCP servers (stdio or SSE-based) configured via
`mcp_client/config_store.py`, discovers their tools, and wraps each one as a
Deimos BaseTool so it can be registered into the normal ToolRegistry
and called by the agent loop exactly like a native tool.

Connections are managed synchronously from Deimos's perspective (the agent
loop is sync) by running a dedicated asyncio event loop in a background
thread — this keeps the rest of the codebase untouched.
"""

import asyncio
import threading
from contextlib import AsyncExitStack

from tools.base import BaseTool

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client, StdioServerParameters
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class _MCPLoopThread:
    """Runs a persistent asyncio event loop on a background thread."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro, timeout: float = 30):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)


_loop_thread: "_MCPLoopThread | None" = None


def _get_loop_thread() -> "_MCPLoopThread":
    global _loop_thread
    if _loop_thread is None:
        _loop_thread = _MCPLoopThread()
    return _loop_thread


class MCPServerConnection:
    """A live connection to one MCP server, kept open for the session."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]
        self.session: "ClientSession | None" = None
        self._stack = AsyncExitStack()
        self._connected = False

    def connect(self) -> list[dict]:
        """Connect and return the list of tool schemas this server exposes."""
        if not MCP_AVAILABLE:
            raise RuntimeError("mcp package not installed. Run: pip install mcp")

        loop_thread = _get_loop_thread()
        tools = loop_thread.run(self._async_connect())
        self._connected = True
        return tools

    async def _async_connect(self):
        if self.config["type"] == "stdio":
            params = StdioServerParameters(
                command=self.config["command"],
                args=self.config.get("args", []),
                env=self.config.get("env"),
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif self.config["type"] == "sse":
            read, write = await self._stack.enter_async_context(sse_client(self.config["url"]))
        else:
            raise ValueError(f"Unknown MCP server type: {self.config['type']}")

        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

        result = await self.session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {"type": "object", "properties": {}},
            }
            for t in result.tools
        ]

    def call_tool(self, tool_name: str, inputs: dict) -> str:
        loop_thread = _get_loop_thread()
        return loop_thread.run(self._async_call_tool(tool_name, inputs))

    async def _async_call_tool(self, tool_name: str, inputs: dict) -> str:
        if not self.session:
            return "Error: MCP server not connected"
        result = await self.session.call_tool(tool_name, inputs)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else "(no output)"

    def disconnect(self):
        if self._connected:
            loop_thread = _get_loop_thread()
            try:
                loop_thread.run(self._stack.aclose(), timeout=10)
            except Exception:
                pass
            self._connected = False


class MCPToolWrapper(BaseTool):
    """Wraps a single MCP server tool as a Deimos BaseTool."""

    def __init__(self, server_name: str, connection: MCPServerConnection, schema: dict):
        self._server_name = server_name
        self._connection = connection
        self._name = f"mcp_{server_name}_{schema['name']}"
        self._description = f"[MCP:{server_name}] {schema['description']}"
        self._input_schema = schema["input_schema"]

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return self._input_schema

    def run(self, **kwargs) -> str:
        original_name = self._name[len(f"mcp_{self._server_name}_"):]
        try:
            return self._connection.call_tool(original_name, kwargs)
        except Exception as e:
            return f"Error calling MCP tool '{original_name}' on server '{self._server_name}': {e}"


class MCPManager:
    """
    Connects to all configured MCP servers and produces BaseTool wrappers
    for each of their tools, ready to register into a ToolRegistry.
    """

    def __init__(self):
        self.connections: dict[str, MCPServerConnection] = {}

    def connect_all(self, server_configs: list[dict]) -> tuple[list[BaseTool], list[str]]:
        """
        Connect to every configured server.
        Returns (tools, errors) — tools is a flat list of MCPToolWrapper
        instances ready to register; errors is a list of human-readable
        failure messages for servers that couldn't connect.
        """
        tools = []
        errors = []

        for config in server_configs:
            name = config["name"]
            try:
                conn = MCPServerConnection(config)
                schemas = conn.connect()
                self.connections[name] = conn
                for schema in schemas:
                    tools.append(MCPToolWrapper(name, conn, schema))
            except Exception as e:
                errors.append(f"{name}: {e}")

        return tools, errors

    def disconnect_all(self):
        for conn in self.connections.values():
            conn.disconnect()
        self.connections.clear()