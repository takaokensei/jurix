from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.adaptive_retrieval import RetrievalOptions
from src.processing.device_revision import structural_key
from src.processing.normative_projection import NormativeProjection
from src.processing.normative_query import classify_normative_query
from src.processing.temporal_retrieval import retrieve_historical_norma
from src.processing.temporal_scope import TemporalScope

AS_OF = date(2021, 3, 1)


@pytest.fixture
def historical_norma(db):
    norma = Norma.objects.create(
        tipo="Lei",
        numero="9001",
        ano=2020,
        status="consolidated",
        ementa="Prazo administrativo sintético",
        data_publicacao=date(2020, 1, 10),
        data_vigencia=date(2020, 1, 10),
        sapl_url="https://sapl.natal.rn.leg.br/norma/9001/",
        texto_original="Art. 5º O prazo é de dez dias.",
        texto_consolidado="Art. 5º O prazo é de vinte dias.",
    )
    key = structural_key("root", "artigo", "5º")
    current = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="5º",
        texto="LATEST TEXT MUST NOT BE USED",
        ordem=1,
        structural_key=key,
        caminho="Art. 5º",
    )
    source_device = SimpleNamespace(
        structural_key=key,
        tipo="artigo",
        numero="5º",
        ordem=1,
    )
    projected_device = SimpleNamespace(
        source=source_device,
        text="O prazo histórico era de dez dias.",
        legal_status="in_force",
        provenance={"base_document_id": "synthetic-reviewed-source"},
    )
    projection = NormativeProjection(
        norma_id=norma.pk,
        as_of=AS_OF,
        status="complete",
        input_sha256="a" * 64,
        content_sha256="b" * 64,
        devices=(projected_device,),
        coverage={
            "reason": "reviewed_source_projection",
            "device_count": 1,
            "applied_event_ids": [],
            "pending_event_ids": [],
        },
    )
    return norma, current, projection


def _service(options):
    service = object.__new__(AdaptiveRAGService)
    service._jurix_retrieval_options = options
    return service


@pytest.mark.django_db
def test_explicit_historical_article_uses_projected_text_not_current_device(
    historical_norma,
):
    norma, current, projection = historical_norma
    service = _service(
        RetrievalOptions(temporal_scope=TemporalScope(as_of=AS_OF), max_sources=12)
    )
    with patch(
        "src.processing.temporal_retrieval.project_norma_as_of",
        return_value=projection,
    ) as project:
        rows = service.semantic_search(
            "O que prevê o art. 5º da Lei nº 9001/2020?",
            k=12,
        )

    assert len(rows) == 1
    assert rows[0]["dispositivo"].id == current.pk
    assert rows[0]["dispositivo"].texto == "O prazo histórico era de dez dias."
    assert rows[0]["dispositivo"].texto != current.texto
    assert rows[0]["temporal_version"]["as_of"] == AS_OF.isoformat()
    assert rows[0]["coverage"]["version_hash"] == "b" * 64
    project.assert_called_once()


@pytest.mark.django_db
def test_historical_context_warns_about_scope_and_never_injects_latest_text(
    historical_norma,
):
    _, _, projection = historical_norma
    service = _service(
        RetrievalOptions(temporal_scope=TemporalScope(as_of=AS_OF), max_sources=48)
    )
    with patch(
        "src.processing.temporal_retrieval.project_norma_as_of",
        return_value=projection,
    ):
        context, rows = service.get_relevant_context(
            "O que prevê a Lei nº 9001/2020?"
        )

    assert classify_normative_query("O que prevê a Lei nº 9001/2020?").is_norma_overview
    assert "ESCOPO TEMPORAL OBRIGATÓRIO" in context
    assert AS_OF.isoformat() in context
    assert "O prazo histórico era de dez dias." in context
    assert "LATEST TEXT MUST NOT BE USED" not in context
    assert rows[0]["coverage"]["complete"] is True
    assert rows[0]["retrieval_strategy"] == "whole_norma"
    assert rows[0]["temporal_version"]["as_of"] == AS_OF.isoformat()


@pytest.mark.django_db
def test_non_reconstructable_history_abstains_instead_of_using_latest(
    historical_norma,
):
    norma, _, projection = historical_norma
    unavailable = NormativeProjection(
        norma_id=norma.pk,
        as_of=AS_OF,
        status="not_reconstructable",
        input_sha256=projection.input_sha256,
        content_sha256=projection.content_sha256,
        devices=(),
        coverage={"reason": "base_document_not_reviewed_or_temporally_unknown"},
    )
    service = _service(
        RetrievalOptions(temporal_scope=TemporalScope(as_of=AS_OF), max_sources=12)
    )
    with patch(
        "src.processing.temporal_retrieval.project_norma_as_of",
        return_value=unavailable,
    ):
        rows = service.semantic_search(
            "O que prevê o art. 5º da Lei nº 9001/2020?",
            k=12,
        )

    assert not rows
    assert rows.reason_code == "historical_version_unavailable"
    assert rows.coverage["complete"] is False


@pytest.mark.django_db
def test_unscoped_historical_question_requires_a_fresh_materialized_snapshot(
    historical_norma,
):
    service = _service(
        RetrievalOptions(temporal_scope=TemporalScope(as_of=AS_OF), max_sources=12)
    )
    with patch.object(service, "semantic_search", wraps=service.semantic_search) as search:
        rows = service.semantic_search("Qual era o prazo administrativo?", k=12)

    assert not rows
    assert rows.reason_code == "historical_evidence_unavailable"
    assert rows.coverage["as_of"] == AS_OF.isoformat()
    search.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize("publication", [None, date(2022, 1, 1)])
def test_historical_retrieval_refuses_unknown_or_future_publication_date(
    historical_norma, publication
):
    norma, _, _ = historical_norma
    norma.data_publicacao = publication
    norma.save(update_fields=["data_publicacao"])

    with patch("src.processing.temporal_retrieval.project_norma_as_of") as project:
        rows = retrieve_historical_norma(
            norma,
            "O que prevê o art. 5º da Lei nº 9001/2020?",
            AS_OF,
            max_sources=12,
            scope=TemporalScope(as_of=AS_OF),
        )

    assert not rows
    assert rows.reason_code == "historical_publication_outside_scope"
    project.assert_not_called()
