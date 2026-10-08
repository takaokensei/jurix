import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from src.apps.ingestion.normative_impact import (
    claim_normative_work_item,
    defer_normative_stage_for_review,
    enqueue_normative_work,
    fail_normative_stage,
    finish_normative_stage,
    resolve_normative_review,
)
from src.apps.ingestion.normative_tasks import (
    _execute_normative_stage,
    dispatch_normative_work_batch_task,
    process_normative_work_item_task,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma
from src.apps.operations.models import NormativeWorkItem

pytestmark = pytest.mark.django_db


def _queued():
    return enqueue_normative_work(
        source_kind="norma", source_id="42", source_revision="a" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )[0]


def test_queue_enqueue_is_idempotent_and_rejects_over_limit(settings):
    settings.NORMATIVE_WORK_QUEUE_MAX_PENDING = 1
    first, created = _queued(), True
    duplicate, duplicate_created = enqueue_normative_work(
        source_kind="norma", source_id="42", source_revision="a" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )
    assert first.pk == duplicate.pk and created and not duplicate_created
    with pytest.raises(RuntimeError, match="pending limit"):
        enqueue_normative_work(
            source_kind="norma", source_id="43", source_revision="b" * 64,
            stage=NormativeWorkItem.Stage.CHANGED,
        )


def test_expired_lease_can_be_reclaimed_but_stale_token_cannot_advance():
    item = _queued()
    _, token = claim_normative_work_item(item.pk, lease_seconds=30)
    item.lease_until = timezone.now() - timedelta(seconds=1)
    item.save(update_fields=["lease_until"])
    _, new_token = claim_normative_work_item(item.pk, lease_seconds=30)
    with pytest.raises(RuntimeError, match="Stale or foreign"):
        finish_normative_stage(item.pk, token, result={"ok": True})
    advanced = finish_normative_stage(item.pk, new_token, result={"ok": True})
    assert advanced.stage == NormativeWorkItem.Stage.EXTRACTION
    assert advanced.status == NormativeWorkItem.Status.PENDING
    assert advanced.attempts == 0


def test_review_is_required_and_records_staff_decision():
    reviewer = get_user_model().objects.create_user(username="norm-reviewer", is_staff=True)
    item = _queued()
    item.stage = NormativeWorkItem.Stage.REVIEW
    item.status = NormativeWorkItem.Status.AWAITING_REVIEW
    item.save(update_fields=["stage", "status"])

    with pytest.raises(PermissionError, match="Active staff"):
        resolve_normative_review(item.pk, actor=get_user_model()(), approved=True, reason="ok")
    resolved = resolve_normative_review(item.pk, actor=reviewer, approved=True, reason="QA revisão")
    assert resolved.status == NormativeWorkItem.Status.PENDING
    assert resolved.stage == NormativeWorkItem.Stage.SEGMENT
    assert resolved.reviewed_by_id == reviewer.pk
    assert resolved.review_reason == "QA revisão"


def test_normative_checkpoint_admin_requires_permission_and_records_decision(monkeypatch):
    from django.contrib.auth.models import Permission
    from django.test import Client
    from django.urls import reverse

    item = _queued()
    item.stage = NormativeWorkItem.Stage.REVIEW
    item.status = NormativeWorkItem.Status.AWAITING_REVIEW
    item.save(update_fields=["stage", "status"])
    reviewer = get_user_model().objects.create_user(
        username="checkpoint-reviewer", is_staff=True, is_active=True
    )
    url = reverse("admin:operations_normativeworkitem_review", args=[item.pk])
    guest_client = Client()
    assert guest_client.get(url).status_code == 302
    unprivileged = get_user_model().objects.create_user(
        username="checkpoint-unprivileged", is_staff=True, is_active=True
    )
    unprivileged_client = Client()
    unprivileged_client.force_login(unprivileged)
    assert unprivileged_client.get(url).status_code == 403
    permission = Permission.objects.get(
        content_type__app_label="operations", codename="change_normativeworkitem"
    )
    reviewer.user_permissions.add(permission)
    client = Client()
    client.force_login(reviewer)

    response = client.get(url)
    assert response.status_code == 200
    assert b"n\xc3\xa3o substitui a revis\xc3\xa3o jur\xc3\xaddica" in response.content
    queue_response = client.get(reverse("admin:operations_normativeworkitem_changelist"))
    assert queue_response.status_code == 200
    assert url.encode() in queue_response.content
    assert client.post(url, {"decision": "approve", "reason": "  "}).status_code == 200
    item.refresh_from_db()
    assert item.status == NormativeWorkItem.Status.AWAITING_REVIEW

    scheduled = []
    monkeypatch.setattr(
        process_normative_work_item_task,
        "apply_async",
        lambda **kwargs: scheduled.append(kwargs),
    )
    response = client.post(
        url,
        {"decision": "approve", "reason": "Checkpoint QA conferido pelo operador."},
    )
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == NormativeWorkItem.Status.PENDING
    assert item.stage == NormativeWorkItem.Stage.SEGMENT
    assert item.reviewed_by_id == reviewer.pk
    assert item.review_reason == "Checkpoint QA conferido pelo operador."
    assert scheduled == [{"args": [item.pk], "queue": "normative_qa"}]


def test_normative_checkpoint_admin_rejects_without_scheduling():
    from django.contrib.auth.models import Permission
    from django.test import Client
    from django.urls import reverse

    item = _queued()
    item.stage = NormativeWorkItem.Stage.REVIEW
    item.status = NormativeWorkItem.Status.AWAITING_REVIEW
    item.save(update_fields=["stage", "status"])
    reviewer = get_user_model().objects.create_user(
        username="checkpoint-rejecter", is_staff=True, is_active=True
    )
    reviewer.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="operations", codename="change_normativeworkitem"
        )
    )
    client = Client()
    client.force_login(reviewer)
    response = client.post(
        reverse("admin:operations_normativeworkitem_review", args=[item.pk]),
        {"decision": "reject", "reason": "Fonte insuficiente para prosseguir."},
    )
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == NormativeWorkItem.Status.CANCELLED
    assert item.result["human_review"] == "rejected"
    assert item.review_reason == "Fonte insuficiente para prosseguir."


