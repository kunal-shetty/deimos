import sys
from config import MAX_ITERATIONS
from agent.context import Context
from llm.client import LLMClient
from tools.registry import ToolRegistry
from tools.run_command import is_dangerous
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

        # If resuming a past conversation, restore its messages
        resumed_messages = memory.load_resumed_messages()
        for msg in resumed_messages:
            if msg["role"] == "user":
                self.ctx.add_user(msg["content"])
            else:
                self.ctx.add_assistant(msg["content"])
        if resumed_messages:
            ui.conversation_resumed(len(resumed_messages))

    def run(self, user_input: str):
        # Detect project context for first or project-relevant messages
        self.memory.detect_and_inject_project(user_input, self.ctx)

        self.ctx.add_user(user_input)
        self.memory.save_message("user", user_input)

        for iteration in range(MAX_ITERATIONS):
            self.ui.thinking()
            response = self._stream_or_complete()

            # Add assistant turn to history
            self.ctx.add_assistant(response["raw_content"])
            self.memory.save_message("assistant", response["raw_content"])

            # No tool calls — agent is done
            if response["stop_reason"] == "end_turn" or not response["tool_calls"]:
                # Text already printed via streaming; only print if non-streaming
                if response["text"] and not self._streamed:
                    self.ui.agent_response(response["text"])
                elif self._streamed:
                    self.ui.stream_end()
                return

            # Process each tool call
            for call in response["tool_calls"]:
                # Safety guardrail for dangerous commands
                if call["name"] == "run_command":
                    cmd = call["inputs"].get("command", "")
                    if is_dangerous(cmd):
                        confirmed = self.ui.confirm_dangerous(cmd)
                        if not confirmed:
                            self.ui.tool_skipped(call["name"])
                            result = "User cancelled: command was flagged as potentially destructive."
                            self.ctx.add_tool_result(call["id"], result)
                            self.memory.save_message("tool", {
                                "tool_call_id": call["id"],
                                "name": call["name"],
                                "content": result,
                            })
                            continue

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

    def _stream_or_complete(self) -> dict:
        """Use streaming for text responses, fall back to non-streaming on error."""
        self._streamed = False
        stream_started = False

        try:
            def on_chunk(text: str):
                nonlocal stream_started
                if not stream_started:
                    self.ui.stream_start()
                    stream_started = True
                self.ui.stream_chunk(text)

            response = self.llm.complete_stream(
                system=self.ctx.system_prompt,
                messages=self.ctx.messages,
                tools=self.tools.all_schemas(),
                on_chunk=on_chunk,
            )
            if stream_started:
                self._streamed = True
            return response
        except Exception:
            # Fallback to non-streaming if streaming fails
            return self.llm.complete(
                system=self.ctx.system_prompt,
                messages=self.ctx.messages,
                tools=self.tools.all_schemas(),
            )

    def shutdown(self):
        """Called on exit — generates episodic summary + title + extracts facts."""
        self.ui.saving_memory()
        title = self.memory.end_session(self.ctx.messages)
        return title

    def reset(self):
        """Clear in-memory context (does not delete persisted memory)."""
        self.ctx.reset()