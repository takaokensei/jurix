"""QA-only, idempotent staging for official Natal DOM edition PDFs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.operations.models import SaplSyncState
from src.clients.dom_natal.client import DomNatalClient, DomNatalEdition, DomNatalPdf


class DomNatalCandidateError(RuntimeError):
    """A DOM edition could not be safely recorded as an unreviewed candidate."""


DEFAULT_DOM_LOOKBACK_MONTHS = 3
MAX_DOM_LOOKBACK_MONTHS = 12
DEFAULT_DOM_NEW_EDITION_BATCH = 5
MAX_DOM_NEW_EDITION_BATCH = 10
DOM_SYNC_LEASE_SECONDS = 900


def _month_scopes(as_of: date, lookback_months: int) -> list[tuple[int, int]]:
    scopes = []
    year, month = as_of.year, as_of.month
    for _ in range(lookback_months):
        scopes.append((year, month))
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return scopes


def _scope_fingerprint(year: int, month: int) -> str:
    scope = json.dumps(
        {"month": month, "year": year}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _require_dom_qa() -> None:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE")
        not in {
            "config.settings_normative_qa",
            "config.settings_normative_container_qa",
        }
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        or not getattr(settings, "QA_ROOT", None)
    ):
        raise DomNatalCandidateError("DOM sync requires the isolated normative QA profile")


def inspect_dom_natal_editions(
    *,
    client: DomNatalClient | None = None,
    as_of: date | None = None,
    lookback_months: int = DEFAULT_DOM_LOOKBACK_MONTHS,
) -> dict:
    """Read the official monthly catalog and compare it with QA candidates.

    This diagnostic never downloads PDFs, creates checkpoints, or writes files
    or database rows. It reports counts only, not edition labels or document
    text.
    """
    _require_dom_qa()
    if not isinstance(lookback_months, int) or not 1 <= lookback_months <= MAX_DOM_LOOKBACK_MONTHS:
        raise ValueError(f"lookback_months must be between 1 and {MAX_DOM_LOOKBACK_MONTHS}")
    client = client or DomNatalClient()
    checked_at = as_of or timezone.localdate()
    scopes = []
    for year, month in _month_scopes(checked_at, lookback_months):
        try:
            editions = client.list_editions(month=month, year=year)
            identities = [edition.identity for edition in editions]
            existing = set(
                DocumentoNormativo.objects.filter(
                    source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
                    source_ref__in=identities,
                ).values_list("source_ref", "official_url")
            )
            missing_count = sum(
                (edition.identity, edition.official_url) not in existing for edition in editions
            )
            scopes.append(
                {
                    "year": year,
                    "month": month,
                    "catalog_status": "available",
                    "edition_count": len(editions),
                    "known_url_count": len(editions) - missing_count,
                    "new_candidate_count": missing_count,
                }
            )
        except Exception as exc:
            scopes.append(
                {
                    "year": year,
                    "month": month,
                    "catalog_status": "unavailable",
                    "error_class": type(exc).__name__,
                }
            )
    statuses = {scope["catalog_status"] for scope in scopes}
    overall = (
        "available"
        if statuses == {"available"}
        else "unavailable"
        if statuses == {"unavailable"}
        else "partial"
    )
    return {
        "source": "dom_natal",
        "catalog_status": overall,
        "read_only": True,
        "scopes": scopes,
    }


@transaction.atomic
def _acquire_dom_scope(year: int, month: int) -> tuple[int, str] | None:
    state, _ = SaplSyncState.objects.select_for_update().get_or_create(
        source="dom_natal",
        filter_fingerprint=_scope_fingerprint(year, month),
    )
    now = timezone.now()
    if state.lease_until and state.lease_until > now:
        return None
    token = uuid.uuid4().hex
    state.last_started_at = now
    state.lease_until = now + timedelta(seconds=DOM_SYNC_LEASE_SECONDS)
    state.lease_token = token
    state.last_error = ""
    state.save(
        update_fields=["last_started_at", "lease_until", "lease_token", "last_error", "updated_at"]
    )
    return state.pk, token


@transaction.atomic
def _release_dom_scope(
    state_id: int,
    token: str,
    *,
    success: bool,
    error: str = "",
    cursor: int = 0,
    cursor_url: str = "",
    expected_count: int | None = None,
    sync_count: int = 0,
) -> None:
    now = timezone.now()
    values = {
        "lease_until": None,
        "lease_token": "",
        "last_cursor": cursor,
        "last_cursor_url": cursor_url[:2048],
        "full_sweep_token": "",
        "full_sweep_expected_count": expected_count,
        "last_sync_count": sync_count,
        "last_error": error[:4000],
    }
    if success:
        values["last_success_at"] = now
        values["last_full_sync_at"] = now
    updated = SaplSyncState.objects.filter(pk=state_id, lease_token=token).update(**values)
    if not updated:
        raise DomNatalCandidateError("DOM sync lease changed before checkpoint release")


def sync_dom_natal_editions(
    *,
    client: DomNatalClient | None = None,
    as_of: date | None = None,
    lookback_months: int = DEFAULT_DOM_LOOKBACK_MONTHS,
    max_new_total: int = DEFAULT_DOM_NEW_EDITION_BATCH,
) -> dict:
    """Find and stage new official editions in a bounded, overlapping QA sweep.

    Every scanned month is re-listed so delayed publications are discovered.
    Existing identity+URL pairs are skipped; a new URL for an existing edition
    is staged as a new document version. Excess new editions are left for the
    next run, and the scope remains degraded until the backlog is consumed.
    """
    _require_dom_qa()
    if not isinstance(lookback_months, int) or not 1 <= lookback_months <= MAX_DOM_LOOKBACK_MONTHS:
        raise ValueError(f"lookback_months must be between 1 and {MAX_DOM_LOOKBACK_MONTHS}")
    if not isinstance(max_new_total, int) or not 1 <= max_new_total <= MAX_DOM_NEW_EDITION_BATCH:
        raise ValueError(f"max_new_total must be between 1 and {MAX_DOM_NEW_EDITION_BATCH}")

    client = client or DomNatalClient()
    checked_at = as_of or timezone.localdate()
    scope_results = []
    processed_total = 0
    for year, month in _month_scopes(checked_at, lookback_months):
        lease = _acquire_dom_scope(year, month)
        if lease is None:
            scope_results.append({"year": year, "month": month, "status": "running"})
            continue

        state_id, token = lease
        staged_count = 0
        processed_count = 0
        last_edition = None
        try:
            editions = client.list_editions(month=month, year=year)
            source_refs = [edition.identity for edition in editions]
            existing = set(
                DocumentoNormativo.objects.filter(
                    source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
                    source_ref__in=source_refs,
                ).values_list("source_ref", "official_url")
            )
            missing = [
                edition
                for edition in editions
                if (edition.identity, edition.official_url) not in existing
            ]
            remaining_budget = max(0, max_new_total - processed_total)
            batch = missing[:remaining_budget]
            for edition in batch:
                downloaded = client.download_edition(edition)
                _, created = stage_dom_edition_candidate(
                    edition=edition, downloaded=downloaded
                )
                staged_count += int(created)
                processed_count += 1
                processed_total += 1
                last_edition = edition

            remaining = max(0, len(missing) - processed_count)
            complete = remaining == 0
            _release_dom_scope(
                state_id,
                token,
                success=complete,
                error="" if complete else f"edition_batch_incomplete:{remaining}",
                cursor=(last_edition.number if last_edition else max((e.number for e in editions), default=0)),
                cursor_url=(last_edition.official_url if last_edition else ""),
                expected_count=len(editions),
                sync_count=staged_count,
            )
            scope_results.append(
                {
                    "year": year,
                    "month": month,
                    "status": "current" if complete else "partial",
                    "edition_count": len(editions),
                    "new_candidates": staged_count,
                    "remaining_candidates": remaining,
                }
            )
        except Exception as exc:
            _release_dom_scope(
                state_id,
                token,
                success=False,
                error=f"source_error:{type(exc).__name__}",
                cursor=last_edition.number if last_edition else 0,
                cursor_url=last_edition.official_url if last_edition else "",
                sync_count=staged_count,
            )
            scope_results.append(
                {"year": year, "month": month, "status": "unavailable", "error_class": type(exc).__name__}
            )

    statuses = {scope["status"] for scope in scope_results}
    overall = "current" if statuses == {"current"} else "running" if statuses == {"running"} else "degraded"
    return {"source": "dom_natal", "status": overall, "scopes": scope_results}


def _qa_storage_root() -> Path:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise DomNatalCandidateError("DOM edition staging requires JURIX_QA_ONLY=1")
    qa_root_value = getattr(settings, "QA_ROOT", None)
    if not qa_root_value:
        raise DomNatalCandidateError("DOM edition staging requires the isolated QA root")
    qa_root = Path(qa_root_value).resolve()
    temp_root_value = os.environ.get("TEMP") or os.environ.get("TMP")
    if not temp_root_value:
        raise DomNatalCandidateError("DOM edition staging requires a system temporary root")
    temp_root = Path(temp_root_value).resolve()
    if qa_root == temp_root or not qa_root.is_relative_to(temp_root):
        raise DomNatalCandidateError("DOM edition staging root is outside the system temp directory")

    configured = getattr(settings, "NORMATIVE_ARCHIVE_ROOT", None)
    archive_root = (
        Path(configured).resolve()
        if configured
        else (qa_root / "normative-archive").resolve()
    )
    if not archive_root.is_relative_to(qa_root) or archive_root == qa_root:
        raise DomNatalCandidateError("DOM edition storage escaped the isolated QA root")
    archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root


def _store_pdf(content: bytes, expected_sha256: str, root: Path) -> str:
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise DomNatalCandidateError("DOM edition failed the PDF structure check")
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise DomNatalCandidateError("DOM edition checksum does not match the downloaded bytes")

    relative_key = Path("sha256") / actual_sha256[:2] / actual_sha256[2:4] / f"{actual_sha256}.pdf"
    destination = (root / relative_key).resolve()
    if not destination.is_relative_to(root):
        raise DomNatalCandidateError("DOM edition path escaped the QA storage root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != actual_sha256:
            raise DomNatalCandidateError("Existing DOM content-addressed blob has a hash conflict")
        return relative_key.as_posix()

    staging = root / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=staging, suffix=".pdf", delete=False) as temporary:
        temp_path = Path(temporary.name)
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        try:
            os.link(temp_path, destination)
        except FileExistsError as exc:
            if hashlib.sha256(destination.read_bytes()).hexdigest() != actual_sha256:
                raise DomNatalCandidateError(
                    "Concurrent DOM blob has a hash conflict"
                ) from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return relative_key.as_posix()


def stage_dom_edition_candidate(
    *, edition: DomNatalEdition, downloaded: DomNatalPdf
) -> tuple[DocumentoNormativo, bool]:
    """Persist one validated edition without accepting or consolidating its acts.

    This operation is deliberately QA-only. The edition remains an unreviewed
    public-record candidate with unknown use conditions; it is not attached to a
    Norma because one gazette PDF may contain many unrelated acts.
    """
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        raise DomNatalCandidateError("Normative document staging is disabled")
    if downloaded.edition.identity != edition.identity:
        raise DomNatalCandidateError("Downloaded DOM PDF belongs to a different edition")
    official_url = DomNatalClient._validate_url(edition.official_url, pdf=True)
    root = _qa_storage_root()
    storage_key = _store_pdf(downloaded.content, downloaded.sha256, root)
    document_key = hashlib.sha256(
        f"dom-natal:{edition.identity}:sha256:{downloaded.sha256}".encode()
    ).hexdigest()
    filename = edition.official_url.rsplit("/", 1)[-1]
    defaults = {
        "norma": None,
        "source_kind": DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
        "source_ref": edition.identity,
        "original_filename": filename[:500],
        "role": DocumentoNormativo.Role.UNDETERMINED,
        "storage_key": storage_key,
        "size_bytes": downloaded.size_bytes,
        "content_sha256": downloaded.sha256,
        "official_url": official_url,
        "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
        "metadata_json": {
            "source": "dom_natal",
            "edition_identity": edition.identity,
            "edition_year": edition.year,
            "edition_number": edition.number,
            "publication_date": edition.publication_date.isoformat(),
            "special_edition": edition.special,
            "label": edition.label[:1000],
            "candidate_reason": "official_gazette_edition",
        },
        "extraction_status": DocumentoNormativo.ExtractionStatus.PENDING,
        "review_status": DocumentoNormativo.ReviewStatus.PENDING,
    }
    document, created = DocumentoNormativo.objects.get_or_create(
        document_key=document_key, defaults=defaults
    )
    if document.content_sha256 != downloaded.sha256 or document.storage_key != storage_key:
        raise DomNatalCandidateError("DOM document identity is already bound to different bytes")
    if document.source_ref != edition.identity or document.official_url != official_url:
        raise DomNatalCandidateError("DOM document identity conflicts with stored provenance")
    return document, created


def repair_dom_edition_blob_qa(
    *,
    year: int,
    month: int,
    edition_number: int,
    apply: bool = False,
    client: DomNatalClient | None = None,
) -> dict:
    """Restore one missing QA PDF only when official bytes match immutable metadata."""
    _require_dom_qa()
    if not 2001 <= year <= 2100 or not 1 <= month <= 12 or edition_number < 1:
        raise ValueError("year, month or edition number is outside the supported range")

    client = client or DomNatalClient()
    matches = [
        edition
        for edition in client.list_editions(month=month, year=year)
        if edition.number == edition_number
    ]
    if len(matches) != 1:
        raise DomNatalCandidateError("DOM edition identity is missing or ambiguous")
    edition = matches[0]
    records = list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
            source_ref=edition.identity,
            official_url=DomNatalClient._validate_url(edition.official_url, pdf=True),
        )[:2]
    )
    if len(records) != 1:
        raise DomNatalCandidateError("Exactly one existing QA candidate is required for repair")
    document = records[0]

    raw_key = str(document.storage_key or "").replace("\\", "/")
    key = PurePosixPath(raw_key)
    if not raw_key or key.is_absolute() or ".." in key.parts or (len(raw_key) > 1 and raw_key[1] == ":"):
        raise DomNatalCandidateError("Stored DOM blob key is not a safe relative path")
    root = _qa_storage_root()
    destination = (root / Path(*key.parts)).resolve()
    if not destination.is_relative_to(root):
        raise DomNatalCandidateError("Stored DOM blob path escaped the QA archive root")
    if destination.is_file():
        existing = destination.read_bytes()
        if len(existing) != document.size_bytes or hashlib.sha256(existing).hexdigest() != document.content_sha256:
            raise DomNatalCandidateError("Existing DOM blob conflicts with immutable metadata")
        return {"status": "already_available", "read_only": True, "restored": False}
    if not apply:
        return {"status": "missing_blob", "read_only": True, "restored": False}

    downloaded = client.download_edition(edition)
    if (
        downloaded.edition.identity != document.source_ref
        or downloaded.sha256 != document.content_sha256
        or downloaded.size_bytes != document.size_bytes
    ):
        raise DomNatalCandidateError("Official PDF does not match the existing immutable record")
    expected_document_key = hashlib.sha256(
        f"dom-natal:{edition.identity}:sha256:{downloaded.sha256}".encode()
    ).hexdigest()
    if document.document_key != expected_document_key:
        raise DomNatalCandidateError("Existing candidate key conflicts with the official PDF identity")

    staged, created = stage_dom_edition_candidate(edition=edition, downloaded=downloaded)
    if created or staged.pk != document.pk or staged.storage_key != document.storage_key:
        raise DomNatalCandidateError("Repair unexpectedly changed the existing candidate record")
    repaired = destination.read_bytes()
    if len(repaired) != document.size_bytes or hashlib.sha256(repaired).hexdigest() != document.content_sha256:
        raise DomNatalCandidateError("Restored QA PDF failed its recorded integrity check")
    return {"status": "restored", "read_only": False, "restored": True}
