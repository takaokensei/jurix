from datetime import date

import pytest

from src.apps.ingestion.task_support import _normalize_norma_tipo
from src.processing.document_metadata import (
    build_normative_identity,
    normalize_document_number,
    parse_filename_metadata,
    parse_initial_epigraphs,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("LeiComplementar_20211220_198_.pdf", ("lei_complementar", "municipal_lc", "198")),
        ("LeiOrdinaria_20260821_055_.pdf", ("lei", "municipal_lo", "055")),
        ("leiPromulgada_5789.pdf", ("lei_promulgada", "municipal_lp", "5789")),
        ("Decreto_20230831_12887_.pdf", ("decreto", "municipal_decreto", "12887")),
    ],
)
def test_filename_parser_extracts_only_type_series_date_and_number(raw, expected):
    parsed = parse_filename_metadata(raw)
    assert (parsed.type_key, parsed.series, parsed.number) == expected
    assert parsed.issues == ()
    if "2021" in raw or "2026" in raw or "2023" in raw:
        assert parsed.candidates[0].field == "unclassified_filename_date"
        assert parsed.candidates[0].source == "filename"


def test_filename_number_that_looks_like_a_year_is_not_promoted_to_a_date():
    parsed = parse_filename_metadata("decreto_7795.pdf")
    assert parsed.number == "7795"
    assert parsed.candidates == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "LeiComplementar20101203_120.pdf",
            ("lei_complementar", "municipal_lc", "120", "2010-12-03"),
        ),
        ("LeiOrdinaria20091228_6021.pdf", ("lei", "municipal_lo", "6021", "2009-12-28")),
        (
            "Decreto20110408_9365.pdf",
            ("decreto", "municipal_decreto", "9365", "2011-04-08"),
        ),
    ],
)
def test_filename_parser_handles_type_and_date_concatenated_in_legacy_archive_name(raw, expected):
    parsed = parse_filename_metadata(raw)
    candidate = parsed.candidates[0]
    assert (parsed.type_key, parsed.series, parsed.number, candidate.value) == expected


def test_invalid_filename_date_is_preserved_as_an_issue_not_a_candidate():
    parsed = parse_filename_metadata("Decreto_20231340_12887_.pdf")
    assert parsed.number is None
    assert parsed.candidates == ()
    assert parsed.issues == ("invalid_filename_date",)
    assert parsed.unparsed_segments == ("20231340", "12887")


def test_filename_role_and_unrecognized_segments_are_preserved():
    parsed = parse_filename_metadata("LeiOrdinaria_20260821_55_anexo_retificacao_extra.pdf")
    assert parsed.role == "retificacao"
    assert parsed.unparsed_segments == ("anexo", "retificacao", "extra")


def test_identity_normalizes_numeric_zeroes_but_preserves_suffix_and_type_series():
    first = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="LC",
        series="municipal_lc",
        number="055",
        year=2004,
    )
    same = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Complementar",
        series="municipal_lc",
        number="55",
        year="2004",
    )
    suffixed = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Complementar",
        series="municipal_lc",
        number="5-A",
        year=2004,
    )
    ordinary = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Ordinária",
        series="municipal_lo",
        number="55",
        year=2004,
    )
    assert first.identity_key == same.identity_key
    assert first.identity_json["number"] == "55"
    assert suffixed.identity_json["number"] == "5-A"
    assert suffixed.identity_key != same.identity_key
    assert ordinary.identity_key != same.identity_key


def test_unknown_or_incompatible_series_keeps_identity_unresolved():
    unknown = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Ordinária",
        series=None,
        number="55",
        year=2004,
    )
    incompatible = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Ordinária",
        series="municipal_lc",
        number="55",
        year=2004,
    )
    assert unknown.identity_key is None
    assert unknown.identity_json["series"] is None
    assert incompatible.identity_key is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "Lei"),
        ("Lei ordinária", "Lei"),
        ("Lei Complementar", "Lei Complementar"),
        ("Decreto Executivo", "Decreto"),
        ("Decreto Legislativo", "Decreto Legislativo"),
        ("tipo SAPL futuro", "tipo SAPL futuro"),
        ("99", "99"),
    ],
)
def test_sapl_type_normalization_preserves_unknown_codes(raw, expected):
    assert _normalize_norma_tipo(raw) == expected


def test_initial_epigraph_extracts_act_date_without_claiming_publication_or_effectivity():
    parsed = parse_initial_epigraphs(
        [
            "CÂMARA MUNICIPAL DE NATAL\n"
            "LEI COMPLEMENTAR Nº 198, DE 20 DE DEZEMBRO DE 2021\n"
            "Ementa: altera a Lei nº 55/2004."
        ]
    )
    assert parsed.status == "candidate"
    assert parsed.candidates[0].type_key == "lei_complementar"
    assert parsed.candidates[0].number == "198"
    assert parsed.candidates[0].year == 2021
    assert parsed.candidates[0].act_date == date(2021, 12, 20).isoformat()


def test_initial_epigraph_accepts_year_only_and_ignores_body_references():
    parsed = parse_initial_epigraphs(["LEI Nº 8205, DE 2026\nArt. 1º Altera a Lei nº 55/2004."])
    assert len(parsed.candidates) == 1
    assert parsed.candidates[0].number == "8205"
    assert parsed.candidates[0].year == 2026
    assert parsed.candidates[0].act_date is None


def test_distinct_initial_epigraphs_mark_a_multi_norm_document():
    parsed = parse_initial_epigraphs(["LEI Nº 1/2020", "DECRETO Nº 2, DE 3 DE MARÇO DE 2021"])
    assert parsed.status == "multi_norm_document"
    assert len(parsed.candidates) == 2


def test_conflicting_dates_for_same_epigraph_are_preserved_for_review():
    parsed = parse_initial_epigraphs(
        [
            "LEI Nº 1, DE 3 DE MARÇO DE 2021",
            "LEI Nº 1, DE 4 DE MARÇO DE 2021",
        ]
    )
    assert parsed.status == "candidate"
    assert {candidate.act_date for candidate in parsed.candidates} == {
        "2021-03-03",
        "2021-03-04",
    }
    assert "conflicting_act_date" in parsed.issues


def test_epigraph_year_suffix_and_page_iteration_are_bounded():
    consumed = []

    def pages():
        for index in range(20):
            consumed.append(index)
            yield "LEI Nº 1/2020" if index == 0 else "LEI Nº 2/2021"

    parsed = parse_initial_epigraphs(pages(), max_pages=2)
    assert consumed == [0, 1]
    assert parsed.status == "multi_norm_document"
    assert [candidate.year for candidate in parsed.candidates] == [2020, 2021]


def test_body_reference_is_not_treated_as_document_epigraph():
    parsed = parse_initial_epigraphs(
        ["EMENTA: altera a Lei nº 55/2004.", "Art. 1º Fica revogada a Lei nº 2/2020."]
    )
    assert parsed.status == "unresolved"
    assert parsed.candidates == ()


def test_unknown_filename_type_and_number_suffix_are_retained():
    parsed = parse_filename_metadata("CategoriaFutura_55-A_extra.pdf")
    assert parsed.type_key is None
    assert parsed.number is None
    assert parsed.unparsed_segments == ("CategoriaFutura", "55-A", "extra")
    assert "unknown_filename_type" in parsed.issues


def test_document_number_preserves_suffix_while_normalizing_numeric_identifiers():
    assert normalize_document_number("00055") == "55"
    assert normalize_document_number("5-A") == "5-A"
