"""
Built-in slash commands for Deimos.
"""

from commands.base import Command, AppState
from agent.core import Agent
from memory.manager import MemoryManager
from memory.conversation import ConversationStore
from config import DEIMOS_USER_ID


class HelpCommand(Command):
    name = "help"
    description = "Show all available commands"
    def run(self, args, state):
        state.ui.print_help(REGISTRY.all())

class ChatsCommand(Command):
    name = "chats"
    description = "List past conversations"
    def run(self, args, state):
        try:
            state.ui.print_conversations(state.agent.memory.list_conversations(limit=20))
        except Exception as e:
            state.ui.error(f"Failed to load conversations: {e}")

class ResumeCommand(Command):
    name = "resume"
    description = "Resume a past conversation by id"
    usage = "/resume <conversation_id>"
    def run(self, args, state):
        target_id = args.strip()
        if not target_id:
            state.ui.error("Usage: /resume <conversation_id>  (run /chats to see ids)")
            return
        state.shutdown_current_agent()
        try:
            memory = MemoryManager(user_id=DEIMOS_USER_ID, resume_id=target_id)
            state.agent = Agent(ui=state.ui, llm=state.llm, tools=state.tools,
                                system_prompt=state.system_prompt, memory=memory)
            state.shutdown_done = False
        except Exception as e:
            state.ui.error(f"Failed to resume conversation: {e}")

class ResetCommand(Command):
    name = "reset"
    description = "Clear current context (memory preserved)"
    def run(self, args, state):
        state.agent.reset()
        state.ui.info("Conversation history cleared (memory preserved).")

class ExitCommand(Command):
    name = "exit"
    description = "Save memory and quit"
    def run(self, args, state):
        state.ui.info("Goodbye.")
        state.running = False

class MemoryCommand(Command):
    name = "memory"
    description = "Show what Deimos remembers about you"
    def run(self, args, state):
        try:
            facts = state.agent.memory.get_facts()
            state.ui.print_facts(facts)
        except Exception as e:
            state.ui.error(f"Failed to load memory: {e}")

class ProjectsCommand(Command):
    name = "projects"
    description = "List all known projects in memory"
    def run(self, args, state):
        try:
            projects = state.agent.memory.get_known_projects()
            if not projects:
                state.ui.info("No project memory found yet.")
                return
            state.ui.print_projects(projects)
        except Exception as e:
            state.ui.error(f"Failed to load projects: {e}")

class ProjectCommand(Command):
    name = "project"
    description = "Show memory for a specific project"
    usage = "/project <name>"
    def run(self, args, state):
        name = args.strip()
        if not name:
            state.ui.error("Usage: /project <name>  (run /projects to see known projects)")
            return
        try:
            facts = state.agent.memory.get_project_facts(name)
            state.ui.print_project_facts(name, facts)
        except Exception as e:
            state.ui.error(f"Failed to load project memory: {e}")

class TitleCommand(Command):
    name = "title"
    description = "Rename the current conversation"
    usage = "/title <new title>"
    def run(self, args, state):
        new_title = args.strip()
        if not new_title:
            state.ui.error("Usage: /title <new title>")
            return
        state.agent.memory.set_title(new_title)
        state.ui.info(f'Conversation renamed to "{new_title}".')

class DeleteCommand(Command):
    name = "delete"
    description = "Delete a past conversation by id"
    usage = "/delete <conversation_id>"
    def run(self, args, state):
        target_id = args.strip()
        if not target_id:
            state.ui.error("Usage: /delete <conversation_id>")
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

class StatusCommand(Command):
    name = "status"
    description = "Show current session info"
    def run(self, args, state):
        import os
        agent = state.agent
        title = agent.memory.current_title() or "(untitled)"
        conv_id = agent.memory.conversation_id or "—"
        msg_count = len(agent.ctx.messages)
        active_project = agent.memory._active_project or "—"
        state.ui.print_status({
            "Working directory": os.getcwd(),
            "Conversation": title,
            "Conversation ID": conv_id,
            "Active project": active_project,
            "Messages in context": msg_count,
            "Model": state.llm.model,
            "Verbose": "on" if state.ui.verbose else "off",
        })

class ModelCommand(Command):
    name = "model"
    description = "Show or switch the active model (persists across sessions)"
    usage = "/model [model_name]"
    def run(self, args, state):
        new_model = args.strip()
        if not new_model:
            state.ui.info(f"Current model: {state.llm.model}")
            return
        state.llm.set_model(new_model)
        try:
            from config import LOCAL_DIR, MODEL_FILE
            LOCAL_DIR.mkdir(parents=True, exist_ok=True)
            MODEL_FILE.write_text(new_model, encoding="utf-8")
        except Exception:
            pass
        state.ui.info(f"Switched to model: {new_model} (saved as default)")

class VerboseCommand(Command):
    name = "verbose"
    description = "Toggle verbose tool-output previews"
    def run(self, args, state):
        state.ui.verbose = not state.ui.verbose
        state.ui.info(f"Verbose mode: {'on' if state.ui.verbose else 'off'}")

class ClearScreenCommand(Command):
    name = "clear-screen"
    description = "Clear the terminal screen"
    def run(self, args, state):
        state.ui.clear_screen()


# ── Registry ─────────────────────────────────────────────────────────────────

REGISTRY = None

def build_registry():
    from commands.registry import CommandRegistry
    registry = CommandRegistry()
    for cmd_cls in [
        HelpCommand, ChatsCommand, ResumeCommand, ResetCommand, ExitCommand,
        MemoryCommand, ProjectsCommand, ProjectCommand,
        TitleCommand, DeleteCommand, StatusCommand,
        ModelCommand, VerboseCommand, ClearScreenCommand,
    ]:
        registry.register(cmd_cls())
    global REGISTRY
    REGISTRY = registry
    return registry