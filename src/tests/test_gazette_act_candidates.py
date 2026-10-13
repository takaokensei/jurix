from src.processing.gazette_act_candidates import find_gazette_act_candidates


def test_finds_distinct_numbered_act_headings_and_preserves_page_offsets():
    pages = [
        "CAPA DO DIÁRIO\n\nLEI Nº 12, DE 2 DE MAIO DE 2026\nEMENTA: ATO UM.\nArt. 1º Texto.\n",
        "PORTARIA Nº 44/2026\nDesigna comissão.\n\nDECRETO EXECUTIVO Nº 5.123, DE 2026\nArt. 1º Ato três.\n",
        "LEI N.º 8.205/2026\nArt. 1º Ato quatro.\nPORTARIA N. 1234/2026-GS/SEMAD\nAto cinco.\n",
        "EXTRATO DE CONTRATO Nº 19/2026\nAVISO DE LICITAÇÃO Nº 8/2026\n",
        "PORTARIA GP N.º 123/2026-GP\nAVISO SEMAD Nº 15/2026\n",
    ]

    parsed = find_gazette_act_candidates(pages)

    assert parsed.status == "candidates_found"
    assert parsed.pages_scanned == 5
    assert parsed.truncated is False
    assert [
        (item.type_key_candidate, item.number_candidate, item.year_candidate)
        for item in parsed.candidates
    ] == [
        ("lei", "12", 2026),
        ("portaria", "44", 2026),
        ("decreto", "5123", 2026),
        ("lei", "8205", 2026),
        ("portaria", "1234", 2026),
        ("extrato", "19", 2026),
        ("aviso", "8", 2026),
        ("portaria", "123", 2026),
        ("aviso", "15", 2026),
    ]
    first, second, third = parsed.candidates[:3]
    assert first.status == second.status == third.status == "candidate"
    assert all(item.review_required for item in parsed.candidates)
    assert first.spans[0].page == 1
    assert first.spans[-1].page == 1
    assert second.spans[0].page == 2
    assert second.spans[-1].page == 2
    assert third.spans[0].page == 2
    assert parsed.candidates[3].heading_page == 3
    assert parsed.candidates[4].heading_page == 3
    assert parsed.candidates[5].heading_page == 4
    assert parsed.candidates[6].heading_page == 4
    assert parsed.candidates[7].heading_page == 5
    assert parsed.candidates[8].heading_page == 5
    assert pages[0][first.heading_start_offset : first.heading_end_offset] == first.heading_text
    assert pages[1][second.heading_start_offset : second.heading_end_offset] == second.heading_text


def test_includes_notice_like_acts_as_candidates_without_adjudicating_them():
    parsed = find_gazette_act_candidates(
        ["EDITAL Nº 7/2026\nAVISO Nº 9\nEXTRATO Nº 3\nRESOLUÇÃO Nº 2\n"]
    )

    assert [item.type_key_candidate for item in parsed.candidates] == [
        "edital",
        "aviso",
        "extrato",
        "resolucao",
    ]
    assert all(item.review_required and item.status == "candidate" for item in parsed.candidates)
    assert parsed.candidates[1].year_candidate is None


def test_rejects_body_mentions_mixed_case_and_untyped_numbers():
    parsed = find_gazette_act_candidates(
        [
            "A portaria nº 12/2026 institui a comissão.\n"
            "LEI Nº 13/2026 é citada no texto, mas segue conteúdo na mesma linha.\n"
            "AVISO IMPORTANTE SOBRE O PROCESSO\n"
            "Nº 14/2026\n"
        ]
    )

    assert parsed.status == "no_candidates"
    assert parsed.candidates == ()


def test_does_not_treat_a_cited_resolution_as_a_gazette_act_heading():
    parsed = find_gazette_act_candidates(
        [
            "Resolução CONTRAN nº 918/2022, NOTIFICA pessoas autuadas por edital.\n"
            "EDITAL Nº 1/2026\nPublicação de notificação.\n"
        ]
    )

    assert [
        (candidate.type_key_candidate, candidate.number_candidate, candidate.year_candidate)
        for candidate in parsed.candidates
    ] == [("edital", "1", 2026)]


def test_accepts_title_case_type_only_when_the_identifier_is_the_whole_line():
    parsed = find_gazette_act_candidates(
        [
            "Lei n. 8.205/2026.\n",
            "Lei n. 8.206/2026 trata do programa municipal.\n",
            "LEI n. 8 . 207/2026.\n",
        ]
    )

    assert len(parsed.candidates) == 2
    assert [item.type_key_candidate for item in parsed.candidates] == ["lei", "lei"]
    assert [item.number_candidate for item in parsed.candidates] == ["8205", "8207"]


