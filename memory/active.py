"""
Active memory: lightweight per-message importance scoring.

Each user message is scored 0-10 so that retrieval can prioritize what
matters. Scoring is a structured decision (a 5-level scale question,
answered by Jev or the Groq fallback) mapped onto 0-10.

Scoring runs on a background thread so the user's message is saved
immediately and the agent loop starts without waiting on an extra
round-trip. Results are applied to the stored row when they arrive
(best-effort — failures are silently ignored).
"""

import threading

from llm.decide import DecisionError, get_decider

IMPORTANCE_INSTRUCTIONS = (
    "How important is this user message for an AI coding agent's long-term "
    "memory of the user and their projects?"
)
IMPORTANCE_LEVELS = [
    "Trivial or small talk, e.g. 'hi', 'thanks', 'what is 2+2'.",
    "Routine one-off task with no lasting context, e.g. 'fix this bug', "
    "'write a function to reverse a list'.",
    "Some lasting context, e.g. mentions a file, library or approach likely to come up again.",
    "Durable information: preferences, project details, decisions, tech stack, goals.",
    "Critical identity or project facts, e.g. 'my name is X', 'I'm building "
    "project Y', major architectural decisions.",
]


def score_message(text: str) -> tuple[int, str | None]:
    """
    Score a user message's importance (0-10).
    Blocking variant — kept for callers that need the result immediately.
    Returns (importance, summary); summary is always None now that scoring
    is a typed decision. Falls back to (0, None) on any failure.
    """
    importance = _score(text)
    return (importance if importance is not None else 0), None


def score_message_async(text: str, apply_result) -> None:
    """
    Score a user message on a background daemon thread and invoke
    `apply_result(importance, summary)` when done. Never raises.
    """
    if not text or not text.strip():
        return

    def worker():
        try:
            importance = _score(text)
            if importance is not None:
                apply_result(importance, None)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _score(text: str) -> int | None:
    """Return importance on a 0-10 scale, or None if no backend could answer."""
    if not text or not text.strip():
        return None
    try:
        answer = get_decider().scale(text[:1000], IMPORTANCE_INSTRUCTIONS, IMPORTANCE_LEVELS)
    except DecisionError:
        return None
    top = len(IMPORTANCE_LEVELS) - 1
    return max(0, min(10, round(float(answer.value) / top * 10)))
