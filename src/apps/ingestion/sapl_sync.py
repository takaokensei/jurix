"""Resumable and auditable SAPL synchronization.

The SAPL API used by Jurix does not currently expose a reliable universal
"updated since" contract. The sync therefore follows a conservative strategy:

* persist the current offset as a checkpoint;
* fingerprint the complete source payload;
* skip unchanged records;
* stop once a complete page is unchanged, assuming the source ordering is
  newest-first;
* keep the checkpoint when a run is bounded or interrupted;
* never delete a local Norma from an incremental run;
* expose a separate full scan that can flag remotely missing records for
  human review.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState
from src.clients.sapl.sapl_client import SaplAPIClient
from src.observability.metrics import SAPL_SYNC_RECORDS, SAPL_SYNC_RUNS

logger = logging.getLogger(__name__)


def payload_hash(payload: dict[str, Any]) -> str:
    """Return a deterministic fingerprint for a source payload."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope_fingerprint(tipo: str | None, ano: int | None) -> str:
    value = json.dumps(
        {"tipo": tipo or "", "ano": ano},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _remote_timestamp(payload: dict[str, Any]):
    from django.utils.dateparse import parse_datetime

    for key in (
        "updated_at",
        "data_atualizacao",
        "data_modificacao",
        "modified_at",
        "alterado_em",
    ):
        raw = payload.get(key)
        if not raw:
            continue
        if hasattr(raw, "tzinfo"):
            value = raw
        else:
            value = parse_datetime(str(raw))
        if value is not None:
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return value
    return None


def _lease_seconds() -> int:
    return max(60, int(getattr(settings, "SAPL_SYNC_LEASE_SECONDS", 900)))


@transaction.atomic
def _acquire_state(scope: str) -> tuple[SaplSyncState | None, str | None]:
    now = timezone.now()
    state, _ = SaplSyncState.objects.select_for_update().get_or_create(
        source="sapl",
        filter_fingerprint=scope,
    )
    if state.lease_until and state.lease_until > now:
        return state, None
    token = uuid.uuid4().hex
    state.last_started_at = now
    state.lease_until = now + timedelta(seconds=_lease_seconds())
    state.lease_token = token
    state.last_error = ""
    state.save(
        update_fields=[
            "last_started_at",
            "lease_until",
            "lease_token",
            "last_error",
            "updated_at",
        ]
    )
    return state, token


def _renew(state_id: int, token: str) -> bool:
    deadline = timezone.now() + timedelta(seconds=_lease_seconds())
    updated = SaplSyncState.objects.filter(
        id=state_id,
        lease_token=token,
    ).update(lease_until=deadline)
    return bool(updated)


def _release(
    state_id: int,
    token: str,
    *,
    success: bool,
    error: str = "",
    cursor: int = 0,
    sync_count: int = 0,
    remote_timestamp=None,
    full_sync: bool = False,
) -> None:
    now = timezone.now()
    values = {
        "lease_until": None,
        "lease_token": "",
        "last_cursor": cursor,
        "last_sync_count": sync_count,
        "last_error": error[:4000],
    }
    if success:
        values["last_success_at"] = now
    if remote_timestamp is not None:
        values["last_remote_timestamp"] = remote_timestamp
    if full_sync and success:
        values["last_full_sync_at"] = now
        values["last_cursor"] = 0
    updated = SaplSyncState.objects.filter(
        id=state_id,
        lease_token=token,
    ).update(**values)
    if not updated:
        logger.warning("SAPL sync lease disappeared before release: state=%s", state_id)


def _old_hash(sapl_id: int) -> str | None:
    existing = Norma.objects.filter(sapl_id=sapl_id).only("sapl_metadata").first()
    if not existing:
        return None
    metadata = existing.sapl_metadata or {}
    return metadata.get("_jurix_source_hash")


def _process_payload(payload: dict[str, Any]) -> tuple[str, int | None]:
    """Persist one changed payload through the existing transactional pipeline."""
    from src.apps.ingestion.tasks import _process_norma_data

    sapl_id = payload.get("id")
    if not sapl_id:
        raise ValueError("Norma sem id no payload SAPL")
    digest = payload_hash(payload)
    stored = dict(payload)
    stored["_jurix_source_hash"] = digest
    _process_norma_data(stored, auto_download=True)
    return digest, int(sapl_id)


def _finalize_status(
    *,
    state: SaplSyncState,
    stats: dict[str, Any],
    partial: bool,
    error: str = "",
) -> dict[str, Any]:
    if error:
        status = "error"
    elif partial:
        status = "partial"
    else:
        status = "success"
    SAPL_SYNC_RUNS.labels(status=status).inc()
    return stats


def run_incremental_sync(
    *,
    limit: int = 100,
    tipo: str | None = None,
    ano: int | None = None,
) -> dict[str, Any]:
    """Resume from the persisted cursor and stop at the first safe boundary."""
    limit = max(1, min(int(limit), 500))
    max_pages = max(1, int(getattr(settings, "SAPL_INCREMENTAL_MAX_PAGES", 20)))
    scope = _scope_fingerprint(tipo, ano)
    state, token = _acquire_state(scope)
    if token is None:
        return {
            "success": True,
            "busy": True,
            "message": "Outra sincronização SAPL ainda possui o lease ativo.",
            "cursor": state.last_cursor if state else 0,
        }

    client = SaplAPIClient()
    offset = int(state.last_cursor)
    stats = {
        "success": False,
        "busy": False,
        "partial": False,
        "fetched": 0,
        "changed": 0,
        "unchanged": 0,
        "failed": 0,
        "pages": 0,
        "cursor_start": offset,
        "cursor_end": offset,
        "safe_stop": False,
        "errors": [],
    }
    newest_remote = state.last_remote_timestamp

    try:
        for _ in range(max_pages):
            if not _renew(state.id, token):
                raise RuntimeError("Lease SAPL perdido durante a sincronização.")
            page = client.fetch_normas_page(
                limit=limit,
                offset=offset,
                tipo=tipo,
                ano=ano,
            )
            results = page.get("results") or []
            if not results:
                stats["success"] = True
                stats["safe_stop"] = True
                break

            stats["pages"] += 1
            stats["fetched"] += len(results)
            page_unchanged = True

            for payload in results:
                sapl_id = payload.get("id")
                if not sapl_id:
                    stats["failed"] += 1
                    stats["errors"].append("Norma sem id no payload SAPL")
                    page_unchanged = False
                    continue
                remote_dt = _remote_timestamp(payload)
                if remote_dt and (newest_remote is None or remote_dt > newest_remote):
                    newest_remote = remote_dt
                digest = payload_hash(payload)
                if _old_hash(int(sapl_id)) == digest:
                    stats["unchanged"] += 1
                    SAPL_SYNC_RECORDS.labels(state="unchanged").inc()
                    continue
                page_unchanged = False
                try:
                    digest, _ = _process_payload(payload)
                    stats["changed"] += 1
                    SAPL_SYNC_RECORDS.labels(state="changed").inc()
                except Exception as exc:
                    stats["failed"] += 1
                    stats["errors"].append(f"Norma {sapl_id}: {exc}")
                    SAPL_SYNC_RECORDS.labels(state="failed").inc()
                    logger.error("Incremental SAPL sync failed for %s", sapl_id, exc_info=True)

            offset += len(results)
            state.last_cursor = offset
            state.last_sync_count = stats["fetched"]
            state.last_remote_timestamp = newest_remote
            state.save(
                update_fields=[
                    "last_cursor",
                    "last_sync_count",
                    "last_remote_timestamp",
                    "updated_at",
                ]
            )
            stats["cursor_end"] = offset

            if page_unchanged or len(results) < limit:
                stats["success"] = stats["failed"] == 0
                stats["safe_stop"] = True
                offset = 0
                state.last_cursor = 0
                state.save(update_fields=["last_cursor", "updated_at"])
                break

        else:
            stats["partial"] = True

        error = "; ".join(stats["errors"])
        _release(
            state.id,
            token,
            success=stats["success"] and not stats["partial"],
            error=error,
            cursor=0 if stats["safe_stop"] else offset,
            sync_count=stats["fetched"],
            remote_timestamp=newest_remote,
        )
        return _finalize_status(
            state=state,
            stats=stats,
            partial=stats["partial"],
            error=error,
        )
    except Exception as exc:
        logger.error("Incremental SAPL sync failed", exc_info=True)
        _release(
            state.id,
            token,
            success=False,
            error=str(exc),
            cursor=offset,
            sync_count=stats["fetched"],
            remote_timestamp=newest_remote,
        )
        raise
    finally:
        client.close()


def run_full_sync(*, limit: int = 100) -> dict[str, Any]:
    """Scan the complete source and flag local records absent from SAPL.

    The operation never deletes local data. Missing records are marked
    ``needs_review`` so a human can distinguish a true remote deletion from a
    transient API/filtering problem.
    """
    limit = max(1, min(int(limit), 500))
    scope = hashlib.sha256((_scope_fingerprint(None, None) + ":full").encode("utf-8")).hexdigest()
    state, token = _acquire_state(scope)
    if token is None:
        return {
            "success": True,
            "busy": True,
            "message": "Outra sincronização SAPL completa está em execução.",
        }
    client = SaplAPIClient()
    seen_ids: set[int] = set()
    offset = 0
    pages = 0
    fetched = 0
    changed = 0
    failed = 0
    max_pages = max(1, int(getattr(settings, "SAPL_FULL_SYNC_MAX_PAGES", 1000)))
    errors: list[str] = []

    try:
        for _ in range(max_pages):
            if not _renew(state.id, token):
                raise RuntimeError("Lease SAPL perdido durante o full sync.")
            page = client.fetch_normas_page(limit=limit, offset=offset)
            results = page.get("results") or []
            if not results:
                break
            pages += 1
            fetched += len(results)
            for payload in results:
                sapl_id = payload.get("id")
                if not sapl_id:
                    failed += 1
                    errors.append("Norma sem id no payload SAPL")
                    continue
                sapl_id = int(sapl_id)
                seen_ids.add(sapl_id)
                digest = payload_hash(payload)
                if _old_hash(sapl_id) == digest:
                    SAPL_SYNC_RECORDS.labels(state="unchanged").inc()
                    continue
                try:
                    digest, _ = _process_payload(payload)
                    changed += 1
                    SAPL_SYNC_RECORDS.labels(state="changed").inc()
                except Exception as exc:
                    failed += 1
                    errors.append(f"Norma {sapl_id}: {exc}")
                    SAPL_SYNC_RECORDS.labels(state="failed").inc()
            offset += len(results)
            state.last_cursor = offset
            state.last_sync_count = fetched
            state.save(update_fields=["last_cursor", "last_sync_count", "updated_at"])
            if len(results) < limit:
                break
        else:
            raise RuntimeError(
                f"Full sync excedeu SAPL_FULL_SYNC_MAX_PAGES={max_pages}; "
                "nenhuma ausência remota foi marcada."
            )

        if failed:
            raise RuntimeError(
                f"Full sync terminou com {failed} registro(s) que não puderam ser processados."
            )

        if seen_ids:
            missing_qs = Norma.objects.filter(sapl_id__isnull=False).exclude(sapl_id__in=seen_ids)
            missing_count = missing_qs.update(
                needs_review=True,
                processing_error=("Norma não localizada no SAPL na última sincronização completa."),
            )
        else:
            missing_count = 0

        state.last_cursor = 0
        state.last_sync_count = fetched
        _release(
            state.id,
            token,
            success=True,
            cursor=0,
            sync_count=fetched,
            full_sync=True,
        )
        stats = {
            "success": True,
            "busy": False,
            "pages": pages,
            "fetched": fetched,
            "changed": changed,
            "missing_marked_for_review": missing_count,
            "failed": 0,
            "errors": errors,
        }
        SAPL_SYNC_RUNS.labels(status="success").inc()
        return stats
    except Exception as exc:
        logger.error("Full SAPL sync failed", exc_info=True)
        _release(
            state.id,
            token,
            success=False,
            error=str(exc),
            cursor=offset,
            sync_count=fetched,
        )
        SAPL_SYNC_RUNS.labels(status="error").inc()
        raise
    finally:
        client.close()
