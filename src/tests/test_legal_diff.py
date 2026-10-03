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


def test_explicit_inciso_label_pairs_with_an_ocr_roman_marker():
    rows = build_legal_diff(
        "Art. 2º A política compreende:\nI – valorizar agentes públicos;\nII - apoiar o programa.",
        "Art. 2º A política compreende:\nInciso I valorizar agentes públicos;\nInciso II apoiar o programa.",
    )

    assert [row["structural_key"] for row in rows] == [
        "art:2#1",
        "art:2:par:-:inc:I#1",
        "art:2:par:-:inc:II#1",
    ]
    assert [row["kind"] for row in rows] == ["equal", "formatting", "formatting"]


def test_explicit_inciso_normalization_preserves_changed_negation_and_amounts():
    rows = build_legal_diff(
        "Art. 2º A política compreende:\nII - não poderá cobrar 10%.",
        "Art. 2º A política compreende:\nInciso II poderá cobrar 100%.",
    )

    assert len(rows) == 2
    assert rows[1]["structural_key"] == "art:2:par:-:inc:II#1"
    assert rows[1]["kind"] == "changed"
    assert "não" in rows[1]["original"]
    assert "10%" in rows[1]["original"]
    assert "100%" in rows[1]["consolidated"]
