from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

ToolKind = Literal["read", "edit", "exec"]


@dataclass(frozen=True)
class FileChange:
    """A proposed change to one text file, used to show a diff before applying."""
    path: str
    old: str | None  # None when the file doesn't exist yet
    new: str


class BaseTool(ABC):
    """Abstract base class for all Deimos tools."""

    # How the permission system treats this tool:
    #   read - never changes anything; always allowed
    #   edit - changes files (checkpointed, undoable with /undo)
    #   exec - runs commands or has other side effects
    kind: ToolKind = "exec"
    # Reaches outside this machine (push, PRs): confirmed even in auto mode
    outward: bool = False

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

    def target_paths(self, **kwargs) -> list[str]:
        """Files an edit tool would change (snapshotted before it runs)."""
        return []

    def preview(self, **kwargs) -> FileChange | str | None:
        """
        The change an edit tool would make, without making it. Returns a
        FileChange, an error string if the call would fail, or None when no
        text diff is available.
        """
        return None

    def to_schema(self) -> dict:
        """Return the full tool schema for the LLM API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
