"""
MemoryManager — orchestrates working/episodic/semantic/active/project memory.
"""

from memory.supabase_client import get_client, validate_schema
from memory.conversation import ConversationStore
from memory.episodic import EpisodicMemory
from memory.semantic import SemanticMemory
from memory.project import ProjectMemory
from memory.active import score_message_async

class MemoryManager:
    """Top-level memory coordinator for a single user session."""

    def __init__(self, user_id: str, resume_id: str | None = None):
        # Validate database schema before initializing stores
        missing = validate_schema()
        if missing:
            raise RuntimeError(
                "Deimos database schema is invalid or incomplete:\n" +
                "\n".join(f"- {m}" for m in missing) +
                "\n\nPlease run the setup SQL provided in docs/installation.md."
            )

        self.user_id = user_id
        self.client = get_client()
        self._active_project: str | None = None

        self.conversations = ConversationStore(user_id)
        self.episodic = EpisodicMemory(user_id)
        self.semantic = SemanticMemory(user_id)
        self.project = ProjectMemory(user_id)

        self.resumed = False
        if resume_id:
            self.conversations.resume_conversation(resume_id)
            self.resumed = True
        else:
            self.conversations.start_conversation()

    # ── Startup: build enriched system prompt ──────────────────────────────────

    def build_memory_context(self) -> str | None:
        sections = []

        facts_block = self.semantic.as_prompt_block()
        if facts_block:
            sections.append(f"### What you know about the user\n{facts_block}")

        known_projects = self.project.get_known_projects()
        if known_projects:
            sections.append(f"### Known projects\n" + "\n".join(f"- {p}" for p in known_projects))

        recent_summaries = self.episodic.get_recent_summaries(limit=3)
        if recent_summaries:
            joined = "\n\n".join(
                f"Session {i+1} ago: {s}" for i, s in enumerate(recent_summaries)
            )
            sections.append(f"### Recent conversation history\n{joined}")

        # Level-2 first (broadest), then level-1 (more specific)
        archive_l2 = self.episodic.get_latest_archive(level=2)
        if archive_l2:
            sections.append(f"### Long-term context (consolidated)\n{archive_l2}")
        else:
            archive_l1 = self.episodic.get_latest_archive(level=1)
            if archive_l1:
                sections.append(f"### Longer-term context\n{archive_l1}")

        if not sections:
            return None

        return (
            "## Memory\n"
            "The following is what you remember about this user from previous "
            "sessions. Use it naturally without explicitly mentioning that "
            "you're recalling memory unless asked.\n\n"
            + "\n\n".join(sections)
        )

    def detect_and_inject_project(self, user_input: str, ctx):
        """
        Detect if the user's message relates to a known project.
        If a new project is detected (or project changed), inject its facts
        into the context as a system-level message.
        Only runs once per unique project detection to avoid repeat injections.
        """
        detected = self.project.detect_project(user_input)
        if detected and detected != self._active_project:
            self._active_project = detected
            block = self.project.as_prompt_block(detected)
            if block:
                # Inject as a user→assistant pair so it's visible in the message history
                ctx.add_user(
                    f"[System: The following facts about the current project "
                    f"have been loaded from memory]\n{block}"
                )
                ctx.add_assistant(
                    f"Understood — I've loaded the context for {detected}. "
                    "I'll take it into account as we work."
                )

    def load_resumed_messages(self) -> list[dict]:
        if not self.resumed:
            return []
        rows = self.conversations.get_messages()
        restored = []
        for row in rows:
            role = row["role"]
            content = row["content"]
            if role == "tool":
                restored.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": content.get("tool_call_id"),
                        "content": content.get("content"),
                    }],
                })
            elif role == "assistant":
                restored.append({"role": "assistant", "content": content})
            else:
                restored.append({"role": "user", "content": content})
        return restored

    # ── Per-turn persistence ─────────────────────────────────────────────────

    def save_message(self, role: str, content):
        """
        Persist a message turn. User messages are scored for importance on a
        background thread (non-blocking); the row is patched when scoring lands.
        """
        self.conversations.save_message(role, content, importance=0, summary=None)

        if role == "user" and isinstance(content, str) and content.strip():
            def _apply(importance: int, summary: str):
                try:
                    self.conversations.update_message_importance(
                        content[:500], importance, summary
                    )
                except Exception:
                    pass

            score_message_async(content, _apply)

    # ── Conversation helpers ─────────────────────────────────────────────────

    SEGMENT_ITEM_CHARS = 1500     # per message / tool result in the transcript
    SEGMENT_TOTAL_CHARS = 60000   # whole transcript sent to the fast model

    def summarize_segment(self, messages: list[dict], prior_summary: str | None = None) -> str | None:
        """
        Summarize a block of trimmed messages, merged with the summary of any
        earlier trimmed blocks, so the session keeps one rolling summary.
        """
        if not messages:
            return None

        def clip(text) -> str:
            text = str(text or "")
            return text if len(text) <= self.SEGMENT_ITEM_CHARS else text[:self.SEGMENT_ITEM_CHARS] + " [...]"

        transcript = []
        for m in messages:
            content = m["content"]
            if isinstance(content, dict):  # assistant turn in OpenAI format
                parts = [clip(content.get("content"))] if content.get("content") else []
                for tc in content.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    parts.append(f"[Tool Call {fn.get('name')}]: {clip(fn.get('arguments'))}")
                content = "\n".join(parts)
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        parts.append(f"[Tool Call {item.get('name')}]: {clip(item.get('input'))}")
                    elif isinstance(item, dict) and item.get("type") == "tool_result":
                        parts.append(f"[Tool Result]: {clip(item.get('content'))}")
                    else:
                        parts.append(clip(item))
                content = "\n".join(parts)
            else:
                content = clip(content)
            transcript.append(f"{m['role']}: {content}")

        full_text = "\n".join(transcript)[-self.SEGMENT_TOTAL_CHARS:]
        earlier = f"Summary of even earlier messages:\n{prior_summary}\n\n" if prior_summary else ""
        prompt = (
            "Summarize the following conversation segment from a coding session into one "
            "concise summary, merged with the earlier summary if given. Preserve the user's "
            "goals, key decisions, files changed, commands run, and unresolved problems.\n\n"
            f"{earlier}Messages:\n{full_text}"
        )
        from llm.client import fast_llm
        try:
            return fast_llm().chat("You are a memory compression engine. Be concise and factual.", prompt, max_tokens=1024)
        except Exception:
            return None

    def save_segment_summary(self, summary: str):
        """Archive a mid-session summary in episodic memory for this conversation."""
        self.episodic.save_summary(self.conversations.conversation_id, summary)

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

    def get_project_facts(self, project_name: str | None = None) -> list[dict]:
        name = project_name or self._active_project
        if not name:
            return []
        return self.project.get_project_facts(name)

    def get_known_projects(self) -> list[str]:
        return self.project.get_known_projects()

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def end_session(self, ctx_messages: list[dict]):
        if not ctx_messages:
            self.conversations.end_conversation()
            return None

        conversation_id = self.conversations.conversation_id

        title = self.episodic.generate_title(ctx_messages)
        if title:
            self.conversations.set_title(title)

        self.episodic.summarize_conversation(conversation_id, ctx_messages)
        self.semantic.extract_and_store(ctx_messages)
        self.project.extract_and_store(ctx_messages)
        self.conversations.end_conversation()

        return title