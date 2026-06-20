"""
Project memory: facts scoped to a specific project (e.g. HRBot, Deimos,
SnapNotes) rather than dumped into the global semantic_memories bucket.

At session start, a quick classifier looks at the user's first message and
known project names to decide if this session is about a specific project.
If so, that project's facts get injected into the system prompt.

At session end, facts are extracted and tagged with a project_name (or
left global if no specific project applies).
"""

import json
import requests
from config import LLM_API_KEY, LLM_MODEL
from memory.supabase_client import get_client
from memory.episodic import _messages_to_transcript, GROQ_API_URL

PROJECT_FACT_EXTRACTION_PROMPT = (
    "You are a fact extractor for an AI coding agent's memory system. "
    "Given a conversation transcript, extract durable facts that are SPECIFIC "
    "to a particular project the user is working on (e.g. tech stack details, "
    "architecture decisions, file/module names, conventions, ongoing tasks). "
    "For each fact, identify which project it belongs to. "
    "\n\n"
    "Respond ONLY with a JSON array of objects, each with 'project_name', "
    "'key', 'value', and 'confidence' (0.0-1.0). "
    "Use short snake_case keys and short, consistent project_name values "
    "(e.g. 'HRBot', 'Deimos', 'SnapNotes'). "
    "If no project-specific facts are present, respond with an empty array []. "
    "Do not include markdown formatting, backticks, or any text outside the JSON array."
)

PROJECT_DETECTION_PROMPT = (
    "You are a project classifier for an AI coding agent's memory system. "
    "Given a list of known project names and a user's message, decide which "
    "(if any) of the known projects this message is about. "
    "\n\n"
    "Respond ONLY with a JSON object: {\"project_name\": \"<name>\" or null}. "
    "Use null if the message doesn't clearly relate to any known project, or "
    "if it's a generic/small-talk message. "
    "Do not include markdown formatting, backticks, or any text outside the JSON object."
)


class ProjectMemory:
    """Manages extraction, retrieval, and detection of project-scoped facts."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_known_projects(self) -> list[str]:
        """Return distinct project names this user has memories for."""
        result = (
            self.client.table("project_memories")
            .select("project_name")
            .eq("user_id", self.user_id)
            .execute()
        )
        names = {row["project_name"] for row in result.data}
        return sorted(names)

    def get_project_facts(self, project_name: str) -> list[dict]:
        """Return all stored facts for a given project."""
        result = (
            self.client.table("project_memories")
            .select("key, value, confidence")
            .eq("user_id", self.user_id)
            .eq("project_name", project_name)
            .order("confidence", desc=True)
            .execute()
        )
        return result.data

    def as_prompt_block(self, project_name: str) -> str | None:
        """Format a project's facts as a block of text for the system prompt."""
        facts = self.get_project_facts(project_name)
        if not facts:
            return None
        lines = [f"- {f['key']}: {f['value']}" for f in facts]
        return f"### Project: {project_name}\n" + "\n".join(lines)

    def detect_project(self, user_message: str) -> str | None:
        """
        Given the user's message, decide if it's about a known project.
        Returns the matching project_name, or None.
        """
        known = self.get_known_projects()
        if not known:
            return None

        payload = {
            "model": LLM_MODEL,
            "max_tokens": 60,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": PROJECT_DETECTION_PROMPT},
                {
                    "role": "user",
                    "content": f"Known projects: {json.dumps(known)}\n\nUser message: {user_message[:500]}",
                },
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
            project_name = data.get("project_name")
            if project_name and project_name in known:
                return project_name
            return None
        except Exception:
            return None

    def extract_and_store(self, messages: list[dict]):
        """Extract project-scoped facts from a conversation and merge them in."""
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return

        facts = self._extract_facts(transcript)
        for fact in facts:
            self._merge_fact(
                fact["project_name"], fact["key"], fact["value"],
                fact.get("confidence", 0.75),
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract_facts(self, transcript: str) -> list[dict]:
        payload = {
            "model": LLM_MODEL,
            "max_tokens": 1024,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": PROJECT_FACT_EXTRACTION_PROMPT},
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

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]

            facts = json.loads(raw)
            if not isinstance(facts, list):
                return []
            return [
                f for f in facts
                if isinstance(f, dict) and "project_name" in f and "key" in f and "value" in f
            ]
        except Exception:
            return []

    def _merge_fact(self, project_name: str, key: str, value: str, confidence: float):
        existing = (
            self.client.table("project_memories")
            .select("*")
            .eq("user_id", self.user_id)
            .eq("project_name", project_name)
            .eq("key", key)
            .execute()
        )

        if not existing.data:
            self.client.table("project_memories").insert({
                "user_id": self.user_id,
                "project_name": project_name,
                "key": key,
                "value": value,
                "confidence": confidence,
            }).execute()
            return

        row = existing.data[0]

        if row["value"] == value:
            new_confidence = min(1.0, max(row["confidence"], confidence) + 0.02)
            self.client.table("project_memories").update({
                "confidence": round(new_confidence, 2),
                "last_updated": "now()",
            }).eq("id", row["id"]).execute()
        elif confidence >= row["confidence"]:
            self.client.table("project_memories").update({
                "value": value,
                "confidence": confidence,
                "last_updated": "now()",
            }).eq("id", row["id"]).execute()
        else:
            decayed = round(max(0.0, row["confidence"] - 0.1), 2)
            self.client.table("project_memories").update({
                "confidence": decayed,
                "last_updated": "now()",
            }).eq("id", row["id"]).execute()