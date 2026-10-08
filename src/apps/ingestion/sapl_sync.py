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

from src.apps.legislation.document_models import DocumentoNormativo
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


def _page_metadata(page: dict[str, Any]) -> dict[str, int] | None:
    metadata = page.get("_jurix_pagination")
    return metadata if isinstance(metadata, dict) else None


def _page_start_url(
    client: SaplAPIClient,
    page: dict[str, Any],
    *,
    tipo: str | None = None,
    ano: int | None = None,
) -> str:
    metadata = _page_metadata(page)
    page_number = metadata.get("page") if metadata else None
    if page_number is None:
        return ""
    return client.build_normas_page_url(page_number, tipo=tipo, ano=ano)


def _validated_next_url(client: SaplAPIClient, page: dict[str, Any]) -> str:
    next_url = page.get("next")
    return client.validate_pagination_url(next_url) if next_url else ""


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


def _remote_pdf_fingerprint(client: SaplAPIClient, payload: dict[str, Any]) -> str | None:
    pdf_url = str(payload.get("texto_integral") or "").strip()
    if not pdf_url:
        return None
    fingerprint = client.fingerprint_pdf(pdf_url)
    if not isinstance(fingerprint, str) or not fingerprint:
        raise RuntimeError("SAPL PDF fingerprint is incomplete")
    return fingerprint[:500]


@transaction.atomic
def _observe_pdf_fingerprint(sapl_id: int, fingerprint: str) -> tuple[bool, bool]:
    """Persist a baseline or mark a changed remote PDF for human review.

    Return ``(new_change, needs_candidate_staging)``. A previously pending
    change can request a staging retry without being counted as newly changed.
    The currently stored PDF and accepted text are never replaced here.
    """
    norma = Norma.objects.select_for_update().filter(sapl_id=sapl_id).first()
    if not norma:
        return False, False
    metadata = dict(norma.sapl_metadata) if isinstance(norma.sapl_metadata, dict) else {}
    baseline = str(metadata.get("_jurix_pdf_fingerprint") or "")
    pending = metadata.get("_jurix_pending_pdf_change")
    pending_fingerprint = pending.get("fingerprint") if isinstance(pending, dict) else ""
    if fingerprint == pending_fingerprint:
        if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
            return False, False
        candidate_id = pending.get("document_public_id") if isinstance(pending, dict) else None
        if not candidate_id:
            return False, True
        return False, not DocumentoNormativo.objects.filter(
            public_id=candidate_id, norma=norma
        ).exists()
    if not baseline:
        metadata["_jurix_pdf_fingerprint"] = fingerprint
        norma.sapl_metadata = metadata
        norma.save(update_fields=["sapl_metadata", "updated_at"])
        return False, False
    if fingerprint == baseline:
        return False, False

    metadata["_jurix_pending_pdf_change"] = {
        "fingerprint": fingerprint,
        "reason": "remote_pdf_fingerprint_changed",
        "detected_at": timezone.now().isoformat(),
    }
    norma.sapl_metadata = metadata
    norma.needs_review = True
    norma.processing_error = "PDF de origem alterado no SAPL; revisão necessária antes de substituir a fonte local."
    norma.save(
        update_fields=["sapl_metadata", "needs_review", "processing_error", "updated_at"]
    )
    return True, True


