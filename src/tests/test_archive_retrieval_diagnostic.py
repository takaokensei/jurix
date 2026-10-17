from src.apps.ingestion.management.commands.diagnose_qa_archive_overview import (
    _whole_norm_selection_metrics,
)
from src.apps.ingestion.management.commands.inspect_archive_candidate_retrieval_qa import (
    _generation_mode,
)


def test_diagnostic_distinguishes_source_only_from_an_ollama_attempt():
    assert _generation_mode({"source_only": True, "generation_attempts": []}) == "source_only_no_llm"
    assert _generation_mode({"source_only": False, "generation_attempts": [{"duration_ms": 12}]}) == "ollama_attempted"
    assert _generation_mode({"source_only": False, "generation_attempts": []}) == "not_generated"


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
