from datetime import date
from types import SimpleNamespace

import pytest

from src.processing.temporal_scope import TemporalScope, parse_iso_date, temporal_status


def test_parse_iso_date_accepts_calendar_dates():
    assert parse_iso_date("2026-01-30", "as_of") == date(2026, 1, 30)


def test_parse_iso_date_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_iso_date("30/01/2026", "as_of")


def test_scope_rejects_future_publication():
    scope = TemporalScope(as_of=date(2025, 1, 1))
    assert not scope.contains_publication(date(2025, 2, 1))


def test_scope_accepts_unknown_publication_without_strict_publication_filter():
    scope = TemporalScope(as_of=date(2025, 1, 1))
    assert scope.contains_publication(None)


def test_temporal_status_for_vacatio():
    norma = SimpleNamespace(data_publicacao=date(2025, 1, 1), data_vigencia=date(2025, 2, 1), id=1)
    assert temporal_status(norma, as_of=date(2025, 1, 15)) == "vacatio_legis"
