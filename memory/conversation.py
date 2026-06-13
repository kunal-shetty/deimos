"""
Conversation + message persistence.
Handles creating conversations and saving each message turn to Supabase.
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

    def start_conversation(self, title: str | None = None) -> str:
        """Create a new conversation row and return its id."""
        result = self.client.table("conversations").insert({
            "user_id": self.user_id,
            "title": title,
        }).execute()
        self.conversation_id = result.data[0]["id"]
        return self.conversation_id

    def end_conversation(self):
        """Mark the conversation as ended."""
        if not self.conversation_id:
            return
        self.client.table("conversations").update({
            "ended_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", self.conversation_id).execute()

    def save_message(self, role: str, content, importance: int = 0, summary: str | None = None):
        """
        Save a single message turn.
        `content` can be a string, dict, or list — stored as jsonb.
        """
        if not self.conversation_id:
            self.start_conversation()

        # Ensure content is JSON-serializable
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


def _to_jsonable(obj):
    """Best-effort conversion of arbitrary objects to JSON-safe structures."""
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)