#!/usr/bin/env python3
"""
Deimos — Autonomous Coding Agent

Usage:
  deimos [--verbose] [--no-plan] [--mode MODE]     start the agent (same as `deimos assemble`)
  deimos setup                                     enter or change API keys (~/.deimos/.env)
  deimos update                                    update to the latest version
  deimos dashboard [--port PORT]                   launch the local web dashboard

Type / in the prompt to see all available in-session commands.
"""

import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (PROMPTS_DIR, DEIMOS_USER_ID, PLAN_MODE_DEFAULT, DASHBOARD_HOST, DASHBOARD_PORT,
                    LLM_MODEL, LLM_API_KEY, CONTEXT_SAFE_LIMIT, ROOT_DIR, SUPABASE_URL, SUPABASE_KEY)
from agent.core import Agent
from agent.permissions import MODES, Permissions
from settings import load_settings
from llm.client import LLMClient
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI
from memory.manager import MemoryManager
from memory.null import NullMemory
from commands import build_registry, AppState

REPO_ZIP = "https://github.com/kunal-shetty/deimos/archive/refs/heads/main.zip"
SUBCOMMANDS = ("assemble", "dashboard", "update", "setup")


def load_system_prompt() -> str:
    path = PROMPTS_DIR / "system.txt"
    base = path.read_text(encoding="utf-8") if path.exists() else "You are Deimos, an autonomous coding agent."
    cwd = os.getcwd()
    return base + f"\n\n## Current working directory\n{cwd}\nAll relative file paths refer to this directory."


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("deimos")
    except Exception:
        return "dev"


