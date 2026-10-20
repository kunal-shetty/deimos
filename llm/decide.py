"""
Structured decisions for Deimos' internal logic: yes/no, pick-one and scale
questions about a piece of state (a user message, a command, a diff...).

JevDecider answers them with TypeSafe's Jev, a model built for typed
decisions. GroqDecider asks the fast Groq model for JSON and validates it.
get_decider() returns Jev with a Groq fallback when TYPESAFE_API_KEY is set
and Jev is enabled in settings, otherwise Groq alone.

decide() raises DecisionError when no backend could answer; callers catch it
and fall back to a safe default for their decision.
"""

import json
import threading
from dataclasses import dataclass

from config import TYPESAFE_API_KEY, JEV_MODEL

JEV_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class YesNo:
    instructions: str
    yes: str | None = None  # what counts as yes (optional)
    no: str | None = None   # what counts as no (optional)


@dataclass(frozen=True)
class Pick:
    instructions: str
    options: dict[str, str | None]  # label -> description (None = self-explanatory)


@dataclass(frozen=True)
class Scale:
    instructions: str
    levels: list[str]  # one description per level, from 0 upwards


Question = YesNo | Pick | Scale


@dataclass(frozen=True)
class Answer:
    value: float | str
    """YesNo: probability of yes (0-1). Pick: the chosen label. Scale: expected level (may be fractional)."""
    confidence: float | None = None


class DecisionError(Exception):
    pass


class Decider:
    name = "base"

    def decide(self, state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        raise NotImplementedError

    # ── Single-question shortcuts ────────────────────────────────────────────

    def yes_no(self, state: str, instructions: str, yes: str | None = None, no: str | None = None) -> float:
        return self.decide(state, {"q": YesNo(instructions, yes, no)})["q"].value

    def pick(self, state: str, instructions: str, options: dict[str, str | None]) -> Answer:
        return self.decide(state, {"q": Pick(instructions, options)})["q"]

    def scale(self, state: str, instructions: str, levels: list[str]) -> Answer:
        return self.decide(state, {"q": Scale(instructions, levels)})["q"]


class JevDecider(Decider):
    name = "jev"

    def __init__(self, api_key: str, model: str | None = None, client=None):
        if client is None:
            from typesafe_sdk import TypeSafeClient
            client = TypeSafeClient(api_key=api_key, model=model, timeout=JEV_TIMEOUT_SECONDS)
        self._client = client

    def decide(self, state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        from typesafe_sdk import Choice, Noul, Score

        wire = {}
        for name, q in questions.items():
            if isinstance(q, YesNo):
                criteria = {"true": q.yes, "false": q.no} if (q.yes or q.no) else None
                wire[name] = Noul(instructions=q.instructions, criteria=criteria)
            elif isinstance(q, Pick):
                wire[name] = Choice(instructions=q.instructions, criteria=dict(q.options))
            else:
                wire[name] = Score(instructions=q.instructions, criteria=list(q.levels))

        try:
            res = self._client.system_one(state=state, questions=wire)
        except Exception as e:  # TypeSafeError and anything the transport raises
            raise DecisionError(f"Jev request failed: {e}") from e

        out = {}
        for name, q in questions.items():
            if isinstance(q, YesNo):
                a = res.nouls.get(name)
                answer = a and Answer(a.noul)
            elif isinstance(q, Pick):
                a = res.choices.get(name)
                answer = a and Answer(a.choice, a.confidence)
            else:
                a = res.scores.get(name)
                answer = a and Answer(a.score, a.confidence)
            if answer is None:
                raise DecisionError(f"Jev returned no answer for {name!r}")
            out[name] = answer
        return out


GROQ_DECIDER_PROMPT = (
    "You answer structured questions about a piece of state for an autonomous "
    "coding agent. Answer every question, using exactly the format it asks for. "
    "Respond with ONLY a JSON object mapping each question name to its answer."
)


class GroqDecider(Decider):
    name = "groq"

    def __init__(self, llm=None):
        self._llm = llm

    def decide(self, state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        from llm.client import fast_llm

        specs = []
        for name, q in questions.items():
            if isinstance(q, YesNo):
                criteria = (f" Yes means: {q.yes}." if q.yes else "") + (f" No means: {q.no}." if q.no else "")
                specs.append(f"- {name}: {q.instructions}{criteria} Answer with the probability (0 to 1) that the answer is yes.")
            elif isinstance(q, Pick):
                opts = "; ".join(f'"{label}"' + (f" ({desc})" if desc else "") for label, desc in q.options.items())
                specs.append(f"- {name}: {q.instructions} Answer with exactly one of: {opts}.")
            else:
                levels = "; ".join(f"{i}: {desc}" for i, desc in enumerate(q.levels))
                specs.append(f"- {name}: {q.instructions} Answer with an integer level. Levels: {levels}.")

        try:
            data = (self._llm or fast_llm()).complete_json(
                system=GROQ_DECIDER_PROMPT,
                messages=[{"role": "user", "content": f"State:\n{state}\n\nQuestions:\n" + "\n".join(specs)}],
                max_tokens=300,
                temperature=0.0,
            )
        except Exception as e:
            raise DecisionError(f"Groq decision request failed: {e}") from e
        if not isinstance(data, dict) or "error" in data:
            raise DecisionError(f"Groq returned unusable JSON: {json.dumps(data)[:200]}")

        return {name: _validate(name, q, data.get(name)) for name, q in questions.items()}


def _validate(name: str, q: Question, raw) -> Answer:
    if isinstance(q, Pick):
        if isinstance(raw, str) and raw in q.options:
            return Answer(raw)
        raise DecisionError(f"{name!r}: {raw!r} is not one of {list(q.options)}")
    if isinstance(raw, bool):
        raw = float(raw)
    if not isinstance(raw, (int, float)):
        raise DecisionError(f"{name!r}: expected a number, got {raw!r}")
    if isinstance(q, YesNo):
        return Answer(min(1.0, max(0.0, float(raw))))
    return Answer(min(float(len(q.levels) - 1), max(0.0, float(raw))))


class FallbackDecider(Decider):
    """Try the primary backend; on failure use the fallback."""

    def __init__(self, primary: Decider, fallback: Decider):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"
        self.primary_failures = 0
        self.last_error: str | None = None

    def decide(self, state: str, questions: dict[str, Question]) -> dict[str, Answer]:
        try:
            return self.primary.decide(state, questions)
        except DecisionError as e:
            self.primary_failures += 1
            self.last_error = str(e)
            return self.fallback.decide(state, questions)


_decider: Decider | None = None
_decider_lock = threading.Lock()


def get_decider() -> Decider:
    """Shared decider: Jev with Groq fallback when configured, else Groq."""
    global _decider
    with _decider_lock:
        if _decider is None:
            from settings import load_settings
            groq = GroqDecider()
            _decider = groq
            if TYPESAFE_API_KEY and load_settings()["jev"].get("enabled", True):
                try:
                    _decider = FallbackDecider(JevDecider(TYPESAFE_API_KEY, model=JEV_MODEL), groq)
                except Exception:
                    pass  # SDK missing or misconfigured: Groq alone
        return _decider
