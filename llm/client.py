import json
import time
import requests
from config import LLM_API_KEY, LLM_MODEL

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
RETRY_ATTEMPTS = 5
RETRY_BASE_DELAY = 2   # seconds — doubles each attempt


class LLMClient:
    """Groq API client using raw HTTP requests (OpenAI-compatible endpoint)."""

    def __init__(self):
        if not LLM_API_KEY:
            raise ValueError("GROQ_API_KEY is not set. Add it to your .env file.")
        self._headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        self.model = LLM_MODEL

    def set_model(self, model_name: str):
        """Switch the model used for subsequent completions."""
        self.model = model_name

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        """
        Send a completion request to Groq with automatic retry on 429.
        Returns a normalized response dict:
          {
            "stop_reason": "end_turn" | "tool_use",
            "text": str | None,
            "tool_calls": [{"id": str, "name": str, "inputs": dict}],
            "raw_content": dict,   # raw assistant message for history
          }
        """
        oai_tools = [_to_oai_tool(t) for t in tools]
        oai_messages = [{"role": "system", "content": system}] + _convert_messages(messages)

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": oai_messages,
            "tools": oai_tools,
            "tool_choice": "auto",
        }

        response = self._post_with_retry(payload)
        data = response.json()

        choice = data["choices"][0]
        msg = choice["message"]
        finish_reason = choice["finish_reason"]

        text = msg.get("content") or None
        tool_calls = []

        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                try:
                    parsed_inputs = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    parsed_inputs = {}
                if not isinstance(parsed_inputs, dict):
                    parsed_inputs = {}
                tool_calls.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "inputs": parsed_inputs,
                })

        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

        return {
            "stop_reason": stop_reason,
            "text": text,
            "tool_calls": tool_calls,
            "raw_content": msg,
        }

    def complete_stream(self, system: str, messages: list[dict], tools: list[dict], on_chunk) -> dict:
        """
        Send a streaming completion request to Groq.
        `on_chunk(text)` is called for each text delta as it arrives.
        Returns the same normalized response dict shape as complete(), built
        up from the accumulated stream.
        """
        oai_tools = [_to_oai_tool(t) for t in tools]
        oai_messages = [{"role": "system", "content": system}] + _convert_messages(messages)

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": oai_messages,
            "tools": oai_tools,
            "tool_choice": "auto",
            "stream": True,
        }

        response = self._post_with_retry(payload, stream=True)

        text_parts = []
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = None

        for line in response.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if not line.startswith("data: "):
                continue

            data_str = line[len("data: "):]
            if data_str.strip() == "[DONE]":
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta", {})

            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

            content = delta.get("content")
            if content:
                text_parts.append(content)
                on_chunk(content)

            for tc_delta in delta.get("tool_calls") or []:
                idx = tc_delta.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}

                if tc_delta.get("id"):
                    tool_calls_acc[idx]["id"] = tc_delta["id"]

                fn = tc_delta.get("function", {})
                if fn.get("name"):
                    tool_calls_acc[idx]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_acc[idx]["arguments"] += fn["arguments"]

        text = "".join(text_parts) or None

        tool_calls = []
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            try:
                inputs = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                inputs = {}
            if not isinstance(inputs, dict):
                inputs = {}
            tool_calls.append({"id": tc["id"], "name": tc["name"], "inputs": inputs})

        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

        raw_content = {"role": "assistant", "content": text}
        if tool_calls:
            raw_content["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["inputs"]),
                    },
                }
                for tc in tool_calls
            ]

        return {
            "stop_reason": stop_reason,
            "text": text,
            "tool_calls": tool_calls,
            "raw_content": raw_content,
        }

    def _post_with_retry(self, payload: dict, stream: bool = False) -> requests.Response:
        """POST with exponential backoff on 429 rate limit responses."""
        delay = RETRY_BASE_DELAY
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            response = requests.post(GROQ_API_URL, headers=self._headers, json=payload, stream=stream)

            if response.status_code == 429:
                # Check if Groq gave us a retry-after header
                retry_after = response.headers.get("retry-after")
                wait = float(retry_after) if retry_after else delay

                if attempt == RETRY_ATTEMPTS:
                    response.raise_for_status()

                print(f"\r  \033[2m⏳ Rate limited — retrying in {wait:.0f}s (attempt {attempt}/{RETRY_ATTEMPTS})...\033[0m",
                      end="", flush=True)
                time.sleep(wait)
                delay *= 2
                continue

            response.raise_for_status()
            return response

        response.raise_for_status()  # final raise if somehow exhausted


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_oai_tool(tool: dict) -> dict:
    """Convert Anthropic tool schema to OpenAI function tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


def _convert_messages(messages: list[dict]) -> list[dict]:
    """
    Convert Anthropic-style message history to OpenAI format.
    Handles tool_result turns (Anthropic) → tool role messages (OpenAI).
    """
    oai = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                oai.append({"role": "user", "content": content})
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        oai.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block["content"],
                        })
                    else:
                        oai.append({"role": "user", "content": str(block)})

        elif role == "assistant":
            if isinstance(content, str):
                oai.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text = None
                tool_calls = []
                for block in content:
                    if hasattr(block, "type"):
                        if block.type == "text":
                            text = block.text
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input),
                                },
                            })
                oai.append({
                    "role": "assistant",
                    "content": text,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                })
            elif isinstance(content, dict):
                oai.append(content)

    return oai