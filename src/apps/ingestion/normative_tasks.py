"""Explicit, single-stage Celery entrypoints for the bounded normative queue."""

from __future__ import annotations

import os
import time
from datetime import date

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from src.apps.ingestion.ner_tasks import extract_entities_task, generate_embedding_task
from src.apps.ingestion.segmentation_tasks import segment_text_task
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Dispositivo, Norma
from src.apps.operations.models import NormativeWorkItem
from src.processing.cache_service import get_cache_service
from src.processing.document_segmentation import segment_document_extraction
from src.processing.normative_projection import persist_projection, project_norma_as_of
from src.processing.target_reconciliation import reconcile_unresolved_event_targets

from .normative_impact import (
    affected_norma_ids,
    cancel_normative_stage,
    claim_normative_work_item,
    defer_normative_stage_for_review,
    enqueue_normative_work,
    fail_normative_stage,
    finish_normative_stage,
    resolve_normative_review,
    safe_norma_revision,
)


class StaleNormativeSource(RuntimeError):
    """The norm changed after this queue item was created."""


def _require_normative_qa() -> None:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise RuntimeError("Normative worker requires the isolated normative QA settings.")


def _current_norma(item: NormativeWorkItem) -> Norma:
    if item.source_kind != "norma" or not str(item.source_id).isdigit():
        raise ValueError("Normative pipeline only accepts a numeric Norma source.")
    norma = Norma.objects.select_related("documento_base__accepted_extraction").get(
        pk=int(item.source_id)
    )
    if safe_norma_revision(norma) != item.source_revision:
        raise StaleNormativeSource("Source revision changed after queueing.")
    return norma


def _execute_normative_stage(item: NormativeWorkItem, norma: Norma) -> dict:
    """Run exactly one bounded stage; every write uses existing reviewed services."""
    stage = item.stage
    if stage == NormativeWorkItem.Stage.CHANGED:
        return {"source_revision_verified": item.source_revision}

    if stage == NormativeWorkItem.Stage.EXTRACTION:
        document = norma.documento_base
        extraction = document.accepted_extraction if document else None
        if not extraction and document:
            extraction = document.extracoes.order_by("-created_at", "-pk").first()
        return {
            "document_available": bool(document),
            "document_review_status": document.review_status if document else "missing",
            "extraction_id": extraction.pk if extraction else None,
            "extraction_status": extraction.status if extraction else "missing",
            "extraction_sha256": extraction.extraction_sha256 if extraction else None,
            "text_mutated": False,
        }

    if stage == NormativeWorkItem.Stage.REVIEW:
        raise RuntimeError("Review checkpoints must be resolved by the staff review workflow.")

    document = norma.documento_base
    extraction = document.accepted_extraction if document else None
    approved = bool(
        document
        and document.norma_id == norma.pk
        and document.review_status == DocumentoNormativo.ReviewStatus.APPROVED
        and document.role == DocumentoNormativo.Role.ORIGINAL
        and document.condition_of_use
        in {
            DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            DocumentoNormativo.ConditionOfUse.LICENSED,
        }
        and extraction
        and extraction.status == ExtracaoDocumento.Status.COMPLETE
    )

    if stage == NormativeWorkItem.Stage.SEGMENT:
        if not approved:
            raise PermissionError("A source document must be approved before segmentation.")
        versioned = segment_document_extraction(extraction.pk)
        if not norma.texto_original:
            # The accepted, immutable extraction is the only permitted source for this
            # QA materialization; no pending or conflicting legacy text is overwritten.
            norma.texto_original = extraction.legal_text
            norma.save(update_fields=["texto_original", "updated_at"])
        elif norma.texto_original != extraction.legal_text:
            raise PermissionError(
                "Legacy OCR differs from the accepted extraction; reconcile the text manually."
            )
        legacy = segment_text_task.apply(args=[norma.pk], throw=True).get()
        if not legacy.get("success"):
            raise PermissionError("Legacy device segmentation requires manual review.")
        return {
            "extraction_id": extraction.pk,
            "document_devices_created": versioned.created,
            "document_unchanged": versioned.unchanged,
            "legacy_segmentation": legacy,
            "review_diagnostics": list(versioned.diagnostics),
        }

    if stage == NormativeWorkItem.Stage.EVENT:
        if not approved:
            raise PermissionError("A source document must be approved before event extraction.")
        result = extract_entities_task.apply(args=[norma.pk], throw=True).get()
        return {"event_extraction": result}

    if stage == NormativeWorkItem.Stage.RECONCILE:
        return reconcile_unresolved_event_targets(limit=10, target_norma_ids=[norma.pk])

    if stage == NormativeWorkItem.Stage.SNAPSHOT:
        projection = project_norma_as_of(norma, date.today())
        if projection.status != "complete":
            return {
                "snapshot_persisted": False,
                "projection_status": projection.status,
                "coverage": projection.coverage,
            }
        snapshot = persist_projection(projection)
        return {
            "snapshot_persisted": True,
            "snapshot_id": snapshot.pk,
            "input_sha256": snapshot.input_sha256,
            "content_sha256": snapshot.content_sha256,
        }

    if stage == NormativeWorkItem.Stage.INVALIDATE:
        version = get_cache_service().bump_corpus_version()
        return {"cache_invalidated": version is not None, "corpus_version": version}

    if stage == NormativeWorkItem.Stage.EMBEDDING:
        if not approved:
            raise PermissionError("A source document must be approved before embeddings.")
        devices = list(
            Dispositivo.objects.filter(norma=norma, is_active=True)
            .order_by("pk")[:10]
        )
        from src.llm_engine.ollama_service import OllamaService

        service = OllamaService(model="nomic-embed-text")
        if not service.check_health():
            return {"embedding_status": "deferred", "reason": "ollama_unavailable", "count": 0}
        results = []
        for dispositivo in devices:
            result = generate_embedding_task.apply(args=[dispositivo.pk], throw=True).get()
            results.append({
                "dispositivo_id": dispositivo.pk,
                "success": bool(result.get("success")),
                "stale_input": bool(result.get("stale_input")),
            })
        return {"embedding_status": "processed", "results": results}

    raise ValueError(f"Unsupported normative work stage: {stage}")


