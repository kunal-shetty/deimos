"""
Semantic memory: persistent key-value facts about the user
(name, preferences, skills, current projects, etc.)

At the end of each conversation, facts are extracted and merged into
semantic_memories with confidence/frequency tracking.
"""

import json
import requests
from config import LLM_API_KEY, LLM_MODEL
from memory.supabase_client import get_client
from memory.episodic import _messages_to_transcript, GROQ_API_URL

FACT_EXTRACTION_PROMPT = (
    "You are a fact extractor for an AI coding agent's memory system. "
    "Given a conversation transcript, extract durable facts about the USER "
    "(not about the assistant). Examples of good facts: their name, role, "
    "tech stack preferences, ongoing projects, tools they use, coding style "
    "preferences, communication preferences. "
    "Ignore one-off requests or temporary details. "
    "\n\n"
    "Respond ONLY with a JSON array of objects, each with 'key', 'value', "
    "and 'confidence' (0.0-1.0, how certain/durable this fact seems). "
    "Use short snake_case keys (e.g. 'name', 'preferred_language', "
    "'current_project', 'os'). "
    "If no durable facts are present, respond with an empty array []. "
    "Do not include markdown formatting, backticks, or any text outside the JSON array."
)


class SemanticMemory:
    """Manages extraction, merging, and retrieval of user facts."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_and_store(self, messages: list[dict]):
        """Extract facts from a conversation and merge them into storage."""
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return

        facts = self._extract_facts(transcript)
        for fact in facts:
            self._merge_fact(fact["key"], fact["value"], fact.get("confidence", 0.75))

    def get_all_facts(self) -> list[dict]:
        """Return all stored facts for this user, ordered by confidence."""
        result = (
            self.client.table("semantic_memories")
            .select("key, value, confidence, frequency")
            .eq("user_id", self.user_id)
            .order("confidence", desc=True)
            .execute()
        )
        return result.data

    def as_prompt_block(self) -> str | None:
        """Format facts as a block of text for the system prompt."""
        facts = self.get_all_facts()
        if not facts:
            return None
        lines = [f"- {f['key']}: {f['value']}" for f in facts]
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract_facts(self, transcript: str) -> list[dict]:
        payload = {
            "model": LLM_MODEL,
            "max_tokens": 1024,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": FACT_EXTRACTION_PROMPT},
                {"role": "user", "content": transcript},
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
                timeout=60,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()

            # Strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]

            facts = json.loads(raw)
            if not isinstance(facts, list):
                return []
            return [
                f for f in facts
                if isinstance(f, dict) and "key" in f and "value" in f
            ]
        except Exception:
            return []

    def _merge_fact(self, key: str, value: str, confidence: float):
        """
        Insert or update a fact.
        If the key exists with a different value, the new fact wins if its
        confidence is >= existing confidence (recency + LLM judgment based).
        Frequency increments when the same key+value is reaffirmed.
        """
        existing = (
            self.client.table("semantic_memories")
            .select("*")
            .eq("user_id", self.user_id)
            .eq("key", key)
            .execute()
        )

        if not existing.data:
            self.client.table("semantic_memories").insert({
                "user_id": self.user_id,
                "key": key,
                "value": value,
                "confidence": confidence,
                "frequency": 1,
            }).execute()
            return

        row = existing.data[0]

        if row["value"] == value:
            # Reaffirmed — bump frequency and confidence slightly
            new_confidence = min(1.0, max(row["confidence"], confidence) + 0.02)
            self.client.table("semantic_memories").update({
                "confidence": round(new_confidence, 2),
                "frequency": row["frequency"] + 1,
                "last_updated": "now()",
            }).eq("id", row["id"]).execute()
        else:
            # Conflicting value — replace if new confidence >= old, else keep old
            # but slightly decay old confidence to reflect uncertainty
            if confidence >= row["confidence"]:
                self.client.table("semantic_memories").update({
                    "value": value,
                    "confidence": confidence,
                    "frequency": 1,
                    "last_updated": "now()",
                }).eq("id", row["id"]).execute()
            else:
                decayed = round(max(0.0, row["confidence"] - 0.1), 2)
                self.client.table("semantic_memories").update({
                    "confidence": decayed,
                    "last_updated": "now()",
                }).eq("id", row["id"]).execute()