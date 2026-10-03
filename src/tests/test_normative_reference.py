import pytest

from src.processing.normative_reference import (
    parse_normative_reference_query,
    parse_normative_references,
)


@pytest.mark.parametrize(
    ("text", "type_key", "number", "year"),
    [
        ("Lei nº 8.205/2026", "lei", "8205", 2026),
        ("Lei n. 8205 de 2026", "lei", "8205", 2026),
        ("Lei Complementar nº 8.205/2026", "lei_complementar", "8205", 2026),
        ("Decreto-Lei 12/1940", "decreto_lei", "12", 1940),
        ("Decreto Legislativo nº 12/2025", "decreto_legislativo", "12", 2025),
        ("Resolução nº 12/2025", "resolucao", "12", 2025),
    ],
)
def test_normalizes_typed_references_without_merging_types(text, type_key, number, year):
    (reference,) = parse_normative_references(text)
    assert reference.identity == (type_key, number, year)
    assert reference.ambiguous is False


def test_yearless_reference_is_preserved_but_marked_ambiguous():
    (reference,) = parse_normative_references("Lei nº 8205")
    assert reference.identity == ("lei", "8205", None)
    assert reference.ambiguous is True


def test_hierarchy_is_attached_only_when_it_is_unambiguous():
    (reference,) = parse_normative_references("Inciso II do Art. 7º da Lei 8205/2026")
    assert reference.article == "7"
    assert reference.item == "II"

    references = parse_normative_references("Art. 1º da Lei 8205/2026 e Art. 2º do Decreto 1/2026")
    assert len(references) == 2
    assert all(reference.article is None and reference.ambiguous for reference in references)


def test_complementary_and_ordinary_laws_have_distinct_canonical_identity():
    (ordinary,) = parse_normative_references("Lei 15/2024")
    (complementary,) = parse_normative_references("Lei Complementar 15/2024")
    assert ordinary.identity != complementary.identity


@pytest.mark.parametrize(
    ("query", "type_key", "number", "year"),
    [
        ("Lei nº 8.206/2026", "lei", "8206", 2026),
        ("Lei Complementar 8.206 de 2026", "lei_complementar", "8206", 2026),
        ("8206/2026", "", "8206", 2026),
    ],
)
def test_complete_norma_search_query_accepts_dotted_and_untyped_identifier(
    query, type_key, number, year
):
    reference = parse_normative_reference_query(query)
    assert reference is not None
    assert reference.identity == (type_key, number, year)


@pytest.mark.parametrize("query", ["8.20.6/2026", "Lei 8.206/20", "text 8206/2026"])
def test_norma_search_parser_rejects_malformed_or_nonexact_queries(query):
    assert parse_normative_reference_query(query) is None
