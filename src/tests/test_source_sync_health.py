from datetime import timedelta

import pytest
from django.utils import timezone

from src.apps.ingestion.source_sync_health import get_source_sync_health
from src.apps.operations.models import SaplSyncState

pytestmark = pytest.mark.django_db


def _state(
    scope,
    *,
    source="sapl",
    success=None,
    started=None,
    error="",
    lease=None,
    full_success=None,
    cursor=0,
    cursor_url="",
):
    return SaplSyncState.objects.create(
        source=source,
        filter_fingerprint=scope,
        last_success_at=success,
        last_started_at=started,
        last_error=error,
        lease_until=lease,
        last_full_sync_at=full_success,
        last_cursor=cursor,
        last_cursor_url=cursor_url,
    )


def test_sync_health_distinguishes_unconfigured_source_without_creating_checkpoint():
    report = get_source_sync_health("dom_natal")

    assert report["status"] == "not_configured"
    assert report["scope_count"] == 0
    assert SaplSyncState.objects.count() == 0


def test_sync_health_reports_current_and_stale_checkpoints():
    now = timezone.now()
    _state("recent", success=now - timedelta(hours=2))
    recent = get_source_sync_health("sapl", now=now, max_age=timedelta(hours=36))

    assert recent["status"] == "current"
    assert recent["last_success_age_seconds"] == 7200

    SaplSyncState.objects.all().delete()
    _state("old", success=now - timedelta(hours=40))
    stale = get_source_sync_health("sapl", now=now, max_age=timedelta(hours=36))
    assert stale["status"] == "stale"


def test_weekly_full_sweep_uses_its_own_freshness_window():
    now = timezone.now()
    _state(
        "weekly-full",
        success=now - timedelta(days=2),
        full_success=now - timedelta(days=2),
    )

    report = get_source_sync_health("sapl", now=now, max_age=timedelta(hours=36))

    assert report["status"] == "current"
    assert report["stale_scope_count"] == 0
    assert report["full_sweep_scope_count"] == 1

    SaplSyncState.objects.all().delete()
    _state(
        "weekly-full-old",
        success=now - timedelta(days=9),
        full_success=now - timedelta(days=9),
    )
    stale = get_source_sync_health("sapl", now=now)
    assert stale["status"] == "stale"


def test_sync_health_fails_closed_for_first_failure_and_redacts_error_text():
    now = timezone.now()
    _state("failed", started=now, error="private exception containing an internal URL")

    report = get_source_sync_health("sapl", now=now)

    assert report["status"] == "unavailable"
    assert report["failed_scope_count"] == 1
    assert report["has_error"] is True
    assert "private" not in repr(report)
    assert "internal URL" not in repr(report)


def test_sync_health_reports_partial_cursor_as_uninitialized_until_first_success():
    now = timezone.now()
    _state("partial", started=now - timedelta(minutes=2), cursor=30, cursor_url="https://sapl.invalid/page/3")

    report = get_source_sync_health("sapl", now=now)

    assert report["status"] == "degraded"
    assert report["last_success_at"] is None
    # Partial is nested under uninitialized: neither has a completed success.
    assert report["uninitialized_scope_count"] == 1
    assert report["partial_scope_count"] == 1
    assert report["failed_scope_count"] == 0
    assert "sapl.invalid" not in repr(report)


def test_sync_health_reports_reachable_dom_with_bounded_backlog_as_degraded():
    now = timezone.now()
    SaplSyncState.objects.create(
        source="dom_natal",
        filter_fingerprint="october-2026",
        last_started_at=now - timedelta(minutes=2),
        last_error="edition_batch_incomplete:6",
        last_cursor=5000,
        last_cursor_url="https://www2.natal.rn.gov.br/_anexos/publicacao/dom/edition.pdf",
        full_sweep_expected_count=8,
        last_sync_count=1,
    )

    report = get_source_sync_health("dom_natal", now=now)

    assert report["status"] == "degraded"
    assert report["partial_scope_count"] == 1
    assert report["failed_scope_count"] == 0
    assert report["has_error"] is False
    assert report["last_success_at"] is None
    assert "edition.pdf" not in repr(report)


def test_sync_health_still_marks_dom_transport_failure_unavailable():
    now = timezone.now()
    _state(
        "dom-failed",
        source="dom_natal",
        started=now - timedelta(minutes=1),
        error="source_error:DomNatalError",
    )

    report = get_source_sync_health("dom_natal", now=now)

    assert report["status"] == "unavailable"
    assert report["failed_scope_count"] == 1
    assert report["has_error"] is True


def test_sync_health_marks_a_live_lease_as_running_and_mixed_scopes_as_degraded():
    now = timezone.now()
    _state("running", started=now, lease=now + timedelta(minutes=5))
    running = get_source_sync_health("sapl", now=now)
    assert running["status"] == "running"

    SaplSyncState.objects.all().delete()
    _state("good", success=now - timedelta(hours=1))
    _state("failed", success=now - timedelta(hours=2), started=now - timedelta(hours=1), error="offline")
    degraded = get_source_sync_health("sapl", now=now)
    assert degraded["status"] == "degraded"
    assert degraded["scope_count"] == 2
    assert degraded["failed_scope_count"] == 1


def test_sync_health_does_not_call_mixed_success_and_never_run_scopes_current():
    now = timezone.now()
    _state("recent", success=now - timedelta(hours=1))
    _state("never-run")

    report = get_source_sync_health("sapl", now=now)

    assert report["status"] == "degraded"
    assert report["uninitialized_scope_count"] == 1


@pytest.mark.parametrize("source", ["", "   "])
def test_sync_health_rejects_empty_source_identifier(source):
    with pytest.raises(ValueError, match="non-empty"):
        get_source_sync_health(source)