def test_accepts_title_case_norm_with_an_explicit_date_but_no_body_prose():
    parsed = find_gazette_act_candidates(
        ["Resolução n. 14/2026, de 8 de outubro de 2026.\n"]
    )

    assert len(parsed.candidates) == 1
    assert parsed.candidates[0].type_key_candidate == "resolucao"
    assert parsed.candidates[0].number_candidate == "14"
    assert parsed.candidates[0].year_candidate == 2026


def test_unnumbered_notices_remain_candidates_with_missing_identity_explicit():
    parsed = find_gazette_act_candidates(
        [
            "EDITAL DE CONVOCAÇÃO DE AUDIÊNCIA PÚBLICA\n"
            "AVISO DE CONSULTA PÚBLICA\n"
            "AVISO IMPORTANTE SOBRE O PROCESSO\n"
        ]
    )

    assert [item.type_key_candidate for item in parsed.candidates] == ["edital", "aviso"]
    assert all(item.number_candidate is None for item in parsed.candidates)
    assert all(item.review_required for item in parsed.candidates)


def test_detects_mixed_case_epigraph_dates_after_uppercase_act_labels():
    parsed = find_gazette_act_candidates(
        [
            "PORTARIA Nº 57, de 29 de setembro de 2026\n",
            "RESOLUÇÃO Nº 1, de 29 de setembro de 2026.\n",
            "PORTARIA Nº 58, de 29 de setembro de 2026 designa comissão.\n",
        ]
    )

    assert [
        (item.type_key_candidate, item.number_candidate, item.year_candidate)
        for item in parsed.candidates
    ] == [("portaria", "57", 2026), ("resolucao", "1", 2026)]
    assert all(item.review_required and item.status == "candidate" for item in parsed.candidates)


def test_detects_unnumbered_notice_and_extract_headings_but_not_generic_alerts():
    parsed = find_gazette_act_candidates(
        [
            "AVISO DE LICITAÇÃO\n",
            "EXTRATO DE CONTRATO\n",
            "AVISO IMPORTANTE SOBRE O PROCESSO\n",
        ]
    )

    assert [item.type_key_candidate for item in parsed.candidates] == ["aviso", "extrato"]
    assert all(item.number_candidate is None and item.review_required for item in parsed.candidates)


def test_spans_end_at_next_heading_and_leave_front_matter_unassigned():
    page = "CAPA\n\nLEI Nº 1/2020\nArt. 1º A\nDECRETO Nº 2/2020\nArt. 1º B\n"

    parsed = find_gazette_act_candidates([page])

    first, second = parsed.candidates
    assert page[first.spans[0].start_offset : first.spans[0].end_offset].startswith("LEI Nº 1/2020")
    assert page[first.spans[0].start_offset : first.spans[0].end_offset].endswith("Art. 1º A\n")
    assert page[second.spans[0].start_offset : second.spans[0].end_offset].startswith(
        "DECRETO Nº 2/2020"
    )
    assert page[second.spans[0].start_offset : second.spans[0].end_offset].endswith("Art. 1º B\n")


def test_scan_limit_is_explicit_and_reported_as_truncated():
    parsed = find_gazette_act_candidates(["LEI Nº 1/2020\n", "DECRETO Nº 2/2020\n"], max_pages=1)

    assert parsed.status == "truncated"
    assert parsed.truncated is True
    assert parsed.pages_scanned == 1
    assert len(parsed.candidates) == 1


def test_repeated_exact_headings_are_flagged_without_deduplicating_occurrences():
    parsed = find_gazette_act_candidates(
        [
            "EDITAL DE CONVOCACAO\n",
            "  EDITAL   DE CONVOCACAO \nLEI Nº 2/2026\n",
        ]
    )

    assert [candidate.type_key_candidate for candidate in parsed.candidates] == ["edital", "edital", "lei"]
    assert [candidate.repeated_heading_count for candidate in parsed.candidates] == [2, 2, 1]
    assert [candidate.heading_page for candidate in parsed.candidates] == [1, 2, 2]
    assert all(candidate.review_required for candidate in parsed.candidates)
    serialized = parsed.as_dict()["candidates"]
    assert [candidate["repeated_heading_count"] for candidate in serialized] == [2, 2, 1]
    assert all("heading_text" not in candidate for candidate in serialized)


def test_rejects_invalid_page_limit():
    try:
        find_gazette_act_candidates([], max_pages=0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected max_pages validation")
