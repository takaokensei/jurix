from __future__ import annotations

import pytest

from src.processing.gazette_segmentation import propose_gazette_boundaries


def test_proposes_page_aware_candidate_spans_without_classifying_notice_as_law():
    pages = [
        "Diário Oficial\nLei nº 123/2024\nArt. 1º\nTexto da lei.",
        "PORTARIA Nº 45, de 2 de janeiro de 2025\nAto administrativo.\n"
        "EDITAL Nº 9/2025\nAviso ao público.",
        "Portaria N.º 46/2025\nAto administrativo.",
    ]

    proposal = propose_gazette_boundaries(pages)

    assert proposal.status == "proposed"
    assert proposal.page_count == proposal.processed_page_count == 3
    assert len(proposal.candidates) == 5
    law, portaria, edital, aviso, portaria_ordinal = proposal.candidates
    assert (law.instrument_type.lower(), law.number, law.year) == ("lei", "123", 2024)
    assert law.document_class == "normative_or_cited_instrument_candidate"
    assert portaria.document_class == "administrative_or_notice_candidate"
    assert (portaria.number, portaria.year, portaria.publication_date) == (
        "45",
        2025,
        "2025-01-02",
    )
    assert (edital.number, edital.year, edital.page_index) == ("9", 2025, 1)
    assert (aviso.instrument_type.lower(), aviso.number, aviso.page_index) == (
        "aviso",
        None,
        1,
    )
    assert (portaria_ordinal.number, portaria_ordinal.year) == ("46", 2025)
    assert all(item.review_status == "pending" for item in proposal.candidates)
    assert law.heading_start_offset < law.heading_end_offset
    assert law.heading_end_offset <= portaria.heading_start_offset
    assert portaria.heading_end_offset <= edital.heading_start_offset
    assert edital.heading_end_offset <= aviso.heading_start_offset
    assert aviso.heading_end_offset <= portaria_ordinal.heading_start_offset
    assert portaria_ordinal.heading_end_offset <= proposal.source_length


def test_ignores_inline_mentions_and_keeps_ambiguous_year_unresolved():
    proposal = propose_gazette_boundaries(
        [
            "A Lei nº 123/2024 foi alterada por outra norma.\n"
            "Lei Complementar nº 55\n"
            "Decreto nº 7"
        ]
    )

    assert [(item.instrument_type.lower(), item.number, item.year) for item in proposal.candidates] == [
        ("lei complementar", "55", None),
        ("decreto", "7", None)
    ]
    assert all(
        item.document_class == "normative_or_cited_instrument_candidate"
        for item in proposal.candidates
    )


def test_rejects_normative_citations_in_gazette_body_as_act_boundaries():
    proposal = propose_gazette_boundaries(
        [
            "Lei Complementar 123/2006 e suas alterações, Lei Municipal nº 6.025/2009, "
            "Decreto nº 13.586/2025, conforme a legislação aplicável.\n"
            "lei complementar nº. 119 de 03 de dezembro de 2010, publicado no Diário Oficial.\n"
            "DECRETO Nº 13.586, DE 01 DE DEZEMBRO DE 2025"
        ]
    )

    assert len(proposal.candidates) == 1
    candidate = proposal.candidates[0]
    assert (candidate.instrument_type, candidate.number, candidate.year) == (
        "DECRETO", "13586", 2025
    )


def test_accepts_official_gazette_year_only_epigraph_date_without_inventing_day():
    proposal = propose_gazette_boundaries(["Lei nº 14.133, de 2021.", "Texto do ato."])

    assert len(proposal.candidates) == 1
    candidate = proposal.candidates[0]
    assert candidate.instrument_type.lower() == "lei"
    assert candidate.number == "14133"
    assert candidate.year == 2021
    assert candidate.publication_date is None


def test_parses_numeric_date_on_gazette_heading():
    proposal = propose_gazette_boundaries(
        ["Portaria nº 45/2025, de 09/10/2025", "Ato administrativo."]
    )

    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].publication_date == "2025-10-09"


def test_parses_gazette_identifier_with_agency_suffix():
    proposal = propose_gazette_boundaries(
        ["Portaria nº 4018/2026-SEAD.01, de 09 de outubro de 2026"]
    )

    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].number == "4018"
    assert proposal.candidates[0].year == 2026
    assert proposal.candidates[0].publication_date == "2026-10-09"


def test_finds_instrument_id_after_agency_or_title_prefix():
    proposal = propose_gazette_boundaries(
        [
            "RESOLUÇÃO CONHABINS N.º 03/2026 – RN",
            "EDITAL DE CHAMAMENTO PÚBLICO Nº 004/2026 - SME",
        ]
    )

    assert [(item.instrument_type.lower(), item.number, item.year) for item in proposal.candidates] == [
        ("resolução", "3", 2026),
        ("edital", "4", 2026),
    ]
    assert proposal.candidates[0].document_class == "normative_or_cited_instrument_candidate"
    assert proposal.candidates[1].document_class == "administrative_or_notice_candidate"


def test_allows_short_unnumbered_notice_or_extract_as_unidentified_candidate():
    proposal = propose_gazette_boundaries(["EDITAL DE CHAMAMENTO PÚBLICO"])
    extract = propose_gazette_boundaries(["EXTRATO DE TERMO DE COOPERAÇÃO MUNICIPAL"])

    assert len(proposal.candidates) == 1
    assert proposal.candidates[0].number is None
    assert proposal.candidates[0].year is None
    assert proposal.candidates[0].document_class == "administrative_or_notice_candidate"
    assert proposal.candidates[0].review_status == "pending"
    assert len(extract.candidates) == 1
    assert extract.candidates[0].instrument_type.lower() == "extrato"
    assert extract.candidates[0].number is None


def test_page_cap_marks_last_candidate_boundary_incomplete():
    proposal = propose_gazette_boundaries(
        ["Lei nº 1/2024", "Art. 1º", "Decreto nº 2/2025"], max_pages=2
    )

    assert proposal.status == "partial"
    assert proposal.page_count == 3
    assert proposal.processed_page_count == 2
    assert proposal.issues == (
        "heading_detection_is_not_exhaustive_or_legal_review",
        "page_limit_reached_final_boundary_incomplete",
    )
    assert proposal.candidates[0].heading_end_offset <= proposal.source_length


def test_rejects_unbounded_or_invalid_page_limit():
    with pytest.raises(ValueError, match="entre 1 e 500"):
        propose_gazette_boundaries([], max_pages=0)
    with pytest.raises(ValueError, match="entre 1 e 500"):
        propose_gazette_boundaries([], max_pages=True)
