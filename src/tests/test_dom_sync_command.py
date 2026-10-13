from __future__ import annotations

import json
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from src.apps.ingestion.management.commands import sync_dom_natal_editions_qa


def test_dom_sync_command_defaults_to_read_only_catalog_inspection(monkeypatch):
    inspected = []
    synced = []

    def inspect(*, as_of, lookback_months):
        inspected.append((as_of, lookback_months))
        return {"source": "dom_natal", "read_only": True, "scopes": []}

    monkeypatch.setattr(sync_dom_natal_editions_qa, "inspect_dom_natal_editions", inspect)
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "sync_dom_natal_editions",
        lambda **kwargs: synced.append(kwargs),
    )
    output = StringIO()

    call_command("sync_dom_natal_editions_qa", stdout=output)

    result = json.loads(output.getvalue())
    assert inspected == [(None, 1)]
    assert synced == []
    assert result["read_only"] is True
    assert result["persisted"] is False
    assert result["apply_required_for_download"] is True
    assert result["max_new_total"] == 1


def test_dom_sync_command_apply_is_explicit_and_limited_to_one_edition(monkeypatch):
    synced = []

    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "inspect_dom_natal_editions",
        lambda **kwargs: pytest.fail("apply must use the bounded sync operation"),
    )
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "sync_dom_natal_editions",
        lambda **kwargs: synced.append(kwargs) or {"source": "dom_natal", "status": "degraded"},
    )
    output = StringIO()

    call_command("sync_dom_natal_editions_qa", "--apply", stdout=output)

    result = json.loads(output.getvalue())
    assert synced == [{"as_of": None, "lookback_months": 1, "max_new_total": 1}]
    assert result["persisted"] is True
    assert result["read_only"] is False


@pytest.mark.parametrize(
    "options",
    [
        ["--lookback-months", "0"],
        ["--lookback-months", "4"],
        ["--max-new-total", "2"],
    ],
)
def test_dom_sync_command_rejects_out_of_bounds_before_calling_sync(monkeypatch, options):
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "inspect_dom_natal_editions",
        lambda **kwargs: pytest.fail("invalid bounds must stop before source access"),
    )
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "sync_dom_natal_editions",
        lambda **kwargs: pytest.fail("invalid bounds must stop before sync"),
    )

    with pytest.raises(CommandError):
        call_command("sync_dom_natal_editions_qa", *options)


def test_dom_sync_command_resumes_one_explicit_historical_month(monkeypatch):
    as_of = date(2026, 1, 1)
    synced = []
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "inspect_dom_natal_editions",
        lambda **kwargs: pytest.fail("apply must use the bounded historical sync"),
    )
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "sync_dom_natal_editions",
        lambda **kwargs: synced.append(kwargs) or {"source": "dom_natal", "status": "degraded"},
    )
    output = StringIO()

    call_command(
        "sync_dom_natal_editions_qa",
        "--lookback-months", "1",
        "--max-new-total", "1",
        "--as-of", as_of.isoformat(),
        "--apply",
        stdout=output,
    )

    assert synced == [{"as_of": as_of, "lookback_months": 1, "max_new_total": 1}]
    assert json.loads(output.getvalue())["persisted"] is True


@pytest.mark.parametrize("offset", [1, 367])
def test_dom_sync_command_rejects_future_or_too_old_explicit_scope(monkeypatch, offset):
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "inspect_dom_natal_editions",
        lambda **kwargs: pytest.fail("invalid scope must stop before source access"),
    )
    monkeypatch.setattr(
        sync_dom_natal_editions_qa,
        "sync_dom_natal_editions",
        lambda **kwargs: pytest.fail("invalid scope must stop before sync"),
    )
    today = timezone.localdate()
    invalid_date = today + timedelta(days=1) if offset == 1 else today - timedelta(days=offset)

    with pytest.raises(CommandError, match="as-of"):
        call_command(
            "sync_dom_natal_editions_qa",
            "--lookback-months", "1",
            "--max-new-total", "1",
            "--as-of", invalid_date.isoformat(),
        )