@shared_task(name="ingestion.enqueue_normative_impact", ignore_result=False)
def enqueue_normative_impact_task(norma_id: int, revision_hash: str, *, max_nodes: int = 50):
    """Queue bounded work metadata; does not import, promote, or mutate legal text."""
    norma = Norma.objects.get(pk=norma_id)
    expected = safe_norma_revision(norma)
    if len(revision_hash) != 64 or revision_hash.lower() != expected:
        raise ValueError("Source revision is stale or does not match the current norm")
    affected_ids = affected_norma_ids(norma_id, max_nodes=max_nodes)
    created = 0
    item_ids = []
    for affected_id in affected_ids:
        affected = Norma.objects.get(pk=affected_id)
        source_revision = revision_hash if affected_id == norma_id else safe_norma_revision(affected)
        if not source_revision:
            continue
        item, was_created = enqueue_normative_work(
            source_kind="norma",
            source_id=affected_id,
            source_revision=source_revision,
            stage=NormativeWorkItem.Stage.CHANGED,
            payload={"impact_root": int(norma_id), "requires_review": True},
        )
        created += int(was_created)
        item_ids.append(item.pk)
    return {"created": created, "item_ids": item_ids, "bounded_norma_count": len(affected_ids)}


@shared_task(name="ingestion.claim_normative_work_item", ignore_result=False)
def claim_normative_work_item_task(item_id: int, lease_seconds: int = 300):
    item, token = claim_normative_work_item(item_id, lease_seconds=lease_seconds)
    return {"item_id": item.pk, "stage": item.stage, "lease_token": token}


@shared_task(name="ingestion.finish_normative_stage", ignore_result=False)
def finish_normative_stage_task(item_id: int, lease_token: str, result=None):
    item = finish_normative_stage(
        item_id, lease_token, result=result if isinstance(result, dict) else {}
    )
    return {"item_id": item.pk, "stage": item.stage, "status": item.status}