def parse_args(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `deimos` on its own (or with only assemble's flags) starts the agent
    if not argv or (argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "assemble")

    parser = argparse.ArgumentParser(prog="deimos", description="Deimos — Autonomous Coding Agent")
    parser.add_argument("--version", action="version", version=f"deimos {_version()}")
    subparsers = parser.add_subparsers(dest="command")

    assemble = subparsers.add_parser("assemble", help="Start the Deimos agent")
    assemble.add_argument("--verbose", "-v", action="store_true", help="Show tool output previews")
    assemble.add_argument("--no-plan", action="store_true", help="Disable plan mode for this session")
    assemble.add_argument("--mode", choices=MODES, default=None,
                          help="Permission mode for this session (default: ask, or permission_mode in settings)")

    dashboard = subparsers.add_parser("dashboard", help="Launch the local web dashboard")
    dashboard.add_argument("--port", type=int, default=DASHBOARD_PORT)

    subparsers.add_parser("update", help="Update Deimos to the latest version")
    subparsers.add_parser("setup", help="Enter or change API keys (saved to ~/.deimos/.env)")

    return parser.parse_args(argv)


def run_update():
    """
    Update the copy of Deimos that is running. A git checkout pulls and
    reinstalls itself; an installed copy reinstalls from the latest source
    on GitHub into the same environment.
    """
    import subprocess

    pip = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    steps = []
    if (ROOT_DIR / ".git").exists():
        print(f"Updating the git checkout at {ROOT_DIR}...")
        steps.append(["git", "-C", str(ROOT_DIR), "pull", "--ff-only"])
        steps.append(pip + ["-e", str(ROOT_DIR)])
    else:
        print("Downloading the latest Deimos from GitHub...")
        steps.append(pip + ["--upgrade", "--force-reinstall", "--no-deps", f"deimos @ {REPO_ZIP}"])
        steps.append(pip + [f"deimos @ {REPO_ZIP}"])  # picks up any new dependencies

    if os.name == "nt":
        # Windows won't let pip replace deimos.exe while this process is running
        # from it, so a helper finishes the update after we exit.
        subprocess.Popen([sys.executable, "-c", _WINDOWS_UPDATER, str(os.getpid()), json.dumps(steps)])
        print("Finishing the update after this command exits...")
        return

    try:
        for step in steps:
            subprocess.run(step, check=True)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Update failed: {e}")
        print("You can also re-run the install script, which updates an existing install.")
        sys.exit(1)
    print("Deimos is up to date. Restart any running sessions to use the new version.")


_WINDOWS_UPDATER = r"""
import ctypes, json, subprocess, sys, time
pid, steps = int(sys.argv[1]), json.loads(sys.argv[2])
handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
if handle:
    ctypes.windll.kernel32.WaitForSingleObject(handle, 60000)
    ctypes.windll.kernel32.CloseHandle(handle)
time.sleep(1.5)  # let the deimos.exe launcher that started us exit too
for step in steps:
    if subprocess.run(step).returncode != 0:
        print("\nDeimos update failed. Close any running Deimos sessions and run `deimos update` again,")
        print("or re-run the install script.")
        sys.exit(1)
print("\nDeimos is up to date.")
"""


def open_memory(ui, user_id, resume_id=None):
    """Long-term memory when Supabase is configured and reachable, otherwise memory off."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return NullMemory("Supabase is not configured")
    if not user_id:
        return NullMemory("DEIMOS_USER_ID is not set")
    try:
        return MemoryManager(user_id=user_id, resume_id=resume_id)
    except Exception as e:
        ui.error(f"Long-term memory is unavailable, continuing without it: {e}")
        return NullMemory(str(e))


def run_dashboard(port: int):
    import uvicorn
    print(f"Starting Deimos dashboard at http://{DASHBOARD_HOST}:{port}")
    uvicorn.run("web.dashboard:app", host=DASHBOARD_HOST, port=port)


def build_agent(ui, llm, tools, system_prompt, plan_mode, user_id, permissions, resume_id=None) -> Agent:
    memory = open_memory(ui, user_id, resume_id)
    return Agent(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, memory=memory,
                 plan_mode=plan_mode, permissions=permissions)


def status_items(state) -> dict:
    """Footer under the input box: permission mode, model, context use, pending plan."""
    agent = state.agent
    return {
        "mode": agent.permissions.mode,
        "model": state.llm.model,
        "context": agent.ctx.estimated_tokens / CONTEXT_SAFE_LIMIT,
        "plan_pending": agent._pending_plan is not None,
    }


def main():
    args = parse_args()

    if args.command == "dashboard":
        run_dashboard(args.port)
        return
    if args.command == "update":
        run_update()
        return
    if args.command == "setup":
        from commands.setup import run_setup
        sys.exit(0 if run_setup() else 1)

    if not LLM_API_KEY:
        from commands.setup import run_setup
        from ui.terminal import stdin_is_terminal
        if not stdin_is_terminal():
            print("Deimos needs a Groq API key. Run `deimos setup` in a terminal to add one.")
            sys.exit(1)
        print("Welcome to Deimos. Let's add your API keys first.\n")
        if not run_setup():
            sys.exit(1)
        # Restart so the new keys are picked up by the config loaded at import
        import subprocess
        sys.exit(subprocess.call([sys.executable, "-m", "main", *sys.argv[1:]]))

    ui = TerminalUI(verbose=getattr(args, "verbose", False))
    permissions = Permissions(ui, mode=args.mode or load_settings()["permission_mode"])
    ui.print_logo()
    ui.print_workdir(
        os.getcwd(),
        model=LLM_MODEL,
        plan_mode=PLAN_MODE_DEFAULT and not getattr(args, "no_plan", False),
        mode=permissions.mode,
    )

    user_id = DEIMOS_USER_ID
    if not user_id:
        # Use AuthManager if available to check login state instead of just .env
        from auth.manager import AuthManager
        auth = AuthManager()
        if auth.is_authenticated():
            # We are authenticated via OAuth, so we can override the missing .env ID
            user_id = auth.get_user_id()

    plan_mode = PLAN_MODE_DEFAULT and not getattr(args, "no_plan", False)

    registry = build_registry()

    try:
        llm = LLMClient()
        tools = ToolRegistry()
        system_prompt = load_system_prompt()
        agent = build_agent(ui, llm, tools, system_prompt, plan_mode, user_id, permissions)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    state = AppState(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, agent=agent)
    if not agent.memory.enabled:
        ui.info(f"Long-term memory is off ({agent.memory.reason}). Run `deimos setup` to connect Supabase.")
    elif not agent.memory.search_available:
        ui.info("Memory search isn't set up, so all facts load up front. Run memory/migrations/001_search.sql "
                "in Supabase to recall only what's relevant (see docs/installation.md).")

    # Enable slash-command completion and the status bar before the first prompt
    ui.setup_input(registry.names_with_descriptions())
    ui.set_status_provider(lambda: status_items(state))
    ui.set_mode_cycler(lambda: state.agent.permissions.cycle_mode())

    try:
        while state.running:
            user_input = ui.prompt()
            if not user_input:
                continue

            lowered = user_input.lower().strip()
            if lowered in ("exit", "quit", "q"):
                user_input = "/exit"
            elif lowered in ("reset", "clear"):
                user_input = "/reset"

            # If a plan is awaiting confirmation, route ALL input to the agent
            # first — any message confirms it, /plan-reject cancels it. This
            # takes priority over normal slash-command dispatch so a pending
            # plan can't be silently bypassed by an unrelated command.
            # Exception: /exit must still be able to quit immediately.
            if state.agent._pending_plan is not None and user_input != "/exit":
                try:
                    state.agent.handle_input(user_input)
                except Exception as e:
                    ui.error(f"Unexpected error: {e}")
                continue

            if registry.dispatch(user_input, state):
                continue

            try:
                state.agent.handle_input(user_input)
            except KeyboardInterrupt:
                ui.info("\nInterrupted.")
            except Exception as e:
                ui.error(f"Unexpected error: {e}")
    finally:
        state.shutdown_current_agent()


if __name__ == "__main__":
    main()