from datetime import date

import pytest

from src.apps.legislation.api_limits import InvalidLLMParams, parse_search_options
from src.processing.adaptive_retrieval import RetrievalOptions
from src.processing.temporal_scope import TemporalScope


def test_search_options_build_temporal_scope():
    values = parse_search_options(
        {
            "as_of": "2024-06-30",
            "published_from": "2020-01-01",
            "published_to": "2024-06-30",
        }
    )
    assert values["temporal_scope"] == TemporalScope(
        as_of=date(2024, 6, 30),
        published_from=date(2020, 1, 1),
        published_to=date(2024, 6, 30),
    )


def test_invalid_temporal_range_is_rejected():
    with pytest.raises(InvalidLLMParams):
        parse_search_options({"published_from": "2025-01-01", "published_to": "2024-01-01"})
    with pytest.raises(InvalidLLMParams):
        parse_search_options({"as_of": "2024-01-01", "published_from": "2024-02-01"})


def test_temporal_scope_changes_retrieval_fingerprint():
    present = RetrievalOptions(temporal_scope=TemporalScope(as_of=date(2024, 6, 30)))
    historical = RetrievalOptions(temporal_scope=TemporalScope(as_of=date(2022, 6, 30)))
    assert present.fingerprint() != historical.fingerprint()
