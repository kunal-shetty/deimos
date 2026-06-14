"""
Built-in slash commands for Deimos.
"""

from commands.base import Command, AppState
from agent.core import Agent
from memory.manager import MemoryManager
from memory.conversation import ConversationStore
from config import DEIMOS_USER_ID, LLM_MODEL


# ── /help ────────────────────────────────────────────────────────────────────

class HelpCommand(Command):
    name = "help"
    description = "Show all available commands"

    def run(self, args: str, state: AppState):
        state.ui.print_help(REGISTRY.all())


# ── /chats ───────────────────────────────────────────────────────────────────

class ChatsCommand(Command):
    name = "chats"
    description = "List past conversations"

    def run(self, args: str, state: AppState):
        try:
            conversations = state.agent.memory.list_conversations(limit=20)
            state.ui.print_conversations(conversations)
        except Exception as e:
            state.ui.error(f"Failed to load conversations: {e}")


# ── /resume ──────────────────────────────────────────────────────────────────

class ResumeCommand(Command):
    name = "resume"
    description = "Resume a past conversation by id"
    usage = "/resume <conversation_id>"

    def run(self, args: str, state: AppState):
        target_id = args.strip()
        if not target_id:
            state.ui.error("Usage: /resume <conversation_id>  (run /chats to see ids)")
            return

        state.shutdown_current_agent()

        try:
            memory = MemoryManager(user_id=DEIMOS_USER_ID, resume_id=target_id)
            state.agent = Agent(
                ui=state.ui, llm=state.llm, tools=state.tools,
                system_prompt=state.system_prompt, memory=memory,
            )
            state.shutdown_done = False
        except Exception as e:
            state.ui.error(f"Failed to resume conversation: {e}")


# ── /reset ───────────────────────────────────────────────────────────────────

class ResetCommand(Command):
    name = "reset"
    description = "Clear current context (memory preserved)"

    def run(self, args: str, state: AppState):
        state.agent.reset()
        state.ui.info("Conversation history cleared (memory preserved).")


# ── /exit ────────────────────────────────────────────────────────────────────

class ExitCommand(Command):
    name = "exit"
    description = "Save memory and quit"

    def run(self, args: str, state: AppState):
        state.ui.info("Goodbye.")
        state.running = False


# ── /memory ──────────────────────────────────────────────────────────────────

class MemoryCommand(Command):
    name = "memory"
    description = "Show what Deimos remembers about you"

    def run(self, args: str, state: AppState):
        try:
            facts = state.agent.memory.get_facts()
            state.ui.print_facts(facts)
        except Exception as e:
            state.ui.error(f"Failed to load memory: {e}")


# ── /title ───────────────────────────────────────────────────────────────────

class TitleCommand(Command):
    name = "title"
    description = "Rename the current conversation"
    usage = "/title <new title>"

    def run(self, args: str, state: AppState):
        new_title = args.strip()
        if not new_title:
            state.ui.error("Usage: /title <new title>")
            return
        state.agent.memory.set_title(new_title)
        state.ui.info(f"Conversation renamed to \"{new_title}\".")


# ── /delete ──────────────────────────────────────────────────────────────────

class DeleteCommand(Command):
    name = "delete"
    description = "Delete a past conversation by id"
    usage = "/delete <conversation_id>"

    def run(self, args: str, state: AppState):
        target_id = args.strip()
        if not target_id:
            state.ui.error("Usage: /delete <conversation_id>  (run /chats to see ids)")
            return

        if target_id == state.agent.memory.conversation_id:
            state.ui.error("Cannot delete the conversation currently in progress.")
            return

        try:
            store = ConversationStore(user_id=DEIMOS_USER_ID)
            ok = store.delete_conversation(target_id)
            if ok:
                state.ui.info(f"Deleted conversation {target_id}.")
            else:
                state.ui.error(f"No conversation found with id {target_id}.")
        except Exception as e:
            state.ui.error(f"Failed to delete conversation: {e}")


# ── /status ──────────────────────────────────────────────────────────────────

class StatusCommand(Command):
    name = "status"
    description = "Show current session info"

    def run(self, args: str, state: AppState):
        agent = state.agent
        title = agent.memory.current_title() or "(untitled)"
        conv_id = agent.memory.conversation_id or "—"
        message_count = len(agent.ctx.messages)
        model = state.llm.model

        state.ui.print_status({
            "Conversation": title,
            "Conversation ID": conv_id,
            "Messages in context": message_count,
            "Model": model,
            "Verbose": "on" if state.ui.verbose else "off",
        })


# ── /model ───────────────────────────────────────────────────────────────────

class ModelCommand(Command):
    name = "model"
    description = "Show or switch the active model"
    usage = "/model [model_name]"

    def run(self, args: str, state: AppState):
        new_model = args.strip()
        if not new_model:
            state.ui.info(f"Current model: {state.llm.model}")
            return
        state.llm.set_model(new_model)
        state.ui.info(f"Switched model to: {new_model}")


# ── /verbose ─────────────────────────────────────────────────────────────────

class VerboseCommand(Command):
    name = "verbose"
    description = "Toggle verbose tool-output previews"

    def run(self, args: str, state: AppState):
        state.ui.verbose = not state.ui.verbose
        status = "on" if state.ui.verbose else "off"
        state.ui.info(f"Verbose mode: {status}")


# ── /clear-screen ────────────────────────────────────────────────────────────

class ClearScreenCommand(Command):
    name = "clear-screen"
    description = "Clear the terminal screen"

    def run(self, args: str, state: AppState):
        state.ui.clear_screen()


# ── Build the registry ──────────────────────────────────────────────────────

REGISTRY = None


def build_registry():
    """Construct and return the global command registry."""
    from commands.registry import CommandRegistry

    registry = CommandRegistry()
    for cmd_cls in [
        HelpCommand, ChatsCommand, ResumeCommand, ResetCommand, ExitCommand,
        MemoryCommand, TitleCommand, DeleteCommand, StatusCommand,
        ModelCommand, VerboseCommand, ClearScreenCommand,
    ]:
        registry.register(cmd_cls())

    global REGISTRY
    REGISTRY = registry
    return registry