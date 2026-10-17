from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from src.apps.operations.management.commands import check_source_sync_health
from src.apps.operations.models import SaplSyncState

pytestmark = pytest.mark.django_db


def _worker_is_current(monkeypatch):
    monkeypatch.setattr(
        check_source_sync_health,
        "get_normative_worker_health",
        lambda: {"status": "current", "responding_workers": 1, "queue_workers": 1},
    )


def test_health_command_emits_machine_readable_current_status(capsys, monkeypatch):
    _worker_is_current(monkeypatch)
    SaplSyncState.objects.create(
        source="sapl", filter_fingerprint="all", last_success_at=timezone.now()
    )

    call_command("check_source_sync_health", source="sapl")

    output = capsys.readouterr().out
    assert '"source_sync": {"active_scope_count": 0' in output
    assert '"status": "current"' in output
    assert '"scope_count": 1' in output
    assert '"last_success_at": "' in output
    assert '"normative_queue": {"queue_workers": 1' in output


def test_health_command_fails_on_stale_source(capsys, monkeypatch):
    _worker_is_current(monkeypatch)
    SaplSyncState.objects.create(
        source="sapl",
        filter_fingerprint="all",
        last_success_at=timezone.now() - timedelta(days=3),
    )

    with pytest.raises(CommandError, match="status=stale"):
        call_command("check_source_sync_health", source="sapl")

    output = capsys.readouterr().out
    assert '"status": "stale"' in output


def test_health_command_never_prints_exception_text(capsys, monkeypatch):
    _worker_is_current(monkeypatch)
    now = timezone.now()
    SaplSyncState.objects.create(
        source="sapl",
        filter_fingerprint="all",
        last_success_at=now - timedelta(minutes=1),
        last_started_at=now,
        last_error="internal host or credential must not be disclosed",
    )

    with pytest.raises(CommandError, match="status=degraded"):
        call_command("check_source_sync_health", source="sapl")

    output = capsys.readouterr().out
    assert '"has_error": true' in output
    assert "internal host" not in output
    assert "credential" not in output


def test_health_command_details_report_checkpoint_state_without_private_values(
    capsys, monkeypatch
):
    _worker_is_current(monkeypatch)
    SaplSyncState.objects.create(
        source="sapl",
        filter_fingerprint="private-scope-fingerprint",
        last_started_at=timezone.now(),
        last_cursor=40,
        last_cursor_url="https://sapl.invalid/private?page=2&token=secret",
        last_error="internal host https://sapl.invalid/private?token=secret",
    )

    with pytest.raises(CommandError, match="status=unavailable"):
        call_command("check_source_sync_health", source="sapl", details=True)

    output = capsys.readouterr().out
    assert '"scope_diagnostics": [{"checkpoint_state": "failed"' in output
    assert '"cursor_position": 40' in output
    assert '"cursor_url_present": true' in output
    assert '"error_recorded": true' in output
    assert "private-scope-fingerprint" not in output
    assert "sapl.invalid" not in output
    assert "secret" not in output


def test_health_command_fails_when_normative_queue_has_no_worker(capsys, monkeypatch):
    SaplSyncState.objects.create(
        source="sapl", filter_fingerprint="all", last_success_at=timezone.now()
    )
    monkeypatch.setattr(
        check_source_sync_health,
        "get_normative_worker_health",
        lambda: {"status": "queue_missing", "responding_workers": 1, "queue_workers": 0},
    )

    with pytest.raises(CommandError, match="queue=queue_missing"):
        call_command("check_source_sync_health", source="sapl")

    assert '"queue_workers": 0' in capsys.readouterr().out


@pytest.mark.parametrize("hours", [0, -1, 8761])
def test_health_command_bounds_maximum_age(hours):
    with pytest.raises(CommandError, match="between 1 and 8760"):
        call_command("check_source_sync_health", source="sapl", max_age_hours=hours)
