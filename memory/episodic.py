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

# After this many level-1 archives accumulate, compress them into a level-2
ARCHIVE_L2_BATCH_SIZE = 5

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

TITLE_PROMPT = (
    "Generate a short, catchy title (3-6 words) for this conversation between "
    "a user and an AI coding agent, based on the transcript below. "
    "The title should capture the main topic or task (e.g. "
    "'Binary Search in Python', 'HRBot Branches Module', 'Deimos Memory System'). "
    "Do not use quotes, punctuation at the end, or generic titles like 'Conversation'. "
    "Respond with ONLY the title text, nothing else."
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

    def generate_title(self, messages: list[dict]) -> str | None:
        """Generate a short, descriptive title for a conversation."""
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return None
        title = _call_llm(TITLE_PROMPT, transcript[:2000], max_tokens=30)
        if not title:
            return None
        # Clean up: strip quotes/whitespace, cap length
        title = title.strip().strip('"\'').strip()
        return title[:80] if title else None

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
        """Compress episodic memories into level-1, then level-1 into level-2."""
        self._maybe_compress_level(
            source_table="episodic_memories",
            source_level=None,
            target_level=1,
            batch_size=ARCHIVE_BATCH_SIZE,
        )
        self._maybe_compress_level(
            source_table="archive_memories",
            source_level=1,
            target_level=2,
            batch_size=ARCHIVE_L2_BATCH_SIZE,
        )

    def _maybe_compress_level(self, source_table: str, source_level: int | None,
                               target_level: int, batch_size: int):
        """
        Generic compression step: if `batch_size` unconsumed rows exist in
        `source_table` (filtered by `source_level` if given), summarize them
        into a new row in archive_memories at `target_level`.
        """
        # Collect ids already consumed by archives at target_level
        used_ids = set()
        consumed = (
            self.client.table("archive_memories")
            .select("source_ids")
            .eq("user_id", self.user_id)
            .eq("level", target_level)
            .execute()
        )
        for row in consumed.data:
            used_ids.update(row["source_ids"])

        # Fetch candidate source rows
        query = (
            self.client.table(source_table)
            .select("id, summary, created_at")
            .eq("user_id", self.user_id)
        )
        if source_level is not None:
            query = query.eq("level", source_level)
        all_rows = query.order("created_at").execute()

        unconsumed = [row for row in all_rows.data if row["id"] not in used_ids]

        if len(unconsumed) < batch_size:
            return

        batch = unconsumed[:batch_size]
        combined_text = "\n\n---\n\n".join(row["summary"] for row in batch)

        compressed = _call_llm(ARCHIVE_COMPRESSION_PROMPT, combined_text, max_tokens=700)
        if not compressed:
            return

        self.client.table("archive_memories").insert({
            "user_id": self.user_id,
            "level": target_level,
            "summary": compressed,
            "source_ids": [row["id"] for row in batch],
        }).execute()

        # Recurse in case this pushes the next level over its threshold too
        if target_level == 1:
            self._maybe_compress_level(
                source_table="archive_memories",
                source_level=1,
                target_level=2,
                batch_size=ARCHIVE_L2_BATCH_SIZE,
            )


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