#!/usr/bin/env python3
"""
Deimos — Autonomous Coding Agent
Usage:
  deimos assemble [--verbose]

Type / in the prompt to see all available in-session commands
(/help, /chats, /resume, /reset, /memory, /status, /model, ...).
"""

import sys
import argparse
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from config import PROMPTS_DIR, DEIMOS_USER_ID
from agent.core import Agent
from llm.client import LLMClient
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI
from memory.manager import MemoryManager
from commands import build_registry, AppState


def load_system_prompt() -> str:
    path = PROMPTS_DIR / "system.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "You are Deimos, an autonomous coding agent."


def parse_args():
    parser = argparse.ArgumentParser(description="Deimos — Autonomous Coding Agent", add_help=False)
    subparsers = parser.add_subparsers(dest="command")

    assemble = subparsers.add_parser("assemble", help="Start the Deimos agent")
    assemble.add_argument("--verbose", "-v", action="store_true", help="Show tool output previews")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    return args


def build_agent(ui, llm, tools, system_prompt, resume_id=None) -> Agent:
    memory = MemoryManager(user_id=DEIMOS_USER_ID, resume_id=resume_id)
    return Agent(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, memory=memory)


def main():
    args = parse_args()

    ui = TerminalUI(verbose=getattr(args, "verbose", False))
    ui.print_logo()

    if not DEIMOS_USER_ID:
        ui.error(
            "DEIMOS_USER_ID is not set in .env. "
            "Create a row in the `users` table in Supabase and set its id in .env."
        )
        sys.exit(1)

    registry = build_registry()

    try:
        llm = LLMClient()
        tools = ToolRegistry()
        system_prompt = load_system_prompt()
        agent = build_agent(ui, llm, tools, system_prompt)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    # Set up '/' command autocomplete with live dropdown
    command_list = [(c.name, c.description) for c in registry.all()]
    ui.setup_input(command_list)

    state = AppState(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, agent=agent)

    try:
        while state.running:
            user_input = ui.prompt()

            if not user_input:
                continue

            # Backwards-compatible plain-word aliases
            lowered = user_input.lower().strip()
            if lowered in ("exit", "quit", "q"):
                user_input = "/exit"
            elif lowered in ("reset", "clear"):
                user_input = "/reset"

            if registry.dispatch(user_input, state):
                continue

            try:
                state.agent.run(user_input)
            except KeyboardInterrupt:
                ui.info("\nInterrupted.")
            except Exception as e:
                ui.error(f"Unexpected error: {e}")
    finally:
        state.shutdown_current_agent()


if __name__ == "__main__":
    main()