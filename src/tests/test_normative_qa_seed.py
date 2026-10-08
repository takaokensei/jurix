from __future__ import annotations

import json
from datetime import date

import pytest
from django.contrib.auth.models import User

from src.apps.ingestion.management.commands.seed_normative_qa import _qa_reviewer, seed_fixture
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    ExtracaoDocumento,
    NormativeSnapshot,
)
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.processing.document_segmentation import segment_document_extraction
from src.processing.normative_projection import project_norma_as_of


@pytest.mark.django_db(transaction=True)
def test_seed_normative_qa_is_idempotent_synthetic_and_has_no_credentials(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    output_one = root / "fixture-map.json"
    output_two = root / "fixture-map-repeat.json"
    first = seed_fixture(output_one)
    collection_norma = Norma.objects.get(pk=first["collection_fixture"]["norma_id"])
    collection_norma.status = Norma.Status.SEGMENTED
    collection_norma.save(update_fields=["status", "updated_at"])
    second = seed_fixture(output_two)
    assert first["dataset"] == "synthetic_not_gold"
    assert first["scenarios"] == second["scenarios"]
    assert first["temporal_scenarios"] == second["temporal_scenarios"]
    assert first["edge_case_fixtures"] == second["edge_case_fixtures"]
    edge_cases = first["normative_edge_cases"]
    assert len(edge_cases) >= 12
    assert all(case["synthetic_only"] and case["human_review_required"] for case in edge_cases)
    assert {case["case_id"] for case in edge_cases} >= {
        "lc_reference", "partial_revocation", "add_article_5_a", "future_norm", "conflicting_candidate"
    }
    assert first["credentials_included"] is False
    assert first["collection_fixture"]["synthetic_only"] is True
    assert first["collection_fixture"]["not_legal_gold"] is True
    collection_norma = Norma.objects.get(pk=first["collection_fixture"]["norma_id"])
    assert collection_norma.status == Norma.Status.CONSOLIDATED
    assert "NÃO É LEGISLAÇÃO REAL" in collection_norma.ementa
    assert "password" not in json.loads(output_one.read_text(encoding="utf-8"))
    assert Norma.objects.filter(ano=2090, numero="9901").count() == 2
    edge = first["edge_case_fixtures"]
    assert edge["synthetic_only"] and edge["no_real_corpus_mutation"]
    assert edge["all_events_pending"] is True
    assert edge["norma_ids"]["partial_target"] == Norma.objects.get(numero="9911", ano=2090).pk
    assert edge["norma_ids"]["total_target"] == Norma.objects.get(numero="9912", ano=2090).pk
    work_item_fixture = edge["norma_ids"]["work_item_review"]
    assert work_item_fixture["synthetic_only"] and work_item_fixture["not_legal_gold"]
    work_item_document = DocumentoNormativo.objects.get(public_id=work_item_fixture["document_id"])
    work_item_extraction = ExtracaoDocumento.objects.get(pk=work_item_fixture["extraction_id"])
    assert work_item_document.norma.identity_json["synthetic_fixture"] is True
    from src.apps.legislation.norma_queries import consolidated_normas_for_product
    assert not consolidated_normas_for_product().filter(pk=work_item_document.norma_id).exists()
    frozen_devices = list(work_item_extraction.dispositivos_documentais.all())
    assert frozen_devices
    assert all(
        device.start_offset is not None
        and device.end_offset is not None
        and work_item_extraction.legal_text[device.start_offset:device.end_offset] == device.texto
        for device in frozen_devices
    )
    assert segment_document_extraction(work_item_extraction.pk).unchanged is True
    assert work_item_document.accepted_extraction_id == work_item_extraction.pk
    assert edge["norma_ids"]["missing_original"] == edge["missing_original"]["norma_id"]
    assert edge["norma_ids"]["future_norm"] == edge["future_norm"]["norma_id"]
    assert set(edge["events"]) >= {
        "partial_revocation", "total_revocation", "add_article_5_a", "generic_revocation",
        "external_federal", "veto", "multi_action_alter", "multi_action_revoke", "admin_review_smoke",
    }
    assert DocumentoNormativo.objects.filter(source_ref__startswith="jurix-synthetic-qa:").count() == 18
    assert ExtracaoDocumento.objects.filter(documento__source_ref__startswith="jurix-synthetic-qa:").count() == 16
    runtime_fixture = edge["norma_ids"]["worker_runtime"]
    assert runtime_fixture["synthetic_only"] and runtime_fixture["not_legal_gold"]
    assert EventoAlteracao.objects.filter(pk__in=edge["events"].values()).count() == 9
    partial = EventoAlteracao.objects.get(pk=edge["events"]["partial_revocation"])
    assert partial.acao == "REVOGA" and partial.dispositivo_alvo.tipo == "inciso"
    assert partial.dispositivo_alvo.numero == "II" and not partial.validado
    admin_smoke = EventoAlteracao.objects.get(pk=edge["events"]["admin_review_smoke"])
    assert admin_smoke.acao == "ALTERA" and not admin_smoke.validado
    assert admin_smoke.target_reference_json["admin_smoke"] is True
    assert admin_smoke.dispositivo_alvo_id is None
    added = EventoAlteracao.objects.get(pk=edge["events"]["add_article_5_a"])
    assert added.dispositivo_alvo.numero == "5º-A" and not added.validado
    federal = EventoAlteracao.objects.get(pk=edge["events"]["external_federal"])
    assert federal.norma_alvo_id is None
    assert federal.target_reference_json["external_identity_key"] == "BR:federal:lei:4320:1964"
    veto = EventoAlteracao.objects.get(pk=edge["events"]["veto"])
    assert veto.norma_alvo_id is None and not veto.validado
    multi_ids = [edge["events"]["multi_action_alter"], edge["events"]["multi_action_revoke"]]
    multi_events = list(EventoAlteracao.objects.filter(pk__in=multi_ids).order_by("acao"))
    assert {event.acao for event in multi_events} == {"ALTERA", "REVOGA"}
    assert len({event.target_reference_json["multi_action_group"] for event in multi_events}) == 1
    references = first["temporal_scenarios"]["lc198_2021"]
    lc55 = Norma.objects.get(pk=first["temporal_scenarios"]["lc55_2004"]["norma_id"])
    assert lc55.data_publicacao.isoformat() == "2004-01-01"
    assert lc55.data_norma.isoformat() == "2004-01-01"
    relation_events = list(
        EventoAlteracao.objects.filter(pk__in=references["reference_event_ids"])
        .select_related("dispositivo_fonte__norma__documento_base", "dispositivo_alvo")
        .order_by("referencia_numero")
    )
    assert len(relation_events) == 2
    assert {event.dispositivo_alvo.numero for event in relation_events} == {"21º", "44º"}
    assert all(event.dispositivo_fonte.norma.documento_base_id for event in relation_events)
    assert all(event.dispositivo_alvo.norma.documento_base_id for event in relation_events)
    assert all(event.target_reference_json["synthetic"] is True for event in relation_events)
    partial_projection = first["temporal_scenarios"]["partial_projection"]
    partial_event = EventoAlteracao.objects.get(pk=partial_projection["pending_event_id"])
    assert partial_projection["expected_projection"] == "partial"
    assert partial_event.norma_alvo_id == partial_projection["norma_id"]
    assert partial_event.review_revision_id is None and not partial_event.validado
    assert edge["missing_original"]["documento_base_id"] is None
    assert edge["missing_original"]["expected_projection"] == "not_reconstructable"
    assert edge["future_norm"]["publication_on"] == "2095-01-01"
    assert DocumentoNormativo.objects.filter(
        public_id__in=edge["versions"].values(),
        role__in=[DocumentoNormativo.Role.REPUBLICATION, DocumentoNormativo.Role.RECTIFICATION],
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    ).count() == 2
    assert Dispositivo.objects.filter(
        norma_id=added.norma_alvo_id, numero="5º-A",
    ).exists()
    temporal = first["temporal_scenarios"]
    assert temporal["synthetic_only"] is True
    assert temporal["snapshots"]["d_minus_1"]["content_sha256"] != temporal["snapshots"]["d"]["content_sha256"]
    assert temporal["snapshots"]["d_minus_1"]["article_5_text"] == "Art. 5º O prazo é de dez dias."
    assert temporal["snapshots"]["d"]["article_5_text"] == "O prazo é de vinte dias."
    assert temporal["snapshots"]["d_plus_1"]["content_sha256"] == temporal["snapshots"]["d"]["content_sha256"]
    assert NormativeSnapshot.objects.filter(norma_id=temporal["norma_a"]["norma_id"]).count() == 3
    conflict_fixture = temporal["same_date_conflict"]
    assert conflict_fixture["synthetic_only"] is True
    assert conflict_fixture["expected_projection"] == "partial"
    conflict_norma = Norma.objects.get(pk=conflict_fixture["norma_id"])
    conflicting_events = list(EventoAlteracao.objects.filter(pk__in=conflict_fixture["event_ids"].values()))
    assert {event.acao for event in conflicting_events} == {"ALTERA", "REVOGA"}
    assert all(event.validado and event.effective_date_status == "confirmed" for event in conflicting_events)
    conflict_projection = project_norma_as_of(conflict_norma, date.fromisoformat(conflict_fixture["as_of"]))
    assert conflict_projection.status == "partial"
    assert conflict_projection.devices[0].text == conflict_fixture["expected_text"]
    assert conflict_projection.coverage["applied_event_ids"] == []
    assert set(conflict_projection.coverage["pending_event_ids"]) == set(conflict_fixture["event_ids"].values())
    assert DocumentoNormativo.objects.filter(norma__isnull=True).count() >= 3
    conflict = DocumentoNormativo.objects.get(source_ref__endswith=":conflito:v1")
    assert conflict.conflicts_json
    reviewer = User.objects.get(username="jurix-qa-reviewer")
    assert reviewer.is_staff and reviewer.is_superuser and not reviewer.has_usable_password()


@pytest.mark.django_db(transaction=True)
def test_seed_refuses_output_outside_qa_and_overwrite(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    with pytest.raises(Exception, match="dentro da raiz QA"):
        seed_fixture(tmp_path / "outside.json")


@pytest.mark.django_db(transaction=True)
def test_seed_rejects_missing_qa_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    with pytest.raises(Exception, match="JURIX_QA_ONLY=1"):
        seed_fixture(tmp_path / "fixture.json")


@pytest.mark.django_db(transaction=True)
def test_qa_reviewer_password_is_opt_in_and_resets_to_unusable(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    temporary_password = "qa-reviewer-only-" + "x" * 32
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", temporary_password)

    seed_fixture(root / "seed-with-reviewer-login.json")
    reviewer = User.objects.get(username="jurix-qa-reviewer")
    assert reviewer.check_password(temporary_password)
    assert "password" not in json.loads((root / "seed-with-reviewer-login.json").read_text(encoding="utf-8"))

    monkeypatch.delenv("JURIX_QA_REVIEWER_PASSWORD")
    _qa_reviewer()
    reviewer.refresh_from_db()
    assert not reviewer.has_usable_password()
