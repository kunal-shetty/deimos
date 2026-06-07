from typing import Literal


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

    def reset(self):
        self._messages = []
