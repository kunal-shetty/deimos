"""
Active memory: lightweight per-message importance scoring.

Each user message is scored 0-10 by a quick, cheap LLM call so that
later phases (retrieval, reflection) can prioritize what matters.
This is intentionally fast and low-token — it does NOT block the
main agent response from streaming.
"""

import json
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
    Returns (importance, summary). Falls back to (0, "") on any failure.
    """
    if not text or not text.strip():
        return 0, ""

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
        importance = int(data.get("importance", 0))
        importance = max(0, min(10, importance))
        summary = str(data.get("summary", "")).strip()
        return importance, summary
    except Exception:
        return 0, ""