from django.test import override_settings

from src.processing.rag_policy import decide_grounding, response_metadata


@override_settings(RAG_MIN_ACCEPTED_SCORE=1.0)
def test_policy_metadata_is_machine_readable():
    decision = decide_grounding({"grounded": True, "score": 1.0}, True)
    metadata = response_metadata(decision)
    assert metadata["policy"] == "strict-grounding-v1"
    assert metadata["cacheable"] is True


def test_policy_never_caches_source_boundary_failure():
    decision = decide_grounding({"grounded": True, "score": 1.0}, False)
    assert decision.cacheable is False