def test_inline_stage_task_result_is_readable_inside_celery_task_context():
    from celery.result import EagerResult, denied_join_result

    from src.apps.ingestion.normative_tasks import _run_inline_task

    class InlineTask:
        def apply(self, *, args, throw):
            assert args == [37]
            assert throw is True
            return EagerResult("qa-inline-result", {"success": True}, "SUCCESS")

    with denied_join_result():
        assert _run_inline_task(InlineTask(), 37) == {"success": True}


def test_failed_stage_uses_bounded_retry_then_terminal_failure():
    item = _queued()
    item.max_attempts = 1
    item.save(update_fields=["max_attempts"])
    _, token = claim_normative_work_item(item.pk)
    failed = fail_normative_stage(item.pk, token, "falha simulada")
    assert failed.status == NormativeWorkItem.Status.FAILED
    assert failed.last_error == "falha simulada"


def test_claim_at_retry_limit_persists_terminal_failure():
    item = _queued()
    item.attempts = item.max_attempts
    item.save(update_fields=["attempts"])

    with pytest.raises(RuntimeError, match="retry limit"):
        claim_normative_work_item(item.pk)

    item.refresh_from_db()
    assert item.status == NormativeWorkItem.Status.FAILED
    assert item.last_error == "Tentativas máximas atingidas."


