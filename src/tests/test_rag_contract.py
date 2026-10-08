from src.processing.rag_contract_helpers import no_retrieval_message
from src.processing.rag_prompt import build_prompt
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


def test_generation_prompt_requires_direct_non_repetitive_claims_with_local_citations():
    prompt = " ".join(
        build_prompt("Art. 1º institui o programa.", "O que estabelece o art. 1º?").split()
    )
    assert "não reescreva a pergunta" in prompt
    assert "não repita a mesma conclusão" in prompt
    assert "cite junto dela o dispositivo" in prompt


def test_no_retrieval_message_does_not_replace_chunks_without_a_reason_code():
    assert no_retrieval_message(None) is None
    assert no_retrieval_message("unknown") is None
    assert "tipo da norma" in no_retrieval_message("norm_not_in_corpus")


def test_historical_version_gap_explains_why_current_text_is_not_used():
    message = no_retrieval_message("historical_version_unavailable")
    assert "versão histórica verificável" in message
    assert "texto atual" in message


def test_historical_retrieval_gaps_have_distinct_safe_messages():
    unavailable = no_retrieval_message("historical_snapshot_unavailable")
    insufficient = no_retrieval_message("historical_evidence_unavailable")
    publication = no_retrieval_message("historical_publication_outside_scope")
    ambiguous = no_retrieval_message("ambiguous_historical_norma_scope")
    assert "não está materializada" in unavailable
    assert "Não encontrei evidências históricas suficientes" in insufficient
    assert "confirmar que a norma já havia sido publicada" in publication
    assert "mais de uma norma" in ambiguous
    assert all("conexão" not in message.casefold() for message in (unavailable, insufficient, publication, ambiguous))
