"""Durable and deterministic identity for the active legal corpus."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone


def _canonical(value):
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _digest_rows(digest, rows) -> int:
    count = 0
    for row in rows.iterator(chunk_size=2000):
        payload = json.dumps(
            [_canonical(value) for value in row],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count


def compute_corpus_identity() -> tuple[str, dict[str, int]]:
    """Stream ordered revision metadata; never include secrets or prompt contents."""
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    digest = hashlib.sha256()
    digest.update(b"jurix-corpus-schema:v1\nsegmentation:hierarchy-v1\n")
    norm_count = _digest_rows(
        digest,
        Norma.objects.order_by("pk").values_list(
            "pk",
            "tipo",
            "numero",
            "ano",
            "status",
            "data_publicacao",
            "data_vigencia",
            "updated_at",
        ),
    )
    device_count = _digest_rows(
        digest,
        Dispositivo.objects.order_by("norma_id", "ordem", "pk").values_list(
            "pk",
            "norma_id",
            "tipo",
            "numero",
            "ordem",
            "structural_key",
            "revision_fingerprint",
            "is_active",
            "updated_at",
        ),
    )
    active_event_count = _digest_rows(
        digest,
        EventoAlteracao.objects.filter(is_active=True)
        .order_by("dispositivo_fonte__norma_id", "dispositivo_fonte_id", "pk")
        .values_list(
            "pk",
            "dispositivo_fonte_id",
            "acao",
            "target_text",
            "norma_alvo_id",
            "dispositivo_alvo_id",
            "validado",
            "revision_fingerprint",
            "updated_at",
        ),
    )
    return digest.hexdigest(), {
        "norm_count": norm_count,
        "device_count": device_count,
        "active_event_count": active_event_count,
    }


def refresh_corpus_revision() -> dict:
    """Recompute once at a legal write boundary and bump only when content differs."""
    from src.apps.operations.models import CorpusRevision

    new_digest, counts = compute_corpus_identity()
    with transaction.atomic():
        state, _created = CorpusRevision.objects.select_for_update().get_or_create(
            key="municipal",
            defaults={
                "digest": new_digest,
                "norm_count": counts["norm_count"],
                "device_count": counts["device_count"],
                "active_event_count": counts["active_event_count"],
                "completeness": "unknown",
                "segmentation_version": "hierarchy-v1",
                "generated_at": timezone.now(),
            },
        )
        changed = state.digest != new_digest
        if changed:
            state.revision += 1
            state.digest = new_digest
            state.norm_count = counts["norm_count"]
            state.device_count = counts["device_count"]
            state.active_event_count = counts["active_event_count"]
            state.generated_at = timezone.now()
            state.save(
                update_fields=[
                    "revision",
                    "digest",
                    "norm_count",
                    "device_count",
                    "active_event_count",
                    "generated_at",
                    "updated_at",
                ]
            )
        return {
            "revision": state.revision,
            "digest": state.digest,
            "changed": changed,
            **counts,
            "completeness": state.completeness,
        }


def get_corpus_revision() -> dict | None:
    """Read the durable identity; never infer corpus completeness from row counts."""
    from src.apps.operations.models import CorpusRevision

    state = CorpusRevision.objects.filter(key="municipal").first()
    if state is None:
        return None
    return {
        "revision": state.revision,
        "digest": state.digest,
        "norm_count": state.norm_count,
        "device_count": state.device_count,
        "active_event_count": state.active_event_count,
        "completeness": state.completeness,
        "generated_at": state.generated_at.isoformat() if state.generated_at else None,
    }
