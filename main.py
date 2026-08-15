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
from mcp_client.config_store import load_servers
from mcp_client.client import MCPManager, MCP_AVAILABLE


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

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    return args


def run_dashboard(port: int):
    import uvicorn
    print(f"Starting Deimos dashboard at http://{DASHBOARD_HOST}:{port}")
    uvicorn.run("web.dashboard:app", host=DASHBOARD_HOST, port=port)


def connect_mcp_servers(ui: TerminalUI, tools: ToolRegistry) -> MCPManager | None:
    """Connect to all configured MCP servers and register their tools."""
    configs = load_servers()
    if not configs:
        return None
    if not MCP_AVAILABLE:
        ui.info("MCP servers are configured but the 'mcp' package isn't installed (pip install mcp).")
        return None

    manager = MCPManager()
    mcp_tools, errors = manager.connect_all(configs)

    if mcp_tools:
        tools.register_mcp_tools(mcp_tools)
        ui.info(f"Connected {len(configs) - len(errors)} MCP server(s), {len(mcp_tools)} tool(s) available.")
    for err in errors:
        ui.error(f"MCP server failed to connect: {err}")

    return manager


def build_agent(ui, llm, tools, system_prompt, plan_mode, resume_id=None) -> Agent:
    memory = MemoryManager(user_id=DEIMOS_USER_ID, resume_id=resume_id)
    return Agent(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, memory=memory, plan_mode=plan_mode)


def main():
    args = parse_args()

    if args.command == "dashboard":
        run_dashboard(args.port)
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
        mcp_manager = connect_mcp_servers(ui, tools)
        agent = build_agent(ui, llm, tools, system_prompt, plan_mode)
    except Exception as e:
        ui.error(f"Failed to initialize Deimos: {e}")
        sys.exit(1)

    state = AppState(ui=ui, llm=llm, tools=tools, system_prompt=system_prompt, agent=agent)
    state.mcp_manager = mcp_manager

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
        if state.mcp_manager:
            state.mcp_manager.disconnect_all()


if __name__ == "__main__":
    main()