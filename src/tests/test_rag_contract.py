from src.processing.rag_service import RAGService


def test_contract_never_uses_similarity_as_confidence():
    contract = RAGService._contract(
        answer="A resposta",
        sources=[{"id": 1, "similarity_score": 0.91}],
        source_relevance=0.91,
        grounded=True,
        grounding={"grounded": True, "score": 1.0, "claims": [], "failed_claims": []},
        model="test-model",
    )

    assert contract["source_relevance"] == 0.91
    assert contract["confidence"] is None
    assert contract["confidence_calibrated"] is False
    assert contract["grounded"] is True


def test_contract_keeps_grounding_failure_auditable():
    grounding = {
        "grounded": False,
        "score": 0.5,
        "claims": [{"claim": "A", "supported": False, "evidence": []}],
        "failed_claims": ["A"],
    }
    contract = RAGService._contract(
        answer="fallback",
        sources=[],
        source_relevance=0.0,
        grounded=False,
        grounding=grounding,
        model="test-model",
    )
    assert contract["grounding"]["failed_claims"] == ["A"]
