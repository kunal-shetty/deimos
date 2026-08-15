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
from config import LLM_API_KEY, LLM_MODEL

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

PLAN_DIR_NAME = ".deimos/plans"

PLANNING_PROMPT = (
    "You are a planning assistant for an autonomous coding agent called Deimos. "
    "Given a user's task request, decide if it requires multiple non-trivial "
    "steps (e.g. touching several files, multiple commands, a refactor, "
    "building a new module). "
    "\n\n"
    "If the task is simple (a single file read, a one-line answer, a quick "
    "question), respond with: {\"needs_plan\": false}. "
    "\n\n"
    "If the task is multi-step, respond with a JSON object: "
    "{\"needs_plan\": true, \"title\": \"<short title>\", "
    "\"steps\": [\"<step 1>\", \"<step 2>\", ...]}. "
    "Steps should be concrete and actionable, each one sentence. "
    "Aim for 3-8 steps — don't over-decompose simple tasks or under-decompose "
    "complex ones. "
    "\n\nRespond with ONLY the JSON object, no markdown fences, no extra text."
)


class Plan:
    """A single proposed plan: title, steps, and metadata."""

    def __init__(self, title: str, steps: list[str], task: str):
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
            "steps": self.steps,
            "task": self.task,
            "created_at": self.created_at,
            "status": self.status,
        }

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"**Task:** {self.task}", "", f"**Status:** {self.status}", "", "## Steps", ""]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines) + "\n"


class Planner:
    """Generates plans via a quick LLM call and persists them to disk."""

    def __init__(self, model: str = None):
        self.model = model or LLM_MODEL

    def maybe_plan(self, task: str) -> Plan | None:
        """
        Ask the LLM whether this task needs a plan. Returns a Plan if so,
        otherwise None (caller should proceed directly to execution).
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
            return None

        if not data.get("needs_plan"):
            return None

        title = data.get("title", "Untitled plan")
        steps = data.get("steps", [])
        if not steps:
            return None

        return Plan(title=title, steps=steps, task=task)

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