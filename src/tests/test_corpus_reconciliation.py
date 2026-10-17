"""Target-arrival reconciliation remains idempotent and non-operative until review."""

import pytest

from src.apps.ingestion.normative_impact import (
    claim_normative_work_item,
    fail_normative_stage,
    finish_normative_stage,
    safe_target_identity_revision,
)
from src.apps.ingestion.reconcile_corpus import (
    enqueue_target_reconciliation,
    reconcile_new_normative_targets_task,
)
from src.apps.legislation.event_review import event_review_status
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.operations.models import NormativeWorkItem
from src.processing.document_metadata import build_normative_identity
from src.processing.event_revision import event_revision_identity
from src.processing.target_reconciliation import (
    inspect_event_target_resolution,
    reconcile_unresolved_event_targets,
    resolve_event_target,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _norma(tipo, numero, ano):
    return Norma.objects.create(
        tipo=tipo,
        numero=numero,
        ano=ano,
        texto_original=f"Art. 1º Norma sintética QA {tipo} {numero}/{ano}.",
    )


def _late_reference_event(action="REFERENCIA", source_number="8801"):
    source_norma = _norma("Lei", source_number, 2025)
    statement = {
        "REFERENCIA": "Faz referência expressa à Lei nº 8206/2026.",
        "ALTERA": "Altera a Lei nº 8206/2026.",
        "REVOGA": "Fica revogada a Lei nº 8206/2026.",
    }.get(action, "Faz referência expressa à Lei nº 8206/2026.")
    device = Dispositivo.objects.create(
        norma=source_norma,
        tipo="artigo",
        numero="1º",
        texto=statement,
        ordem=1,
        structural_key=f"qa-source-{source_number}-art-1",
        revision_fingerprint="a" * 64,
    )
    evidence = {"quote": device.texto, "start_offset": 0, "end_offset": len(device.texto)}
    fingerprint, provenance = event_revision_identity(
        source_identity=device.structural_key,
        source_revision=device.revision_fingerprint,
        action=action,
        target_text="Lei nº 8206/2026",
        reference_type="lei",
        reference_number="8206/2026",
        target_norma_id=None,
        occurrence=0,
        evidence=evidence,
    )
    return EventoAlteracao.objects.create(
        dispositivo_fonte=device,
        acao=action,
        target_text="Lei nº 8206/2026",
        referencia_tipo="lei",
        referencia_numero="8206/2026",
        evidence_json=evidence,
        provenance_json=provenance,
        revision_fingerprint=fingerprint,
        target_reference_json={"schema_version": 1, "resolution_status": "not_found_in_corpus"},
    )


def test_late_target_resolution_updates_provenance_but_never_validates_relation():
    event = _late_reference_event("REFERENCIA")
    before_fingerprint = event.revision_fingerprint
    assert resolve_event_target(event) is False
    event.refresh_from_db()
    assert event.target_reference_json["resolution_status"] == "not_found_in_corpus"
    target = _norma("Lei", "8206", 2026)

    stats = reconcile_unresolved_event_targets(target_norma_ids=[target.pk])
    assert stats["resolved"] == 1
    event.refresh_from_db()

    assert event.norma_alvo_id == target.pk
    assert event.acao == "REFERENCIA"
    assert event.validado is False
    assert event.revision_fingerprint != before_fingerprint
    assert event.provenance_json["target_norma_id"] == target.pk
    assert event.target_reference_json["resolution_status"] == "resolved_unreviewed"
    assert event_review_status(event) == "pending"

    fingerprint = event.revision_fingerprint
    assert resolve_event_target(event, target_norma_ids=[target.pk]) is True
    event.refresh_from_db()
    assert event.revision_fingerprint == fingerprint
    assert event.validado is False


def test_reconciliation_dry_run_reports_late_target_without_mutating_event():
    event = _late_reference_event("ALTERA")
    target = _norma("Lei", "8206", 2026)
    original_reference = dict(event.target_reference_json)
    original_fingerprint = event.revision_fingerprint

    decision = inspect_event_target_resolution(event, target_norma_ids=[target.pk])
    stats = reconcile_unresolved_event_targets(
        target_norma_ids=[target.pk],
        dry_run=True,
        return_cursor=True,
    )

    event.refresh_from_db()
    assert decision == {
        "status": "resolved_unreviewed",
        "target_norma_id": target.pk,
        "identity_key": target.identity_key or None,
        "match_method": "unique_legacy_type_number_year",
    }
    assert stats["dry_run"] is True
    assert stats["inspected"] == 1
    assert stats["resolved"] == 1
    assert stats["resolution_status_counts"] == {"resolved_unreviewed": 1}
    assert event.norma_alvo_id is None
    assert event.target_reference_json == original_reference
    assert event.revision_fingerprint == original_fingerprint


def test_reconciliation_dry_run_diagnostics_explain_without_emitting_raw_target_text():
    event = _late_reference_event("ALTERA")
    source_norma = event.dispositivo_fonte.norma
    source_norma.identity_json = {"synthetic_fixture": True}
    source_norma.save(update_fields=["identity_json"])
    target = _norma("Lei", "8206", 2026)

    report = reconcile_unresolved_event_targets(
        target_norma_ids=[target.pk],
        dry_run=True,
        return_cursor=True,
        include_diagnostics=True,
    )

    assert report["diagnostics"] == [
        {
            "synthetic_fixture": True,
            "source_norma": {"type": "Lei", "number": "8801", "year": 2025},
            "source_device": {"type": "artigo", "number": "1º"},
            "action": "ALTERA",
            "reference_count": 1,
            "parsed_reference": {
                "type": "lei",
                "number": "8206",
                "year": 2026,
                "jurisdiction": "unknown",
            },
            "status": "resolved_unreviewed",
        }
    ]
    assert "Faz referência expressa" not in str(report["diagnostics"])
    assert event.target_text not in str(report["diagnostics"])
    event.refresh_from_db()
    assert event.norma_alvo_id is None
    assert event.target_reference_json["resolution_status"] == "not_found_in_corpus"


def test_late_repeal_target_is_linked_as_unreviewed_candidate_only():
    event = _late_reference_event("REVOGA")

    assert resolve_event_target(event) is False
    target = _norma("Lei", "8206", 2026)
    stats = reconcile_unresolved_event_targets(target_norma_ids=[target.pk])
    event.refresh_from_db()

    assert stats["resolved"] == 1
    assert event.norma_alvo_id == target.pk
    assert event.acao == "REVOGA"
    assert event.validado is False
    assert event.target_reference_json["resolution_status"] == "resolved_unreviewed"
    assert event_review_status(event) == "pending"


def test_ambiguous_identity_stays_unlinked_and_requires_human_review():
    event = _late_reference_event("ALTERA")
    first = _norma("Lei", "8206", 2026)
    second = _norma("Lei Ordinária", "8206", 2026)

    assert resolve_event_target(event, target_norma_ids=[first.pk, second.pk]) is False
    event.refresh_from_db()
    assert event.norma_alvo_id is None
    assert event.validado is False
    assert event.target_reference_json["resolution_status"] == "ambiguous_multiple_candidates"


def test_new_target_queue_is_bounded_idempotent_and_finishes_only_reconcile():
    from src.apps.ingestion.normative_tasks import _execute_normative_stage

    target = _norma("Lei", "8206", 2026)
    event = _late_reference_event("REFERENCIA")

    first = reconcile_new_normative_targets_task.apply(
        args=[[target.pk, target.pk]], throw=True
    ).get()
    second = enqueue_target_reconciliation([target.pk])
    assert first["requested"] == 1
    assert first["created"] == 1
    assert second["created"] == 0
    item = NormativeWorkItem.objects.get(pk=first["queued"][0]["item_id"])
    assert item.stage == NormativeWorkItem.Stage.RECONCILE
    assert item.payload["reconciliation_only"] is True

    leased, token = claim_normative_work_item(item.pk)
    result = _execute_normative_stage(leased, target)
    assert result["resolved"] == 1
    completed = finish_normative_stage(leased.pk, token, result=result)
    assert completed.status == NormativeWorkItem.Status.COMPLETED
    assert completed.stage == NormativeWorkItem.Stage.RECONCILE
    event.refresh_from_db()
    assert event.norma_alvo_id == target.pk
    assert event.acao == "REFERENCIA"
    assert event.validado is False


def test_identity_only_target_is_queued_and_worker_accepts_its_fingerprint():
    from src.apps.ingestion.normative_tasks import _current_norma, _execute_normative_stage

    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei",
        series="municipal_lo",
        number="8206",
        year=2026,
    )
    target = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        identity_key=identity.identity_key,
        identity_json=identity.identity_json,
        texto_original="",
        texto_consolidado="",
    )
    event = _late_reference_event("REFERENCIA")

    queued = enqueue_target_reconciliation([target.pk])
    item = NormativeWorkItem.objects.get(pk=queued["queued"][0]["item_id"])
    assert queued["created"] == 1
    assert item.source_revision == safe_target_identity_revision(target)
    assert _current_norma(item).pk == target.pk

    leased, token = claim_normative_work_item(item.pk)
    result = _execute_normative_stage(leased, target)
    completed = finish_normative_stage(leased.pk, token, result=result)
    event.refresh_from_db()
    assert completed.status == NormativeWorkItem.Status.COMPLETED
    assert event.norma_alvo_id == target.pk
    assert event.acao == "REFERENCIA"
    assert event.validado is False
    assert event.target_reference_json["resolution_status"] == "resolved_unreviewed"


