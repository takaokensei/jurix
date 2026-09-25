import pytest

from src.apps.legislation.api_limits import InvalidLLMParams, parse_search_options


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
