from __future__ import annotations

from scripts.benchmark_pdf_layout_qa import _require_qa, _table_summary


def test_table_benchmark_serializes_candidate_cells_to_markdown_and_semantic_html():
    summary = _table_summary(
        {
            "page": 2,
            "detector": "pymupdf_find_tables",
            "status": "unreviewed_candidate",
            "rows": [["Descrição", "Valor"], ["linha A\nlinha B", "1.200,00"]],
        },
        {
            "stored_extraction": "descrição valor linha a linha b 1.200,00",
            "poppler_layout_text": "descrição valor linha a linha b 1.200,00",
        },
    )

    assert summary["page"] == 2
    assert summary["rows"] == 2
    assert summary["columns_max"] == 2
    assert summary["candidate_cells_matching"] == {
        "stored_extraction": 4,
        "poppler_layout_text": 4,
    }
    assert summary["candidate_cells_missing"] == {
        "stored_extraction": 0,
        "poppler_layout_text": 0,
    }
    assert summary["serialized_markdown_rows"] == 3
    assert summary["serialized_html_tables"] == 1
    assert summary["serialized_html_rows"] == 2
    assert summary["serialized_html_cells"] == 4


def test_table_benchmark_refuses_non_qa_execution(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")

    try:
        _require_qa()
    except RuntimeError as error:
        assert "QA normativo isolado" in str(error)
    else:
        raise AssertionError("O benchmark deve recusar o perfil de produto")
