"""
Sub-agents: run independent tasks in parallel, each in a fresh context.

The main agent calls the `delegate` tool with a list of self-contained tasks.
Each runs in a SubAgent with its own conversation, the same tools (minus
`delegate`), the same permission mode and checkpoints, and reports back a
short summary. Up to `subagents.max_parallel` run at once.

Approval prompts from sub-agents are queued and shown one at a time on the
main thread. The first sub-agent to edit a file claims it; others are told
to leave it alone, so parallel edits never collide.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from agent.context import Context
from tools.base import BaseTool

MAX_SUB_ITERATIONS = 20
SUB_CONTEXT_TOKENS = 60000

SUBAGENT_PROMPT = (
    "## You are a sub-agent\n"
    "The main Deimos agent gave you one task, which you are doing in parallel with other "
    "sub-agents working on other tasks. Do only your task, and don't change files outside its "
    "scope: another sub-agent may be editing them. You can't ask the user questions; make "
    "reasonable choices and note them. When you're done, reply with a short report: what you "
    "did, which files you changed, and anything left unresolved."
)


@dataclass
class SubAgentReport:
    label: str
    task: str
    summary: str
    ok: bool = True


class FileClaims:
    """The first sub-agent to edit a file owns it for the rest of the delegation."""

    def __init__(self):
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()

    def claim(self, path: str, owner: str) -> str | None:
        """Claim `path` for `owner`. Returns the other owner if someone else has it."""
        import os
        key = os.path.normcase(os.path.abspath(path))
        with self._lock:
            current = self._owners.setdefault(key, owner)
        return None if current == owner else current


class PromptBroker:
    """Runs UI prompts requested by worker threads on the main thread, one at a time."""

    def __init__(self):
        self._requests: queue.Queue = queue.Queue()

    def ask(self, fn, *args, **kwargs):
        """Called from a worker: block until the main thread has run fn(*args, **kwargs)."""
        done, box = threading.Event(), {}
        self._requests.put((fn, args, kwargs, box, done))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["value"]

    def serve(self, futures, before=None, after=None):
        """Called on the main thread: answer prompts until every future is done."""
        while not all(f.done() for f in futures):
            try:
                fn, args, kwargs, box, done = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if before:
                    before()
                box["value"] = fn(*args, **kwargs)
            except BaseException as e:  # hand Ctrl+C and errors back to the worker
                box["error"] = e
            finally:
                if after:
                    after()
                done.set()


class SubAgentUI:
    """A sub-agent's view of the terminal: compact, prefixed lines and brokered prompts."""

    def __init__(self, ui, label: str, broker: PromptBroker, lock: threading.Lock):
        self.ui = ui
        self.label = label
        self.broker = broker
        self.lock = lock
        self.verbose = False

    def _line(self, text: str):
        import sys
        with self.lock:
            sys.stdout.write(f"\r\033[K{text}\n")
            sys.stdout.flush()

    def tool_call(self, name: str, inputs: dict):
        from ui.terminal import ACCENT_DIM, BOLD, GREY, RESET, _fit, _term_width, tool_label, tool_summary
        room = max(10, _term_width() - len(self.label) - len(tool_label(name)) - 12)
        self._line(f"  {ACCENT_DIM}[{self.label}]{RESET} {BOLD}{tool_label(name)}{RESET}"
                   f"{GREY}({_fit(tool_summary(name, inputs), room, pad=False)}){RESET}")

    def tool_result(self, result: str):
        from ui.terminal import _FAIL_PREFIXES, ACCENT_DIM, FAINT, RED, RESET, _fit, _term_width
        if result.startswith(_FAIL_PREFIXES):
            first = (result.strip().splitlines() or [""])[0]
            self._line(f"  {ACCENT_DIM}[{self.label}]{RESET} {FAINT}⎿{RESET} {RED}{_fit(first, _term_width() - 20, pad=False)}{RESET}")

    def show_change(self, change, max_lines: int = 20):
        from ui.terminal import ACCENT_DIM, FAINT, RESET, diff_headline
        self._line(f"  {ACCENT_DIM}[{self.label}]{RESET} {FAINT}⎿{RESET} {diff_headline(change)}")

    def ask_permission(self, title, detail=None, change=None, danger=False, always_label=None, question=None):
        return self.broker.ask(self.ui.ask_permission, f"[{self.label}] {title}", detail, change=change,
                               danger=danger, always_label=always_label, question=question)

    def info(self, message: str):
        from ui.terminal import ACCENT_DIM, GREY, RESET
        self._line(f"  {ACCENT_DIM}[{self.label}]{RESET} {GREY}{message}{RESET}")

    error = info

    def tool_running(self, name: str):
        pass

    def _stop_spinner(self):
        pass


