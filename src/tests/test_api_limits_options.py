import pytest

from src.apps.legislation.api_limits import (
    InvalidLLMParams,
    parse_search_options,
    parse_temperature,
)


def test_search_options_default_is_broad_budget_but_bounded(settings):
    settings.LLM_MAX_K = 20
    values = parse_search_options({"question": "teste"})
    assert values["mode"] == "hybrid"
    assert values["norma_status"] == "consolidated"
    assert values["max_sources"] == 12


def test_search_options_rejects_invalid_mode():
    with pytest.raises(InvalidLLMParams):
        parse_search_options({"search_mode": "magic"})


def test_search_options_accepts_attachments():
    values = parse_search_options({"attachment_ids": ["a", "b"], "max_sources": 20})
    assert values["attachment_ids"] == ["a", "b"]
    assert values["max_sources"] == 20


def test_search_options_caps_attachment_count():
    with pytest.raises(InvalidLLMParams):
        parse_search_options({"attachment_ids": ["1", "2", "3", "4", "5", "6"]})


def test_temperature_is_bounded_and_defaults_safely():
    assert parse_temperature(None) == 0.3
    assert parse_temperature("0.8") == 0.8
    with pytest.raises(InvalidLLMParams):
        parse_temperature(1.1)
    with pytest.raises(InvalidLLMParams):
        parse_temperature(True)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_temperature_is_rejected(value):
    with pytest.raises(InvalidLLMParams):
        parse_temperature(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, False])
def test_invalid_similarity_is_rejected(value):
    with pytest.raises(InvalidLLMParams):
        parse_search_options({"min_similarity": value})
