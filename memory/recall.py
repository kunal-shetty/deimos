"""
Recall: fetch the memories relevant to the current message.

Wraps the `search_memories` Postgres function (memory/migrations/001_search.sql),
which ranks facts, project facts, session summaries and past user messages by
full-text relevance, confidence/importance and recency. When the migration
hasn't been run, `available` is False and callers fall back to loading facts
up front as before.
"""

from datetime import datetime, timezone

RECALL_LIMIT = 8
RELATIVE_CUTOFF = 0.2  # drop results scoring under this fraction of the best match

_LABELS = {"fact": "fact", "session": "earlier session", "message": "you said"}


class MemoryRecall:
    def __init__(self, client, user_id: str):
        self.client = client
        self.user_id = user_id
        self.available = self._probe()

    def search(self, query: str, exclude_conversation: str | None = None,
               limit: int = RECALL_LIMIT) -> list[dict]:
        if not self.available or not query or not query.strip():
            return []
        try:
            result = self.client.rpc("search_memories", {
                "p_user_id": self.user_id,
                "p_query": query[:2000],
                "p_limit": limit,
                "p_exclude_conversation": exclude_conversation,
            }).execute()
        except Exception:
            return []
        rows = [r for r in (result.data or []) if r.get("body")]
        if not rows:
            return []
        best = max(float(r.get("score") or 0) for r in rows)
        return [r for r in rows if float(r.get("score") or 0) >= best * RELATIVE_CUTOFF]

    def _probe(self) -> bool:
        """True when the search function exists (the migration has been run)."""
        try:
            self.client.rpc("search_memories", {
                "p_user_id": self.user_id, "p_query": "deimos", "p_limit": 1,
                "p_exclude_conversation": None,
            }).execute()
            return True
        except Exception:
            return False


def format_recall(rows: list[dict], skip_bodies: set[str] = frozenset(), now: datetime | None = None) -> str | None:
    """A system-prompt block listing recalled memories, or None if there are none."""
    now = now or datetime.now(timezone.utc)
    lines = []
    for r in rows:
        body = " ".join(str(r["body"]).split())
        if body in skip_bodies:
            continue
        if len(body) > 400:
            body = body[:400] + "…"
        kind = r.get("kind")
        label = f"project {r['project_name']}" if kind == "project" else _LABELS.get(kind, kind)
        when = _ago(r.get("created_at"), now) if kind in ("session", "message") else ""
        lines.append(f"- ({label}{', ' + when if when else ''}) {body}")
    if not lines:
        return None
    return (
        "## Relevant memory\n"
        "Retrieved from earlier sessions because they may relate to the current message. "
        "Use them when they help; don't mention that you looked them up.\n"
        + "\n".join(lines)
    )


def _ago(timestamp, now: datetime) -> str:
    try:
        then = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = (now - then).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    return then.strftime("%b %Y")
