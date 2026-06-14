"""
MemoryManager — orchestrates working/episodic/semantic/active memory.

Lifecycle:
  startup  → load semantic facts + recent episodic summaries → build system prompt
             (optionally resume a past conversation's messages)
  per turn → save messages to conversations/messages tables, score importance
  on exit  → summarize this conversation (episodic) + generate title +
             extract facts (semantic)
"""

from memory.supabase_client import get_client
from memory.conversation import ConversationStore
from memory.episodic import EpisodicMemory
from memory.semantic import SemanticMemory
from memory.active import score_message


class MemoryManager:
    """Top-level memory coordinator for a single user session."""

    def __init__(self, user_id: str, resume_id: str | None = None):
        self.user_id = user_id
        self.client = get_client()

        self.conversations = ConversationStore(user_id)
        self.episodic = EpisodicMemory(user_id)
        self.semantic = SemanticMemory(user_id)

        self.resumed = False
        if resume_id:
            self.conversations.resume_conversation(resume_id)
            self.resumed = True
        else:
            self.conversations.start_conversation()

    # ── Startup: build enriched system prompt ──────────────────────────────────

    def build_memory_context(self) -> str | None:
        """
        Returns a block of text to append to the system prompt, containing
        semantic facts + recent episodic summaries + archive overview.
        Returns None if there's no memory yet (first ever run).
        """
        sections = []

        facts_block = self.semantic.as_prompt_block()
        if facts_block:
            sections.append(f"### What you know about the user\n{facts_block}")

        recent_summaries = self.episodic.get_recent_summaries(limit=3)
        if recent_summaries:
            joined = "\n\n".join(
                f"Session {i+1} ago: {s}" for i, s in enumerate(recent_summaries)
            )
            sections.append(f"### Recent conversation history\n{joined}")

        archive = self.episodic.get_latest_archive(level=1)
        if archive:
            sections.append(f"### Longer-term context\n{archive}")

        if not sections:
            return None

        return (
            "## Memory\n"
            "The following is what you remember about this user from previous "
            "sessions. Use it naturally without explicitly mentioning that "
            "you're recalling memory unless asked.\n\n"
            + "\n\n".join(sections)
        )

    def load_resumed_messages(self) -> list[dict]:
        """
        If resuming a past conversation, return its stored messages
        converted back into the format Context expects.
        """
        if not self.resumed:
            return []

        rows = self.conversations.get_messages()
        restored = []
        for row in rows:
            role = row["role"]
            content = row["content"]

            if role == "tool":
                # Stored as {"tool_call_id":..., "name":..., "content":...}
                restored.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": content.get("tool_call_id"),
                        "content": content.get("content"),
                    }],
                })
            elif role == "assistant":
                # content is the raw OAI message dict
                restored.append({"role": "assistant", "content": content})
            else:
                restored.append({"role": "user", "content": content})

        return restored

    # ── Per-turn persistence ─────────────────────────────────────────────────

    def save_message(self, role: str, content):
        importance, summary = 0, None

        # Active memory: score user messages only (keeps it cheap)
        if role == "user" and isinstance(content, str):
            importance, summary = score_message(content)

        self.conversations.save_message(role, content, importance=importance, summary=summary)

    # ── Conversation listing ────────────────────────────────────────────────

    def list_conversations(self, limit: int = 20) -> list[dict]:
        return self.conversations.list_conversations(limit=limit)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.conversations.delete_conversation(conversation_id)

    @property
    def conversation_id(self) -> str | None:
        return self.conversations.conversation_id

    def current_title(self) -> str | None:
        if not self.conversation_id:
            return None
        conv = self.conversations.get_conversation(self.conversation_id)
        return conv.get("title") if conv else None

    def set_title(self, title: str):
        self.conversations.set_title(title)

    def get_facts(self) -> list[dict]:
        return self.semantic.get_all_facts()

    # ── Shutdown: summarize + title + extract facts ──────────────────────────

    def end_session(self, ctx_messages: list[dict]):
        """
        Called on exit. Generates an episodic summary + title for this
        conversation and extracts/updates semantic facts.
        Safe to call even if the conversation was empty or very short.
        """
        if not ctx_messages:
            self.conversations.end_conversation()
            return

        conversation_id = self.conversations.conversation_id

        title = self.episodic.generate_title(ctx_messages)
        if title:
            self.conversations.set_title(title)

        self.episodic.summarize_conversation(conversation_id, ctx_messages)
        self.semantic.extract_and_store(ctx_messages)
        self.conversations.end_conversation()

        return title