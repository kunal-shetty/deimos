import requests
from config import MAX_ITERATIONS, DASHBOARD_HOST, DASHBOARD_PORT
import re
from agent.context import Context
from agent.planner import Planner, StepStatus
from llm.client import LLMClient
from tools.registry import ToolRegistry
from tools.run_command import is_dangerous
from ui.terminal import TerminalUI
from memory.manager import MemoryManager


class Agent:
    """
    The core Deimos agent loop.
    think → act → observe → repeat until task complete.

    Plan mode: for multi-step tasks, a Planner proposes a short plan and
    persists it under .deimos/plans/ before any tool runs. The agent then
    waits for the user's next input as confirmation (any message proceeds;
    /plan-reject cancels) before executing.
    """

    def __init__(self, ui: TerminalUI, llm: LLMClient, tools: ToolRegistry,
                 system_prompt: str, memory: MemoryManager, plan_mode: bool = True):
        self.ui = ui
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.plan_mode = plan_mode
        self.planner = Planner()

        self._pending_plan = None  # Plan awaiting confirmation
        self._pending_task = None  # the original task text, replayed on confirm
        self.active_plan = None    # Currently executing workflow
        self.waiting_for_clarification = False
        self._clarification_questions = []

        memory_block = memory.build_memory_context()
        enriched_system = system_prompt
        if memory_block:
            enriched_system += f"\n\n{memory_block}"
            ui.memory_loaded()

        self.ctx = Context(enriched_system)

        resumed_messages = memory.load_resumed_messages()
        for msg in resumed_messages:
            if msg["role"] == "user":
                self.ctx.add_user(msg["content"])
            else:
                self.ctx.add_assistant(msg["content"])
        if resumed_messages:
            ui.conversation_resumed(len(resumed_messages))

    # ── Plan mode entry point ────────────────────────────────────────────────

    def handle_input(self, user_input: str):
        """
        Top-level entry point from main.py. Routes between clarification,
        plan confirmation, and normal execution.
        """
        if self.waiting_for_clarification:
            # User is answering a clarification question
            self.waiting_for_clarification = False
            self._clarification_questions = []
            # Fall through to the planner to see if we can now proceed

        if self._pending_plan is not None:
            self._resolve_pending_plan(user_input)
            return

        if self.plan_mode:
            self.ui.thinking()
            analysis = self.planner.maybe_plan(user_input)

            if analysis.decision == AnalysisResult.CLARIFY:
                self.waiting_for_clarification = True
                self._clarification_questions = analysis.questions or ["Could you provide more details?"]
                self.ui.agent_response(
                    "I need a bit more information before I can plan this effectively:\n\n" +
                    "\n".join(f"- {q}" for q in self._clarification_questions)
                )
                return

            if analysis.decision == AnalysisResult.PLAN and analysis.plan:
                plan = analysis.plan
                self.planner.save(plan, cwd=None)
                self._pending_plan = plan
                self._pending_task = user_input
                self.ui.print_plan(plan)
                return

            # Decision is EXECUTE or PLAN failed to generate a plan -> proceed to run

        self.run(user_input)

    def _resolve_pending_plan(self, user_input: str):
        if user_input.strip().lower() in ("/plan-reject", "/reject"):
            self.planner.update_status(self._pending_plan, "rejected")
            self.ui.plan_rejected()
            self._pending_plan = None
            self._pending_task = None
            return

        # Any other input confirms the plan and proceeds with the original task
        self.planner.update_status(self._pending_plan, "confirmed")
        self.ui.plan_confirmed()
        task = self._pending_task
        self.active_plan = self._pending_plan
        self._pending_plan = None
        self._pending_task = None
        self.run(task)

    # ── Core execution loop ──────────────────────────────────────────────────

    def run(self, user_input: str):
        self.memory.detect_and_inject_project(user_input, self.ctx)

        self.ctx.add_user(user_input)
        self.memory.save_message("user", user_input)

        # If we have an active plan, inject its current state into the context
        if self.active_plan:
            workflow_status = f"\n\n## Current Workflow Status\n{self.active_plan.to_markdown()}"
            self.ctx.add_assistant(f"[System: {workflow_status}]")

        for _ in range(MAX_ITERATIONS):
            self.ui.thinking()
            response = self._stream_or_complete()

            raw_content = response["raw_content"]
            self.ctx.add_assistant(raw_content)
            self.memory.save_message("assistant", raw_content)

            # --- Dashboard Real-time Push ---
            try:
                import requests
                from config import DASHBOARD_HOST, DASHBOARD_PORT
                push_url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/api/push"

                # Determine update type
                update_type = "thought"
                if response["tool_calls"]:
                    update_type = "tool"
                elif "completed" in raw_content.lower():
                    update_type = "workflow"

                requests.post(push_url, json={
                    "type": update_type,
                    "message": raw_content[:500] + "..." if len(raw_content) > 500 else raw_content
                }, timeout=0.1)
            except:
                pass

            # --- Workflow Tracking ---
            if self.active_plan:
                matches = re.findall(r"\[Step\s+([a-zA-Z0-9]+)\s+completed\]", raw_content)
                for step_id in matches:
                    for step in self.active_plan.steps:
                        if step.id == step_id:
                            step.status = StepStatus.COMPLETED
                            self.ui.info(f"Workflow: Step {step_id} marked as completed.")

                if all(s.status == StepStatus.COMPLETED for s in self.active_plan.steps):
                    self.active_plan.status = "completed"
                    self.planner.save(self.active_plan)
                    self.ui.info("Workflow complete! All steps finished.")
                else:
                    self.planner.save(self.active_plan)

            if response["stop_reason"] == "end_turn" or not response["tool_calls"]:
                if response["text"] and not self._streamed:
                    self.ui.agent_response(response["text"])
                elif self._streamed:
                    self.ui.stream_end()
                return

            for call in response["tool_calls"]:
                if call["name"] == "run_command":
                    cmd = call["inputs"].get("command", "")
                    if is_dangerous(cmd):
                        confirmed = self.ui.confirm_dangerous(cmd)
                        if not confirmed:
                            self.ui.tool_skipped(call["name"])
                            result = "User cancelled: command was flagged as potentially destructive."
                            self.ctx.add_tool_result(call["id"], result)
                            self.memory.save_message("tool", {
                                "tool_call_id": call["id"], "name": call["name"], "content": result,
                            })
                            continue

                self.ui.tool_call(call["name"], call["inputs"])
                result = self.tools.dispatch(call["name"], call["inputs"])
                self.ui.tool_result(result)
                self.ctx.add_tool_result(call["id"], result)
                self.memory.save_message("tool", {
                    "tool_call_id": call["id"], "name": call["name"], "content": result,
                })

        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

    def _stream_or_complete(self) -> dict:
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
                system=self.ctx.system_prompt, messages=self.ctx.messages,
                tools=self.tools.all_schemas(), on_chunk=on_chunk,
            )
            if stream_started:
                self._streamed = True
            return response
        except Exception:
            return self.llm.complete(
                system=self.ctx.system_prompt, messages=self.ctx.messages,
                tools=self.tools.all_schemas(),
            )

    def shutdown(self):
        self.ui.saving_memory()
        return self.memory.end_session(self.ctx.messages)

    def reset(self):
        self.ctx.reset()
        self._pending_plan = None
        self._pending_task = None