from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings

from src.apps.ingestion.document_relation_candidates import persist_document_relation_candidates
from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    ExtracaoDocumento,
    RevisaoEventoNormativoCandidato,
)
from src.apps.legislation.document_relation_review import review_document_relation_candidate
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.temporal_api import norma_version_api  # noqa: F401
from src.processing.normative_graph import (
    build_candidate_document_graph,
    build_normative_graph,
)


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
def test_graph_at_exact_edge_limit_is_not_marked_truncated(graph_map):
    norma = Norma.objects.get(pk=graph_map["norma_a"]["norma_id"])
    existing = EventoAlteracao.objects.get(pk=graph_map["norma_b"]["event_id"])
    EventoAlteracao.objects.bulk_create([
        EventoAlteracao(
            dispositivo_fonte=existing.dispositivo_fonte,
            acao="REFERENCIA",
            target_text=f"Referência sintética no limite exato {index}",
            norma_alvo=norma,
            target_reference_json={"synthetic_pending": True},
            revision_fingerprint=f"exact-limit-{index}",
        )
        for index in range(79)
    ])

    graph = build_normative_graph(norma, depth=1, include_pending=True)

    assert len(graph["edges"]) == 80
    assert graph["truncated"] is False


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=True)
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
    assert response.json()["corpus_coverage"]["coverage_status"] == "unknown"
    assert response.json()["corpus_coverage"]["checked_until"] is None


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=True)
def test_candidate_evidence_api_requires_both_review_permissions(graph_map):
    event = EventoAlteracao.objects.get(pk=graph_map["norma_b"]["event_id"])
    source_norma = event.dispositivo_fonte.norma
    document = DocumentoNormativo.objects.create(
        document_key="candidate-evidence-api-test",
        norma=source_norma,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="jurix-qa:candidate-evidence-api-test",
        content_sha256="b" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    source_norma.documento_base = document
    source_norma.save(update_fields=["documento_base", "updated_at"])
    event.evidence_json = {"quote": "[QA] trecho candidato não revisado", "page": 2}
    event.save(update_fields=["evidence_json", "updated_at"])
    endpoint = f"/api/v1/normas/{source_norma.pk}/relations/?include_pending=true"
    client = Client()

    assert client.get(endpoint).status_code == 403
    reviewer = get_user_model().objects.create_user(
        username="candidate-evidence-reviewer",
        password="qa-password",
        is_staff=True,
    )
    reviewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao")
    )
    client.force_login(reviewer)
    assert client.get(endpoint).status_code == 403
    reviewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="legislation", codename="view_documentonormativo")
    )
    assert client.get(endpoint).status_code == 403
    reviewer.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="legislation",
            codename="review_eventonormativocandidato",
        )
    )

    public_graph = client.get(endpoint.replace("include_pending=true", "include_pending=false"))
    response = client.get(endpoint)

    assert public_graph.status_code == 200
    assert all("[QA] trecho candidato não revisado" not in str(edge) for edge in public_graph.json()["edges"])
    assert response.status_code == 200
    edge = next(item for item in response.json()["edges"] if item["id"].startswith(f"event:{event.pk}:"))
    assert edge["review_status"] == "pending"
    source_node = next(item for item in response.json()["nodes"] if item["id"] == f"norma:{source_norma.pk}")
    assert source_node["url"] == f"/normas/documentos/{document.public_id}/"
    assert edge["evidence"] == {
        "quote": "[QA] trecho candidato não revisado",
        "document_id": str(document.public_id),
        "page": 2,
    }


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=True)
def test_reviewer_graph_includes_reviewed_extraction_as_nonoperative_candidate_only():
    from src.apps.ingestion.normative_impact import affected_norma_ids

    source_norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="400",
        ano=2026,
        identity_json={"jurisdiction": "BR-RN-NATAL"},
    )
    target_norma = Norma.objects.create(
        tipo="Lei",
        numero="10",
        ano=2000,
        identity_json={"jurisdiction": "BR-RN-NATAL"},
    )
    text = "Art. 4º Ficam revogados:\nI - Lei nº 10/2000.\n"
    document = DocumentoNormativo.objects.create(
        document_key="reviewed-relation-graph-document",
        norma=source_norma,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa:reviewed-relation-graph",
        content_sha256="c" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    source_norma.documento_base = document
    source_norma.save(update_fields=["documento_base", "updated_at"])
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="graph-candidate-v1",
        policy_fingerprint="d" * 64,
        text_version="legal-text-v1",
        raw_text=text,
        legal_text=text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(text), "page": 1}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    persist_document_relation_candidates(extraction)
    candidate = extraction.eventos_normativos_candidatos.get()
    reviewer = get_user_model().objects.create_user(
        username="relation-graph-reviewer", is_staff=True
    )
    reviewer.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="legislation",
            codename__in=(
                "view_documentonormativo",
                "review_eventonormativocandidato",
                "view_eventoalteracao",
            ),
        )
    )
    review_document_relation_candidate(
        candidate_id=candidate.pk,
        actor=reviewer,
        decision=RevisaoEventoNormativoCandidato.Decision.CONFIRM,
        reason="Conferi que o texto expresso cita essa identidade normativa.",
        expected_fingerprint=candidate.fingerprint,
        target_norma_id=target_norma.pk,
    )

    public_graph = build_normative_graph(source_norma, include_pending=False)
    reviewer_graph = build_normative_graph(source_norma, include_pending=True)
    client = Client()
    client.force_login(reviewer)
    api_graph = client.get(f"/api/v1/normas/{source_norma.pk}/relations/?include_pending=true")

    assert public_graph["edges"] == []
    candidate_edges = [edge for edge in reviewer_graph["edges"] if edge["id"].startswith("document-candidate:")]
    assert len(candidate_edges) == 1
    edge = candidate_edges[0]
    assert edge["review_status"] == "candidate_confirmed"
    assert edge["effective_status"] == "not_assessed"
    assert edge["resolution"] == "resolved_candidate"
    assert edge["evidence"]["document_id"] == str(document.public_id)
    # Confirming the literal extraction and exact target identity is still not
    # a legal-effect decision: candidate edges must not enter impact traversal.
    assert affected_norma_ids(source_norma.pk) == [source_norma.pk]
    assert api_graph.status_code == 200
    assert any(item["id"].startswith("document-candidate:") for item in api_graph.json()["edges"])


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_GRAPH_ENABLED=True)
def test_unlinked_pending_document_has_reviewer_only_candidate_graph():
    text = "Art. 260. Ficam revogados:\nI - Lei nº 55/2004.\n"
    document = DocumentoNormativo.objects.create(
        document_key="e" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa:unlinked-candidate-graph",
        original_filename="lc258-2024-candidato.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256="f" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "jurisdiction": "BR-RN-NATAL",
                "type": "Lei Complementar",
                "number": "258",
                "year": "2024",
            }
        },
    )
    target_document = DocumentoNormativo.objects.create(
        document_key="target-pending-law-55-2004",
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="qa:target-law-55-2004",
        original_filename="lei-55-2004.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        content_sha256="a" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "jurisdiction": "BR-RN-NATAL",
                "type": "Lei",
                "number": "55",
                "year": "2004",
            }
        },
    )
    conflicting_type_document = DocumentoNormativo.objects.create(
        document_key="target-pending-lc-55-2004",
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa:target-lc-55-2004-conflicting-type",
        original_filename="lei-complementar-55-2004.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        content_sha256="b" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "jurisdiction": "BR-RN-NATAL",
                "type": "Lei Complementar",
                "number": "55",
                "year": "2004",
            }
        },
    )
    synthetic_target_document = DocumentoNormativo.objects.create(
        document_key="synthetic-target-law-55-2004",
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa:synthetic-target-law-55-2004",
        original_filename="synthetic-law-55-2004.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        content_sha256="d" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "synthetic_fixture": True,
            "identity_candidate": {
                "jurisdiction": "BR-RN-NATAL",
                "type": "Lei",
                "number": "55",
                "year": "2004",
            },
        },
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="unlinked-candidate-graph-v1",
        policy_fingerprint="1" * 64,
        text_version="legal-text-v1",
        raw_text=text,
        legal_text=text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    persist_document_relation_candidates(extraction)
    candidate = extraction.eventos_normativos_candidatos.get()
    endpoint = f"/api/v1/documentos/{document.public_id}/relations/"

    client = Client()
    assert client.get(endpoint).status_code == 403
    reviewer = get_user_model().objects.create_user(
        username="unlinked-candidate-graph-reviewer", is_staff=True
    )
    reviewer.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="legislation",
            codename__in=(
                "view_documentonormativo",
                "review_eventonormativocandidato",
                "view_eventoalteracao",
            ),
        )
    )
    client.force_login(reviewer)
    response = client.get(endpoint)
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_document"]["label"] == "Lei Complementar 258 2024"
    assert payload["root_id"] == f"candidate-document:{document.public_id}"
    assert payload["filters"]["include_pending"] is True
    assert len(payload["edges"]) == 1
    edge = payload["edges"][0]
    assert edge["action"] == "REVOGA"
    assert edge["review_status"] == "candidate_pending"
    assert edge["effective_status"] == "not_assessed"
    assert edge["resolution"] == "unresolved_candidate"
    assert edge["evidence"]["quote"] == "I - Lei nº 55/2004.\n"
    target_leads = edge["evidence"]["target_document_candidates"]
    assert synthetic_target_document.public_id not in {
        item["url"].rsplit("/", 2)[-2] for item in target_leads
    }
    assert target_leads == [
        {
            "url": f"/normas/documentos/{target_document.public_id}/",
            "filename": "lei-55-2004.pdf",
            "source": "SAPL",
            "review_status": "Pendente",
            "identity_type": "lei",
            "type_matches": True,
        },
        {
            "url": f"/normas/documentos/{conflicting_type_document.public_id}/",
            "filename": "lei-complementar-55-2004.pdf",
            "source": "Acervo local",
            "review_status": "Pendente",
            "identity_type": "lei_complementar",
            "type_matches": False,
        },
    ]
    assert client.get(endpoint + "?actions=NOT-A-RELATION").status_code == 400

    explore = client.get(
        f"/explorar/?escopo=candidatas&documento={document.public_id}"
    )
    assert explore.status_code == 200
    assert b"PDF selecionado para revis\xc3\xa3o" in explore.content
    assert b"Rela\xc3\xa7\xc3\xb5es mencionadas neste PDF" in explore.content
    assert f"/api/v1/documentos/{document.public_id}/relations/".encode() in explore.content

    graph = build_candidate_document_graph(document)
    assert graph["edges"] == payload["edges"]

    review_document_relation_candidate(
        candidate_id=candidate.pk,
        actor=reviewer,
        decision=RevisaoEventoNormativoCandidato.Decision.CONFIRM,
        reason="O trecho foi conferido; a espécie do alvo permanece conflitante.",
        expected_fingerprint=candidate.fingerprint,
        target_norma_id=None,
    )
    confirmed_text_payload = client.get(endpoint).json()
    confirmed_text_edge = confirmed_text_payload["edges"][0]
    assert confirmed_text_edge["review_status"] == "candidate_text_confirmed_unresolved"
    assert confirmed_text_edge["resolution"] == "unresolved_candidate"
    assert build_candidate_document_graph(document)["edges"][0]["review_status"] == (
        "candidate_text_confirmed_unresolved"
    )


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
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
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
    assert payload["corpus_coverage"]["coverage_status"] == "unknown"
    assert payload["corpus_coverage"]["checked_until"] is None
    assert payload["document"]["local_evidence_url"].startswith("/normas/documentos/")
    assert payload["document"]["local_pdf_url"] is None
    assert Norma.objects.get(pk=pk).normative_snapshots.count() == before
    assert client.get(f"/api/v1/normas/{pk}/version/").status_code == 400
    assert client.get(f"/api/v1/normas/{pk}/version/?as_of=not-a-date").status_code == 400
    assert client.post(f"/api/v1/normas/{pk}/version/?as_of=2021-02-27").status_code == 405
