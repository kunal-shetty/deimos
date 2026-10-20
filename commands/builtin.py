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
        if not state.agent.memory.enabled:
            state.ui.info("Long-term memory is off, so there are no saved conversations to resume.")
            return
        state.shutdown_current_agent()
        try:
            memory = MemoryManager(user_id=state.agent.memory.user_id, resume_id=target_id)
            state.agent = Agent(ui=state.ui, llm=state.llm, tools=state.tools,
                                system_prompt=state.system_prompt, memory=memory,
                                plan_mode=state.agent.plan_mode,
                                permissions=state.agent.permissions)
            state.shutdown_done = False
        except Exception as e:
            state.ui.error(f"Failed to resume conversation: {e}")


class ResetCommand(Command):
    name = "reset"
    description = "Clear current context (memory preserved)"
    def run(self, args, state):
        state.agent.reset()
        state.llm.reset_usage()
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
        if not state.agent.memory.enabled:
            state.ui.info("Long-term memory is off, so there are no saved conversations.")
            return
        if target_id == state.agent.memory.conversation_id:
            state.ui.error("Cannot delete the conversation currently in progress.")
            return
        try:
            store = ConversationStore(user_id=state.agent.memory.user_id)
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
            "Fast model": _fast_model_name(),
            "Decisions": _decider_status(),
            "Session tokens": f"↑{state.llm.total_input_tokens} ↓{state.llm.total_output_tokens}",
            "Permission mode": agent.permissions.mode,
            "Plan mode": "on" if agent.plan_mode else "off",
            "Verbose": "on" if state.ui.verbose else "off",
        })


def _fast_model_name() -> str:
    try:
        from llm.client import fast_llm
        return fast_llm().model
    except Exception as e:
        return f"unavailable ({e})"


def _decider_status() -> str:
    from llm.decide import get_decider
    decider = get_decider()
    status = decider.name
    failures = getattr(decider, "primary_failures", 0)
    if failures:
        status += f" ({failures} Jev failures; last: {decider.last_error[:80]})"
    return status


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


class RecallCommand(Command):
    name = "recall"
    description = "Show the memories Deimos would recall for some text"
    usage = "/recall <text>"
    def run(self, args, state):
        memory = state.agent.memory
        if not args.strip():
            state.ui.error("Usage: /recall <text>")
            return
        if not memory.enabled:
            state.ui.info("Long-term memory is off.")
            return
        if not memory.search_available:
            state.ui.info("Memory search isn't set up yet: run memory/migrations/001_search.sql in Supabase.")
            return
        block = memory.recall(args)
        if not block:
            state.ui.info("Nothing relevant found.")
            return
        for line in block.splitlines()[2:]:  # skip the heading and the instruction line
            state.ui.info(line)


# ── Safety: permission modes and checkpoints ─────────────────────────────────

class ModeCommand(Command):
    name = "mode"
    description = "Show or set the permission mode (ask, auto-edit, auto, read-only)"
    usage = "/mode [ask|auto-edit|auto|read-only]"
    def run(self, args, state):
        from agent.permissions import MODES, MODE_DESCRIPTIONS
        perms = state.agent.permissions
        arg = args.strip().lower()
        if not arg:
            state.ui.info(f"Permission mode: {perms.mode} ({MODE_DESCRIPTIONS[perms.mode]})")
            for m in MODES:
                state.ui.info(f"  {m:<10} {MODE_DESCRIPTIONS[m]}")
            return
        try:
            perms.set_mode(arg)
        except ValueError as e:
            state.ui.error(str(e))
            return
        state.ui.success(f"Permission mode set to {arg}: {MODE_DESCRIPTIONS[arg]}")


class UndoCommand(Command):
    name = "undo"
    description = "Restore the files changed in the last agent turn"
    def run(self, args, state):
        result = state.agent.undo_last_turn()
        if result is None:
            state.ui.info("Nothing to undo: no file changes have been checkpointed in this project.")
            return
        cwd = os.getcwd()
        for path in result.restored:
            state.ui.success(f"Restored {os.path.relpath(path, cwd)}")
        for path in result.deleted:
            state.ui.success(f"Deleted {os.path.relpath(path, cwd)} (created by the agent)")
        for path in result.failed:
            state.ui.error(f"Could not restore {path}")
        state.ui.info(f"Undid: {result.checkpoint.label}")
        state.ui.info("Changes made by shell commands are not tracked and were not undone.")


class CheckpointsCommand(Command):
    name = "checkpoints"
    description = "List file checkpoints that /undo can restore"
    def run(self, args, state):
        state.ui.print_checkpoints(state.agent.checkpoints.list())


# ── Project instructions ─────────────────────────────────────────────────────

INIT_PROMPT = (
    "Create a DEIMOS.md file in the current working directory: instructions that "
    "future sessions of you (an autonomous coding agent) will load into the system "
    "prompt when working in this project. First explore the repository with your "
    "tools: list the top-level layout, read the README and build/package files "
    "(pyproject.toml, package.json, Makefile, etc.), and skim the main entry points. "
    "Then write DEIMOS.md with short sections covering: what the project is; how to "
    "install, run, build, test and lint it (exact commands); the code layout and "
    "where key logic lives; coding conventions you observed; and anything to be "
    "careful about. Keep it under ~80 lines, factual, and specific to this repo — "
    "no generic advice. Only state commands you found evidence for."
)


class InitCommand(Command):
    name = "init"
    description = "Explore this project and write a DEIMOS.md for future sessions"
    usage = "/init [--force]"
    def run(self, args, state):
        from agent.instructions import INSTRUCTIONS_FILE
        path = os.path.join(os.getcwd(), INSTRUCTIONS_FILE)
        if os.path.exists(path) and "--force" not in args.split():
            state.ui.info(f"{INSTRUCTIONS_FILE} already exists here. Use /init --force to regenerate it.")
            return
        state.agent.run(INIT_PROMPT)
        if os.path.exists(path) and state.agent.reload_instructions():
            state.ui.info(f"Loaded {INSTRUCTIONS_FILE} into this session.")
        else:
            state.ui.error(f"{INSTRUCTIONS_FILE} was not created.")


class InstructionsCommand(Command):
    name = "instructions"
    description = "List the DEIMOS.md files loaded into this session"
    def run(self, args, state):
        from agent.instructions import instruction_files
        state.agent.reload_instructions()
        files = instruction_files()
        if not files:
            state.ui.info("No DEIMOS.md files found. Run /init to create one for this project.")
            return
        for f in files:
            state.ui.info(f"• {f}")


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
        PlanCommand, PlansCommand, PlanRejectCommand, DashboardCommand,
        InitCommand, InstructionsCommand, ModeCommand, UndoCommand, CheckpointsCommand, RecallCommand,
    ]:
        registry.register(cmd_cls())
    global REGISTRY
    REGISTRY = registry
    return registry