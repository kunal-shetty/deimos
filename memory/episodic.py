"""
Episodic memory: 300-500 word summaries of finished conversations.
Also handles compression into archive_memories once enough episodes pile up.
"""

import json
import requests
from config import LLM_API_KEY, LLM_MODEL
from memory.supabase_client import get_client

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# After this many episodic memories accumulate (uncompressed), compress them
ARCHIVE_BATCH_SIZE = 10

EPISODIC_SUMMARY_PROMPT = (
    "You are a memory summarizer for an AI coding agent called Deimos. "
    "Given the full transcript of a conversation between a user and Deimos, "
    "write a 300-500 word summary covering: "
    "what the user was working on, key decisions made, files created or edited, "
    "commands run, problems solved, and anything the agent should remember for "
    "future conversations. Be specific (mention project names, languages, file names). "
    "Write in plain prose, third person ('The user...'). "
    "Output only the summary, no preamble or headers."
)

ARCHIVE_COMPRESSION_PROMPT = (
    "You are a memory consolidator for an AI coding agent. "
    "Below are several conversation summaries from different sessions. "
    "Combine them into a single condensed summary (around 400 words) that "
    "captures the overall themes, ongoing projects, recurring topics, and "
    "the user's general trajectory across these sessions. "
    "Output only the summary, no preamble or headers."
)


class EpisodicMemory:
    """Manages episodic summaries and their compression into archives."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()

    # ── Public API ────────────────────────────────────────────────────────────

    def summarize_conversation(self, conversation_id: str, messages: list[dict]):
        """Generate and store a summary for a finished conversation."""
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return

        summary = _call_llm(EPISODIC_SUMMARY_PROMPT, transcript, max_tokens=700)
        if not summary:
            return

        self.client.table("episodic_memories").insert({
            "user_id": self.user_id,
            "conversation_id": conversation_id,
            "summary": summary,
        }).execute()

        self._maybe_compress()

    def get_recent_summaries(self, limit: int = 3) -> list[str]:
        """Get the most recent episodic summaries (level-0)."""
        result = (
            self.client.table("episodic_memories")
            .select("summary")
            .eq("user_id", self.user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [row["summary"] for row in result.data]

    def get_latest_archive(self, level: int = 1) -> str | None:
        """Get the most recent compressed archive summary at the given level."""
        result = (
            self.client.table("archive_memories")
            .select("summary")
            .eq("user_id", self.user_id)
            .eq("level", level)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0]["summary"] if result.data else None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_compress(self):
        """If enough uncompressed episodic memories exist, compress them."""
        # Get all episodic memory ids already used in archives
        used_ids = set()
        archives = (
            self.client.table("archive_memories")
            .select("source_ids")
            .eq("user_id", self.user_id)
            .eq("level", 1)
            .execute()
        )
        for row in archives.data:
            used_ids.update(row["source_ids"])

        # Get all episodic memories not yet archived
        all_episodic = (
            self.client.table("episodic_memories")
            .select("id, summary, created_at")
            .eq("user_id", self.user_id)
            .order("created_at")
            .execute()
        )
        unarchived = [row for row in all_episodic.data if row["id"] not in used_ids]

        if len(unarchived) < ARCHIVE_BATCH_SIZE:
            return

        batch = unarchived[:ARCHIVE_BATCH_SIZE]
        combined_text = "\n\n---\n\n".join(row["summary"] for row in batch)

        compressed = _call_llm(ARCHIVE_COMPRESSION_PROMPT, combined_text, max_tokens=700)
        if not compressed:
            return

        self.client.table("archive_memories").insert({
            "user_id": self.user_id,
            "level": 1,
            "summary": compressed,
            "source_ids": [row["id"] for row in batch],
        }).execute()


# ── helpers ──────────────────────────────────────────────────────────────────

def _messages_to_transcript(messages: list[dict]) -> str:
    """Convert stored messages into a readable transcript for summarization."""
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, str):
            text = content
        elif isinstance(content, dict):
            # OpenAI-format assistant message
            text = content.get("content") or ""
            if content.get("tool_calls"):
                for tc in content["tool_calls"]:
                    fn = tc.get("function", {})
                    text += f"\n[called tool: {fn.get('name')} with {fn.get('arguments')}]"
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    parts.append(f"[tool result: {str(block.get('content', ''))[:200]}]")
            text = " ".join(parts)
        else:
            text = str(content)

        if text and text.strip():
            lines.append(f"{role.upper()}: {text.strip()[:600]}")

    return "\n".join(lines)


def _call_llm(system_prompt: str, user_content: str, max_tokens: int = 512) -> str | None:
    """Call Groq for a one-off summarization task."""
    if not user_content.strip():
        return None

    payload = {
        "model": LLM_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None