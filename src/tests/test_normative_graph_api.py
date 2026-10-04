from __future__ import annotations

from datetime import date

import pytest
from django.test import Client, override_settings

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.processing.normative_graph import build_normative_graph


@pytest.fixture
def graph_map(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    return seed_fixture(root / "fixture-map.json")["temporal_scenarios"]


@pytest.mark.django_db(transaction=True)
def test_graph_traverses_reviewed_edge_with_stable_nodes_and_date_scope(graph_map):
    source_id = graph_map["norma_a"]["norma_id"]
    graph = build_normative_graph(source_id, depth=2, as_of=date(2021, 3, 1))
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert edge["action"] == "ALTERA"
    assert edge["review_status"] == "confirmed"
    assert edge["effective_status"] == "confirmed"
    assert edge["effective_on"] == "2021-03-01"
    assert edge["source"] == f"norma:{graph_map['norma_b']['norma_id']}"
    assert edge["target"] == f"norma:{source_id}"
    assert edge["source_device"]["label"]
    assert edge["source_device"]["structural_key"] == edge["source_device_key"]
    assert edge["target_device"]["label"]
    assert edge["target_device"]["structural_key"] == edge["target_device_key"]

    before = build_normative_graph(source_id, depth=1, as_of=date(2021, 2, 28))
    assert before["edges"] == []


@pytest.mark.django_db(transaction=True)
def test_bfs_terminates_on_normative_cycle_and_deduplicates_edges(graph_map):
    norma_a = Norma.objects.get(pk=graph_map["norma_a"]["norma_id"])
    norma_b = Norma.objects.get(pk=graph_map["norma_b"]["norma_id"])
    source_device = Dispositivo.objects.get(norma=norma_a)
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        acao="REFERENCIA",
        target_text="Referência sintética inversa",
        norma_alvo=norma_b,
        target_reference_json={"synthetic_pending": True},
        revision_fingerprint="synthetic-cycle-edge",
    )
    graph = build_normative_graph(norma_a, depth=2, include_pending=True)
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 2
    assert len({edge["id"] for edge in graph["edges"]}) == 2


@pytest.mark.django_db(transaction=True)
def test_graph_is_bounded_and_query_count_does_not_scale_per_edge(graph_map, django_assert_num_queries):
    norma = Norma.objects.get(pk=graph_map["norma_a"]["norma_id"])
    existing = EventoAlteracao.objects.get(pk=graph_map["norma_b"]["event_id"])

    EventoAlteracao.objects.bulk_create([
        EventoAlteracao(
            dispositivo_fonte=existing.dispositivo_fonte,
            acao="REFERENCIA",
            target_text=f"Candidato sintético {index}",
            norma_alvo=norma,
            target_reference_json={"synthetic_pending": True},
            revision_fingerprint=f"pending-graph-{index}",
        )
        for index in range(40)
    ])
    with django_assert_num_queries(12, exact=False):
        result = build_normative_graph(norma, depth=2, include_pending=True)
    assert result["limits"] == {"nodes": 40, "edges": 80}
    assert result["truncated"] is False
    assert len(result["edges"]) == 41


@pytest.mark.django_db(transaction=True)
def test_graph_edge_limit_reports_truncation(graph_map):
    norma = Norma.objects.get(pk=graph_map["norma_a"]["norma_id"])
    existing = EventoAlteracao.objects.get(pk=graph_map["norma_b"]["event_id"])
    EventoAlteracao.objects.bulk_create([
        EventoAlteracao(
            dispositivo_fonte=existing.dispositivo_fonte,
            acao="REFERENCIA",
            target_text=f"Candidato limitado {index}",
            norma_alvo=norma,
            target_reference_json={"synthetic_pending": True},
            revision_fingerprint=f"pending-limit-{index}",
        )
        for index in range(82)
    ])
    graph = build_normative_graph(norma, depth=1, include_pending=True)
    assert len(graph["edges"]) == 80
    assert graph["truncated"] is True


@pytest.mark.django_db(transaction=True)
def test_relations_api_validates_filters_permissions_and_methods(graph_map):
    pk = graph_map["norma_a"]["norma_id"]
    client = Client()
    base = f"/api/v1/normas/{pk}/relations/"
    assert client.get(base + "?depth=3").status_code == 400
    assert client.get(base + "?include_pending=yes").status_code == 400
    assert client.get(base + "?actions=ALTERA,NOPE").status_code == 400
    assert client.get(base + "?as_of=03-01-2021").status_code == 400
    assert client.post(base).status_code == 405
    assert client.get("/api/v1/normas/999999/relations/").status_code == 404
    denied = client.get(base + "?include_pending=true")
    assert denied.status_code == 403

    staff = __import__("django.contrib.auth.models", fromlist=["User"]).User.objects.get(
        username="jurix-qa-reviewer"
    )
    client.force_login(staff)
    response = client.get(base + "?depth=2&as_of=2021-03-01&include_pending=false")
    assert response.status_code == 200
    assert response.json()["edges"][0]["action"] == "ALTERA"


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=True)
def test_norma_detail_mounts_lazy_relations_component_only_when_enabled(graph_map):
    norma_id = graph_map["norma_a"]["norma_id"]
    response = Client().get(f"/normas/{norma_id}/")
    assert response.status_code == 200
    assert b"data-normative-relations" in response.content
    assert f"/api/v1/normas/{norma_id}/relations/".encode() in response.content


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=False)
def test_norma_detail_does_not_advertise_disabled_relations_component(graph_map):
    norma_id = graph_map["norma_a"]["norma_id"]
    response = Client().get(f"/normas/{norma_id}/")
    assert response.status_code == 200
    assert b"data-normative-relations" not in response.content


@pytest.mark.django_db(transaction=True)
def test_version_api_reads_projection_without_persisting_a_get(graph_map):
    pk = graph_map["norma_a"]["norma_id"]
    client = Client()
    before = Norma.objects.get(pk=pk).normative_snapshots.count()
    response = client.get(f"/api/v1/normas/{pk}/version/?as_of=2021-02-27")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["devices"][0]["text"] == "Art. 5º O prazo é de dez dias."
    assert payload["snapshot_id"] is None
    assert payload["document"]["local_evidence_url"].startswith("/normas/documentos/")
    assert payload["document"]["local_pdf_url"] is None
    assert Norma.objects.get(pk=pk).normative_snapshots.count() == before
    assert client.get(f"/api/v1/normas/{pk}/version/").status_code == 400
    assert client.get(f"/api/v1/normas/{pk}/version/?as_of=not-a-date").status_code == 400
    assert client.post(f"/api/v1/normas/{pk}/version/?as_of=2021-02-27").status_code == 405