def test_review_gate_resumes_same_stage_and_rejection_cancels():
    reviewer = get_user_model().objects.create_user(username="norm-reviewer-gate", is_staff=True)
    item = _queued()
    _, token = claim_normative_work_item(item.pk)
    paused = defer_normative_stage_for_review(
        item.pk, token, reason="fonte precisa de revisão", result={"required_action": "review"}
    )
    assert paused.status == NormativeWorkItem.Status.AWAITING_REVIEW
    assert paused.stage == NormativeWorkItem.Stage.CHANGED
    resumed = resolve_normative_review(
        paused.pk, actor=reviewer, approved=True, reason="Fonte verificada"
    )
    assert resumed.status == NormativeWorkItem.Status.PENDING
    assert resumed.stage == NormativeWorkItem.Stage.CHANGED

    second = enqueue_normative_work(
        source_kind="norma", source_id="43", source_revision="b" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )[0]
    _, second_token = claim_normative_work_item(second.pk)
    defer_normative_stage_for_review(second.pk, second_token, reason="validar fonte")
    rejected = resolve_normative_review(
        second.pk, actor=reviewer, approved=False, reason="hash inconsistente"
    )
    assert rejected.status == NormativeWorkItem.Status.CANCELLED


def test_worker_checkpoints_changed_and_extraction_then_waits_for_review(monkeypatch):
    norma = Norma.objects.create(
        tipo="Lei Ordinária", numero="9001", ano=2020,
        texto_original="Art. 1º Esta norma é uma fixture técnica QA.",
    )
    from src.apps.ingestion.normative_impact import safe_norma_revision

    item, _ = enqueue_normative_work(
        source_kind="norma", source_id=norma.pk,
        source_revision=safe_norma_revision(norma), stage=NormativeWorkItem.Stage.CHANGED,
    )
    scheduled = []
    monkeypatch.setattr(
        process_normative_work_item_task, "apply_async",
        lambda *, args, **kwargs: scheduled.append((args, kwargs)),
    )

    first = process_normative_work_item_task.apply(args=[item.pk], throw=True).get()
    item.refresh_from_db()
    assert first["stage"] == NormativeWorkItem.Stage.EXTRACTION
    assert item.status == NormativeWorkItem.Status.PENDING
    assert norma.texto_original in Norma.objects.get(pk=norma.pk).texto_original
    assert len(scheduled) == 1

    second = process_normative_work_item_task.apply(args=[item.pk], throw=True).get()
    item.refresh_from_db()
    assert second["status"] == NormativeWorkItem.Status.AWAITING_REVIEW
    assert item.stage == NormativeWorkItem.Stage.REVIEW
    assert item.result["text_mutated"] is False
    assert set(item.result["stage_results"]) == {
        NormativeWorkItem.Stage.CHANGED,
        NormativeWorkItem.Stage.EXTRACTION,
    }
    assert Norma.objects.get(pk=norma.pk).texto_original == norma.texto_original


def test_worker_cancels_a_stale_source_without_mutating_it(monkeypatch):
    assert process_normative_work_item_task.acks_late is True
    assert process_normative_work_item_task.reject_on_worker_lost is True
    norma = Norma.objects.create(
        tipo="Lei Ordinária", numero="9002", ano=2020,
        texto_original="Art. 1º Texto original QA.",
    )
    from src.apps.ingestion.normative_impact import safe_norma_revision

    item, _ = enqueue_normative_work(
        source_kind="norma", source_id=norma.pk,
        source_revision=safe_norma_revision(norma), stage=NormativeWorkItem.Stage.CHANGED,
    )
    norma.texto_original = "Art. 1º Texto alterado depois da fila."
    norma.save(update_fields=["texto_original", "updated_at"])
    result = process_normative_work_item_task.apply(args=[item.pk], throw=True).get()
    item.refresh_from_db()
    assert result["status"] == NormativeWorkItem.Status.CANCELLED
    assert item.status == NormativeWorkItem.Status.CANCELLED
    assert Norma.objects.get(pk=norma.pk).texto_original == "Art. 1º Texto alterado depois da fila."


