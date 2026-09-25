from django.test import override_settings

from src.processing.rag_policy import decide_grounding


def test_policy_rejects_non_source_answer():
    decision = decide_grounding({"grounded": True, "score": 1.0}, False)
    assert decision.accepted is False
    assert decision.cacheable is False


@override_settings(RAG_MIN_ACCEPTED_SCORE=1.0)
def test_policy_requires_perfect_grounding_score():
    decision = decide_grounding({"grounded": True, "score": 0.9}, True)
    assert decision.accepted is False


@override_settings(RAG_MIN_ACCEPTED_SCORE=1.0)
def test_policy_accepts_grounded_answer():
    decision = decide_grounding({"grounded": True, "score": 1.0}, True)
    assert decision.accepted is True
    assert decision.cacheable is True
