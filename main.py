#!/usr/bin/env python3
"""
Deimos — Autonomous Coding Agent
Usage:
  deimos assemble [--verbose]

In-session slash commands:
  /chats          List past conversations
  /resume <id>    Resume a past conversation (full id from /chats)
  /reset          Clear current context (memory preserved)
  /exit           Quit
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
from memory.conversation import ConversationStore


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


def build_agent(ui: TerminalUI, llm: LLMClient, tools: ToolRegistry,
                 system_prompt: str, resume_id: str | None = None) -> Agent:
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

    try:
        llm = LLMClient()
        tools = ToolRegistry()
        system_prompt = load_system_prompt()
        agent = build_agent(ui, llm, tools, system_prompt)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    shutdown_done = False

    def do_shutdown(current_agent):
        nonlocal shutdown_done
        title = current_agent.shutdown()
        ui.memory_saved(title)
        shutdown_done = True

    try:
        while True:
            user_input = ui.prompt()

            if not user_input:
                continue

            lowered = user_input.lower().strip()

            # ── Exit ─────────────────────────────────────────────────────────
            if lowered in ("exit", "quit", "q", "/exit", "/quit"):
                ui.info("Goodbye.")
                break

            # ── /reset ───────────────────────────────────────────────────────
            if lowered in ("reset", "clear", "/reset", "/clear"):
                agent.reset()
                ui.info("Conversation history cleared (memory preserved).")
                continue

            # ── /chats ───────────────────────────────────────────────────────
            if lowered == "/chats":
                try:
                    store = ConversationStore(user_id=DEIMOS_USER_ID)
                    conversations = store.list_conversations(limit=20)
                    ui.print_conversations(conversations)
                except Exception as e:
                    ui.error(f"Failed to load conversations: {e}")
                continue

            # ── /resume <id> ─────────────────────────────────────────────────
            if lowered.startswith("/resume"):
                parts = user_input.split(maxsplit=1)
                if len(parts) != 2:
                    ui.error("Usage: /resume <conversation_id>  (run /chats to see ids)")
                    continue
                target_id = parts[1].strip()

                # End/save current session before switching
                try:
                    do_shutdown(agent)
                except Exception as e:
                    ui.error(f"Failed to save current memory: {e}")

                try:
                    agent = build_agent(ui, llm, tools, system_prompt, resume_id=target_id)
                    shutdown_done = False
                except Exception as e:
                    ui.error(f"Failed to resume conversation: {e}")
                continue

            # ── Normal agent turn ────────────────────────────────────────────
            try:
                agent.run(user_input)
            except KeyboardInterrupt:
                ui.info("\nInterrupted.")
            except Exception as e:
                ui.error(f"Unexpected error: {e}")
    finally:
        if not shutdown_done:
            try:
                do_shutdown(agent)
            except Exception as e:
                ui.error(f"Failed to save memory: {e}")


if __name__ == "__main__":
    main()