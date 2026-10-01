from src.processing.legal_diff import build_legal_diff


def test_article_blocks_are_paired_by_structure_despite_ocr_line_wraps():
    rows = build_legal_diff(
        "Art. 1º Fica instituído o Programa Municipal.\nArt. 2º A execução será anual.",
        "Art. 1º Fica instituído\n o Programa Municipal.\nArt. 2º A execução será anual.",
    )

    assert [row["structural_key"] for row in rows] == ["art:1#1", "art:2#1"]
    assert [row["kind"] for row in rows] == ["formatting", "equal"]


def test_textual_diff_preserves_negation_numbers_and_punctuation():
    rows = build_legal_diff(
        "Art. 1º O Município não poderá cobrar 10%.",
        "Art. 1º O Município poderá cobrar 100%.",
    )

    assert len(rows) == 1
    assert rows[0]["kind"] == "changed"
    assert "não" in rows[0]["original"]
    assert "10%" in rows[0]["original"]
    assert "100%" in rows[0]["consolidated"]
    assert "não" not in rows[0]["consolidated"]


def test_inserted_and_removed_devices_are_textual_not_legal_validation():
    rows = build_legal_diff(
        "Art. 1º Institui o programa.",
        "Art. 1º Institui o programa.\nArt. 2º Define os critérios.",
    )

    assert [(row["kind"], row["structural_key"]) for row in rows] == [
        ("equal", "art:1#1"),
        ("added", "art:2#1"),
    ]
    assert "Diferença" in rows[1]["label"] or "presente" in rows[1]["label"]
