"""Explicit, single-stage Celery entrypoints for the bounded normative queue."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import date
from pathlib import Path

from celery import shared_task
from celery.result import allow_join_result
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils import timezone

from src.apps.ingestion.ner_tasks import extract_entities_task, generate_embedding_task
from src.apps.ingestion.segmentation_tasks import segment_text_task
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Dispositivo, Norma
from src.apps.operations.models import NormativeWorkItem
from src.processing.cache_service import get_cache_service
from src.processing.document_extraction import extract_pdf_document, normalize_extracted_text
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
from .task_support import _configure_tesseract


def _run_inline_task(task, *args):
    """Run a bounded task locally and permit reading its already-eager result.

    These stage helpers use ``Task.apply`` (not ``apply_async``), so execution is
    synchronous in this worker process and cannot wait on another queue slot.
    Celery normally blocks ``get()`` from task context to prevent deadlocks; the
    narrow context below only lifts that guard for this completed eager result.
    """
    with allow_join_result():
        return task.apply(args=list(args), throw=True).get()


class StaleNormativeSource(RuntimeError):
    """The norm changed after this queue item was created."""


def _stage_progress(item: NormativeWorkItem, stage: str) -> dict:
    result = item.result if isinstance(item.result, dict) else {}
    stages = result.get("stage_progress")
    progress = stages.get(stage) if isinstance(stages, dict) else None
    if not isinstance(progress, dict) or progress.get("source_revision") != item.source_revision:
        return {"source_revision": item.source_revision}
    return dict(progress)


def _reusable_ocr_pages(extraction: ExtracaoDocumento) -> dict[int, tuple[str, str]]:
    """Return hash-verified OCR spans and preserve their original extraction hash."""
    legal_text = extraction.legal_text or ""
    reusable: dict[int, tuple[str, str]] = {}
    for span in extraction.page_map_json or []:
        if not isinstance(span, dict) or span.get("method") != "ocr":
            continue
        page = span.get("page")
        start, end = span.get("start"), span.get("end")
        if (
            not isinstance(page, int)
            or page < 1
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(legal_text)
        ):
            continue
        text = normalize_extracted_text(legal_text[start:end])
        quote_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if not text or quote_hash != span.get("quote_hash"):
            continue
        source_hash = span.get("reused_from_extraction_sha256") or extraction.extraction_sha256
        if isinstance(source_hash, str) and source_hash:
            reusable[page] = (text, source_hash)
    return reusable


def _extract_archive_candidate(
    document: DocumentoNormativo,
    *,
    max_pages: int = 200,
    max_ocr_pages: int | None = None,
    ocr_timeout_seconds: int = 90,
    ocr_pages_to_process: set[int] | None = None,
    raster_table_pages_to_process: set[int] | None = None,
    reuse_from: ExtracaoDocumento | None = None,
) -> ExtracaoDocumento:
    """Extract verified bytes inside QA storage without accepting/promoting the text."""
    allowed_source_kinds = {
        DocumentoNormativo.SourceKind.ARCHIVE,
        DocumentoNormativo.SourceKind.SAPL,
    }
    if document.source_kind not in allowed_source_kinds or not document.storage_key:
        raise PermissionError("A extração exige PDF candidato no storage QA.")
    if document.source_kind == DocumentoNormativo.SourceKind.SAPL:
        if document.norma_id:
            if (
                document.norma.status != "pending"
                or document.norma.documento_base_id is not None
                or document.norma.texto_original
                or document.norma.texto_consolidado
            ):
                raise PermissionError(
                    "PDF SAPL vinculado só pode ser extraído enquanto a Norma QA está pendente e vazia."
                )
        else:
            metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
            identity = metadata.get("identity_candidate") or {}
            provenance = metadata.get("source_provenance") or {}
            if (
                document.review_status != DocumentoNormativo.ReviewStatus.PENDING
                or document.accepted_extraction_id is not None
                or metadata.get("identity_status") != "candidate"
                or identity.get("jurisdiction") != "BR-RN-NATAL"
                or not metadata.get("identity_key")
                or provenance.get("kind") != "sapl_norma_pdf"
                or not str(provenance.get("official_url") or "").startswith(
                    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/"
                )
            ):
                raise PermissionError(
                    "PDF SAPL sem Norma exige identidade municipal candidata e proveniência oficial verificáveis."
                )
    root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    archive_root = (root / "normative-archive").resolve()
    pdf_path = (archive_root / document.storage_key).resolve()
    if not root.is_dir() or not pdf_path.is_relative_to(archive_root) or not pdf_path.is_file():
        raise PermissionError("PDF não está disponível dentro do storage QA isolado.")
    digest = hashlib.sha256()
    with pdf_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != document.content_sha256:
        raise StaleNormativeSource("Hash do PDF staging diverge do registro da fonte.")

    reusable_pages = {}
    if reuse_from is not None:
        if reuse_from.documento_id != document.pk:
            raise ValueError("A extração de origem precisa pertencer ao mesmo documento.")
        reusable_pages = _reusable_ocr_pages(reuse_from)

    _configure_tesseract()
    extracted = extract_pdf_document(
        str(pdf_path),
        max_pages=max_pages,
        ocr_timeout_seconds=ocr_timeout_seconds,
        max_ocr_pages=max_ocr_pages,
        ocr_pages_to_process=ocr_pages_to_process,
        raster_table_pages_to_process=raster_table_pages_to_process,
        reusable_ocr_pages=reusable_pages,
    )
    policy_fingerprint = str(extracted["policy_fingerprint"])
    candidate = ExtracaoDocumento.objects.filter(
        documento=document,
        extractor_version=extracted["extractor_version"],
        policy_fingerprint=policy_fingerprint,
    ).first()
    if candidate:
        return candidate
    candidate = ExtracaoDocumento(
        documento=document,
        extractor_version=extracted["extractor_version"],
        policy_fingerprint=policy_fingerprint,
        text_version=extracted["text_version"],
        raw_text=extracted["raw_text"],
        legal_text=extracted["legal_text"],
        page_count=extracted["page_count"],
        page_map_json=extracted["source_map"],
        metadata_candidates_json=extracted["metadata_candidates"],
        quality_json={
            **extracted["quality"],
            "needs_review": extracted["needs_review"],
            "pipeline_candidate_only": True,
            "duration_seconds": extracted["duration_seconds"],
        },
        status=(
            ExtracaoDocumento.Status.COMPLETE
            if extracted["complete"]
            else (
                ExtracaoDocumento.Status.PARTIAL
                if extracted["legal_text"].strip()
                else ExtracaoDocumento.Status.UNREADABLE
            )
        ),
        extraction_sha256=extracted["extraction_sha256"],
    )
    candidate.save()
    document.extraction_status = (
        DocumentoNormativo.ExtractionStatus.EXTRACTED
        if extracted["complete"]
        else DocumentoNormativo.ExtractionStatus.NEEDS_REVIEW
    )
    document.save(update_fields=["extraction_status", "updated_at"])
    return candidate


def _require_normative_qa() -> None:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE")
        not in {
            "config.settings_normative_qa",
            "config.settings_normative_container_qa",
        }
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise RuntimeError("Normative worker requires the isolated normative QA settings.")


def _current_norma(item: NormativeWorkItem) -> Norma:
    if item.source_kind != "norma" or not str(item.source_id).isdigit():
        raise ValueError("Normative pipeline only accepts a numeric Norma source.")
    norma = Norma.objects.select_related("documento_base__accepted_extraction").get(
        pk=int(item.source_id)
    )
    expected_revision = safe_norma_revision(norma)
    if (
        item.stage == NormativeWorkItem.Stage.RECONCILE
        and isinstance(item.payload, dict)
        and item.payload.get("reconciliation_only") is True
    ):
        from src.apps.ingestion.normative_impact import safe_target_identity_revision

        expected_revision = expected_revision or safe_target_identity_revision(norma)
    if expected_revision != item.source_revision:
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
        created = False
        if (
            not extraction
            and document
            and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
        ):
            before = document.extracoes.count()
            extraction = _extract_archive_candidate(document)
            created = document.extracoes.count() > before
        return {
            "document_available": bool(document),
            "document_review_status": document.review_status if document else "missing",
            "extraction_id": extraction.pk if extraction else None,
            "extraction_status": extraction.status if extraction else "missing",
            "extraction_sha256": extraction.extraction_sha256 if extraction else None,
            "extraction_candidate_created": created,
            "legal_text_accepted": bool(document and document.accepted_extraction_id),
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
        legacy = _run_inline_task(segment_text_task, norma.pk)
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
        result = _run_inline_task(extract_entities_task, norma.pk)
        return {"event_extraction": result}

    if stage == NormativeWorkItem.Stage.RECONCILE:
        from src.apps.legislation.models import EventoAlteracao

        progress = _stage_progress(item, stage)
        maximum = progress.get("max_event_id")
        if maximum is None:
            maximum = (
                EventoAlteracao.objects.filter(norma_alvo__isnull=True, is_active=True)
                .order_by("-pk")
                .values_list("pk", flat=True)
                .first()
                or 0
            )
        expected_count = progress.get("expected_count")
        if expected_count is None:
            expected_count = EventoAlteracao.objects.filter(
                norma_alvo__isnull=True, is_active=True, pk__lte=int(maximum)
            ).count()
        result = reconcile_unresolved_event_targets(
            limit=10,
            target_norma_ids=[norma.pk],
            after_event_id=int(progress.get("cursor", 0)),
            max_event_id=int(maximum),
            return_cursor=True,
        )
        processed = int(progress.get("processed_count", 0)) + int(result["inspected"])
        resolved_total = int(progress.get("resolved_count", 0)) + int(result["resolved"])
        unresolved_total = int(progress.get("unresolved_count", 0)) + int(
            result["remaining_unresolved"]
        )
        next_cursor = result.get("next_cursor") or progress.get("cursor", 0)
        checkpoint = {
            "source_revision": item.source_revision,
            "max_event_id": int(maximum),
            "cursor": int(next_cursor),
            "expected_universe_sha256": hashlib.sha256(
                f"{norma.pk}:{item.source_revision}:{maximum}".encode()
            ).hexdigest(),
            "expected_count": int(expected_count),
            "processed_count": processed,
            "resolved_count": resolved_total,
            "unresolved_count": unresolved_total,
            "errors": int(progress.get("errors", 0)) + int(result["remaining_unresolved"]),
        }
        return {
            **result,
            "continue_stage": bool(result["has_more"]),
            "stage_progress": checkpoint,
            "stage_result": {
                "inspected": processed,
                "resolved": resolved_total,
                "remaining_unresolved": unresolved_total,
                "cursor": next_cursor,
                "max_event_id": maximum,
            },
        }

    if stage == NormativeWorkItem.Stage.SNAPSHOT:
        projection = project_norma_as_of(norma, date.today())
        if projection.status != "complete":
            return {
                "snapshot_persisted": False,
                "projection_status": projection.status,
                "coverage": projection.coverage,
                "awaiting_review": True,
                "review_reason": "A projeção temporal não está completa e exige revisão antes de continuar.",
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
        model_name = "nomic-embed-text"
        devices_query = Dispositivo.objects.filter(norma=norma, is_active=True).order_by("pk")
        device_rows = list(devices_query.values_list("pk", "revision_fingerprint"))
        if any(not revision for _pk, revision in device_rows):
            return {
                "awaiting_review": True,
                "review_reason": "Há dispositivos sem fingerprint de revisão; embeddings não serão certificados.",
                "embedding_status": "blocked_missing_revision",
            }
        universe_hash = hashlib.sha256(
            "\n".join(f"{pk}:{revision}" for pk, revision in device_rows).encode()
        ).hexdigest()
        progress = _stage_progress(item, stage)
        if progress.get("expected_universe_sha256") != universe_hash:
            progress = {
                "source_revision": item.source_revision,
                "expected_universe_sha256": universe_hash,
                "expected_count": len(device_rows),
                "processed_count": 0,
                "cursor": 0,
                "errors": [],
            }
        cursor = int(progress.get("cursor", 0))
        # Recheck the processed prefix so deletion or invalidation of an earlier
        # vector restarts safely instead of leaving a false-complete cursor.
        stale_prefix = (
            devices_query.filter(pk__lte=cursor)
            .exclude(
                embedding__isnull=False,
                embedding_model=model_name,
                embedding_revision_fingerprint=F("revision_fingerprint"),
            )
            .exists()
        )
        if stale_prefix:
            cursor = 0
            progress["processed_count"] = 0
        batch = list(devices_query.filter(pk__gt=cursor)[:10])
        from src.llm_engine.ollama_service import OllamaService

        service = OllamaService(model=model_name)
        if not service.check_health():
            raise RuntimeError("Ollama indisponível; lote de embeddings permanece pendente.")
        results = []
        for dispositivo in batch:
            if (
                dispositivo.embedding is not None
                and dispositivo.embedding_model == model_name
                and dispositivo.embedding_revision_fingerprint == dispositivo.revision_fingerprint
            ):
                results.append(
                    {"dispositivo_id": dispositivo.pk, "success": True, "reused_current": True}
                )
                continue
            result = _run_inline_task(generate_embedding_task, dispositivo.pk)
            if not result.get("success") or result.get("stale_input"):
                raise RuntimeError("Embedding falhou ou a revisão mudou durante o lote.")
            results.append(
                {
                    "dispositivo_id": dispositivo.pk,
                    "success": True,
                    "stale_input": False,
                }
            )
        next_cursor = batch[-1].pk if batch else cursor
        has_more = devices_query.filter(pk__gt=next_cursor).exists()
        processed = int(progress.get("processed_count", 0)) + len(batch)
        checkpoint = {
            "source_revision": item.source_revision,
            "expected_universe_sha256": universe_hash,
            "expected_count": len(device_rows),
            "processed_count": processed,
            "cursor": next_cursor,
            "errors": [],
        }
        return {
            "embedding_status": "processing" if has_more else "complete",
            "count": processed,
            "results": results,
            "continue_stage": has_more,
            "stage_progress": checkpoint,
            "stage_result": {
                "embedding_status": "complete" if not has_more else "processing",
                "count": processed,
                "expected_count": len(device_rows),
                "batch_count": len(batch),
            },
        }

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
        source_revision = (
            revision_hash if affected_id == norma_id else safe_norma_revision(affected)
        )
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
    item = resolve_normative_review(item_id, actor=reviewer, approved=bool(approved), reason=reason)
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
    except NormativeWorkItem.DoesNotExist:
        # A stale broker message can outlive deletion of its QA work item.
        # Acknowledge it as a no-op instead of retrying a permanently missing row.
        return {
            "item_id": item_id,
            "status": "missing",
            "skipped": "missing_work_item",
        }
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
            return {
                "item_id": current.pk,
                "stage": current.stage,
                "status": current.status,
                "skipped": "not_claimable",
            }
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

    if result.get("awaiting_review"):
        item = defer_normative_stage_for_review(
            item.pk,
            token,
            reason=result.get("review_reason", "Revisão humana necessária."),
            result={
                "required_action": "human_review",
                "stage_result": result,
            },
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
