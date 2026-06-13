"""
Conversation + message persistence.
Handles creating conversations, saving messages, listing past conversations,
and resuming a previous conversation's message history.
"""

import json
from datetime import datetime, timezone
from memory.supabase_client import get_client


class ConversationStore:
    """Persists the current conversation's messages to Supabase."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = get_client()
        self.conversation_id: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start_conversation(self, title: str | None = None) -> str:
        """Create a new conversation row and return its id."""
        result = self.client.table("conversations").insert({
            "user_id": self.user_id,
            "title": title,
        }).execute()
        self.conversation_id = result.data[0]["id"]
        return self.conversation_id

    def resume_conversation(self, conversation_id: str):
        """Attach to an existing conversation (for continuing past chats)."""
        self.conversation_id = conversation_id
        # Clear ended_at so it shows as active again
        self.client.table("conversations").update({
            "ended_at": None
        }).eq("id", conversation_id).execute()

    def end_conversation(self):
        """Mark the conversation as ended."""
        if not self.conversation_id:
            return
        self.client.table("conversations").update({
            "ended_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", self.conversation_id).execute()

    def set_title(self, title: str):
        """Set/update the title of the current conversation."""
        if not self.conversation_id:
            return
        self.client.table("conversations").update({
            "title": title
        }).eq("id", self.conversation_id).execute()

    # ── Messages ─────────────────────────────────────────────────────────────

    def save_message(self, role: str, content, importance: int = 0, summary: str | None = None):
        """
        Save a single message turn.
        `content` can be a string, dict, or list — stored as jsonb.
        """
        if not self.conversation_id:
            self.start_conversation()

        if not isinstance(content, (str, int, float, bool, type(None))):
            content = _to_jsonable(content)

        self.client.table("messages").insert({
            "conversation_id": self.conversation_id,
            "role": role,
            "content": content,
            "importance": importance,
            "summary": summary,
        }).execute()

    def get_messages(self, conversation_id: str | None = None) -> list[dict]:
        """Fetch all messages for a conversation, oldest first."""
        cid = conversation_id or self.conversation_id
        if not cid:
            return []
        result = (
            self.client.table("messages")
            .select("*")
            .eq("conversation_id", cid)
            .order("created_at")
            .execute()
        )
        return result.data

    # ── Listing past conversations ──────────────────────────────────────────

    def list_conversations(self, limit: int = 20) -> list[dict]:
        """
        List past conversations for this user, most recent first.
        Returns id, title, started_at, ended_at, and a message count.
        """
        result = (
            self.client.table("conversations")
            .select("id, title, started_at, ended_at")
            .eq("user_id", self.user_id)
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        conversations = result.data

        # Attach message counts
        for conv in conversations:
            count_result = (
                self.client.table("messages")
                .select("id", count="exact")
                .eq("conversation_id", conv["id"])
                .execute()
            )
            conv["message_count"] = count_result.count or 0

        return conversations


def _to_jsonable(obj):
    """Best-effort conversion of arbitrary objects to JSON-safe structures."""
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)