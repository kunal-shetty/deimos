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
        self.system_prompt = system_prompt

    def run(self, user_input: str):
        ctx = Context(self.system_prompt)
        ctx.add_user(user_input)

        for iteration in range(MAX_ITERATIONS):
            self.ui.thinking()

            response = self.llm.complete(
                system=ctx.system_prompt,
                messages=ctx.messages,
                tools=self.tools.all_schemas(),
            )

            # Add assistant turn to history (Groq returns a dict, not a list)
            ctx.add_assistant(response["raw_content"])

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
                ctx.add_tool_result(call["id"], result)

        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")
