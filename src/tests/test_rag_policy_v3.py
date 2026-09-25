from django.test import override_settings

from src.processing.rag_policy import decide_grounding, response_metadata


@override_settings(RAG_MIN_ACCEPTED_SCORE=1.0)
def test_policy_rejects_non_strict_report():
    decision = decide_grounding({"grounded": True, "score": 1.0, "strict": False}, True)
    assert decision.accepted is False
    assert decision.reason == "strict_contract_missing"
    assert decision.cacheable is False


def test_policy_rejects_failed_claims_even_with_full_score():
    decision = decide_grounding(
        {"grounded": True, "strict": True, "score": 1.0, "failed_claims": ["claim"]},
        True,
    )
    assert decision.accepted is False
    assert decision.reason == "unsupported_claims"


def test_policy_metadata_uses_v2_contract():
    decision = decide_grounding(
        {"grounded": True, "strict": True, "score": 1.0, "failed_claims": []},
        True,
    )
    assert response_metadata(decision)["policy"] == "strict-grounding-v2"
