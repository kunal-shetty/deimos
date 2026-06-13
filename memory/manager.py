"""
MemoryManager — orchestrates working/episodic/semantic memory.

Lifecycle:
  startup  → load semantic facts + recent episodic summaries → build system prompt
  per turn → save messages to conversations/messages tables
  on exit  → summarize this conversation (episodic) + extract facts (semantic)
"""

from memory.supabase_client import get_client
from memory.conversation import ConversationStore
from memory.episodic import EpisodicMemory
from memory.semantic import SemanticMemory


class MemoryManager:
    """Top-level memory coordinator for a single user session."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()

        self.conversations = ConversationStore(user_id)
        self.episodic = EpisodicMemory(user_id)
        self.semantic = SemanticMemory(user_id)

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

    # ── Per-turn persistence ─────────────────────────────────────────────────

    def save_message(self, role: str, content):
        self.conversations.save_message(role, content)

    # ── Shutdown: summarize + extract facts ──────────────────────────────────

    def end_session(self, ctx_messages: list[dict]):
        """
        Called on exit. Generates an episodic summary of this conversation
        and extracts/updates semantic facts.
        Safe to call even if the conversation was empty or very short.
        """
        if not ctx_messages:
            self.conversations.end_conversation()
            return

        conversation_id = self.conversations.conversation_id

        self.episodic.summarize_conversation(conversation_id, ctx_messages)
        self.semantic.extract_and_store(ctx_messages)
        self.conversations.end_conversation()