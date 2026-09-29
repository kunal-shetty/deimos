from typing import Literal
from config import CONTEXT_SAFE_LIMIT

MessageRole = Literal["user", "assistant"]


class Context:
    """Manages the conversation message history for the agent loop."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self._messages: list[dict] = []

    def add_user(self, content: str | list):
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str | list):
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
            msg = self._messages[0]

            if msg["role"] == "assistant" and isinstance(msg["content"], list):
                has_tool_calls = any(item.get("type") == "tool_use" for item in msg["content"] if isinstance(item, dict))
                if has_tool_calls:
                    tool_call_count = sum(1 for item in msg["content"] if isinstance(item, dict) and item.get("type") == "tool_use")
                    results_found = 0
                    for i in range(1, len(self._messages)):
                        if self._messages[i]["role"] == "user" and isinstance(self._messages[i]["content"], list):
                            results_found += sum(1 for item in self._messages[i]["content"] if isinstance(item, dict) and item.get("type") == "tool_result")
                            if results_found >= tool_call_count:
                                unit_end = i + 1
                                break
                    else:
                        unit_end = len(self._messages)

            removed.extend(self._messages[:unit_end])
            self._messages = self._messages[unit_end:]

        return removed

    def reset(self):
        self._messages = []
