from config import MAX_ITERATIONS
from agent.context import Context
from llm.client import LLMClient
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI
from memory.manager import MemoryManager


class Agent:
    """
    The core Deimos agent loop.
    think → act → observe → repeat until task complete.
    """

    def __init__(self, ui: TerminalUI, llm: LLMClient, tools: ToolRegistry,
                 system_prompt: str, memory: MemoryManager):
        self.ui = ui
        self.llm = llm
        self.tools = tools
        self.memory = memory

        # Build enriched system prompt with memory injected
        memory_block = memory.build_memory_context()
        enriched_system = system_prompt
        if memory_block:
            enriched_system += f"\n\n{memory_block}"
            ui.memory_loaded()

        self.ctx = Context(enriched_system)

    def run(self, user_input: str):
        self.ctx.add_user(user_input)
        self.memory.save_message("user", user_input)

        for iteration in range(MAX_ITERATIONS):
            self.ui.thinking()

            response = self.llm.complete(
                system=self.ctx.system_prompt,
                messages=self.ctx.messages,
                tools=self.tools.all_schemas(),
            )

            # Add assistant turn to history
            self.ctx.add_assistant(response["raw_content"])
            self.memory.save_message("assistant", response["raw_content"])

            # No tool calls — agent is done
            if response["stop_reason"] == "end_turn" or not response["tool_calls"]:
                if response["text"]:
                    self.ui.agent_response(response["text"])
                return

            # Process each tool call
            for call in response["tool_calls"]:
                self.ui.tool_call(call["name"], call["inputs"])
                result = self.tools.dispatch(call["name"], call["inputs"])
                self.ui.tool_result(result)
                self.ctx.add_tool_result(call["id"], result)
                self.memory.save_message("tool", {
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": result,
                })

        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

    def shutdown(self):
        """Called on exit — generates episodic summary + extracts semantic facts."""
        self.ui.saving_memory()
        self.memory.end_session(self.ctx.messages)

    def reset(self):
        """Clear in-memory context (does not delete persisted memory)."""
        self.ctx.reset()