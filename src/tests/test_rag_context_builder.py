from types import SimpleNamespace
from unittest.mock import Mock

from django.test import override_settings

from src.processing.grounding_service import build_evidence
from src.processing.rag_context_builder import build_relevant_context
from src.processing.strict_grounding import evaluate_strict_grounding


def _result(text: str) -> dict:
    norma = SimpleNamespace(
        numero="1",
        ano=2024,
        tipo="Lei",
        ementa="",
        data_publicacao=None,
        data_vigencia=None,
    )
    dispositivo = SimpleNamespace(
        norma=norma,
        texto=text,
        get_full_identifier=lambda: "Art. 1º",
    )
    return {"dispositivo": dispositivo, "similarity_score": 0.91}


def test_grounding_only_receives_exact_bounded_body_sent_to_model():
    source = _result("Supported legal wording. " + ("x" * 50) + " 987654321")
    service = Mock()
    service.semantic_search.return_value = [source]

    with override_settings(RAG_MAX_CONTEXT_CHARS=80):
        context, used_sources = build_relevant_context(service, "consulta", max_tokens=20)

    assert len(context) <= 80
    assert "987654321" not in context
    assert used_sources[0]["full_text"].endswith("987654321")
    assert used_sources[0]["snippet"] == used_sources[0]["evidence_text"]
    assert used_sources[0]["context_start"] == 0
    assert used_sources[0]["context_end"] == len(used_sources[0]["snippet"])
    assert "987654321" not in used_sources[0]["evidence_text"]

    report = evaluate_strict_grounding("A obrigação legal é de 987654321 unidades.", used_sources)
    assert report["grounded"] is False


def test_empty_bounded_evidence_never_falls_back_to_full_text():
    assert build_evidence([{"evidence_text": "", "full_text": "texto não enviado ao modelo"}]) == ()
