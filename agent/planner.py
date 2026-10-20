"""
Plan mode: for multi-step tasks, Deimos proposes a short numbered plan and
waits for user confirmation before executing any tools.

Plans are persisted to disk under .deimos/plans/ in the current working
directory (per-project), as both a JSON record and a readable markdown file.
"""
from __future__ import annotations

import os
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from llm.decide import DecisionError, Pick, get_decider

PLAN_DIR_NAME = ".deimos/plans"

class AnalysisResult(Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    CLARIFY = "clarify"

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Step:
    id: str
    description: str
    dependencies: list[str]
    status: StepStatus = StepStatus.PENDING
    output: Optional[str] = None

@dataclass
class PlanAnalysis:
    decision: AnalysisResult
    plan: Optional[Plan] = None
    questions: Optional[list[str]] = None

TRIAGE_QUESTION = Pick(
    instructions="How should an autonomous coding agent handle this user request?",
    options={
        "execute": (
            "Can be handled directly: small talk or thanks, the user telling the agent about "
            "themselves, their project or preferences (no task requested), a question, "
            "a single file read or edit, a one-line answer."
        ),
        "plan": "An explicit task request that is multi-step: needs several coordinated changes or actions.",
        "clarify": (
            "A task request that is ambiguous, too broad, or missing critical context "
            "(e.g. 'fix the bug' without saying which bug)."
        ),
    },
)

PLANNING_PROMPT = (
    "You are a planning assistant for an autonomous coding agent called Deimos. "
    "Break the user's task into a structured workflow: "
    "{\"title\": \"<short title>\", "
    "\"steps\": [ "
    "{\"id\": \"s1\", \"description\": \"...\", \"dependencies\": []}, "
    "{\"id\": \"s2\", \"description\": \"...\", \"dependencies\": [\"s1\"]}, "
    " ... ]}. "
    "Each step must have a unique ID and a list of IDs it depends on. "
    "Ensure the graph is a Directed Acyclic Graph (DAG). "
    "Aim for 3-8 steps. "
    "\n\nRespond with ONLY the JSON object, no markdown fences, no extra text."
)

CLARIFY_PROMPT = (
    "The user's request to an autonomous coding agent is ambiguous or missing "
    "critical context. Ask 1-3 short, targeted questions that would narrow it "
    "down enough to start. Respond with ONLY a JSON object: "
    "{\"questions\": [\"<question 1>\", ...]}."
)


class Plan:
    """A structured workflow plan: title, a DAG of steps, and metadata."""

    def __init__(self, title: str, steps: list[Step], task: str):
        self.id = str(uuid.uuid4())[:8]
        self.title = title
        self.steps = steps
        self.task = task
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.status = "pending"  # pending | confirmed | rejected | completed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "dependencies": s.dependencies,
                    "status": s.status.value,
                    "output": s.output
                }
                for s in self.steps
            ],
            "task": self.task,
            "created_at": self.created_at,
            "status": self.status,
        }

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"**Task:** {self.task}", "", f"**Status:** {self.status}", "", "## Workflow Steps", ""]
        for step in self.steps:
            deps = f" (depends on: {', '.join(step.dependencies)})" if step.dependencies else ""
            lines.append(f"- [{step.status.value}] {step.description}{deps}")
        return "\n".join(lines) + "\n"


class Planner:
    """Generates plans via a quick LLM call and persists them to disk."""

    def __init__(self, llm_client=None, decider=None):
        self.llm = llm_client
        self._decider = decider

    @property
    def decider(self):
        return self._decider or get_decider()

    def maybe_plan(self, task: str) -> PlanAnalysis:
        """
        Analyze the task and decide whether to plan, execute immediately, or clarify.
        The decision itself is a cheap structured call; plans and questions are
        only generated when that decision calls for them.
        """
        if not self.llm:
            return PlanAnalysis(decision=AnalysisResult.EXECUTE)

        try:
            decision = AnalysisResult(self.decider.decide(task, {"route": TRIAGE_QUESTION})["route"].value)
        except (DecisionError, ValueError):
            # Fallback: assume immediate execution if analysis fails
            return PlanAnalysis(decision=AnalysisResult.EXECUTE)

        if decision == AnalysisResult.CLARIFY:
            return PlanAnalysis(decision=AnalysisResult.CLARIFY, questions=self._clarifying_questions(task))

        if decision == AnalysisResult.PLAN:
            plan = self._generate_plan(task)
            if plan:
                return PlanAnalysis(decision=AnalysisResult.PLAN, plan=plan)

        return PlanAnalysis(decision=AnalysisResult.EXECUTE)

    def _generate_plan(self, task: str) -> Optional[Plan]:
        try:
            data = self.llm.complete_json(
                system=PLANNING_PROMPT,
                messages=[{"role": "user", "content": task}],
                max_tokens=600,
                temperature=0.2,
            )
        except Exception:
            return None
        steps_data = data.get("steps") if isinstance(data, dict) else None
        if not steps_data or not isinstance(steps_data, list):
            return None
        steps = [
            Step(
                id=str(s.get("id", f"s{i + 1}")),
                description=s.get("description", "No description"),
                dependencies=[str(d) for d in s.get("dependencies", [])],
            )
            for i, s in enumerate(steps_data) if isinstance(s, dict)
        ]
        if not steps:
            return None
        return Plan(title=data.get("title", "Untitled plan"), steps=steps, task=task)

    def _clarifying_questions(self, task: str) -> list[str]:
        from llm.client import fast_llm
        try:
            data = fast_llm().complete_json(
                system=CLARIFY_PROMPT,
                messages=[{"role": "user", "content": task}],
                max_tokens=300,
            )
        except Exception:
            return []
        questions = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(questions, list):
            return []
        return [str(q) for q in questions if str(q).strip()][:3]

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self, plan: Plan, cwd: str = None) -> str:
        """Save plan as both JSON and markdown under .deimos/plans/ in cwd."""
        base = os.path.join(cwd or os.getcwd(), PLAN_DIR_NAME)
        os.makedirs(base, exist_ok=True)

        json_path = os.path.join(base, f"{plan.id}.json")
        md_path = os.path.join(base, f"{plan.id}.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(plan.to_markdown())

        return md_path

    def update_status(self, plan: Plan, status: str, cwd: str = None):
        plan.status = status
        self.save(plan, cwd)

    def list_plans(self, cwd: str = None, limit: int = 20) -> list[dict]:
        base = os.path.join(cwd or os.getcwd(), PLAN_DIR_NAME)
        if not os.path.isdir(base):
            return []

        plans = []
        for fname in sorted(os.listdir(base), reverse=True):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(base, fname), "r", encoding="utf-8") as f:
                        plans.append(json.load(f))
                except Exception:
                    continue
        return plans[:limit]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()