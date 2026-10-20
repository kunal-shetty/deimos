"""
NullMemory: stands in for MemoryManager when Supabase isn't configured or
can't be reached, so Deimos still runs, just without long-term memory.

The in-session rolling summary still works (it only needs the LLM); nothing
is stored between sessions.
"""

from memory.manager import MemoryManager


class NullMemory:
    enabled = False

    SEGMENT_ITEM_CHARS = MemoryManager.SEGMENT_ITEM_CHARS
    SEGMENT_TOTAL_CHARS = MemoryManager.SEGMENT_TOTAL_CHARS
    summarize_segment = MemoryManager.summarize_segment

    def __init__(self, reason: str = "Supabase is not configured"):
        self.reason = reason
        self.user_id = None
        self.resumed = False
        self._active_project = None

    def build_memory_context(self) -> None:
        return None

    def detect_and_inject_project(self, user_input: str, ctx):
        pass

    def load_resumed_messages(self) -> list[dict]:
        return []

    def save_message(self, role: str, content):
        pass

    def save_segment_summary(self, summary: str):
        pass

    def list_conversations(self, limit: int = 20) -> list[dict]:
        return []

    def delete_conversation(self, conversation_id: str) -> bool:
        return False

    @property
    def conversation_id(self) -> None:
        return None

    def current_title(self) -> None:
        return None

    def set_title(self, title: str):
        pass

    def get_facts(self) -> list[dict]:
        return []

    def get_project_facts(self, project_name: str | None = None) -> list[dict]:
        return []

    def get_known_projects(self) -> list[str]:
        return []

    def end_session(self, ctx_messages: list[dict]) -> None:
        return None
