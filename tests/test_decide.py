import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from llm.decide import (
    Answer, DecisionError, FallbackDecider, GroqDecider, JevDecider, Pick, Scale, YesNo,
)


def _fake_llm(reply):
    llm = MagicMock()
    if isinstance(reply, Exception):
        llm.complete_json.side_effect = reply
    else:
        llm.complete_json.return_value = reply
    return llm


QUESTIONS = {
    "danger": YesNo("Is this command destructive?"),
    "route": Pick("How to handle it?", {"plan": None, "execute": "simple"}),
    "importance": Scale("How important?", ["low", "mid", "high"]),
}


def test_groq_decider_validates_answers():
    llm = _fake_llm({"danger": 0.9, "route": "plan", "importance": 7})
    out = GroqDecider(llm=llm).decide("rm -rf build", QUESTIONS)
    assert out["danger"].value == 0.9
    assert out["route"].value == "plan"
    assert out["importance"].value == 2.0  # clamped to the top level


def test_groq_decider_rejects_unknown_choice():
    llm = _fake_llm({"danger": 0.1, "route": "dance", "importance": 1})
    with pytest.raises(DecisionError):
        GroqDecider(llm=llm).decide("x", QUESTIONS)


def test_groq_decider_wraps_transport_errors():
    with pytest.raises(DecisionError):
        GroqDecider(llm=_fake_llm(RuntimeError("boom"))).decide("x", QUESTIONS)


def test_jev_decider_maps_typed_answers():
    response = SimpleNamespace(
        nouls={"danger": SimpleNamespace(noul=0.97)},
        choices={"route": SimpleNamespace(choice="execute", confidence=0.8)},
        scores={"importance": SimpleNamespace(score=1.4, confidence=0.6)},
    )
    client = MagicMock()
    client.system_one.return_value = response

    out = JevDecider(api_key="k", client=client).decide("state", QUESTIONS)

    assert out["danger"] == Answer(0.97)
    assert out["route"] == Answer("execute", 0.8)
    assert out["importance"] == Answer(1.4, 0.6)
    sent = client.system_one.call_args.kwargs["questions"]
    assert sent["route"].criteria == {"plan": None, "execute": "simple"}
    assert list(sent["importance"].criteria) == ["low", "mid", "high"]


def test_jev_decider_missing_answer_is_an_error():
    client = MagicMock()
    client.system_one.return_value = SimpleNamespace(nouls={}, choices={}, scores={})
    with pytest.raises(DecisionError):
        JevDecider(api_key="k", client=client).decide("s", {"danger": YesNo("?")})


def test_fallback_uses_groq_when_jev_fails():
    client = MagicMock()
    client.system_one.side_effect = ConnectionError("offline")
    groq = GroqDecider(llm=_fake_llm({"q": 0.2}))
    decider = FallbackDecider(JevDecider(api_key="k", client=client), groq)

    assert decider.yes_no("ls", "Destructive?") == 0.2
    assert decider.primary_failures == 1
    assert "offline" in decider.last_error
