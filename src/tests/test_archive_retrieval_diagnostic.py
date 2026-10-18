from src.apps.ingestion.management.commands.diagnose_qa_archive_overview import (
    _whole_norm_selection_metrics,
)
from src.apps.ingestion.management.commands.inspect_archive_candidate_retrieval_qa import (
    _generation_mode,
    _is_isolated_qa_environment,
)


def test_diagnostic_distinguishes_source_only_from_an_ollama_attempt():
    assert _generation_mode({"source_only": True, "generation_attempts": []}) == "source_only_no_llm"
    assert _generation_mode({"source_only": False, "generation_attempts": [{"duration_ms": 12}]}) == "ollama_attempted"
    assert _generation_mode({"source_only": False, "generation_attempts": []}) == "not_generated"


def test_archive_retrieval_diagnostic_accepts_only_the_two_isolated_qa_profiles():
    for settings_module in (
        "config.settings_normative_qa",
        "config.settings_normative_container_qa",
    ):
        assert _is_isolated_qa_environment(
            {
                "JURIX_QA_ONLY": "1",
                "DJANGO_SETTINGS_MODULE": settings_module,
            },
            assistant_enabled=True,
        )

    assert not _is_isolated_qa_environment(
        {"JURIX_QA_ONLY": "1", "DJANGO_SETTINGS_MODULE": "config.settings"},
        assistant_enabled=True,
    )
    assert not _is_isolated_qa_environment(
        {
            "JURIX_QA_ONLY": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_container_qa",
        },
        assistant_enabled=False,
    )
    assert not _is_isolated_qa_environment(
        {"DJANGO_SETTINGS_MODULE": "config.settings_normative_qa"},
        assistant_enabled=True,
    )


def test_whole_norm_selection_diagnostic_reports_only_scope_and_size():
    candidates = [
        {"dispositivo_ref": "Art. 1º", "full_text": "public law text one"},
        {"dispositivo_ref": "Art. 2º", "full_text": "public law text two"},
        {"dispositivo_ref": "Art. 3º", "full_text": "public law text six"},
    ]
    selected = [candidates[0], candidates[2]]

    metrics = _whole_norm_selection_metrics(
        candidates, selected, context_budget_chars=24_000
    )

    assert metrics == {
        "candidate_article_count": 3,
        "selected_article_count": 2,
        "omitted_article_refs": ["Art. 2º"],
        "candidate_text_characters": 57,
        "selected_text_characters": 38,
        "context_budget_characters": 24_000,
    }
    assert "full_text" not in metrics
