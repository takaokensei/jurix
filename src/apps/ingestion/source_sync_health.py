"""Read-only, source-scoped freshness summary for operational sync checkpoints."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from src.apps.operations.models import SaplSyncState


def get_source_sync_health(
    source: str,
    *,
    now=None,
    max_age: timedelta = timedelta(hours=36),
    full_sweep_max_age: timedelta = timedelta(days=8),
) -> dict:
    """Report freshness without implying corpus completeness or legal validity.

    Raw exception text is intentionally omitted. A source can be "fresh" only
    when every known scope has a recent success and no newer failed attempt.
    ``uninitialized_scope_count`` means no successful run has completed and
    therefore includes partial cursors; ``partial_scope_count`` is a subset,
    not an additional disjoint category.
    """
    if not source or not source.strip():
        raise ValueError("source must be a non-empty identifier")
    if max_age.total_seconds() <= 0:
        raise ValueError("max_age must be positive")
    if full_sweep_max_age.total_seconds() <= 0:
        raise ValueError("full_sweep_max_age must be positive")
    checked_at = now or timezone.now()
    states = list(SaplSyncState.objects.filter(source=source).order_by("filter_fingerprint"))
    if not states:
        return {
            "source": source,
            "status": "not_configured",
            "scope_count": 0,
            "checked_at": checked_at,
            "last_success_at": None,
            "last_success_age_seconds": None,
            "failed_scope_count": 0,
            "uninitialized_scope_count": 0,
            "partial_scope_count": 0,
            "stale_scope_count": 0,
            "full_sweep_scope_count": 0,
            "active_scope_count": 0,
            "has_error": False,
        }

    active = [state for state in states if state.lease_until and state.lease_until > checked_at]
    initialized = [state for state in states if state.last_success_at is not None]
    active_ids = {state.pk for state in active}
    uninitialized = [
        state for state in states if state.last_success_at is None and state.pk not in active_ids
    ]
    partial = [
        state
        for state in states
        if state.last_success_at is None
        and state.pk not in active_ids
        and (state.last_cursor > 0 or bool(state.last_cursor_url))
    ]
    # A bounded DOM batch records its remaining backlog in last_error for
    # checkpoint diagnostics. That is an incomplete-but-reachable source, not
    # a transport/processing failure; cursor state reports it as partial below.
    def is_expected_partial_batch(state) -> bool:
        return source == "dom_natal" and state.last_error.startswith(
            "edition_batch_incomplete:"
        )

    failed = [
        state
        for state in states
        if state.last_error
        and not is_expected_partial_batch(state)
        and state.last_started_at
        and (state.last_success_at is None or state.last_started_at > state.last_success_at)
    ]
    stale = [
        state
        for state in initialized
        if (
            checked_at - (state.last_full_sync_at or state.last_success_at)
        ).total_seconds()
        > (
            full_sweep_max_age.total_seconds()
            if state.last_full_sync_at
            else max_age.total_seconds()
        )
    ]
    successes = [state.last_success_at for state in states if state.last_success_at is not None]
    latest_success = max(successes, default=None)
    latest_age = (
        max(0, int((checked_at - latest_success).total_seconds()))
        if latest_success is not None
        else None
    )

    if failed and latest_success is None:
        status = "unavailable"
    elif latest_success is None:
        status = "running" if active else "degraded" if partial else "unavailable"
    elif failed or uninitialized or (active and stale):
        status = "degraded"
    elif active:
        status = "running"
    elif stale:
        status = "stale"
    else:
        status = "current"

    return {
        "source": source,
        "status": status,
        "scope_count": len(states),
        "checked_at": checked_at,
        "last_success_at": latest_success,
        "last_success_age_seconds": latest_age,
        "failed_scope_count": len(failed),
        "uninitialized_scope_count": len(uninitialized),
        "partial_scope_count": len(partial),
        "stale_scope_count": len(stale),
        "full_sweep_scope_count": sum(state.last_full_sync_at is not None for state in states),
        "active_scope_count": len(active),
        "has_error": bool(failed),
    }