@shared_task(name="ingestion.fail_normative_stage", ignore_result=False)
def fail_normative_stage_task(item_id: int, lease_token: str, error: str):
    item = fail_normative_stage(item_id, lease_token, error)
    return {"item_id": item.pk, "status": item.status}


@shared_task(name="ingestion.review_normative_work_item", ignore_result=False)
def review_normative_work_item_task(item_id: int, reviewer_id: int, approved: bool, reason: str):
    reviewer = get_user_model().objects.get(pk=reviewer_id)
    item = resolve_normative_review(
        item_id, actor=reviewer, approved=bool(approved), reason=reason
    )
    if approved and item.status == NormativeWorkItem.Status.PENDING:
        process_normative_work_item_task.apply_async(args=[item.pk], queue="normative_qa")
    return {"item_id": item.pk, "stage": item.stage, "status": item.status}


@shared_task(
    bind=True,
    name="ingestion.process_normative_work_item",
    ignore_result=False,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_normative_work_item_task(self, item_id: int):
    """QA-only checkpoint worker: run one stage and queue at most one continuation."""
    _require_normative_qa()
    try:
        item, token = claim_normative_work_item(item_id)
    except RuntimeError:
        current = NormativeWorkItem.objects.get(pk=item_id)
        active_lease = (
            current.status == NormativeWorkItem.Status.LEASED
            and current.lease_until is not None
            and current.lease_until > timezone.now()
        )
        if active_lease or current.status in {
            NormativeWorkItem.Status.AWAITING_REVIEW,
            NormativeWorkItem.Status.COMPLETED,
            NormativeWorkItem.Status.CANCELLED,
            NormativeWorkItem.Status.FAILED,
        }:
            return {"item_id": current.pk, "stage": current.stage, "status": current.status, "skipped": "not_claimable"}
        raise
    pause_ms = min(
        max(int(os.environ.get("JURIX_QA_TEST_WORKER_PAUSE_AFTER_CLAIM_MS", "0") or 0), 0),
        30000,
    )
    if pause_ms:
        time.sleep(pause_ms / 1000)
    try:
        norma = _current_norma(item)
        result = _execute_normative_stage(item, norma)
    except StaleNormativeSource as exc:
        item = cancel_normative_stage(item.pk, token, reason=str(exc))
        return {"item_id": item.pk, "status": item.status, "stage": item.stage}
    except PermissionError as exc:
        item = defer_normative_stage_for_review(
            item.pk,
            token,
            reason=str(exc),
            result={"required_action": "approve_source_document"},
        )
        return {"item_id": item.pk, "status": item.status, "stage": item.stage}
    except Exception as exc:
        item = fail_normative_stage(item.pk, token, type(exc).__name__)
        if item.status == NormativeWorkItem.Status.PENDING:
            process_normative_work_item_task.apply_async(
                args=[item.pk], queue="normative_qa", countdown=min(2**item.attempts, 30)
            )
        return {"item_id": item.pk, "status": item.status, "stage": item.stage}

    item = finish_normative_stage(item.pk, token, result=result)
    if item.status == NormativeWorkItem.Status.PENDING:
        process_normative_work_item_task.apply_async(args=[item.pk], queue="normative_qa")
    return {"item_id": item.pk, "status": item.status, "stage": item.stage}


@shared_task(name="ingestion.dispatch_normative_work_batch", ignore_result=False)
def dispatch_normative_work_batch_task(max_items: int = 10):
    """Manually dispatch at most ten pending item IDs; never scans/enqueues a corpus."""
    _require_normative_qa()
    max_items = max(1, min(int(max_items), 10))
    now = timezone.now()
    item_ids = list(
        NormativeWorkItem.objects.filter(
            Q(status=NormativeWorkItem.Status.PENDING)
            | Q(status=NormativeWorkItem.Status.LEASED, lease_until__lte=now)
        )
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)[:max_items]
    )
    for item_id in item_ids:
        process_normative_work_item_task.apply_async(args=[item_id], queue="normative_qa")
    return {"dispatched": len(item_ids), "item_ids": item_ids, "batch_limit": max_items}