def _stage_pending_pdf_candidate(
    client: SaplAPIClient, payload: dict[str, Any], fingerprint: str
) -> bool:
    """Stage the pending SAPL PDF revision without promoting it to the Norma."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        return False
    sapl_id = int(payload["id"])
    pdf_url = str(payload.get("texto_integral") or "").strip()
    if not pdf_url:
        return False
    norma = Norma.objects.filter(sapl_id=sapl_id).first()
    if norma is None:
        return False
    metadata = norma.sapl_metadata if isinstance(norma.sapl_metadata, dict) else {}
    pending = metadata.get("_jurix_pending_pdf_change")
    if not isinstance(pending, dict) or pending.get("fingerprint") != fingerprint:
        return False
    if pending.get("document_public_id"):
        attached = DocumentoNormativo.objects.filter(
            public_id=pending["document_public_id"], norma=norma
        ).exists()
        if attached:
            return False

    from src.apps.ingestion.sapl_document_sync import stage_sapl_pdf_candidate

    candidate, _created = stage_sapl_pdf_candidate(
        client=client,
        norma=norma,
        pdf_url=pdf_url,
        remote_fingerprint=fingerprint,
    )
    return _attach_pdf_candidate(sapl_id, fingerprint, candidate)


@transaction.atomic
def _attach_pdf_candidate(
    sapl_id: int, fingerprint: str, candidate: DocumentoNormativo
) -> bool:
    norma = Norma.objects.select_for_update().filter(sapl_id=sapl_id).first()
    if norma is None:
        return False
    metadata = dict(norma.sapl_metadata) if isinstance(norma.sapl_metadata, dict) else {}
    pending = metadata.get("_jurix_pending_pdf_change")
    if not isinstance(pending, dict) or pending.get("fingerprint") != fingerprint:
        return False
    existing_id = pending.get("document_public_id")
    if existing_id and str(existing_id) != str(candidate.public_id):
        existing_candidate = DocumentoNormativo.objects.filter(
            public_id=existing_id, norma=norma
        ).exists()
        if existing_candidate:
            raise RuntimeError("Pending SAPL PDF change is already linked to another candidate")
    pending["document_public_id"] = str(candidate.public_id)
    pending["document_key"] = candidate.document_key
    metadata["_jurix_pending_pdf_change"] = pending
    norma.sapl_metadata = metadata
    norma.save(update_fields=["sapl_metadata", "updated_at"])
    return True


@transaction.atomic
def _mark_full_sweep_record(sapl_id: int, sweep_token: str, expected_count: int) -> None:
    norma = Norma.objects.select_for_update().filter(sapl_id=sapl_id).first()
    if not norma:
        raise RuntimeError(f"Norma SAPL {sapl_id} não foi persistida durante o sweep.")
    metadata = dict(norma.sapl_metadata) if isinstance(norma.sapl_metadata, dict) else {}
    metadata["_jurix_full_sweep_id"] = sweep_token
    metadata["_jurix_full_sweep_expected_count"] = expected_count
    norma.sapl_metadata = metadata
    norma.save(update_fields=["sapl_metadata", "updated_at"])


def _process_payload(
    payload: dict[str, Any],
    *,
    pdf_fingerprint: str | None = None,
    client: SaplAPIClient | None = None,
) -> tuple[str, int | None]:
    """Persist changed catalogue metadata without silently replacing accepted PDFs."""
    from src.apps.ingestion.tasks import _process_norma_data

    sapl_id = payload.get("id")
    if not sapl_id:
        raise ValueError("Norma sem id no payload SAPL")
    digest = payload_hash(payload)
    existing = (
        Norma.objects.filter(sapl_id=sapl_id)
        .only("status", "pdf_url", "pdf_path", "texto_consolidado", "sapl_metadata")
        .first()
    )
    accepted_source_exists = bool(
        existing
        and (
            existing.pdf_path
            or existing.texto_consolidado
            or existing.status
            in ("consolidated", "embedded", "segmented", "ocr_completed", "text_extracted")
        )
    )
    prior_metadata = existing.sapl_metadata if existing and isinstance(existing.sapl_metadata, dict) else {}
    prior_fingerprint = str(prior_metadata.get("_jurix_pdf_fingerprint") or "")
    remote_pdf_url = str(payload.get("texto_integral") or "").strip()
    pdf_url_changed = bool(existing and remote_pdf_url and remote_pdf_url != existing.pdf_url)
    pending_reason = ""
    if accepted_source_exists and pdf_fingerprint:
        if prior_fingerprint and prior_fingerprint != pdf_fingerprint:
            pending_reason = "remote_pdf_fingerprint_changed"
        elif not prior_fingerprint and pdf_url_changed:
            pending_reason = "remote_pdf_url_changed_without_baseline"

    stored = dict(payload)
    stored["_jurix_source_hash"] = digest
    if pdf_fingerprint and not pending_reason:
        stored["_jurix_pdf_fingerprint"] = pdf_fingerprint
    # Sync updates catalog metadata only. Candidate PDFs use the explicit,
    # review-pending staging path below; never fan out automatic downloads.
    _process_norma_data(
        stored,
        auto_download=False,
        preserve_existing_pdf=accepted_source_exists,
    )

    if accepted_source_exists and existing:
        norma = Norma.objects.get(sapl_id=sapl_id)
        metadata = dict(norma.sapl_metadata) if isinstance(norma.sapl_metadata, dict) else {}
        if pending_reason and pdf_fingerprint:
            if prior_fingerprint:
                metadata["_jurix_pdf_fingerprint"] = prior_fingerprint
            old_pending = prior_metadata.get("_jurix_pending_pdf_change")
            pending = (
                dict(old_pending)
                if isinstance(old_pending, dict)
                and old_pending.get("fingerprint") == pdf_fingerprint
                else {
                    "fingerprint": pdf_fingerprint,
                    "reason": pending_reason,
                    "detected_at": timezone.now().isoformat(),
                }
            )
            metadata["_jurix_pending_pdf_change"] = pending
            norma.needs_review = True
            norma.processing_error = (
                "PDF de origem alterado no SAPL; revisão necessária antes de substituir a fonte local."
            )
            norma.sapl_metadata = metadata
            norma.save(
                update_fields=["sapl_metadata", "needs_review", "processing_error", "updated_at"]
            )
            if client is not None:
                _stage_pending_pdf_candidate(client, payload, pdf_fingerprint)
        elif prior_fingerprint:
            # Keep the fingerprint of the accepted source until a candidate is reviewed.
            metadata["_jurix_pdf_fingerprint"] = prior_fingerprint
            norma.sapl_metadata = metadata
            norma.save(update_fields=["sapl_metadata", "updated_at"])
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
    limit = max(1, min(int(limit), 50))
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
    resume_url = state.last_cursor_url
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
    seen_page_urls: set[str] = set()
    seen_page_fingerprints: set[str] = set()

    try:
        for _ in range(max_pages):
            if not _renew(state.id, token):
                raise RuntimeError("Lease SAPL perdido durante a sincronização.")
            requested_url = resume_url
            page = (
                client._make_request_url(requested_url)
                if requested_url
                else client.fetch_normas_page(
                    limit=limit,
                    offset=offset,
                    tipo=tipo,
                    ano=ano,
                )
            )
            resume_url = ""
            results = page.get("results") or []
            if not results:
                stats["success"] = True
                stats["safe_stop"] = True
                offset = 0
                state.last_cursor = 0
                state.last_cursor_url = ""
                state.save(update_fields=["last_cursor", "last_cursor_url", "updated_at"])
                break

            metadata = _page_metadata(page)
            page_start = int(metadata["start_index"]) - 1 if metadata else offset
            skip_count = offset - page_start if requested_url else 0
            if skip_count < 0 or skip_count > len(results):
                raise RuntimeError(
                    "Cursor SAPL não corresponde à página retomada; sync não certificado."
                )
            current_page_url = requested_url or _page_start_url(
                client, page, tipo=tipo, ano=ano
            )
            next_url = _validated_next_url(client, page)
            if current_page_url:
                if current_page_url in seen_page_urls:
                    raise RuntimeError("SAPL repetiu URL de página durante sync incremental.")
                seen_page_urls.add(current_page_url)
                state.last_cursor_url = current_page_url
                state.save(update_fields=["last_cursor_url", "updated_at"])
            if next_url and next_url in seen_page_urls:
                raise RuntimeError("SAPL repetiu URL next durante sync incremental.")
            ids = [int(item["id"]) for item in results if item.get("id") is not None]
            if len(ids) != len(results) or len(set(ids)) != len(ids):
                raise RuntimeError("SAPL retornou ids ausentes ou repetidos na página incremental.")
            page_fingerprint = hashlib.sha256(
                ",".join(str(item) for item in ids).encode("ascii")
            ).hexdigest()
            if page_fingerprint in seen_page_fingerprints:
                raise RuntimeError("SAPL repetiu página durante sync incremental.")
            seen_page_fingerprints.add(page_fingerprint)

            stats["pages"] += 1
            page_unchanged = True

            for index, payload in enumerate(results):
                if index < skip_count:
                    continue
                sapl_id = payload.get("id")
                if not sapl_id:
                    stats["failed"] += 1
                    stats["errors"].append("Norma sem id no payload SAPL")
                    page_unchanged = False
                    offset = page_start + index
                    break
                remote_dt = _remote_timestamp(payload)
                if remote_dt and (newest_remote is None or remote_dt > newest_remote):
                    newest_remote = remote_dt
                digest = payload_hash(payload)
                pdf_fingerprint = _remote_pdf_fingerprint(client, payload)
                if _old_hash(int(sapl_id)) == digest:
                    pdf_changed = False
                    if pdf_fingerprint:
                        pdf_changed, needs_staging = _observe_pdf_fingerprint(
                            int(sapl_id), pdf_fingerprint
                        )
                        if needs_staging:
                            pdf_changed = (
                                _stage_pending_pdf_candidate(client, payload, pdf_fingerprint)
                                or pdf_changed
                            )
                    if pdf_changed:
                        page_unchanged = False
                        stats["changed"] += 1
                        SAPL_SYNC_RECORDS.labels(state="changed").inc()
                    else:
                        stats["unchanged"] += 1
                        SAPL_SYNC_RECORDS.labels(state="unchanged").inc()
                else:
                    page_unchanged = False
                    try:
                        digest, _ = _process_payload(
                            payload, pdf_fingerprint=pdf_fingerprint, client=client
                        )
                        stats["changed"] += 1
                        SAPL_SYNC_RECORDS.labels(state="changed").inc()
                    except Exception as exc:
                        stats["failed"] += 1
                        stats["errors"].append(f"Norma {sapl_id}: {exc}")
                        SAPL_SYNC_RECORDS.labels(state="failed").inc()
                        logger.error("Incremental SAPL sync failed for %s", sapl_id, exc_info=True)
                        offset = page_start + index
                        break
                offset = page_start + index + 1
                stats["fetched"] += 1
                state.last_cursor = offset
                state.last_sync_count = stats["fetched"]
                state.last_remote_timestamp = newest_remote
                state.save(
                    update_fields=[
                        "last_cursor",
                        "last_sync_count",
                        "last_remote_timestamp",
                        "last_cursor_url",
                        "updated_at",
                    ]
                )

            if stats["failed"]:
                # Preserve the current page URL and the first unprocessed row.
                stats["partial"] = True
                stats["cursor_end"] = offset
                break

            stats["cursor_end"] = offset

            if page_unchanged:
                stats["success"] = stats["failed"] == 0
                stats["safe_stop"] = True
                offset = 0
                state.last_cursor = 0
                state.last_cursor_url = ""
                state.save(update_fields=["last_cursor", "last_cursor_url", "updated_at"])
                break
            if next_url:
                resume_url = next_url
                state.last_cursor_url = next_url
                state.save(update_fields=["last_cursor_url", "updated_at"])
                continue

            if "next" in page and next_url == "":
                stats["success"] = True
                stats["safe_stop"] = True
                offset = 0
                state.last_cursor = 0
                state.last_cursor_url = ""
                state.save(update_fields=["last_cursor", "last_cursor_url", "updated_at"])
                break

            if len(results) < limit:
                stats["success"] = True
                stats["safe_stop"] = True
                offset = 0
                state.last_cursor = 0
                state.last_cursor_url = ""
                state.save(update_fields=["last_cursor", "last_cursor_url", "updated_at"])
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
    limit = max(1, min(int(limit), 50))
    scope = hashlib.sha256((_scope_fingerprint(None, None) + ":full").encode("utf-8")).hexdigest()
    state, token = _acquire_state(scope)
    if token is None:
        return {
            "success": True,
            "busy": True,
            "message": "Outra sincronização SAPL completa está em execução.",
        }
    client = SaplAPIClient()
    if state.full_sweep_token:
        sweep_token = state.full_sweep_token
        offset = int(state.last_cursor)
        resume_url = state.last_cursor_url
        fetched = int(state.last_sync_count)
        expected_count = state.full_sweep_expected_count
    else:
        sweep_token = uuid.uuid4().hex
        offset = 0
        resume_url = ""
        fetched = 0
        expected_count = None
        state.full_sweep_token = sweep_token
        state.full_sweep_expected_count = None
        state.last_cursor = 0
        state.last_cursor_url = ""
        state.last_sync_count = 0
        state.save(
            update_fields=[
                "full_sweep_token",
                "full_sweep_expected_count",
                "last_cursor",
                "last_cursor_url",
                "last_sync_count",
                "updated_at",
            ]
        )
    seen_ids = set(
        Norma.objects.filter(sapl_metadata___jurix_full_sweep_id=sweep_token)
        .exclude(sapl_id__isnull=True)
        .values_list("sapl_id", flat=True)
    )
    pages = 0
    changed = 0
    failed = 0
    max_pages = max(1, int(getattr(settings, "SAPL_FULL_SYNC_MAX_PAGES", 1000)))
    errors: list[str] = []
    seen_page_fingerprints: set[str] = set()
    pagination_urls: set[str] = set()

    try:
        for _ in range(max_pages):
            if not _renew(state.id, token):
                raise RuntimeError("Lease SAPL perdido durante o full sync.")
            requested_url = resume_url
            page = (
                client._make_request_url(requested_url)
                if requested_url
                else client.fetch_normas_page(limit=limit, offset=offset)
            )
            resume_url = ""
            results = page.get("results") or []
            if not results:
                if expected_count is None:
                    raise RuntimeError(
                        "Full sync sem contagem declarada não certifica cobertura; "
                        "nenhuma ausência remota foi marcada."
                    )
                if fetched < expected_count:
                    raise RuntimeError(
                        f"Full sync incompleto: recebido {fetched} de {expected_count}; "
                        "nenhuma ausência remota foi marcada."
                    )
                break
            if "count" in page:
                try:
                    page_count = int(page["count"])
                    if expected_count is not None and expected_count != page_count:
                        raise RuntimeError("Contagem SAPL mudou durante full sync; scan não certificado.")
                    expected_count = page_count
                    state.full_sweep_expected_count = expected_count
                    state.save(update_fields=["full_sweep_expected_count", "updated_at"])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Contagem SAPL inválida; scan não certificado.") from exc
                metadata = _page_metadata(page)
                page_start = (
                    int(metadata["start_index"]) - 1 if metadata else offset
                )
                skip_count = offset - page_start if requested_url else 0
                if skip_count < 0 or skip_count > len(results):
                    raise RuntimeError(
                        "Cursor SAPL não corresponde à página retomada; scan não certificado."
                    )
                if fetched + len(results) - skip_count > expected_count:
                    raise RuntimeError("SAPL retornou mais registros que a contagem declarada.")
            elif expected_count is None:
                raise RuntimeError(
                    "SAPL não declarou a contagem; full sync não pode certificar cobertura."
                )
            if "count" not in page:
                metadata = _page_metadata(page)
                page_start = (
                    int(metadata["start_index"]) - 1 if metadata else offset
                )
                skip_count = offset - page_start if requested_url else 0
                if skip_count < 0 or skip_count > len(results):
                    raise RuntimeError(
                        "Cursor SAPL não corresponde à página retomada; scan não certificado."
                    )
            next_url = _validated_next_url(client, page)
            if next_url:
                if next_url in pagination_urls:
                    raise RuntimeError("SAPL repetiu URL de paginação; scan não certificado.")
                pagination_urls.add(next_url)
            current_page_url = requested_url or _page_start_url(client, page)
            page_ids = [int(item["id"]) for item in results if item.get("id") is not None]
            if len(page_ids) != len(results):
                raise RuntimeError("SAPL retornou registro sem id; sweep não certificado.")
            if len(set(page_ids)) != len(page_ids):
                raise RuntimeError("SAPL repetiu ids dentro da página; sweep não certificado.")
            page_fingerprint = hashlib.sha256(
                ",".join(str(item) for item in page_ids).encode("ascii")
            ).hexdigest()
            if page_fingerprint in seen_page_fingerprints:
                raise RuntimeError("SAPL repetiu uma página; nenhuma ausência remota foi marcada.")
            seen_page_fingerprints.add(page_fingerprint)
            resumed_ids = set(page_ids[:skip_count]) if requested_url else set()
            overlap = seen_ids.intersection(page_ids) - resumed_ids
            if overlap:
                raise RuntimeError(
                    "Páginas SAPL sobrepostas; cobertura não certificada e nenhuma ausência marcada."
                )
            pages += 1
            if current_page_url:
                state.last_cursor_url = current_page_url
                state.save(update_fields=["last_cursor_url", "updated_at"])
            for index, payload in enumerate(results):
                if index < skip_count:
                    continue
                current_offset = page_start + index
                sapl_id = payload.get("id")
                if not sapl_id:
                    failed += 1
                    errors.append("Norma sem id no payload SAPL")
                    offset = current_offset
                    break
                sapl_id = int(sapl_id)
                digest = payload_hash(payload)
                pdf_fingerprint = _remote_pdf_fingerprint(client, payload)
                if _old_hash(sapl_id) == digest:
                    pdf_changed = False
                    if pdf_fingerprint:
                        pdf_changed, needs_staging = _observe_pdf_fingerprint(
                            sapl_id, pdf_fingerprint
                        )
                        if needs_staging:
                            pdf_changed = (
                                _stage_pending_pdf_candidate(client, payload, pdf_fingerprint)
                                or pdf_changed
                            )
                    if pdf_changed:
                        changed += 1
                        SAPL_SYNC_RECORDS.labels(state="changed").inc()
                    else:
                        SAPL_SYNC_RECORDS.labels(state="unchanged").inc()
                else:
                    try:
                        digest, _ = _process_payload(
                            payload, pdf_fingerprint=pdf_fingerprint, client=client
                        )
                        changed += 1
                        SAPL_SYNC_RECORDS.labels(state="changed").inc()
                    except Exception as exc:
                        failed += 1
                        errors.append(f"Norma {sapl_id}: {exc}")
                        SAPL_SYNC_RECORDS.labels(state="failed").inc()
                        offset = current_offset
                        break
                _mark_full_sweep_record(sapl_id, sweep_token, expected_count)
                seen_ids.add(sapl_id)
                fetched += 1
                offset = current_offset + 1
                state.last_cursor = offset
                state.last_sync_count = fetched
                state.save(
                    update_fields=[
                        "last_cursor",
                        "last_sync_count",
                        "last_cursor_url",
                        "updated_at",
                    ]
                )
            if failed:
                raise RuntimeError(
                    f"Full sync interrompido após falha em {failed} registro(s); "
                    "cursor preservado para retomada."
                )
            if fetched > expected_count:
                raise RuntimeError("SAPL retornou mais registros que a contagem declarada.")
            if fetched == expected_count:
                if next_url:
                    raise RuntimeError("SAPL informou próxima página após a contagem declarada.")
                break
            if next_url:
                resume_url = next_url
                state.last_cursor_url = next_url
                state.save(update_fields=["last_cursor_url", "updated_at"])
                continue
            if not next_url and "next" in page:
                if fetched != expected_count:
                    raise RuntimeError("SAPL encerrou a paginação antes da contagem declarada.")
                break
            if not next_url and len(results) < limit:
                raise RuntimeError(
                    "SAPL encerrou antes da contagem declarada; sweep permanece incompleto."
                )
        else:
            raise RuntimeError(
                f"Full sync excedeu SAPL_FULL_SYNC_MAX_PAGES={max_pages}; "
                "nenhuma ausência remota foi marcada."
            )

        if failed:
            raise RuntimeError(
                f"Full sync terminou com {failed} registro(s) que não puderam ser processados."
            )

        if expected_count is None or fetched != expected_count:
            raise RuntimeError("Full sync não cobriu a contagem SAPL; ausência não certificada.")

        with transaction.atomic():
            if seen_ids:
                missing_qs = Norma.objects.filter(sapl_id__isnull=False).exclude(
                    sapl_id__in=seen_ids
                )
                missing_count = missing_qs.update(
                    needs_review=True,
                    processing_error=(
                        "Norma não localizada no SAPL na última sincronização completa."
                    ),
                )
            else:
                missing_count = 0

            state.full_sweep_token = ""
            state.full_sweep_expected_count = None
            state.last_cursor = 0
            state.last_cursor_url = ""
            state.last_sync_count = fetched
            state.save(
                update_fields=[
                    "full_sweep_token",
                    "full_sweep_expected_count",
                    "last_cursor",
                    "last_cursor_url",
                    "last_sync_count",
                    "updated_at",
                ]
            )
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
