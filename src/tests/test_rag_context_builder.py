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


def test_context_uses_stable_markers_and_expands_bounded_budget_for_whole_norma():
    source = _result("Conteúdo normativo específico.")
    source["coverage"] = {
        "strategy": "whole_norma",
        "total_devices": 80,
        "selected_devices": 48,
        "total_articles": 40,
        "selected_articles": 30,
        "complete": False,
    }
    source["retrieval_strategy"] = "whole_norma"
    service = Mock()
    service.semantic_search.return_value = [source]

    with override_settings(RAG_MAX_CONTEXT_CHARS=100, RAG_NORMA_OVERVIEW_MAX_CONTEXT_CHARS=12000):
        context, used_sources = build_relevant_context(
            service, "O que prevê a Lei nº 1/2024?", max_tokens=3000
        )

    assert "[[1]] Lei nº 1/2024, Art. 1º" in context
    assert "nem todos os dispositivos previstos" in context
    assert used_sources[0]["citation_index"] == 1
    assert used_sources[0]["evidence_scope"] == "sampled"
    assert len(context) > 100


def test_whole_norma_coverage_is_incomplete_when_a_38000_character_body_is_truncated():
    source = _result("A" * 38_000)
    source["coverage"] = {
        "strategy": "whole_norma",
        "total_devices": 1,
        "selected_devices": 1,
        "total_articles": 1,
        "selected_articles": 1,
        "complete": True,
    }
    service = Mock()
    service.semantic_search.return_value = [source]

    with override_settings(
        RAG_MAX_CONTEXT_CHARS=48_000,
        RAG_NORMA_OVERVIEW_MAX_CONTEXT_CHARS=24_000,
    ):
        context, used_sources = build_relevant_context(
            service, "O que prevê a Lei nº 1/2024?", max_tokens=2_000
        )

    assert len(context) <= 8_000
    assert used_sources[0]["coverage"]["complete"] is False
    assert used_sources[0]["evidence_scope"] == "sampled"
    assert used_sources[0]["snippet_truncated"] is True
    assert used_sources[0]["evidence_text"] == used_sources[0]["snippet"]
    assert len(used_sources[0]["evidence_text"]) < len(used_sources[0]["full_text"])


def test_overview_coverage_boundary_and_appended_ementa_are_counted_as_context():
    source = _result("Texto do artigo.")
    source["dispositivo"].norma.ementa = "E" * 1_000
    source["coverage"] = {
        "strategy": "whole_norma",
        "total_devices": 1,
        "selected_devices": 1,
        "total_articles": 1,
        "selected_articles": 1,
        "complete": True,
    }
    service = Mock()
    service.semantic_search.return_value = [source]

    with override_settings(RAG_MAX_CONTEXT_CHARS=48_000):
        context, used_sources = build_relevant_context(
            service, "O que prevê a Lei nº 1/2024 sobre o tema?", max_tokens=150
        )

    assert len(context) <= 600
    assert used_sources[0]["coverage"]["complete"] is False
    assert used_sources[0]["snippet_truncated"] is True
    assert used_sources[0]["evidence_text"] == used_sources[0]["snippet"]
    assert "E" * 1_001 not in context


def test_overview_body_fitting_exactly_at_context_boundary_remains_complete():
    scope_note = (
        "ESCOPO: todos os dispositivos atualmente indexados foram recuperados; o corpus "
        "ainda pode estar incompleto ou desatualizado."
    )
    header = "[[1]] Lei nº 1/2024, Art. 1º: "
    body_length = 600 - len(scope_note) - 2 - len(header)
    source = _result("T" * body_length)
    source["coverage"] = {
        "strategy": "whole_norma",
        "total_devices": 1,
        "selected_devices": 1,
        "total_articles": 1,
        "selected_articles": 1,
        "complete": True,
    }
    service = Mock()
    service.semantic_search.return_value = [source]

    with override_settings(RAG_MAX_CONTEXT_CHARS=48_000):
        context, used_sources = build_relevant_context(
            service, "O que prevê a Lei nº 1/2024 sobre o tema?", max_tokens=150
        )

    assert len(context) == 600
    assert used_sources[0]["snippet_truncated"] is False
    assert used_sources[0]["coverage"]["context_complete"] is True
    assert used_sources[0]["coverage"]["complete"] is True