def test_manual_batch_dispatch_never_exceeds_ten(monkeypatch):
    for number in range(12):
        enqueue_normative_work(
            source_kind="norma", source_id=str(100 + number),
            source_revision=f"{number + 1:064x}", stage=NormativeWorkItem.Stage.CHANGED,
        )
    scheduled = []
    monkeypatch.setattr(
        process_normative_work_item_task, "apply_async",
        lambda *, args, **kwargs: scheduled.append((args, kwargs)),
    )
    result = dispatch_normative_work_batch_task.run(max_items=50)
    assert result["dispatched"] == 10
    assert result["batch_limit"] == 10
    assert len(scheduled) == 10


def test_batch_dispatch_includes_only_expired_leases_and_pending_items(monkeypatch):
    pending = _queued()
    expired = enqueue_normative_work(
        source_kind="norma", source_id="201", source_revision="c" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )[0]
    active = enqueue_normative_work(
        source_kind="norma", source_id="202", source_revision="d" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )[0]
    _, expired_token = claim_normative_work_item(expired.pk)
    _, active_token = claim_normative_work_item(active.pk)
    expired.refresh_from_db()
    expired.lease_until = timezone.now() - timedelta(seconds=1)
    expired.save(update_fields=["lease_until"])
    scheduled = []
    monkeypatch.setattr(
        process_normative_work_item_task, "apply_async",
        lambda *, args, **kwargs: scheduled.append((args, kwargs)),
    )

    result = dispatch_normative_work_batch_task.run(max_items=10)
    dispatched_ids = {args[0] for args, _ in scheduled}
    assert dispatched_ids == {pending.pk, expired.pk}
    assert active.pk not in dispatched_ids
    assert result["dispatched"] == 2
    # The live lease remains owned by its original token until its deadline.
    assert NormativeWorkItem.objects.get(pk=active.pk).lease_token
    assert expired_token != active_token


def test_redelivered_task_skips_an_active_lease_or_review_checkpoint():
    leased = _queued()
    claim_normative_work_item(leased.pk)
    duplicate = process_normative_work_item_task.apply(args=[leased.pk], throw=True).get()
    assert duplicate["skipped"] == "not_claimable"
    assert duplicate["status"] == NormativeWorkItem.Status.LEASED

    review = enqueue_normative_work(
        source_kind="norma", source_id="203", source_revision="e" * 64,
        stage=NormativeWorkItem.Stage.CHANGED,
    )[0]
    review.stage = NormativeWorkItem.Stage.REVIEW
    review.status = NormativeWorkItem.Status.AWAITING_REVIEW
    review.save(update_fields=["stage", "status"])
    duplicate_review = process_normative_work_item_task.apply(args=[review.pk], throw=True).get()
    assert duplicate_review["skipped"] == "not_claimable"
    assert duplicate_review["status"] == NormativeWorkItem.Status.AWAITING_REVIEW


