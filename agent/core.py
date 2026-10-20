import json
import re
import subprocess
import time

import requests
from config import MAX_ITERATIONS, DASHBOARD_HOST, DASHBOARD_PORT
from agent.checkpoints import CheckpointStore
from agent.context import Context
from agent.instructions import load_instructions
from agent.permissions import Permissions
from agent.planner import Planner, StepStatus, AnalysisResult
from llm.client import LLMClient
from settings import load_settings
from tools.base import FileChange
from tools.registry import ToolRegistry
from ui.terminal import TerminalUI
from memory.manager import MemoryManager

SESSION_SUMMARY_KEY = "session_summary"
SESSION_SUMMARY_HEADER = (
    "## Earlier in this session\n"
    "Older messages were trimmed to fit the context window. Summary of them:\n"
)


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
                 system_prompt: str, memory: MemoryManager, plan_mode: bool = True,
                 permissions: Permissions | None = None):
        self.ui = ui
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.plan_mode = plan_mode
        self.planner = Planner(llm_client=llm)
        self.permissions = permissions or Permissions(ui, mode=load_settings()["permission_mode"])
        self.checkpoints = CheckpointStore()

        self._pending_plan = None  # Plan awaiting confirmation
        self._pending_task = None  # the original task text, replayed on confirm
        self.active_plan = None    # Currently executing workflow
        self.waiting_for_clarification = False
        self._clarification_questions = []
        self._clarification_task = None

        memory_block = memory.build_memory_context()
        enriched_system = system_prompt
        if memory_block:
            enriched_system += f"\n\n{memory_block}"
            ui.memory_loaded()

        self.ctx = Context(enriched_system)
        self.reload_instructions()

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
            # User is answering a clarification question: combine it with the
            # original request so neither the planner nor the agent loses it.
            questions = "\n".join(f"- {q}" for q in self._clarification_questions)
            user_input = (
                f"{self._clarification_task}\n\n"
                f"Clarifying questions asked:\n{questions}\n\n"
                f"User's answer: {user_input}"
            )
            self.waiting_for_clarification = False
            self._clarification_questions = []
            self._clarification_task = None
            # Fall through to the planner to see if we can now proceed

        if self._pending_plan is not None:
            self._resolve_pending_plan(user_input)
            return

        if self.plan_mode:
            self.ui.thinking()
            analysis = self.planner.maybe_plan(user_input)

            if analysis.decision == AnalysisResult.CLARIFY:
                self.waiting_for_clarification = True
                self._clarification_task = user_input
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

            self.ctx.set_transient("git", git_block)
        except Exception:
            self.ctx.set_transient("git", None)  # Not a git repo or git not installed

    def _recall(self, user_input: str):
        """Swap in the memories relevant to this message (replaced every turn)."""
        try:
            block = self.memory.recall(user_input)
        except Exception:
            block = None
        self.ctx.set_transient("recall", block)

    def _inject_workflow_status(self):
        """Expose the active plan (and how to report progress) as a transient system block."""
        if not self.active_plan:
            self.ctx.set_transient("workflow", None)
            return
        self.ctx.set_transient("workflow", (
            "## Current Workflow Status\n"
            f"{self.active_plan.to_markdown()}\n"
            "Work through the steps in dependency order. When you finish a step, "
            "write `[Step <id> completed]` (e.g. `[Step s1 completed]`) on its own line."
        ))

    def run(self, user_input: str):
        start_time = time.time()
        start_in = self.llm.total_input_tokens
        start_out = self.llm.total_output_tokens

        self.checkpoints.begin(user_input)
        self.memory.detect_and_inject_project(user_input, self.ctx)
        self._recall(user_input)
        self._inject_git_context()

        self.ctx.add_user(user_input)
        self.memory.save_message("user", user_input)

        # If we have an active plan, inject its current state into the context
        self._inject_workflow_status()

        for iterations in range(1, MAX_ITERATIONS + 1):
            self._compact_if_needed()
            self.ui.thinking()
            response = self._stream_or_complete()

            raw_content = response["raw_content"]
            text = response["text"] or ""
            self.ctx.add_assistant(raw_content)
            self.memory.save_message("assistant", raw_content)
            if self._streamed:
                self.ui.stream_end()
            elif text:
                self.ui.agent_response(text)

            # --- Dashboard Real-time Push ---
            try:
                push_url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/api/push"

                # Determine update type
                update_type = "thought"
                if response["tool_calls"]:
                    update_type = "tool"
                elif "completed" in text.lower():
                    update_type = "workflow"

                message = text or ", ".join(c["name"] for c in response["tool_calls"])
                requests.post(push_url, json={
                    "type": update_type,
                    "message": message[:500] + "..." if len(message) > 500 else message
                }, timeout=0.1)
            except Exception:
                pass

            # --- Workflow Tracking ---
            if self.active_plan:
                matches = re.findall(r"\[Step\s+([a-zA-Z0-9]+)\s+completed\]", text)
                for step_id in matches:
                    for step in self.active_plan.steps:
                        if step.id == step_id:
                            step.status = StepStatus.COMPLETED
                            self.ui.info(f"Workflow: Step {step_id} marked as completed.")

                if all(s.status == StepStatus.COMPLETED for s in self.active_plan.steps):
                    self.active_plan.status = "completed"
                    self.planner.save(self.active_plan)
                    self.ui.info("Workflow complete! All steps finished.")
                    self.active_plan = None
                else:
                    self.planner.save(self.active_plan)
                self._inject_workflow_status()

            if response["stop_reason"] == "end_turn" or not response["tool_calls"]:
                self.ui.turn_end({
                    "turns": iterations,
                    "input_tokens": self.llm.total_input_tokens - start_in,
                    "output_tokens": self.llm.total_output_tokens - start_out,
                    "seconds": time.time() - start_time,
                })
                return

            for call in response["tool_calls"]:
                self.ui.tool_call(call["name"], call["inputs"])

                # --- Self-Healing Loop ---
                result = self._execute_tool(call["name"], call["inputs"])
                retries = 0
                while result.startswith("Error:") and retries < 3:
                    self.ui.info(f"Self-healing: Tool {call['name']} failed. Attempting fix {retries+1}/3...")

                    # Ask for corrected inputs in a standalone request: the main history
                    # still has this tool call unanswered, which the API would reject.
                    tool = self.tools.get(call["name"])
                    fix_prompt = (
                        f"The tool `{call['name']}` failed with error: {result}\n"
                        f"Inputs used: {json.dumps(call['inputs'])}\n"
                        f"Input schema: {json.dumps(tool.input_schema) if tool else 'unknown'}\n"
                        "Respond with corrected inputs as a JSON object matching the schema."
                    )
                    try:
                        new_inputs = self.llm.complete_json(
                            system="You repair failed tool calls for an autonomous coding agent.",
                            messages=[{"role": "user", "content": fix_prompt}],
                        )
                        if new_inputs and "error" not in new_inputs:
                            call["inputs"] = new_inputs
                            result = self._execute_tool(call["name"], new_inputs)
                    except Exception:
                        pass  # fall through to the retry counter below

                    retries += 1

                self.ui.tool_result(result)
                self.ctx.add_tool_result(call["id"], result)
                self.memory.save_message("tool", {
                    "tool_call_id": call["id"], "name": call["name"], "content": result,
                })


        self.ui.error(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

    def _execute_tool(self, name: str, inputs: dict) -> str:
        """
        Run one tool call through the permission gate. Edit tools show their
        diff (asking first unless the mode allows edits) and the files they
        touch are checkpointed so /undo can restore them.
        """
        tool = self.tools.get(name)
        if tool is None:
            return self.tools.dispatch(name, inputs)

        change = None
        if tool.kind == "edit":
            preview = tool.preview(**inputs)
            if isinstance(preview, str):
                return preview  # the edit would fail; report it without asking
            change = preview

        verdict = self.permissions.check(tool, inputs, change)
        if not verdict.allowed:
            return verdict.message
        if isinstance(change, FileChange) and not verdict.prompted:
            self.ui.show_change(change)

        if tool.kind == "edit":
            try:
                self.checkpoints.snapshot(tool.target_paths(**inputs))
            except OSError as e:
                return f"Error: could not checkpoint files before editing ({e}); edit not applied."

        self.ui.tool_running(name)
        try:
            return self.tools.dispatch(name, inputs)
        finally:
            self.ui._stop_spinner()

    def undo_last_turn(self):
        """Restore the files changed in the most recent checkpointed turn."""
        result = self.checkpoints.undo()
        if result and (result.restored or result.deleted):
            files = ", ".join(result.restored + result.deleted)
            self.ctx.add_user(
                f"[System: the user ran /undo. These files were restored to their state before "
                f"the turn \"{result.checkpoint.label}\": {files}. Re-read them before editing again.]"
            )
            self.ctx.add_assistant("Understood. I'll re-read those files before making further changes.")
        return result

    def _compact_if_needed(self):
        """
        When the history outgrows the context budget, trim the oldest messages
        and fold them into a rolling session summary on the system prompt, so
        the agent keeps the gist of what it already did this session.
        """
        removed_msgs = self.ctx.truncate()
        if not removed_msgs:
            return
        self.ui.info(f"Context limit reached. Summarizing {len(removed_msgs)} old messages...")
        prior = self.ctx.get_transient(SESSION_SUMMARY_KEY)
        summary = self.memory.summarize_segment(
            removed_msgs, prior_summary=prior[len(SESSION_SUMMARY_HEADER):] if prior else None,
        )
        if not summary:
            self.ui.info("Could not summarize the trimmed messages; continuing without them.")
            return
        self.ctx.set_transient(SESSION_SUMMARY_KEY, SESSION_SUMMARY_HEADER + summary)
        try:
            # Also archive in episodic memory: end-of-session summaries only see what's left
            self.memory.save_segment_summary(summary)
        except Exception:
            pass
        self.ui.info("Older messages summarized and archived to memory.")

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

    def reload_instructions(self) -> bool:
        """(Re)load DEIMOS.md files into the system prompt. Returns True if any were found."""
        block = load_instructions()
        self.ctx.set_transient("instructions", block)
        return block is not None

    def reset(self):
        self.ctx.reset()
        self.reload_instructions()
        self._pending_plan = None
        self._pending_task = None
        self.active_plan = None
        self.waiting_for_clarification = False
        self._clarification_questions = []
        self._clarification_task = None