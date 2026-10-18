"""Conservative, versioned coverage evidence for legal-corpus scopes.

Coverage is never inferred from a successful import or a global row count. A
reviewed record describes only its declared source/jurisdiction/series/range.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _coverage_date(value: Any) -> str | None:
    """Normalize a date-only coverage bound; reject datetimes and bad strings."""
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scope_identity(*, source, jurisdiction, series, period_start, period_end) -> dict[str, Any]:
    return {
        "source": str(source).strip().casefold(),
        "jurisdiction": str(jurisdiction).strip().upper(),
        "series": str(series).strip().casefold(),
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
    }


def _safe_intervals(value: Any) -> list[dict[str, str]] | None:
    """Return only valid public date bounds; malformed data stays unknown."""
    if not isinstance(value, list):
        return None
    safe: list[dict[str, str]] = []
    for interval in value:
        if not isinstance(interval, dict):
            return None
        bounds: dict[str, str] = {}
        for key in ("start", "end"):
            raw = interval.get(key)
            normalized = _coverage_date(raw)
            if normalized is None:
                return None
            bounds[key] = normalized
        if bounds["start"] > bounds["end"]:
            return None
        safe.append(bounds)
    return safe


def _coverage_row(scope: Any) -> dict[str, Any]:
    if isinstance(scope, dict):
        row = scope
    else:
        row = {
            "source": scope.source,
            "jurisdiction": scope.jurisdiction,
            "series": scope.series,
            "period_start": scope.period_start,
            "period_end": scope.period_end,
            "checked_until": scope.checked_until,
            "source_checksum": scope.source_checksum,
            "coverage_status": scope.coverage_status,
            "missing_intervals": scope.missing_intervals,
            "pending_review_count": scope.pending_review_count,
            "last_success_at": scope.last_success_at,
        }
    missing_intervals = _safe_intervals(row.get("missing_intervals"))
    pending_review = row.get("pending_review_count", row.get("pending_review"))
    if (
        isinstance(pending_review, bool)
        or not isinstance(pending_review, int)
        or pending_review < 0
    ):
        pending_review = None

    source_value = str(row.get("source") or "").strip().casefold()
    jurisdiction_value = str(row.get("jurisdiction") or "").strip().upper()
    series_value = str(row.get("series") or "").strip().casefold()
    source_valid = bool(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", source_value))
    jurisdiction_valid = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,99}", jurisdiction_value))
    series_valid = bool(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", series_value))
    coverage_status = str(row.get("coverage_status") or "unknown")
    period_start = _coverage_date(row.get("period_start"))
    raw_period_end = row.get("period_end")
    period_end = _coverage_date(raw_period_end)
    checked_until = _coverage_date(row.get("checked_until"))
    period_bounds_valid = bool(
        period_start
        and (raw_period_end is None or period_end)
        and (period_end is None or period_start <= period_end)
    )
    checksum_value = str(row.get("source_checksum") or "").lower()
    source_checksum = checksum_value if re.fullmatch(r"[a-f0-9]{64}", checksum_value) else None
    if coverage_status == "reviewed" and not (
        source_valid
        and jurisdiction_valid
        and series_valid
        and period_bounds_valid
        and checked_until
        and source_checksum
        and missing_intervals is not None
        and pending_review is not None
    ):
        coverage_status = "partial"

    return {
        "source": source_value if source_valid else "unknown",
        "jurisdiction": jurisdiction_value if jurisdiction_valid else "unknown",
        "series": series_value if series_valid else "unknown",
        "period_start": period_start,
        "period_end": period_end,
        "checked_until": checked_until,
        "source_checksum": source_checksum,
        "coverage_status": coverage_status,
        "missing_intervals": missing_intervals,
        "pending_review": pending_review,
        "last_success_at": _iso(row.get("last_success_at")),
    }


def build_corpus_coverage(
    corpus_revision: dict[str, Any] | None = None,
    *,
    scopes: list[Any] | tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    """Build a safe DTO; without explicit source scopes, report unknown."""
    revision = corpus_revision or {}
    rows = [_coverage_row(scope) for scope in (scopes or ())]
    base = {
        "coverage_status": "unknown",
        "corpus_revision": {
            "revision": revision.get("revision"),
            "digest": revision.get("digest"),
        },
        "checked_until": None,
        "sources_checked": [],
        "missing_intervals": None,
        "pending_review": None,
        "reason": "no_reviewed_coverage_scope",
    }
    if not rows:
        return base

    allowed_statuses = {"unknown", "partial", "reviewed"}
    for row in rows:
        if row["coverage_status"] not in allowed_statuses:
            row["coverage_status"] = "unknown"
    statuses = {row["coverage_status"] for row in rows}
    if statuses == {"reviewed"}:
        status = "reviewed"
    elif "partial" in statuses or "reviewed" in statuses:
        status = "partial"
    else:
        status = "unknown"

    cutoffs = [row["checked_until"] for row in rows]
    checked_until = min(cutoffs) if all(cutoffs) else None
    missing_intervals = []
    for row in rows:
        for interval in row["missing_intervals"] or []:
            if isinstance(interval, dict):
                safe_interval = {
                    key: str(interval[key])[:10]
                    for key in ("start", "end")
                    if interval.get(key) is not None
                }
                missing_intervals.append({
                    "source": row["source"],
                    "jurisdiction": row["jurisdiction"],
                    "series": row["series"],
                    **safe_interval,
                })
    pending_values = [row["pending_review"] for row in rows]
    has_unresolved_scope = any(
        row["coverage_status"] != "reviewed"
        or row["missing_intervals"] is None
        or bool(row["missing_intervals"])
        or not isinstance(row["pending_review"], int)
        or isinstance(row["pending_review"], bool)
        or row["pending_review"] != 0
        or row["checked_until"] is None
        for row in rows
    )
    if status == "reviewed" and has_unresolved_scope:
        status = "partial"
    base.update(
        {
            "coverage_status": status,
        "scope_limited": True,
            "checked_until": checked_until,
            "sources_checked": rows,
            "missing_intervals": (
                missing_intervals
                if all(row["missing_intervals"] is not None for row in rows)
                else None
            ),
            "pending_review": sum(pending_values) if all(isinstance(value, int) for value in pending_values) else None,
            "reason": "registered_scopes_only_not_a_universal_completeness_claim",
        }
    )
    return base


@transaction.atomic
def record_corpus_coverage_scope(
    *,
    source: str,
    jurisdiction: str,
    series: str,
    coverage_status: str,
    period_start: date | None = None,
    period_end: date | None = None,
    checked_until: date | None = None,
    source_checksum: str = "",
    last_success_at: datetime | None = None,
    missing_intervals: list[dict[str, Any]] | None = None,
    pending_review_count: int | None = None,
    reviewer=None,
    reason: str = "",
) -> tuple[Any, bool]:
    """Append one coverage snapshot; reviewed scopes require explicit staff approval."""
    from src.apps.operations.models import CorpusCoverageScope, CorpusRevision

    if coverage_status not in CorpusCoverageScope.Status.values:
        raise ValidationError("Estado de cobertura inválido.")
    source = str(source or "").strip().casefold()
    jurisdiction = str(jurisdiction or "").strip().upper()
    series = str(series or "").strip().casefold()
    if not source or not jurisdiction or not series:
        raise ValidationError("Fonte, jurisdição e série são obrigatórias.")
    if source_checksum and not re.fullmatch(r"[a-fA-F0-9]{64}", source_checksum):
        raise ValidationError("Checksum da fonte deve ser SHA-256 hexadecimal.")
    if missing_intervals is not None and not isinstance(missing_intervals, list):
        raise ValidationError("Intervalos ausentes devem ser uma lista JSON.")
    if pending_review_count is not None and pending_review_count < 0:
        raise ValidationError("Pendências não podem ser negativas.")
    if coverage_status == CorpusCoverageScope.Status.REVIEWED:
        if not (
            reviewer
            and reviewer.is_active
            and reviewer.is_staff
            and reviewer.has_perm("operations.add_corpuscoveragescope")
            and reason.strip()
            and checked_until
            and period_start
            and source_checksum
            and missing_intervals is not None
            and pending_review_count is not None
        ):
            raise PermissionDenied(
                "Escopo revisado exige permissão de curadoria, justificativa e data de corte."
            )
    elif reviewer is not None or reason.strip():
        # A review identity/reason must not be attached to an automated partial snapshot.
        raise ValidationError("Identidade e justificativa de revisor só cabem em escopo revisado.")

    if period_start and period_end and period_start > period_end:
        raise ValidationError("O início do período não pode ser posterior ao fim.")

    revision = CorpusRevision.objects.select_for_update().get(key="municipal")
    scope = _scope_identity(
        source=source,
        jurisdiction=jurisdiction,
        series=series,
        period_start=period_start,
        period_end=period_end,
    )
    snapshot = {
        **scope,
        "checked_until": _iso(checked_until),
        "source_checksum": source_checksum.lower(),
        "corpus_revision_number": revision.revision,
        "corpus_revision_digest": revision.digest,
        "last_success_at": _iso(last_success_at),
        "coverage_status": coverage_status,
        "missing_intervals": missing_intervals,
        "pending_review_count": pending_review_count,
        "reviewer_id": reviewer.pk if reviewer else None,
        "review_reason": reason.strip(),
    }
    fingerprint = _digest(snapshot)
    defaults = {
        "scope_key": _digest(scope),
        "source": source,
        "jurisdiction": jurisdiction,
        "series": series,
        "period_start": period_start,
        "period_end": period_end,
        "checked_until": checked_until,
        "source_checksum": source_checksum.lower(),
        "corpus_revision_number": revision.revision,
        "corpus_revision_digest": revision.digest,
        "last_success_at": last_success_at,
        "coverage_status": coverage_status,
        "missing_intervals": missing_intervals,
        "pending_review_count": pending_review_count,
        "reviewed_by": reviewer,
        "reviewed_at": timezone.now() if reviewer else None,
        "review_reason": reason.strip(),
    }
    try:
        row, created = CorpusCoverageScope.objects.get_or_create(
            record_fingerprint=fingerprint, defaults=defaults
        )
    except IntegrityError:
        row = CorpusCoverageScope.objects.get(record_fingerprint=fingerprint)
        created = False
    return row, created


def current_corpus_coverage(corpus_revision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read latest registered scope snapshots for the exact active corpus digest."""
    if corpus_revision is None:
        try:
            from src.processing.corpus_identity import get_corpus_revision

            corpus_revision = get_corpus_revision()
        except (DatabaseError, RuntimeError):
            corpus_revision = None
    revision = corpus_revision or {}
    digest = str(revision.get("digest") or "")
    if not digest:
        return build_corpus_coverage(revision)
    try:
        from src.apps.operations.models import CorpusCoverageScope

        candidates = CorpusCoverageScope.objects.filter(corpus_revision_digest=digest).order_by(
            "scope_key", "-created_at", "-pk"
        )
        latest = {}
        for scope in candidates.iterator(chunk_size=200):
            latest.setdefault(scope.scope_key, scope)
        return build_corpus_coverage(revision, scopes=list(latest.values()))
    except (DatabaseError, RuntimeError):
        # A rolling deployment before the additive migration must remain safe.
        return build_corpus_coverage(revision)
