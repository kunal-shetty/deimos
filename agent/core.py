from config import MAX_ITERATIONS
from agent.context import Context
from llm.client import LLMClient
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI


class Agent:
    """
    The core Deimos agent loop.
    think → act → observe → repeat until task complete.
    """

    def __init__(self, ui: TerminalUI, llm: LLMClient, tools: ToolRegistry, system_prompt: str):
        self.ui = ui
        self.llm = llm
        self.tools = tools
        self.ctx = Context(system_prompt)  # persists across all run() calls

    def run(self, user_input: str):
        self.ctx.add_user(user_input)

        for iteration in range(MAX_ITERATIONS):
            self.ui.thinking()

            response = self.llm.complete(
                system=self.ctx.system_prompt,
                messages=self.ctx.messages,
                tools=self.tools.all_schemas(),
            )

            # Add assistant turn to history
            self.ctx.add_assistant(response["raw_content"])

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

        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

    def reset(self):
        """Clear conversation history (start fresh)."""
        self.ctx.reset()