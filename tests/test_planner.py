from unittest.mock import MagicMock, patch

from agent.planner import AnalysisResult, Planner
from llm.decide import Answer, DecisionError


def _decider(route=None, error=False):
    decider = MagicMock()
    if error:
        decider.decide.side_effect = DecisionError("down")
    else:
        decider.decide.return_value = {"route": Answer(route)}
    return decider


def test_execute_skips_plan_generation():
    llm = MagicMock()
    result = Planner(llm_client=llm, decider=_decider("execute")).maybe_plan("what is 2+2")
    assert result.decision == AnalysisResult.EXECUTE
    llm.complete_json.assert_not_called()


def test_plan_builds_steps_with_main_model():
    llm = MagicMock()
    llm.complete_json.return_value = {
        "title": "Add auth",
        "steps": [{"id": "s1", "description": "a", "dependencies": []},
                  {"id": "s2", "description": "b", "dependencies": ["s1"]}],
    }
    result = Planner(llm_client=llm, decider=_decider("plan")).maybe_plan("add auth")
    assert result.decision == AnalysisResult.PLAN
    assert [s.id for s in result.plan.steps] == ["s1", "s2"]
    assert result.plan.steps[1].dependencies == ["s1"]


def test_plan_without_steps_falls_back_to_execute():
    llm = MagicMock()
    llm.complete_json.return_value = {"title": "x", "steps": []}
    result = Planner(llm_client=llm, decider=_decider("plan")).maybe_plan("add auth")
    assert result.decision == AnalysisResult.EXECUTE


def test_clarify_asks_fast_model_for_questions():
    fast = MagicMock()
    fast.complete_json.return_value = {"questions": ["Which bug?", "Where?"]}
    with patch("llm.client.fast_llm", return_value=fast):
        result = Planner(llm_client=MagicMock(), decider=_decider("clarify")).maybe_plan("fix the bug")
    assert result.decision == AnalysisResult.CLARIFY
    assert result.questions == ["Which bug?", "Where?"]


def test_decision_failure_executes():
    result = Planner(llm_client=MagicMock(), decider=_decider(error=True)).maybe_plan("anything")
    assert result.decision == AnalysisResult.EXECUTE