class SubAgent:
    def __init__(self, parent, label: str, task: str, ui: SubAgentUI, stop: threading.Event, llm):
        self.parent = parent
        self.label = label
        self.task = task
        self.ui = ui
        self.stop = stop
        self.llm = llm

    def run(self) -> SubAgentReport:
        ctx = Context(self.parent.ctx.system_prompt + "\n\n" + SUBAGENT_PROMPT)
        ctx.add_user(self.task)
        schemas = [s for s in self.parent.tools.all_schemas() if s["name"] != DelegateTool.name]
        last_text = ""
        try:
            for _ in range(MAX_SUB_ITERATIONS):
                if self.stop.is_set():
                    return SubAgentReport(self.label, self.task, "Stopped before finishing. " + last_text, ok=False)
                ctx.truncate(limit_tokens=SUB_CONTEXT_TOKENS)
                response = self.llm.complete(system=ctx.system_prompt, messages=ctx.messages, tools=schemas)
                ctx.add_assistant(response["raw_content"])
                last_text = response["text"] or last_text
                if not response["tool_calls"]:
                    return SubAgentReport(self.label, self.task, last_text.strip() or "(no report)")
                for call in response["tool_calls"]:
                    self.ui.tool_call(call["name"], call["inputs"])
                    result = self.parent._execute_tool(call["name"], call["inputs"], ui=self.ui, owner=self.label)
                    self.ui.tool_result(result)
                    ctx.add_tool_result(call["id"], result)
        except Exception as e:
            return SubAgentReport(self.label, self.task, f"Failed: {e}. Last progress: {last_text}", ok=False)
        return SubAgentReport(self.label, self.task,
                              f"Stopped after {MAX_SUB_ITERATIONS} steps without finishing. Last progress: {last_text}",
                              ok=False)


def run_subagents(parent, tasks: list[dict], max_parallel: int) -> list[SubAgentReport]:
    """Run tasks in parallel sub-agents, serving their prompts on this (the main) thread."""
    from llm.client import LLMClient

    broker, stop, lock = PromptBroker(), threading.Event(), threading.Lock()
    labels = _labels(tasks)
    parent.claims = FileClaims()
    clients = [LLMClient(model=parent.llm.model) for _ in tasks]
    agents = [
        SubAgent(parent, label, str(t["task"]), SubAgentUI(parent.ui, label, broker, lock), stop, client)
        for label, t, client in zip(labels, tasks, clients)
    ]
    message = f"Running {len(agents)} sub-agent{'s' if len(agents) != 1 else ''}"
    parent.ui.thinking(message)
    pool = ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(agents))))
    futures = [pool.submit(a.run) for a in agents]
    try:
        broker.serve(futures, before=parent.ui._stop_spinner, after=lambda: parent.ui.thinking(message))
    except KeyboardInterrupt:
        stop.set()
        parent.ui.info("Stopping sub-agents after their current step...")
        for f in futures:
            f.cancel()
    finally:
        pool.shutdown(wait=True)
        parent.ui._stop_spinner()
        parent.claims = None
        for client in clients:  # count sub-agent usage in the session totals
            parent.llm.total_input_tokens += client.total_input_tokens
            parent.llm.total_output_tokens += client.total_output_tokens

    reports = []
    for agent, future in zip(agents, futures):
        if future.cancelled():
            reports.append(SubAgentReport(agent.label, agent.task, "Cancelled before it started.", ok=False))
        else:
            reports.append(future.result())
    return reports


def _labels(tasks: list[dict]) -> list[str]:
    labels, seen = [], set()
    for i, t in enumerate(tasks, 1):
        label = str(t.get("id") or f"t{i}")[:12]
        while label in seen:
            label += "'"
        seen.add(label)
        labels.append(label)
    return labels


class DelegateTool(BaseTool):
    name = "delegate"
    kind = "read"  # it only orchestrates; each sub-agent's own tool calls are permission-checked
    description = (
        "Run independent tasks in parallel, each in a fresh sub-agent with its own context and "
        "the same tools. Use it when two or more pieces of work don't depend on each other and "
        "touch different files (e.g. separate plan steps, implementing unrelated modules, "
        "investigating several areas). Give each task complete, self-contained instructions: the "
        "sub-agent sees none of this conversation. Returns each sub-agent's report. Don't use it "
        "for a single task or for steps that must happen in order."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short label, e.g. a plan step id like s2."},
                        "task": {"type": "string", "description": "Full instructions for the sub-agent."},
                    },
                    "required": ["task"],
                },
            },
        },
        "required": ["tasks"],
    }

    def __init__(self, agent):
        self.agent = agent

    def run(self, tasks: list) -> str:
        return self.agent.delegate(tasks)
