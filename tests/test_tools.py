import pytest
from tools.registry import ToolRegistry
from tools.base import BaseTool

class MockTool(BaseTool):
    @property
    def name(self) -> str: return "mock_tool"
    @property
    def description(self) -> str: return "Mock description"
    @property
    def input_schema(self) -> dict: return {"type": "object", "properties": {}}
    def run(self, **kwargs) -> str: return "mock result"

def test_tool_registry_dispatch():
    registry = ToolRegistry()
    tool = MockTool()
    registry.register(tool)

    result = registry.dispatch("mock_tool", {})
    assert result == "mock result"

def test_tool_registry_unknown_tool():
    registry = ToolRegistry()
    result = registry.dispatch("unknown_tool", {})
    assert "Error: Unknown tool" in result
