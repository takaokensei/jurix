import pytest

from src.processing.foundation_reference_parser import (
    MAX_FOUNDATION_CHARS,
    parse_foundation_references,
)


def test_parser_preserves_exact_offsets_and_normalizes_nested_device():
    text = "Fundamento: Art. 1º, inciso II, da Lei Complementar nº 198/2021."

    refs = parse_foundation_references(text)

    assert len(refs) == 1
    ref = refs[0]
    assert text[ref.start : ref.end] == ref.text
    assert ref.type_key == "lei_complementar"
    assert ref.number == "198" and ref.year == 2021
    assert ref.article == "1" and ref.item == "II"
    assert not ref.requires_confirmation


def test_parser_attaches_multiple_abbreviated_articles_only_to_one_nearby_norm():
    text = "Lei nº 10/2020, Art. 1º e Art. 2º são relevantes."

    refs = parse_foundation_references(text)

    assert [ref.article for ref in refs] == ["1", "2"]
    assert all(ref.number == "10" and ref.year == 2020 for ref in refs)
    assert len({ref.reference_id for ref in refs}) == 2


def test_parser_keeps_two_explicit_law_article_pairs_separate():
    text = "Art. 1º da Lei nº 10/2020 e Art. 1º da Lei Complementar nº 20/2021."

    refs = parse_foundation_references(text)

    assert [(ref.type_key, ref.number, ref.year, ref.article) for ref in refs] == [
        ("lei", "10", 2020, "1"),
        ("lei_complementar", "20", 2021, "1"),
    ]
    assert all(not ref.requires_confirmation for ref in refs)


def test_parser_marks_unqualified_article_near_competing_laws_for_confirmation():
    refs = parse_foundation_references(
        "Lei nº 10/2020 e Lei nº 20/2021. O Art. 1º deve ser confirmado."
    )

    article_refs = [ref for ref in refs if ref.article]
    assert len(article_refs) == 1
    assert article_refs[0].requires_confirmation
    assert article_refs[0].type_key is None


def test_parser_rejects_oversized_text_and_reference_count():
    with pytest.raises(ValueError, match="caracteres"):
        parse_foundation_references("x" * (MAX_FOUNDATION_CHARS + 1))
    text = " ".join(f"Lei nº {number}/2020" for number in range(1, 102))
    with pytest.raises(ValueError, match="referências"):
        parse_foundation_references(text)
