from src.processing.grounding import evaluate_grounding
from src.processing.rag_service import RAGService


def _evidence(text, norma_ref="Lei 123/2020"):
    return [
        {
            "text": text,
            "identifier": "Art. 5º",
            "norma_ref": norma_ref,
        }
    ]


def test_grounding_accepts_claim_supported_by_source_text():
    report = evaluate_grounding(
        "O prazo previsto é de quinze dias.",
        _evidence("O prazo previsto é de quinze dias para apresentação do recurso."),
    )
    assert report["grounded"] is True
    assert report["failed_claims"] == []


def test_grounding_rejects_unsupported_factual_claim():
    report = evaluate_grounding(
        "O prazo previsto é de trinta dias.",
        _evidence("O prazo previsto é de quinze dias para apresentação do recurso."),
    )
    assert report["grounded"] is False
    assert report["failed_claims"]


def test_grounding_accepts_citation_matching_retrieved_norm():
    report = evaluate_grounding(
        "A regra está prevista na Lei nº 123/2020.",
        _evidence("Regra qualquer.", norma_ref="Lei 123/2020"),
    )
    assert report["grounded"] is True


def test_rag_alias_uses_grounding_guard():
    assert (
        RAGService._ground_answer(
            "Texto baseado na regra de quinze dias.",
            _evidence("A regra de quinze dias é aplicável."),
        )["grounded"]
        is True
    )
