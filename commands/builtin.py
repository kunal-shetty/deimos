"""
Built-in slash commands for Deimos.
"""
import os
import subprocess
import sys

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
                                system_prompt=state.system_prompt, memory=memory,
                                plan_mode=state.agent.plan_mode)
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
            state.ui.print_facts(state.agent.memory.get_facts())
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
            for p in projects:
                print(f"  · {p}")
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
            if not facts:
                state.ui.info(f"No facts found for project '{name}'.")
                return
            for f in facts:
                print(f"  {f['key']}: {f['value']}")
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
            state.ui.info(f"Deleted conversation {target_id}." if ok else f"No conversation found with id {target_id}.")
        except Exception as e:
            state.ui.error(f"Failed to delete conversation: {e}")


class StatusCommand(Command):
    name = "status"
    description = "Show current session info"
    def run(self, args, state):
        agent = state.agent
        state.ui.print_status({
            "Working directory": os.getcwd(),
            "Conversation": agent.memory.current_title() or "(untitled)",
            "Conversation ID": agent.memory.conversation_id or "—",
            "Active project": agent.memory._active_project or "—",
            "Messages in context": len(agent.ctx.messages),
            "Model": state.llm.model,
            "Plan mode": "on" if agent.plan_mode else "off",
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


# ── Plan mode commands ───────────────────────────────────────────────────────

class PlanCommand(Command):
    name = "plan"
    description = "Show or toggle plan mode (on/off)"
    usage = "/plan [on|off]"
    def run(self, args, state):
        arg = args.strip().lower()
        if not arg:
            status = "on" if state.agent.plan_mode else "off"
            state.ui.info(f"Plan mode is {status}.")
            return
        if arg not in ("on", "off"):
            state.ui.error("Usage: /plan [on|off]")
            return
        state.agent.plan_mode = (arg == "on")
        state.ui.info(f"Plan mode turned {arg}.")


class PlansCommand(Command):
    name = "plans"
    description = "List plans created in this project"
    def run(self, args, state):
        try:
            plans = state.agent.planner.list_plans(cwd=os.getcwd())
            state.ui.print_plans(plans)
        except Exception as e:
            state.ui.error(f"Failed to load plans: {e}")


class PlanRejectCommand(Command):
    name = "plan-reject"
    description = "Reject the currently pending plan"
    def run(self, args, state):
        if state.agent._pending_plan is None:
            state.ui.info("No plan is pending.")
            return
        state.agent._resolve_pending_plan("/plan-reject")


# ── MCP commands ─────────────────────────────────────────────────────────────

class McpCommand(Command):
    name = "mcp"
    description = "List configured MCP servers and their connection status"
    def run(self, args, state):
        from mcp_client.config_store import load_servers
        servers = load_servers()
        connected = state.mcp_manager.connections.keys() if state.mcp_manager else []
        state.ui.print_mcp_servers(servers, set(connected))


class McpAddCommand(Command):
    name = "mcp-add"
    description = "Add an MCP server (stdio or sse)"
    usage = "/mcp-add <name> stdio <command> [args...]  OR  /mcp-add <name> sse <url>"
    def run(self, args, state):
        parts = args.split()
        if len(parts) < 3:
            state.ui.error(self.usage)
            return
        name, server_type = parts[0], parts[1].lower()
        from mcp_client.config_store import add_server

        if server_type == "stdio":
            command, *cmd_args = parts[2:]
            add_server(name, "stdio", command=command, args=cmd_args)
        elif server_type == "sse":
            add_server(name, "sse", url=parts[2])
        else:
            state.ui.error("Server type must be 'stdio' or 'sse'.")
            return
        state.ui.info(f"Added MCP server '{name}'. Restart Deimos (or reconnect) to load its tools.")


class McpRemoveCommand(Command):
    name = "mcp-remove"
    description = "Remove a configured MCP server"
    usage = "/mcp-remove <name>"
    def run(self, args, state):
        name = args.strip()
        if not name:
            state.ui.error(self.usage)
            return
        from mcp_client.config_store import remove_server
        ok = remove_server(name)
        state.ui.info(f"Removed MCP server '{name}'." if ok else f"No MCP server named '{name}'.")
        if ok and state.mcp_manager and name in state.mcp_manager.connections:
            state.mcp_manager.connections[name].disconnect()
            del state.mcp_manager.connections[name]
            state.tools.unregister_mcp_tools()


# ── Dashboard command ────────────────────────────────────────────────────────

class DashboardCommand(Command):
    name = "dashboard"
    description = "Launch the local web dashboard"
    def run(self, args, state):
        from config import DASHBOARD_HOST, DASHBOARD_PORT
        state.ui.info(f"Starting dashboard at http://{DASHBOARD_HOST}:{DASHBOARD_PORT} ...")
        try:
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "web.dashboard:app",
                 "--host", DASHBOARD_HOST, "--port", str(DASHBOARD_PORT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            state.ui.info(f"Dashboard running in background. Open http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
        except Exception as e:
            state.ui.error(f"Failed to start dashboard: {e}")


# ── Registry ─────────────────────────────────────────────────────────────────

REGISTRY = None

def build_registry():
    from commands.registry import CommandRegistry
    registry = CommandRegistry()
    for cmd_cls in [
        HelpCommand, ChatsCommand, ResumeCommand, ResetCommand, ExitCommand,
        MemoryCommand, ProjectsCommand, ProjectCommand, TitleCommand, DeleteCommand,
        StatusCommand, ModelCommand, VerboseCommand, ClearScreenCommand,
        PlanCommand, PlansCommand, PlanRejectCommand,
        McpCommand, McpAddCommand, McpRemoveCommand, DashboardCommand,
    ]:
        registry.register(cmd_cls())
    global REGISTRY
    REGISTRY = registry
    return registry