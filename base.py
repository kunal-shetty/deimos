from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstract base class for all Deimos tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name used in the schema."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """What this tool does (shown to the LLM)."""
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON schema for the tool's input parameters."""
        ...

    @abstractmethod
    def run(self, **kwargs) -> str:
        """Execute the tool and return a string result."""
        ...

    def to_schema(self) -> dict:
        """Return the full tool schema for the LLM API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
