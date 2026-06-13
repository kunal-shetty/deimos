#!/usr/bin/env python3
"""
Deimos — Autonomous Coding Agent
Usage: deimos assemble [--verbose]
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

    # Show help if no subcommand given
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    return args


def main():
    args = parse_args()

    ui = TerminalUI(verbose=args.verbose)
    ui.print_logo()

    if not DEIMOS_USER_ID:
        ui.error(
            "DEIMOS_USER_ID is not set in .env. "
            "Create a row in the `users` table in Supabase and set its id in .env."
        )
        sys.exit(1)

    agent = None
    try:
        llm = LLMClient()
        tools = ToolRegistry()
        system_prompt = load_system_prompt()
        memory = MemoryManager(user_id=DEIMOS_USER_ID)
        agent = Agent(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, memory=memory)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    try:
        while True:
            user_input = ui.prompt()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                ui.info("Goodbye.")
                break

            if user_input.lower() in ("reset", "clear"):
                agent.reset()
                ui.info("Conversation history cleared (memory preserved).")
                continue

            try:
                agent.run(user_input)
            except KeyboardInterrupt:
                ui.info("\nInterrupted.")
            except Exception as e:
                ui.error(f"Unexpected error: {e}")
    finally:
        if agent:
            try:
                agent.shutdown()
                ui.memory_saved()
            except Exception as e:
                ui.error(f"Failed to save memory: {e}")


if __name__ == "__main__":
    main()