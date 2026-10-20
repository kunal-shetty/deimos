from typing import Literal
from config import CONTEXT_SAFE_LIMIT

MessageRole = Literal["user", "assistant"]


class Context:
    """Manages the conversation message history for the agent loop."""

    def __init__(self, system_prompt: str):
        self._base_system = system_prompt
        # Named blocks appended to the system prompt and replaced on every
        # update (git state, workflow status) so they never pile up in history.
        self._transient: dict[str, str] = {}
        self._messages: list[dict] = []

    @property
    def system_prompt(self) -> str:
        if not self._transient:
            return self._base_system
        return self._base_system + "".join(f"\n\n{block}" for block in self._transient.values())

    def get_transient(self, key: str) -> str | None:
        return self._transient.get(key)

    def set_transient(self, key: str, block: str | None):
        """Set (or clear, with None/empty) a named block on the system prompt."""
        if block:
            self._transient[key] = block
        else:
            self._transient.pop(key, None)

    def add_user(self, content: str | list):
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str | list | dict):
        self._messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_use_id: str, result: str):
        """Append a tool result as a user turn (Anthropic format)."""
        self._messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            ],
        })

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def estimated_tokens(self) -> int:
        """Estimate total tokens using a characters/4 heuristic."""
        def get_text(obj):
            if isinstance(obj, str):
                return obj
            if isinstance(obj, list):
                return "".join(get_text(i) for i in obj)
            if isinstance(obj, dict):
                return "".join(get_text(v) for v in obj.values())
            return ""

        total_chars = len(self.system_prompt)
        for msg in self._messages:
            total_chars += len(get_text(msg.get("content", "")))

        return total_chars // 4

    def truncate(self, limit_tokens: int = CONTEXT_SAFE_LIMIT) -> list[dict]:
        """
        Remove oldest messages to fit within token limit while preserving
        tool call -> tool result pairs. Returns the list of removed messages.
        """
        if self.estimated_tokens <= limit_tokens:
            return []

        removed = []

        while self.estimated_tokens > limit_tokens and self._messages:
            unit_end = 1
            tool_call_count = _count_tool_calls(self._messages[0])

            if tool_call_count:
                results_found = 0
                for i in range(1, len(self._messages)):
                    results_found += _count_tool_results(self._messages[i])
                    if results_found >= tool_call_count:
                        unit_end = i + 1
                        break
                else:
                    unit_end = len(self._messages)

            # Never leave an orphaned tool result at the head of the history
            while unit_end < len(self._messages) and _count_tool_results(self._messages[unit_end]):
                unit_end += 1

            # Always keep the latest unit so the model has something to answer
            if unit_end >= len(self._messages):
                break

            removed.extend(self._messages[:unit_end])
            self._messages = self._messages[unit_end:]

        return removed

    def reset(self):
        self._messages = []
        self._transient = {}


def _count_tool_calls(msg: dict) -> int:
    """Count tool calls in an assistant message (OpenAI dict or Anthropic blocks)."""
    if msg["role"] != "assistant":
        return 0
    content = msg["content"]
    if isinstance(content, dict):
        return len(content.get("tool_calls") or [])
    if isinstance(content, list):
        return sum(1 for item in content if isinstance(item, dict) and item.get("type") == "tool_use")
    return 0


def _count_tool_results(msg: dict) -> int:
    if msg["role"] != "user" or not isinstance(msg["content"], list):
        return 0
    return sum(1 for item in msg["content"] if isinstance(item, dict) and item.get("type") == "tool_result")
