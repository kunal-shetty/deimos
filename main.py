#!/usr/bin/env python3
"""
Deimos — Autonomous Coding Agent

Usage:
  deimos assemble [--verbose] [--no-plan]
  deimos dashboard [--port PORT]

Type / in the prompt to see all available in-session commands.
"""

import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import PROMPTS_DIR, DEIMOS_USER_ID, PLAN_MODE_DEFAULT, DASHBOARD_HOST, DASHBOARD_PORT
from agent.core import Agent
from llm.client import LLMClient
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI
from memory.manager import MemoryManager
from commands import build_registry, AppState


def load_system_prompt() -> str:
    path = PROMPTS_DIR / "system.txt"
    base = path.read_text(encoding="utf-8") if path.exists() else "You are Deimos, an autonomous coding agent."
    cwd = os.getcwd()
    return base + f"\n\n## Current working directory\n{cwd}\nAll relative file paths refer to this directory."


def parse_args():
    parser = argparse.ArgumentParser(description="Deimos — Autonomous Coding Agent", add_help=False)
    subparsers = parser.add_subparsers(dest="command")

    assemble = subparsers.add_parser("assemble", help="Start the Deimos agent")
    assemble.add_argument("--verbose", "-v", action="store_true", help="Show tool output previews")
    assemble.add_argument("--no-plan", action="store_true", help="Disable plan mode for this session")

    dashboard = subparsers.add_parser("dashboard", help="Launch the local web dashboard")
    dashboard.add_argument("--port", type=int, default=DASHBOARD_PORT)

    update = subparsers.add_parser("update", help="Update Deimos to the latest version")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    return args


def run_update():
    import subprocess
    import sys
    from pathlib import Path

    print("Updating Deimos...")
    deimos_home = Path.home() / ".deimos"
    venv_pip = deimos_home / "venv" / "bin" / "pip"

    if not venv_pip.exists():
        print("Error: Deimos virtual environment not found. Please run the install script again.")
        sys.exit(1)

    try:
        # If we are in a git repo, pull changes first
        subprocess.run(["git", "pull"], capture_output=True)
        # Update the package
        subprocess.run([str(venv_pip), "install", "--upgrade", "."], check=True)
        print("Deimos updated successfully!")
    except Exception as e:
        print(f"Update failed: {e}")
        sys.exit(1)


def run_dashboard(port: int):
    import uvicorn
    print(f"Starting Deimos dashboard at http://{DASHBOARD_HOST}:{port}")
    uvicorn.run("web.dashboard:app", host=DASHBOARD_HOST, port=port)


def build_agent(ui, llm, tools, system_prompt, plan_mode, resume_id=None) -> Agent:
    memory = MemoryManager(user_id=DEIMOS_USER_ID, resume_id=resume_id)
    return Agent(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, memory=memory, plan_mode=plan_mode)


def main():
    args = parse_args()

    if args.command == "dashboard":
        run_dashboard(args.port)
        return
    if args.command == "update":
        run_update()
        return

    ui = TerminalUI(verbose=getattr(args, "verbose", False))
    ui.print_logo()
    ui.print_workdir(os.getcwd())

    if not DEIMOS_USER_ID:
        ui.error(
            "DEIMOS_USER_ID is not set in .env. "
            "Create a row in the `users` table in Supabase and set its id in .env."
        )
        sys.exit(1)

    plan_mode = PLAN_MODE_DEFAULT and not getattr(args, "no_plan", False)

    registry = build_registry()

    try:
        llm = LLMClient()
        tools = ToolRegistry()
        system_prompt = load_system_prompt()
        agent = build_agent(ui, llm, tools, system_prompt, plan_mode)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    state = AppState(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, agent=agent)

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