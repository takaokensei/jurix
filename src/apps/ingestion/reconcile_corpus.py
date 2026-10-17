"""Explicit QA-only second pass for newly available normative identities."""

from __future__ import annotations

from collections.abc import Iterable

from celery import shared_task

from src.apps.ingestion.normative_impact import (
    enqueue_normative_work,
    safe_norma_revision,
    safe_target_identity_revision,
)
from src.apps.ingestion.normative_tasks import _require_normative_qa
from src.apps.legislation.models import Norma
from src.apps.operations.models import NormativeWorkItem

MAX_TARGETS_PER_REQUEST = 10


def enqueue_target_reconciliation(target_norma_ids: Iterable[int]) -> dict:
    """Queue bounded, idempotent reconcile-only work for identities that just arrived."""
    _require_normative_qa()
    ids = list(dict.fromkeys(int(value) for value in target_norma_ids))
    if not ids or len(ids) > MAX_TARGETS_PER_REQUEST or any(value < 1 for value in ids):
        raise ValueError("Informe de 1 a 10 IDs de normas válidos por chamada.")
    normas = {norma.pk: norma for norma in Norma.objects.filter(pk__in=ids)}
    if set(normas) != set(ids):
        raise ValueError("Um ou mais IDs não correspondem a normas existentes.")

    queued = []
    created = 0
    for norma_id in ids:
        norma = normas[norma_id]
        revision = safe_norma_revision(norma) or safe_target_identity_revision(norma)
        if not revision:
            continue
        item, was_created = enqueue_normative_work(
            source_kind="norma",
            source_id=norma.pk,
            source_revision=revision,
            stage=NormativeWorkItem.Stage.RECONCILE,
            payload={
                "reconciliation_only": True,
                "target_identity": {
                    "tipo": norma.tipo,
                    "numero": norma.numero,
                    "ano": norma.ano,
                    "identity_key": norma.identity_key or None,
                },
            },
        )
        created += int(was_created)
        queued.append({"item_id": item.pk, "norma_id": norma.pk, "status": item.status})
    return {"created": created, "queued": queued, "requested": len(ids)}


@shared_task(name="ingestion.reconcile_new_normative_targets", ignore_result=False)
def reconcile_new_normative_targets_task(target_norma_ids: list[int]) -> dict:
    """QA-only queue entrypoint; dispatch remains controlled by the QA work runner."""
    _require_normative_qa()
    return enqueue_target_reconciliation(target_norma_ids)
