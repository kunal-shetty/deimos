import json
import requests
from config import LLM_API_KEY, LLM_MODEL
from memory.supabase_client import get_client

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
ARCHIVE_BATCH_SIZE = 3    # compress into level-1 after 3 episodic summaries
ARCHIVE_L2_BATCH_SIZE = 3  # compress into level-2 after 3 level-1 archives

EPISODIC_SUMMARY_PROMPT = (
    "You are a memory summarizer for an AI coding agent called Deimos. "
    "Given the full transcript of a conversation, write a 300-500 word summary "
    "covering: what the user was working on, key decisions, files created or "
    "edited, commands run, problems solved. Write in plain prose, third person. "
    "Output only the summary, no preamble."
)
ARCHIVE_COMPRESSION_PROMPT = (
    "Combine the following conversation summaries into a single condensed "
    "summary (~400 words) capturing overall themes and trajectory. "
    "Output only the summary, no preamble."
)
TITLE_PROMPT = (
    "Generate a short, catchy title (3-6 words) for this conversation, based "
    "on the transcript. No quotes, no trailing punctuation, no generic titles. "
    "Respond with ONLY the title text."
)


class EpisodicMemory:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()

    def summarize_conversation(self, conversation_id: str, messages: list[dict]):
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return
        summary = _call_llm(EPISODIC_SUMMARY_PROMPT, transcript, max_tokens=700)
        if not summary:
            return
        self.client.table("episodic_memories").insert({
            "user_id": self.user_id, "conversation_id": conversation_id, "summary": summary,
        }).execute()
        self._maybe_compress()

    def generate_title(self, messages: list[dict]) -> str | None:
        transcript = _messages_to_transcript(messages)
        if not transcript.strip():
            return None
        title = _call_llm(TITLE_PROMPT, transcript[:2000], max_tokens=30)
        if not title:
            return None
        return title.strip().strip("\"'").strip()[:80] or None

    def get_recent_summaries(self, limit: int = 3) -> list[str]:
        result = (
            self.client.table("episodic_memories").select("summary")
            .eq("user_id", self.user_id).order("created_at", desc=True).limit(limit).execute()
        )
        return [row["summary"] for row in result.data]

    def get_latest_archive(self, level: int = 1) -> str | None:
        result = (
            self.client.table("archive_memories").select("summary")
            .eq("user_id", self.user_id).eq("level", level)
            .order("created_at", desc=True).limit(1).execute()
        )
        return result.data[0]["summary"] if result.data else None

    def _maybe_compress(self):
        self._maybe_compress_level("episodic_memories", None, 1, ARCHIVE_BATCH_SIZE)
        self._maybe_compress_level("archive_memories", 1, 2, ARCHIVE_L2_BATCH_SIZE)

    def _maybe_compress_level(self, source_table, source_level, target_level, batch_size):
        # Collect all source ids already consumed by archives at target_level.
        # Normalize to lowercase strings to guard against any UUID formatting
        # inconsistencies between the uuid[] array and the id column.
        used_ids = set()
        consumed = (
            self.client.table("archive_memories").select("source_ids")
            .eq("user_id", self.user_id).eq("level", target_level).execute()
        )
        for row in consumed.data:
            ids = row.get("source_ids") or []
            used_ids.update(str(i).lower() for i in ids)

        query = self.client.table(source_table).select("id, summary, created_at").eq("user_id", self.user_id)
        if source_level is not None:
            query = query.eq("level", source_level)
        all_rows = query.order("created_at").execute()
        unconsumed = [row for row in all_rows.data if str(row["id"]).lower() not in used_ids]

        if len(unconsumed) < batch_size:
            return

        batch = unconsumed[:batch_size]
        combined_text = "\n\n---\n\n".join(row["summary"] for row in batch)
        compressed = _call_llm(ARCHIVE_COMPRESSION_PROMPT, combined_text, max_tokens=700)
        if not compressed:
            return

        self.client.table("archive_memories").insert({
            "user_id": self.user_id, "level": target_level, "summary": compressed,
            "source_ids": [row["id"] for row in batch],
        }).execute()

        if target_level == 1:
            self._maybe_compress_level("archive_memories", 1, 2, ARCHIVE_L2_BATCH_SIZE)


def _messages_to_transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, dict):
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
    if not user_content.strip():
        return None
    payload = {
        "model": LLM_MODEL, "max_tokens": max_tokens, "temperature": 0.3,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
    }
    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None