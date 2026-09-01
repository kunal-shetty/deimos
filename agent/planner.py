"""
Plan mode: for multi-step tasks, Deimos proposes a short numbered plan and
waits for user confirmation before executing any tools.

Plans are persisted to disk under .deimos/plans/ in the current working
directory (per-project), as both a JSON record and a readable markdown file.
"""

import os
import json
import re
import uuid
import requests
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from config import LLM_API_KEY, LLM_MODEL

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

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

PLANNING_PROMPT = (
    "You are a planning assistant for an autonomous coding agent called Deimos. "
    "Given a user's task request, you must first determine if the request is clear "
    "enough to proceed. "
    "\n\n"
    "1. CLARIFY: If the request is ambiguous, lacks critical context, or is too broad "
    "(e.g., 'fix the bug' without specifying which bug), respond with: "
    "{\"decision\": \"clarify\", \"questions\": [\"<question 1>\", \"<question 2>\"]}. "
    "Ask targeted questions to narrow down the scope. "
    "\n\n"
    "2. EXECUTE: If the task is simple and unambiguous (a single file read, a "
    "one-line answer, a quick question), respond with: "
    "{\"decision\": \"execute\"}. "
    "\n\n"
    "3. PLAN: If the task is clear but multi-step, respond with a structured workflow: "
    "{\"decision\": \"plan\", \"title\": \"<short title>\", "
    "\"steps\": [ "
    "{\"id\": \"s1\", \"description\": \"...\", \"dependencies\": []}, "
    "{\"id\": \"s2\", \"description\": \"...\", \"dependencies\": [\"s1\"]}, "
    " ... ]}. "
    "Each step must have a unique ID and a list of IDs it depends on. "
    "Ensure the graph is a Directed Acyclic Graph (DAG). "
    "Aim for 3-8 steps. "
    "\n\nRespond with ONLY the JSON object, no markdown fences, no extra text."
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

    def __init__(self, model: str = None):
        self.model = model or LLM_MODEL

    def maybe_plan(self, task: str) -> PlanAnalysis:
        """
        Analyze the task and decide whether to plan, execute immediately, or clarify.
        """
        payload = {
            "model": self.model,
            "max_tokens": 600,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": PLANNING_PROMPT},
                {"role": "user", "content": task},
            ],
        }

        try:
            response = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()
            raw = _strip_fences(raw)
            data = json.loads(raw)
        except Exception:
            # Fallback: assume immediate execution if analysis fails
            return PlanAnalysis(decision=AnalysisResult.EXECUTE)

        decision_str = data.get("decision", "execute").lower()
        decision = AnalysisResult(decision_str) if decision_str in [r.value for r in AnalysisResult] else AnalysisResult.EXECUTE

        if decision == AnalysisResult.CLARIFY:
            return PlanAnalysis(decision=AnalysisResult.CLARIFY, questions=data.get("questions", []))

        if decision == AnalysisResult.PLAN:
            title = data.get("title", "Untitled plan")
            steps_data = data.get("steps", [])
            if steps_data:
                steps = []
                for s in steps_data:
                    steps.append(Step(
                        id=s.get("id", "unknown"),
                        description=s.get("description", "No description"),
                        dependencies=s.get("dependencies", [])
                    ))
                return PlanAnalysis(decision=AnalysisResult.PLAN, plan=Plan(title=title, steps=steps, task=task))
            return PlanAnalysis(decision=AnalysisResult.EXECUTE)

        return PlanAnalysis(decision=AnalysisResult.EXECUTE)

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