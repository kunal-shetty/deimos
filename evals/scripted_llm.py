"""A deterministic stand-in for LLMClient that replays a fixed script."""

from __future__ import annotations

import json


class ScriptedLLM:
    """
    Each script entry is one model turn:

        {"text": "optional message", "tool_calls": [{"name": "write_file", "inputs": {...}}]}

    A turn with no tool_calls ends the agent's turn. `repairs` are the corrected
    inputs returned, in order, when the agent's self-healing loop asks the model
    to fix a failed tool call. When the script runs out the model "says" so and
    stops, and `exhausted` is set so a check can flag it.
    """

    model = "scripted"

    def __init__(self, script: list[dict], repairs: list[dict] | None = None, repeat_last: bool = False):
        self._script = list(script)
        self._repairs = list(repairs or [])
        self._repeat_last = repeat_last
        self._index = 0
        self.exhausted = False
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def reset_usage(self):
        self.total_input_tokens = self.total_output_tokens = 0

    def set_model(self, model_name: str):
        pass

    def _next_turn(self) -> dict:
        if self._index < len(self._script):
            turn = self._script[self._index]
        elif self._repeat_last and self._script:
            turn = self._script[-1]
        else:
            self.exhausted = True
            return {"text": "[script exhausted]"}
        self._index += 1
        return turn

    def _respond(self, system: str, messages: list[dict]) -> dict:
        turn = self._next_turn()
        calls = [
            {"id": f"call_{self._index}_{i}", "name": c["name"], "inputs": dict(c.get("inputs") or {})}
            for i, c in enumerate(turn.get("tool_calls") or [])
        ]
        text = turn.get("text")
        raw = {"role": "assistant", "content": text}
        if calls:
            raw["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["inputs"])}}
                for c in calls
            ]
        # Same chars/4 estimate the agent uses for its own context budget
        self.total_input_tokens += (len(system) + len(json.dumps(messages, default=str))) // 4
        self.total_output_tokens += (len(text or "") + sum(len(json.dumps(c["inputs"])) for c in calls)) // 4
        return {
            "stop_reason": "tool_use" if calls else "end_turn",
            "text": text,
            "tool_calls": calls,
            "raw_content": raw,
        }

    def complete_stream(self, system, messages, tools, on_chunk, max_tokens=4096, temperature=1.0):
        response = self._respond(system, messages)
        if response["text"]:
            on_chunk(response["text"])
        return response

    def complete(self, system, messages, tools, max_tokens=4096, temperature=1.0):
        return self._respond(system, messages)

    def complete_json(self, system, messages, max_tokens=1000, temperature=0.2):
        if self._repairs:
            return self._repairs.pop(0)
        return {"error": "no scripted repair available"}

    def chat(self, system, user, max_tokens=512, temperature=0.3):
        return None