def test_segmentation_waits_for_approved_source_then_materializes_exact_extraction(monkeypatch):
    from src.apps.ingestion import normative_tasks

    text = "Art. 1º Texto exato da fonte aprovada.\nArt. 2º Esta Lei entra em vigor na publicação."
    def sha(value):
        return hashlib.sha256(value.encode()).hexdigest()
    norma = Norma.objects.create(tipo="Lei", numero="9003", ano=2020)
    document = DocumentoNormativo.objects.create(
        norma=norma, document_key=sha("doc:9003"),
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref="qa:queue-stage-test", content_sha256=sha("pdf:9003"), size_bytes=10,
        role=DocumentoNormativo.Role.ORIGINAL,
        condition_of_use=DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document, extractor_version="queue-stage-test-v1",
        policy_fingerprint=sha("policy"), text_version="technical_text_v1",
        raw_text=text, legal_text=text, page_count=1,
        metadata_candidates_json={}, quality_json={},
        status=ExtracaoDocumento.Status.COMPLETE, extraction_sha256=sha("extraction"),
    )
    document.accepted_extraction = extraction
    document.review_status = DocumentoNormativo.ReviewStatus.PENDING
    document.save(update_fields=["accepted_extraction", "review_status", "updated_at"])
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    from src.apps.ingestion.normative_impact import safe_norma_revision

    assert safe_norma_revision(norma) == document.content_sha256
    item = NormativeWorkItem(
        source_kind="norma", source_id=str(norma.pk), source_revision=sha("revision"),
        stage=NormativeWorkItem.Stage.SEGMENT,
    )
    segment_calls = []
    monkeypatch.setattr(
        normative_tasks, "segment_document_extraction",
        lambda _id: segment_calls.append(_id) or SimpleNamespace(
            created=2, unchanged=False, diagnostics=()
        ),
    )
    monkeypatch.setattr(
        normative_tasks.segment_text_task, "apply",
        lambda **_kwargs: SimpleNamespace(get=lambda: {"success": True, "dispositivos_created": 2}),
    )

    with pytest.raises(PermissionError, match="approved"):
        _execute_normative_stage(item, norma)
    norma.refresh_from_db()
    assert norma.texto_original == ""
    assert segment_calls == []

    document.review_status = DocumentoNormativo.ReviewStatus.APPROVED
    document.save(update_fields=["review_status", "updated_at"])
    result = _execute_normative_stage(item, norma)
    norma.refresh_from_db()
    assert norma.texto_original == text
    assert result["document_devices_created"] == 2
    assert result["legacy_segmentation"]["success"] is True


