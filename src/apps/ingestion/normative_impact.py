"""Bounded impact discovery and queue primitives for normative updates."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from src.apps.legislation.models import EventoAlteracao, Norma
from src.apps.operations.models import NormativeWorkItem

MODIFYING_ACTIONS = ("ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA")
STAGE_ORDER = tuple(NormativeWorkItem.Stage.values)


def affected_norma_ids(source_norma_id: int, *, max_nodes: int = 50) -> list[int]:
    """Traverse only active, validated modifying edges; references never propagate."""
    max_nodes = max(1, min(int(max_nodes), 50))
    visited = {int(source_norma_id)}
    queue = [int(source_norma_id)]
    while queue and len(visited) < max_nodes:
        current = queue.pop(0)
        events = EventoAlteracao.objects.filter(
            dispositivo_fonte__norma_id=current,
            validado=True,
            is_active=True,
            acao__in=MODIFYING_ACTIONS,
            review_revision__isnull=False,
        ).filter(Q(dispositivo_alvo__isnull=False) | Q(norma_alvo__isnull=False)).select_related(
            "dispositivo_fonte", "dispositivo_alvo", "norma_alvo", "review_revision"
        )
        from src.apps.legislation.event_review import event_review_status

        for event in events:
            if event_review_status(event) != "confirmed":
                continue
            device_norma_id = event.dispositivo_alvo.norma_id if event.dispositivo_alvo_id else None
            target_norma_id = event.norma_alvo_id
            target_id = device_norma_id or target_norma_id
            if target_id and target_id not in visited:
                visited.add(target_id)
                if len(visited) >= max_nodes:
                    break
                queue.append(target_id)
    return sorted(visited)


def enqueue_normative_work(
    *, source_kind: str, source_id: str | int, source_revision: str, stage: str,
    payload: dict | None = None,
) -> tuple[NormativeWorkItem, bool]:
    """Create an idempotent work item only while the explicit bounded queue has room."""
    if stage not in NormativeWorkItem.Stage.values:
        raise ValueError("Unsupported normative work stage")
    source_kind = str(source_kind).strip()[:32]
    source_id = str(source_id).strip()[:100]
    source_revision = str(source_revision).strip()[:64]
    if not source_kind or not source_id or not source_revision:
        raise ValueError("Work item identity and source revision are required")
    identity = f"{source_kind}:{source_id}:{source_revision}:{stage}"
    dedupe_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    limit = max(1, int(getattr(settings, "NORMATIVE_WORK_QUEUE_MAX_PENDING", 200)))
    with transaction.atomic():
        existing = NormativeWorkItem.objects.select_for_update().filter(dedupe_key=dedupe_key).first()
        if existing:
            return existing, False
        active_count = NormativeWorkItem.objects.filter(
            status__in=[NormativeWorkItem.Status.PENDING, NormativeWorkItem.Status.LEASED]
        ).count()
        if active_count >= limit:
            raise RuntimeError("Normative work queue is at its configured pending limit")
        item = NormativeWorkItem.objects.create(
            dedupe_key=dedupe_key,
            source_kind=source_kind,
            source_id=source_id,
            source_revision=source_revision,
            stage=stage,
            payload=payload or {},
        )
        return item, True


def claim_normative_work_item(item_id: int, *, lease_seconds: int = 300) -> tuple[NormativeWorkItem, str]:
    # Commit terminal retry exhaustion before raising; raising inside atomic would roll it back.
    retry_exhausted = False
    with transaction.atomic():
        item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
        now = timezone.now()
        if item.status == NormativeWorkItem.Status.LEASED and item.lease_until and item.lease_until > now:
            raise RuntimeError("Normative work item already has an active lease")
        if item.status not in {NormativeWorkItem.Status.PENDING, NormativeWorkItem.Status.LEASED}:
            raise RuntimeError("Normative work item is not claimable")
        if item.attempts >= item.max_attempts:
            item.status = NormativeWorkItem.Status.FAILED
            item.last_error = "Tentativas máximas atingidas."
            item.lease_token = None
            item.lease_until = None
            item.save(update_fields=["status", "last_error", "lease_token", "lease_until", "updated_at"])
            retry_exhausted = True
        else:
            token = uuid.uuid4()
            item.status = NormativeWorkItem.Status.LEASED
            item.lease_token = token
            item.lease_until = now + timedelta(seconds=max(30, min(int(lease_seconds), 1800)))
            item.attempts += 1
            item.save(update_fields=["status", "lease_token", "lease_until", "attempts", "updated_at"])
            return item, str(token)
    if retry_exhausted:
        raise RuntimeError("Normative work item reached its retry limit")
    raise RuntimeError("Normative work item could not be claimed")


@transaction.atomic
def finish_normative_stage(item_id: int, token: str, *, result: dict | None = None):
    item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
    if item.status != NormativeWorkItem.Status.LEASED or str(item.lease_token) != str(token):
        raise RuntimeError("Stale or foreign normative work lease")
    if item.stage == NormativeWorkItem.Stage.REVIEW:
        raise RuntimeError("Human review must use the separately authorized review workflow")
    stage = item.stage
    previous_result = item.result if isinstance(item.result, dict) else {}
    stage_results = previous_result.get("stage_results")
    if not isinstance(stage_results, dict):
        stage_results = {}
    stage_results = {**stage_results, stage: result or {}}
    item.result = {**previous_result, **(result or {}), "stage_results": stage_results}
    item.lease_token = None
    item.lease_until = None
    position = STAGE_ORDER.index(item.stage)
    if position + 1 >= len(STAGE_ORDER):
        item.status = NormativeWorkItem.Status.COMPLETED
    else:
        # attempts limits retries for this checkpoint, not the entire multi-stage pipeline.
        item.stage = STAGE_ORDER[position + 1]
        item.attempts = 0
        item.status = (
            NormativeWorkItem.Status.AWAITING_REVIEW
            if item.stage == NormativeWorkItem.Stage.REVIEW
            else NormativeWorkItem.Status.PENDING
        )
    item.save(update_fields=[
        "stage", "status", "result", "attempts", "lease_token", "lease_until", "updated_at"
    ])
    return item


@transaction.atomic
def defer_normative_stage_for_review(
    item_id: int, token: str, *, reason: str, result: dict | None = None
):
    """Release a stage lease without advancing when a human decision is required."""
    item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
    if item.status != NormativeWorkItem.Status.LEASED or str(item.lease_token) != str(token):
        raise RuntimeError("Stale or foreign normative work lease")
    item.status = NormativeWorkItem.Status.AWAITING_REVIEW
    item.lease_token = None
    item.lease_until = None
    item.last_error = ""
    item.result = {
        **(item.result or {}),
        **(result or {}),
        "review_gate": {"reason": str(reason or "Revisão necessária")[:240]},
    }
    item.save(
        update_fields=["status", "lease_token", "lease_until", "last_error", "result", "updated_at"]
    )
    return item


@transaction.atomic
def cancel_normative_stage(item_id: int, token: str, *, reason: str):
    """Stop stale work while preserving its source and every prior checkpoint."""
    item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
    if item.status != NormativeWorkItem.Status.LEASED or str(item.lease_token) != str(token):
        raise RuntimeError("Stale or foreign normative work lease")
    item.status = NormativeWorkItem.Status.CANCELLED
    item.lease_token = None
    item.lease_until = None
    item.last_error = str(reason or "Entrada desatualizada")[:500]
    item.save(update_fields=["status", "lease_token", "lease_until", "last_error", "updated_at"])
    return item


@transaction.atomic
def resolve_normative_review(item_id: int, *, actor, approved: bool, reason: str):
    reason = str(reason or "").strip()[:500]
    if not getattr(actor, "is_active", False) or not getattr(actor, "is_staff", False):
        raise PermissionError("Active staff review is required")
    if not reason:
        raise ValueError("A review reason is required")
    item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
    if item.status != NormativeWorkItem.Status.AWAITING_REVIEW:
        raise RuntimeError("Normative work item is not awaiting review")
    item.reviewed_by = actor
    item.review_reason = reason
    item.reviewed_at = timezone.now()
    item.result = {**(item.result or {}), "human_review": "approved" if approved else "rejected"}
    if approved:
        if item.stage == NormativeWorkItem.Stage.REVIEW:
            position = STAGE_ORDER.index(item.stage)
            if position + 1 >= len(STAGE_ORDER):
                item.status = NormativeWorkItem.Status.COMPLETED
            else:
                item.stage = STAGE_ORDER[position + 1]
                item.attempts = 0
                item.status = NormativeWorkItem.Status.PENDING
        else:
            # A stage-specific gate (for example, an unapproved source document)
            # resumes the same checkpoint after the separate source review is done.
            item.status = NormativeWorkItem.Status.PENDING
    else:
        item.status = NormativeWorkItem.Status.CANCELLED
    item.save(update_fields=[
        "stage", "status", "result", "attempts", "reviewed_by", "review_reason", "reviewed_at", "updated_at"
    ])
    return item


@transaction.atomic
def fail_normative_stage(item_id: int, token: str, error: str):
    item = NormativeWorkItem.objects.select_for_update().get(pk=item_id)
    if item.status != NormativeWorkItem.Status.LEASED or str(item.lease_token) != str(token):
        raise RuntimeError("Stale or foreign normative work lease")
    item.last_error = str(error or "Falha sem detalhe")[:500]
    item.lease_token = None
    item.lease_until = None
    item.status = (
        NormativeWorkItem.Status.PENDING
        if item.attempts < item.max_attempts
        else NormativeWorkItem.Status.FAILED
    )
    item.save(update_fields=["last_error", "lease_token", "lease_until", "status", "updated_at"])
    return item


def safe_norma_revision(norma: Norma) -> str:
    """Return a source revision hash, or empty if the current text has no fingerprint."""
    metadata = norma.sapl_metadata if isinstance(norma.sapl_metadata, dict) else {}
    digest = str(metadata.get("_jurix_source_hash") or "")
    if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest.lower()):
        return digest.lower()
    document = norma.documento_base
    revision = (
        getattr(document, "content_sha256", "") or getattr(document, "sha256", "")
        if document
        else ""
    )
    if len(revision) == 64 and all(char in "0123456789abcdef" for char in revision.lower()):
        return revision.lower()
    legal_text = norma.texto_consolidado or norma.texto_original or ""
    content = "\n".join((norma.ementa or "", legal_text))
    return hashlib.sha256(content.encode("utf-8")).hexdigest() if content.strip() else ""
