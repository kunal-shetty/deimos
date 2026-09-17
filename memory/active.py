"""
Active memory: lightweight per-message importance scoring.

Each user message is scored 0-10 by a quick, cheap LLM call so that
later phases (retrieval, reflection) can prioritize what matters.

Scoring runs on a background thread so the user's message is saved
immediately and the agent loop starts without waiting on an extra
LLM round-trip. Results are applied to the stored row when they arrive
(best-effort — failures are silently ignored).
"""

import json
import threading
import requests
from config import LLM_API_KEY, LLM_MODEL

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

IMPORTANCE_PROMPT = (
    "Rate how important this user message is for long-term memory, on a "
    "scale of 0-10. "
    "0-2: trivial/small talk (e.g. 'hi', 'thanks', 'what is 2+2'). "
    "3-5: routine task request with no lasting context (e.g. 'fix this bug', "
    "'write a function to reverse a list'). "
    "6-8: reveals durable info — preferences, project details, decisions, "
    "tech stack, goals. "
    "9-10: critical identity/project facts (e.g. 'my name is X', 'I'm building "
    "project Y', major architectural decisions). "
    "\n\nRespond with ONLY a JSON object: {\"importance\": <int>, \"summary\": \"<one short sentence>\"}. "
    "No markdown, no extra text."
)


def score_message(text: str) -> tuple[int, str]:
    """
    Score a user message's importance and produce a one-line summary.
    Blocking variant — kept for callers that need the result immediately.
    Returns (importance, summary). Falls back to (0, "") on any failure.
    """
    data = _score_request(text)
    if not data:
        return 0, ""
    importance = max(0, min(10, int(data.get("importance", 0))))
    summary = str(data.get("summary", "")).strip()
    return importance, summary


def score_message_async(text: str, apply_result) -> None:
    """
    Score a user message on a background daemon thread and invoke
    `apply_result(importance, summary)` when done. Never raises.
    """
    if not text or not text.strip():
        return

    def worker():
        try:
            data = _score_request(text)
            if data:
                apply_result(int(data.get("importance", 0)), str(data.get("summary", "")).strip())
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _score_request(text: str) -> dict | None:
    """Call the LLM and return the parsed importance JSON, or None on failure."""
    payload = {
        "model": LLM_MODEL,
        "max_tokens": 100,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": IMPORTANCE_PROMPT},
            {"role": "user", "content": text[:1000]},
        ],
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()

        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