def test_target_queue_rejects_unbounded_or_unknown_ids():
    with pytest.raises(ValueError, match="1 a 10"):
        enqueue_target_reconciliation(list(range(1, 12)))
    with pytest.raises(ValueError, match="não correspondem"):
        enqueue_target_reconciliation([999999999])


def test_reconciliation_exception_preserves_cursor_and_retries_idempotently(monkeypatch):
    from src.apps.ingestion import normative_tasks
    from src.processing import target_reconciliation

    target = _norma("Lei", "8206", 2026)
    first_event = _late_reference_event("REFERENCIA", "8801")
    second_event = _late_reference_event("REFERENCIA", "8802")
    queue = enqueue_target_reconciliation([target.pk])
    item = NormativeWorkItem.objects.get(pk=queue["queued"][0]["item_id"])
    leased, token = claim_normative_work_item(item.pk)
    original_resolver = target_reconciliation.resolve_event_target
    calls = []

    def fail_after_one_success(event, **kwargs):
        calls.append(event.pk)
        if len(calls) == 2:
            raise RuntimeError("temporary reconciliation failure")
        return original_resolver(event, **kwargs)

    monkeypatch.setattr(target_reconciliation, "resolve_event_target", fail_after_one_success)
    with pytest.raises(RuntimeError, match="temporary reconciliation failure"):
        normative_tasks._execute_normative_stage(leased, target)

    retried = fail_normative_stage(item.pk, token, "temporary reconciliation failure")
    assert retried.status == NormativeWorkItem.Status.PENDING
    assert "stage_progress" not in retried.result
    first_event.refresh_from_db()
    second_event.refresh_from_db()
    assert first_event.norma_alvo_id == target.pk
    assert second_event.norma_alvo_id is None
    assert first_event.acao == second_event.acao == "REFERENCIA"
    assert first_event.validado is False
    assert second_event.validado is False

    monkeypatch.setattr(target_reconciliation, "resolve_event_target", original_resolver)
    retry_leased, retry_token = claim_normative_work_item(retried.pk)
    result = normative_tasks._execute_normative_stage(retry_leased, target)
    completed = finish_normative_stage(retry_leased.pk, retry_token, result=result)
    first_event.refresh_from_db()
    second_event.refresh_from_db()
    assert completed.status == NormativeWorkItem.Status.COMPLETED
    assert result["resolved"] == 1
    assert first_event.norma_alvo_id == second_event.norma_alvo_id == target.pk
    assert first_event.validado is False
    assert second_event.validado is False
