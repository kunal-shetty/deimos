"""Trace capture: a recording UI, a tracing LLM wrapper and the Trace itself."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Trace:
    """Ordered record of everything that happened during one task run."""

    started: float = field(default_factory=time.perf_counter)
    events: list[dict] = field(default_factory=list)

    def add(self, type: str, **data) -> dict:
        event = {"type": type, "t_ms": round((time.perf_counter() - self.started) * 1000, 1), **data}
        self.events.append(event)
        return event

    def of(self, type: str) -> list[dict]:
        return [e for e in self.events if e["type"] == type]


class RecordingUI:
    """
    Stands in for TerminalUI. Records what the agent shows and answers
    permission prompts with a fixed policy (`approve`). Any other UI method
    the agent calls is a silent no-op.
    """

    def __init__(self, trace: Trace, approve: bool = True):
        self.trace = trace
        self.approve = approve

    def ask_permission(self, title, detail=None, change=None, danger=False, always_label=None, question=None):
        self.trace.add("permission", title=title, danger=bool(danger), question=question,
                       detail=[str(d) for d in (detail or [])][:5], answer="yes" if self.approve else "no")
        if self.approve:
            return ("y", None)
        return ("n", "declined by eval policy")

    def agent_response(self, text):
        self.trace.add("assistant", text=str(text)[:2000])

    def error(self, message="", *a, **k):
        self.trace.add("error", message=str(message))

    def info(self, message="", *a, **k):
        self.trace.add("info", message=str(message))

    def turn_end(self, stats=None):
        self.trace.add("turn_end", stats=dict(stats or {}))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class TracingLLM:
    """Wraps any LLM client, recording latency, token use and tool calls per request."""

    def __init__(self, inner, trace: Trace):
        self._inner = inner
        self._trace = trace

    @property
    def total_input_tokens(self) -> int:
        return self._inner.total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._inner.total_output_tokens

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def _traced(self, kind: str, fn, *args, **kwargs):
        in0, out0 = self._inner.total_input_tokens, self._inner.total_output_tokens
        t0 = time.perf_counter()
        error = None
        result = None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            event = {
                "kind": kind,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "input_tokens": self._inner.total_input_tokens - in0,
                "output_tokens": self._inner.total_output_tokens - out0,
                "error": error,
            }
            if isinstance(result, dict) and "tool_calls" in result:
                event["tool_calls"] = [c["name"] for c in result["tool_calls"]]
                event["text"] = (result.get("text") or "")[:500]
            self._trace.add("llm", **event)

    def complete_stream(self, *args, **kwargs):
        return self._traced("stream", self._inner.complete_stream, *args, **kwargs)

    def complete(self, *args, **kwargs):
        return self._traced("complete", self._inner.complete, *args, **kwargs)

    def complete_json(self, *args, **kwargs):
        return self._traced("json", self._inner.complete_json, *args, **kwargs)
