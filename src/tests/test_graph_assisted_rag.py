from datetime import date
from unittest.mock import patch

import pytest
from django.test import override_settings

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.adaptive_retrieval import RetrievalOptions
from src.processing.graph_retrieval import expand_relation_evidence
from src.processing.normative_query import classify_normative_query
from src.processing.temporal_scope import TemporalScope


@pytest.fixture
def relation_devices(db):
    source_norma = Norma.objects.create(
        tipo="Lei", numero="9101", ano=2020, status="consolidated",
        data_publicacao="2020-01-01", texto_original="", texto_consolidado="",
    )
    target_norma = Norma.objects.create(
        tipo="Lei", numero="9102", ano=2021, status="consolidated",
        data_publicacao="2021-01-01", texto_original="", texto_consolidado="",
    )
    source = Dispositivo.objects.create(
        norma=source_norma, tipo="artigo", numero="3º",
        texto="O art. 5º da Lei nº 9102/2021 passa a vigorar com esta redação.",
        ordem=1, structural_key="source-art-3", caminho="Art. 3º",
    )
    target = Dispositivo.objects.create(
        norma=target_norma, tipo="artigo", numero="5º",
        texto="O prazo será de vinte dias.", ordem=1,
        structural_key="target-art-5", caminho="Art. 5º",
    )
    return source, target


def _edge(source, target, *, action="ALTERA", event_id="event:1"):
    return {
        "id": event_id,
        "source": f"norma:{source.norma_id}",
        "target": f"norma:{target.norma_id}",
        "action": action,
        "source_device_key": source.structural_key,
        "target_device_key": target.structural_key,
        "review_status": "confirmed",
        "effective_status": "confirmed",
        "effective_on": "2022-01-01",
        "publication_on": "2021-12-20",
        "resolution": "resolved",
        "evidence": {"quote": "passa a vigorar com esta redação"},
    }


@pytest.mark.django_db
def test_relation_intent_is_detected_without_changing_article_scope():
    plan = classify_normative_query("Quem alterou o art. 5º?")
    assert plan.kind == "general"
    assert plan.relation_intent == "modification"


@pytest.mark.django_db
def test_modification_expansion_requires_and_adds_target_text(relation_devices):
    source, target = relation_devices
    baseline = [{"dispositivo": target, "similarity_score": 0.9}]
    edge = _edge(source, target)
    graph = {"edges": [edge], "nodes": [], "truncated": False}

    with patch("src.processing.graph_retrieval.build_normative_graph", return_value=graph):
        rows, trace = expand_relation_evidence(
            "Quem alterou o art. 5º?", baseline,
            relation_intent="modification",
        )

    assert [row["dispositivo"].pk for row in rows] == [target.pk, source.pk]
    assert rows[1]["graph_relation"]["role"] == "modifying_device"
    assert rows[1]["graph_relation"]["quote"] in rows[1]["dispositivo"].texto
    assert rows[1]["retrieval_score"] == 0.0
    assert trace["added_evidence_count"] == 1


@pytest.mark.django_db
def test_reference_is_explicitly_not_treated_as_amendment(relation_devices):
    source, target = relation_devices
    edge = _edge(source, target, action="REFERENCIA", event_id="event:2")
    with patch(
        "src.processing.graph_retrieval.build_normative_graph",
        return_value={"edges": [edge], "nodes": [], "truncated": False},
    ):
        rows, _ = expand_relation_evidence(
            "Quais referências esta lei faz?",
            [{"dispositivo": source}],
            relation_intent="reference",
        )

    assert len(rows) == 2
    assert rows[-1]["graph_relation"]["action"] == "REFERENCIA"
    assert "não é evidência de alteração" in rows[-1]["graph_relation"]["label"]


@pytest.mark.django_db
def test_missing_target_text_and_unrelated_neighbor_are_discarded(relation_devices):
    source, target = relation_devices
    missing_target = _edge(source, target)
    missing_target["target_device_key"] = "not-resolved"
    unrelated = _edge(source, target, event_id="event:unrelated")
    unrelated["source"] = "norma:999999"
    with patch(
        "src.processing.graph_retrieval.build_normative_graph",
        return_value={"edges": [missing_target, unrelated], "nodes": [], "truncated": False},
    ):
        rows, trace = expand_relation_evidence(
            "O que alterou a norma?",
            [{"dispositivo": source}],
            relation_intent="modification",
        )

    assert len(rows) == 1
    assert trace["added_evidence_count"] == 0
    assert any(item["reason"] == "target_device_text_unavailable" for item in trace["discarded"])


@pytest.mark.django_db
def test_event_quote_must_match_source_device_text(relation_devices):
    source, target = relation_devices
    edge = _edge(source, target)
    edge["evidence"]["quote"] = "quote inexistente na fonte"
    with patch(
        "src.processing.graph_retrieval.build_normative_graph",
        return_value={"edges": [edge], "nodes": [], "truncated": False},
    ):
        rows, trace = expand_relation_evidence(
            "Quem alterou esta norma?",
            [{"dispositivo": target}],
            relation_intent="modification",
        )

    assert len(rows) == 1
    assert trace["discarded"] == [
        {"event_id": edge["id"], "reason": "source_quote_not_verifiable"}
    ]


@pytest.mark.django_db
def test_graph_expansion_is_capped_at_eight_additional_sources(relation_devices):
    source, target = relation_devices
    edges = [_edge(source, target, event_id=f"event:{index}") for index in range(12)]
    with patch(
        "src.processing.graph_retrieval.build_normative_graph",
        return_value={"edges": edges, "nodes": [], "truncated": False},
    ):
        rows, trace = expand_relation_evidence(
            "Quem alterou esta norma?",
            [{"dispositivo": target}],
            relation_intent="modification",
            max_additional=40,
        )

    assert len(rows) <= 9
    assert trace["added_evidence_count"] <= 8
    assert trace["additional_evidence_limit"] == 8


def test_feature_flag_off_preserves_baseline_rows():
    baseline = [{"dispositivo": None, "similarity_score": 1.0}]
    plan = classify_normative_query("Quem alterou o art. 5º?")
    with override_settings(RAG_GRAPH_CONTEXT_ENABLED=False), patch(
        "src.processing.adaptive_rag_service.expand_relation_evidence"
    ) as expand:
        result = AdaptiveRAGService._expand_relation_rows(
            baseline, "Quem alterou o art. 5º?", RetrievalOptions(), plan
        )

    assert result == baseline
    expand.assert_not_called()


def test_historical_relation_query_does_not_mix_latest_graph_text():
    baseline = [{"dispositivo": None, "similarity_score": 1.0}]
    plan = classify_normative_query("Quem alterou o art. 5º?")
    options = RetrievalOptions(temporal_scope=TemporalScope(as_of=date(2020, 1, 1)))
    with override_settings(RAG_GRAPH_CONTEXT_ENABLED=True), patch(
        "src.processing.adaptive_rag_service.expand_relation_evidence"
    ) as expand:
        result = AdaptiveRAGService._expand_relation_rows(
            baseline, "Quem alterou o art. 5º?", options, plan
        )

    assert len(result) == 1
    assert result.graph_trace["discarded"][0]["reason"] == "historical_graph_text_not_projected"
    expand.assert_not_called()