@pytest.mark.django_db(transaction=True)
def test_approved_synthetic_pipeline_checkpoints_through_snapshot_and_defers_embedding(
    monkeypatch, tmp_path, settings
):
    """Exercise every worker checkpoint with an explicitly synthetic source only."""
    from src.apps.ingestion import normative_tasks
    from src.apps.ingestion.document_promotion import promotion_fingerprint
    from src.apps.ingestion.normative_tasks import review_normative_work_item_task
    from src.apps.legislation.review_models import RevisaoJuridica
    from src.processing.normative_projection import NormativeSnapshot

    qa_root = tmp_path / "isolated-normative-qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    settings.NORMATIVE_ARCHIVE_ENABLED = True
    text = "Art. 1º Esta fixture sintética autoriza apenas teste técnico.\nArt. 2º Esta Lei entra em vigor na publicação."

    def digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    norma = Norma.objects.create(
        tipo="Lei",
        numero="9903",
        ano=2091,
        data_publicacao=timezone.localdate() - timedelta(days=1),
        identity_json={"synthetic": True, "qa_only": True},
    )
    document = DocumentoNormativo.objects.create(
        norma=norma,
        document_key=digest("worker-pipeline-synthetic-document"),
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref="jurix-synthetic-qa:worker-pipeline-v1",
        original_filename="[SINTÉTICO QA] worker pipeline.pdf",
        content_sha256=digest("synthetic-pdf-bytes"),
        size_bytes=16,
        role=DocumentoNormativo.Role.ORIGINAL,
        condition_of_use=DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
        review_status=DocumentoNormativo.ReviewStatus.APPROVED,
        extraction_status=DocumentoNormativo.ExtractionStatus.EXTRACTED,
        metadata_json={"synthetic": True, "qa_only": True},
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="synthetic-worker-integration-v1",
        policy_fingerprint=digest("synthetic-worker-policy"),
        text_version="synthetic-worker-text-v1",
        raw_text=text,
        legal_text=text,
        page_count=1,
        metadata_candidates_json={"synthetic": True},
        quality_json={"synthetic": True, "not_human_reviewed": True},
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256=digest(text),
    )
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction", "updated_at"])
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    reviewer = get_user_model().objects.create_user(
        username="worker-pipeline-qa-reviewer", is_staff=True
    )
    RevisaoJuridica.objects.create(
        documento=document,
        target_fingerprint=promotion_fingerprint(document),
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="[QA SINTÉTICO] Fixture aprovada somente para exercitar o worker.",
        actor=reviewer,
    )

    from src.apps.ingestion.normative_impact import safe_norma_revision

    item, created = enqueue_normative_work(
        source_kind="norma",
        source_id=str(norma.pk),
        source_revision=safe_norma_revision(norma),
        stage=NormativeWorkItem.Stage.CHANGED,
        payload={"synthetic_fixture": True},
    )
    assert created
    scheduled = []
    monkeypatch.setattr(
        process_normative_work_item_task,
        "apply_async",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    monkeypatch.setattr(
        review_normative_work_item_task,
        "apply_async",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )

    first = process_normative_work_item_task.apply(args=[item.pk], throw=True).get()
    assert first["stage"] == NormativeWorkItem.Stage.EXTRACTION
    extraction_result = process_normative_work_item_task.apply(
        args=[item.pk], throw=True
    ).get()
    assert extraction_result["status"] == NormativeWorkItem.Status.AWAITING_REVIEW
    item.refresh_from_db()
    assert item.stage == NormativeWorkItem.Stage.REVIEW

    reviewed = review_normative_work_item_task.apply(
        args=[item.pk, reviewer.pk, True, "[QA SINTÉTICO] Integração de pipeline; não é revisão jurídica."],
        throw=True,
    ).get()
    assert reviewed["stage"] == NormativeWorkItem.Stage.SEGMENT
    assert reviewed["status"] == NormativeWorkItem.Status.PENDING

    monkeypatch.setattr(
        normative_tasks.extract_entities_task,
        "apply",
        lambda **_kwargs: SimpleNamespace(
            get=lambda: {"success": True, "synthetic_fixture": True, "created": 0}
        ),
    )
    monkeypatch.setattr(
        normative_tasks,
        "reconcile_unresolved_event_targets",
        lambda **_kwargs: {"resolved": 0, "synthetic_fixture": True},
    )
    monkeypatch.setattr(
        normative_tasks,
        "get_cache_service",
        lambda: SimpleNamespace(bump_corpus_version=lambda: 17),
    )

    from src.llm_engine.ollama_service import OllamaService

    monkeypatch.setattr(OllamaService, "check_health", lambda _self: False)

    stages = [
        NormativeWorkItem.Stage.SEGMENT,
        NormativeWorkItem.Stage.EVENT,
        NormativeWorkItem.Stage.RECONCILE,
        NormativeWorkItem.Stage.SNAPSHOT,
        NormativeWorkItem.Stage.INVALIDATE,
        NormativeWorkItem.Stage.EMBEDDING,
    ]
    for stage in stages:
        item.refresh_from_db()
        assert item.stage == stage
        result = process_normative_work_item_task.apply(args=[item.pk], throw=True).get()
        item.refresh_from_db()
        if stage != NormativeWorkItem.Stage.EMBEDDING:
            assert result["status"] == NormativeWorkItem.Status.PENDING, item.last_error

    item.refresh_from_db()
    norma.refresh_from_db()
    assert item.status == NormativeWorkItem.Status.COMPLETED
    assert item.result["human_review"] == "approved"
    assert set(item.result["stage_results"]) == {
        NormativeWorkItem.Stage.CHANGED,
        NormativeWorkItem.Stage.EXTRACTION,
        NormativeWorkItem.Stage.SEGMENT,
        NormativeWorkItem.Stage.EVENT,
        NormativeWorkItem.Stage.RECONCILE,
        NormativeWorkItem.Stage.SNAPSHOT,
        NormativeWorkItem.Stage.INVALIDATE,
        NormativeWorkItem.Stage.EMBEDDING,
    }
    assert item.result["stage_results"][NormativeWorkItem.Stage.EMBEDDING]["embedding_status"] == "deferred"
    snapshot = NormativeSnapshot.objects.filter(norma=norma).order_by("-as_of", "-pk").first()
    assert snapshot is not None
    assert snapshot.coverage_json["reason"] == "reviewed_source_projection"
    assert norma.texto_original == norma.documento_base.accepted_extraction.legal_text
    assert scheduled
