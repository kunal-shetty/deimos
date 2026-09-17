import json
import re
import subprocess
import time

import requests
from config import MAX_ITERATIONS, DASHBOARD_HOST, DASHBOARD_PORT
import re
from agent.context import Context
from agent.planner import Planner, StepStatus, AnalysisResult
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
        self.planner = Planner(llm_client=llm)


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

    def _inject_git_context(self):
        """Inject current git state as a transient system message."""
        try:
            branch = subprocess.check_output(["git", "branch", "--show-current"], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
            diff = subprocess.check_output(["git", "diff", "--staged"], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
            log = subprocess.check_output(["git", "log", "--oneline", "-5"], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()

            git_block = f"### Git Context\n- Branch: {branch}\n"
            if diff:
                git_block += f"- Staged Changes:\n```diff\n{diff}\n```\n"
            if log:
                git_block += f"- Recent Log:\n{log}"

            self.ctx.add_assistant(f"[System: {git_block}]")
        except Exception:
            pass # Not a git repo or git not installed

    def run(self, user_input: str):
        start_time = time.time()
        start_in = self.llm.total_input_tokens
        start_out = self.llm.total_output_tokens

        self.memory.detect_and_inject_project(user_input, self.ctx)
        self._inject_git_context()

        self.ctx.add_user(user_input)
        self.memory.save_message("user", user_input)

        # If we have an active plan, inject its current state into the context
        if self.active_plan:
            workflow_status = f"\n\n## Current Workflow Status\n{self.active_plan.to_markdown()}"
            self.ctx.add_assistant(f"[System: {workflow_status}]")

        for iterations in range(1, MAX_ITERATIONS + 1):
            self.ui.thinking()
            response = self._stream_or_complete()

            raw_content = response["raw_content"]
            self.ctx.add_assistant(raw_content)
            self.memory.save_message("assistant", raw_content)

            # --- Dashboard Real-time Push ---
            try:
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
                if not self._streamed:
                    if response["text"]:
                        self.ui.agent_response(response["text"])
                else:
                    self.ui.stream_end()
                self.ui.turn_end({
                    "turns": iterations,
                    "input_tokens": self.llm.total_input_tokens - start_in,
                    "output_tokens": self.llm.total_output_tokens - start_out,
                    "seconds": time.time() - start_time,
                })
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

                # --- Self-Healing Loop ---
                result = self.tools.dispatch(call["name"], call["inputs"])
                retries = 0
                while result.startswith("Error:") and retries < 3:
                    self.ui.info(f"Self-healing: Tool {call['name']} failed. Attempting fix {retries+1}/3...")

                    # Trigger a quick "fix" turn from the LLM
                    fix_prompt = f"The tool {call['name']} failed with error: {result}. The inputs were {call['inputs']}. Please provide corrected inputs in JSON format."
                    fix_res = self.llm.complete(
                        system=self.ctx.system_prompt,
                        messages=self.ctx.messages + [{"role": "user", "content": fix_prompt}],
                        tools=[]
                    )

                    try:
                        # Assume the LLM provides the new inputs as JSON in the text
                        raw = (fix_res.get("text") or "").strip()
                        if raw.startswith("```"):
                            raw = re.sub(r"^```(?:json)?\n?", "", raw)
                            raw = re.sub(r"\n?```$", "", raw)
                        new_inputs = json.loads(raw)
                        result = self.tools.dispatch(call["name"], new_inputs)
                    except Exception:
                        pass  # fall through to the retry counter below

                    retries += 1

                self.ui.tool_result(result)
                self.ctx.add_tool_result(call["id"], result)
                self.memory.save_message("tool", {
                    "tool_call_id": call["id"], "name": call["name"], "content": result,
                })


        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

    def _stream_or_complete(self) -> dict:
        self._streamed = False
        stream_started = False

        def on_chunk(text: str):
            nonlocal stream_started
            if not stream_started:
                self.ui.stream_start()
                stream_started = True
            self.ui.stream_chunk(text)

        try:
            response = self.llm.complete_stream(
                system=self.ctx.system_prompt, messages=self.ctx.messages,
                tools=self.tools.all_schemas(), on_chunk=on_chunk,
            )
            if stream_started:
                self._streamed = True
            return response
        except Exception:
            # Network/API hiccup — retry once before giving up to the caller.
            try:
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
        self.active_plan = None