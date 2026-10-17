"""
Unit tests for LegalNERExtractor.

Verifies:
- Elimination of Cartesian product between actions and references
- Clean distinction between self-references ('desta Lei') and external statute numbers ('da Lei 100/2020')
- Correct extraction of articles, paragraphs, incisos, and alíneas
"""

import pytest

from src.processing.ner_extractor import LegalNERExtractor


class TestLegalNERExtractor:
    """Test suite for LegalNERExtractor."""

    @pytest.fixture
    def extractor(self):
        return LegalNERExtractor()

    def test_no_cartesian_product_on_multiple_actions(self, extractor):
        """
        Verify that 'Revoga o art. 1º e altera o art. 2º da Lei 100/2020'
        does NOT generate Cartesian product (REVOGA -> art. 2º must not exist).
        """
        text = "Fica revogado o art. 1º e alterado o art. 2º da Lei 100/2020."
        events = extractor.extract_events(text)

        assert len(events) == 2

        # First event must be REVOGA -> art 1º
        assert events[0]["acao"] == "REVOGA"
        assert events[0]["referencia_tipo"] == "artigo"
        assert events[0]["referencia_numero"] == "1º"

        # Second event must be ALTERA -> art 2º
        assert events[1]["acao"] == "ALTERA"
        assert events[1]["referencia_tipo"] == "artigo"
        assert events[1]["referencia_numero"] == "2º"
        assert events[1]["norma_referenciada"] is not None
        assert events[1]["norma_referenciada"]["numero"] == "100"
        assert events[1]["norma_referenciada"]["ano"] == "2020"

    def test_self_reference_vs_external_law(self, extractor):
        """
        'desta Lei' should be self_reference; 'da Lei 500/2021' must NOT be classified as self_reference.
        """
        text_self = "Fica alterado o art. 5º desta Lei."
        events_self = extractor.extract_events(text_self)
        assert len(events_self) == 1
        assert events_self[0]["acao"] == "ALTERA"
        assert events_self[0]["referencia_numero"] == "5º"

        # External law should not produce a separate self_reference token
        text_ext = "Fica revogado o art. 12 da Lei nº 4.567/2022."
        events_ext = extractor.extract_events(text_ext)
        assert len(events_ext) == 1
        assert events_ext[0]["acao"] == "REVOGA"
        assert events_ext[0]["referencia_numero"] == "12"
        assert events_ext[0]["norma_referenciada"]["numero"] == "4.567"
        assert events_ext[0]["norma_referenciada"]["ano"] == "2022"

        # Verify no self_reference event was spuriously generated
        assert not any(e["referencia_tipo"] == "self_reference" for e in events_ext)

    def test_structural_elements_extraction(self, extractor):
        """Verify extraction of parágrafo único, inciso, and alínea."""
        text = "Fica alterado o § único, o inciso III e a alínea a) do art. 8º."
        events = extractor.extract_events(text)

        types_extracted = {e["referencia_tipo"]: e["referencia_numero"] for e in events}
        assert "paragrafo" in types_extracted
        assert "inciso" in types_extracted
        assert types_extracted["inciso"] == "III"
        assert "artigo" in types_extracted
        assert types_extracted["artigo"] == "8º"

    def test_suffixed_article_number_is_preserved(self, extractor):
        """'Art. 2º-A' must not collapse into 'Art. 2º' (a different article)."""
        events = extractor.extract_events("Fica adicionado o art. 2º-A à Lei 100/2020.")
        artigos = [e for e in events if e["referencia_tipo"] == "artigo"]
        assert [e["referencia_numero"] for e in artigos] == ["2º-A"]

    def test_revocation_of_suffixed_article_does_not_target_base_article(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º-B da Lei 100/2020.")
        artigos = [e for e in events if e["referencia_tipo"] == "artigo"]
        assert [e["referencia_numero"] for e in artigos] == ["5º-B"]

    def test_plain_article_followed_by_dash_and_word_is_not_suffixed(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º-Aplicam-se demais regras.")
        artigos = [e for e in events if e["referencia_tipo"] == "artigo"]
        assert [e["referencia_numero"] for e in artigos] == ["5º"]

    # ---- the most common amendment wordings used to produce NO event at all ----
    @pytest.mark.parametrize(
        "text",
        [
            "O art. 5º da Lei nº 123/2020 passa a vigorar com a seguinte redação: “Art. 5º O prazo é de 30 dias.”",
            "O art. 5º da Lei nº 123/2020 passa a ter a seguinte redação: “Art. 5º Novo texto.”",
            "Dê-se ao art. 5º da Lei nº 123/2020 a seguinte redação: “Art. 5º Novo texto.”",
            "Dá-se nova redação ao art. 5º da Lei nº 123/2020.",
            "Fica dada nova redação ao art. 5º da Lei nº 123/2020.",
        ],
    )
    def test_common_amendment_wordings_yield_an_alteration(self, extractor, text):
        events = extractor.extract_events(text)
        altera = [e for e in events if e["acao"] == "ALTERA" and e["referencia_tipo"] == "artigo"]
        assert altera, f"no ALTERA event for: {text}"
        assert altera[0]["referencia_numero"] == "5º"
        assert (altera[0]["norma_referenciada"] or {}).get("numero") == "123"

    def test_entry_into_force_is_not_an_alteration(self, extractor):
        events = extractor.extract_events("Esta Lei entra em vigor na data de sua publicação.")
        assert [e for e in events if e["acao"] == "ALTERA"] == []

    def test_plain_citation_stays_a_reference_not_an_alteration(self, extractor):
        events = extractor.extract_events(
            "Nos termos do art. 5º da Lei nº 123/2020, o prazo é de 30 dias."
        )
        assert {e["acao"] for e in events} == {"REFERENCIA"}

    def test_revocation_wording_is_unchanged(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º da Lei nº 123/2020.")
        assert [(e["acao"], e["referencia_numero"]) for e in events] == [("REVOGA", "5º")]

    def test_common_legal_vocabulary_is_not_misclassified_as_change_actions(self, extractor):
        text = (
            "A norma apresenta alternativas de atendimento, incluindo opções adicionais "
            "para o interessado."
        )
        events = extractor.extract_events(text)
        assert not {
            "ALTERA",
            "ADICIONA",
            "SUBSTITUI",
            "REVOGA",
        }.intersection(event["acao"] for event in events)

    def test_dotted_thousands_separator_does_not_truncate_statute_reference(self, extractor):
        text = (
            "Ficam revogados o art. 21 da Lei Complementar nº 1.894/1969."
        )
        events = extractor.extract_events(text)
        article_event = next(event for event in events if event["referencia_tipo"] == "artigo")
        assert article_event["referencia_numero"] == "21"
        assert article_event["norma_referenciada"]["numero"] == "1.894"
        assert article_event["norma_referenciada"]["ano"] == "1969"

    def test_comma_after_statute_number_is_not_part_of_its_identity(self, extractor):
        text = (
            "Fica alterado o art. 14 da Lei Complementar nº 208, "
            "de 07 de março de 2022."
        )
        events = extractor.extract_events(text)
        article_event = next(event for event in events if event["referencia_tipo"] == "artigo")
        assert article_event["norma_referenciada"]["tipo"] == "Lei Complementar"
        assert article_event["norma_referenciada"]["numero"] == "208"
        assert article_event["norma_referenciada"]["ano"] == "2022"

    def test_action_clause_is_inherited_by_each_enumerated_target_without_cross_linking(
        self, extractor
    ):
        introduction = extractor.list_action_introduction(
            "Art. 260. Ficam revogados:"
        )
        assert introduction == {
            "action": "REVOGA",
            "quote": "Ficam revogados",
            "start_offset": 10,
            "end_offset": 25,
        }
        items = [
            ("I - Lei Complementar nº 1.894 de 31 de dezembro de 1969;", "1.894", "1969"),
            ("II - Lei Nº 4.566 de 19 de maio de 1992;", "4.566", "1992"),
            ("III - Lei nº 4.885 de 07 de outubro de 1997;", "4.885", "1997"),
            ("IV - Lei Complementar nº 055 de 27 de janeiro de 2004;", "055", "2004"),
            (
                "V - Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009;",
                "275",
                "2009",
            ),
            ("VI - Lei Promulgada nº 562 de 14 de setembro de 2018;", "562", "2018"),
            ("VII - Lei nº 198 de 12 de novembro de 2021.", "198", "2021"),
        ]
        extracted = []
        for item, expected_number, expected_year in items:
            events = extractor.extract_inherited_list_item_events(introduction, item)
            assert len(events) == 1
            event = events[0]
            assert event["acao"] == "REVOGA"
            assert event["norma_referenciada"]["numero"] == expected_number
            assert event["norma_referenciada"]["ano"] == expected_year
            assert event["evidence"]["quote"] == item
            assert event["evidence"]["action_context"]["source_quote"] == "Ficam revogados"
            extracted.append(event["norma_referenciada"]["numero"])
        assert extracted == ["1.894", "4.566", "4.885", "055", "275", "562", "198"]
        article_event = extractor.extract_inherited_list_item_events(introduction, items[4][0])[0]
        assert article_event["referencia_tipo"] == "artigo"
        assert article_event["referencia_numero"] == "21"

    def test_list_action_introduction_requires_a_terminal_colon(self, extractor):
        assert extractor.list_action_introduction("Ficam revogados:") is not None
        assert extractor.list_action_introduction("Art. 117. Revogam-se:")["quote"] == "Revogam-se"
        assert extractor.list_action_introduction("Ficam revogados os arts. 1º e 2º.") is None

    def test_inherited_revocation_resolves_municipal_qualifier_but_keeps_article_target(self, extractor):
        introduction = extractor.list_action_introduction("Art. 117. Revogam-se:")
        events = extractor.extract_inherited_list_item_events(
            introduction,
            "I - Art. 21 e Anexo A da Lei Municipal nº 208 de 08 de março de 2022;",
        )
        article_event = next(event for event in events if event["referencia_tipo"] == "artigo")
        assert article_event["referencia_numero"] == "21"
        assert article_event["norma_referenciada"]["tipo"] == "Lei"
        assert article_event["norma_referenciada"]["numero"] == "208"
        assert article_event["norma_referenciada"]["ano"] == "2022"

    def test_inherited_action_expands_each_numbered_law_in_a_plural_list_item(self, extractor):
        introduction = extractor.list_action_introduction("Art. 117. Revogam-se:")
        item = (
            "II - Leis Municipais nº 4.664 de 31 de julho de 1995, nº 5.273 de 20 de junho de "
            "2001, nº 4.912 de 10 de dezembro de 1997, nº 5.565 de 21 de junho de 2004, "
            "nº 221 de 22 de dezembro de 2022, nº 222 de 22 de dezembro de 2022, "
            "nº 223 de 22 de dezembro de 2022;"
        )
        events = extractor.extract_inherited_list_item_events(introduction, item)
        assert [
            (event["norma_referenciada"]["numero"], event["norma_referenciada"]["ano"])
            for event in events
        ] == [
            ("4.664", "1995"),
            ("5.273", "2001"),
            ("4.912", "1997"),
            ("5.565", "2004"),
            ("221", "2022"),
            ("222", "2022"),
            ("223", "2022"),
        ]
        assert all(event["acao"] == "REVOGA" for event in events)
        assert all(event["evidence"]["quote"] == item for event in events)

    # ---- lists and ranges of articles (a partial extraction silently leaves articles in force) ----
    @staticmethod
    def _articles(events):
        return [
            (e["acao"], e["referencia_numero"]) for e in events if e["referencia_tipo"] == "artigo"
        ]

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Ficam revogados os arts. 5º e 6º da Lei nº 123/2020.", ["5º", "6º"]),
            ("Ficam revogados os artigos 5º e 6º da Lei nº 123/2020.", ["5º", "6º"]),
            ("Revogam-se os arts. 5º, 6º e 7º da Lei nº 123/2020.", ["5º", "6º", "7º"]),
            ("Ficam revogados o art. 5º, 6º e 7º da Lei nº 123/2020.", ["5º", "6º", "7º"]),
            (
                "Ficam revogados o art. 5º e os arts. 7º e 8º da Lei nº 123/2020.",
                ["5º", "7º", "8º"],
            ),
            (
                "Ficam revogados os arts. 7º e 8º e o art. 5º da Lei nº 123/2020.",
                ["7º", "8º", "5º"],
            ),
            (
                "Fica revogado o art. 5º, bem como os arts. 7º a 9º da Lei nº 123/2020.",
                ["5º", "7º a 9º"],
            ),
            ("Ficam revogados os arts. 5º a 8º da Lei nº 123/2020.", ["5º a 8º"]),
            ("Ficam revogados os arts. 5º ao 8º da Lei nº 123/2020.", ["5º a 8º"]),
            ("Ficam revogados os arts. 10 a 12 da Lei nº 123/2020.", ["10 a 12"]),
            ("Ficam revogados os arts. 5º-A e 5º-B da Lei nº 123/2020.", ["5º-A", "5º-B"]),
        ],
    )
    def test_lists_and_ranges_of_articles_are_fully_extracted(self, extractor, text, expected):
        assert [n for _, n in self._articles(extractor.extract_events(text))] == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Fica revogado o art. 5º e 10 dias de prazo.", ["5º"]),
            ("Fica revogado o art. 5º, 2020 conforme registro.", ["5º"]),
            ("Fica revogado o art. 5º e 30% do valor.", ["5º"]),
            ("Fica revogado o art. 5º a Lei nº 123/2020.", ["5º"]),
            ("Fica revogado o art. 5º, § 1º da Lei nº 123/2020.", ["5º"]),
        ],
    )
    def test_numbers_that_are_not_articles_are_not_swallowed_into_the_list(
        self, extractor, text, expected
    ):
        assert [n for _, n in self._articles(extractor.extract_events(text))] == expected

    def test_an_inverted_or_huge_range_is_kept_verbatim_for_the_resolver_to_refuse(self, extractor):
        inverted = self._articles(
            extractor.extract_events("Ficam revogados os arts. 9º a 5º da Lei nº 123/2020.")
        )
        assert inverted == [("REVOGA", "9º a 5º")]

    def test_line_wrapped_article_suffix_keeps_the_remainder_of_real_amendment_list(
        self, extractor
    ):
        text = (
            "Os artigos 2º, 3º, 16, 23, 25, 31, 38, 43, 43-A, 48, 50, 57, 60, 64, 68, 86, "
            "97, 98-\n A, 99, 100, 107, 112, 113, 131, 133, 143, 146, 156, 160-B, 161 e 169 "
            "da Lei 3.882 de 11 de dezembro de 1989 passam a vigorar com as seguintes redações."
        )
        expected = [
            "2º", "3º", "16", "23", "25", "31", "38", "43", "43-A", "48", "50",
            "57", "60", "64", "68", "86", "97", "98-A", "99", "100", "107", "112",
            "113", "131", "133", "143", "146", "156", "160-B", "161", "169",
        ]

        assert [number for _, number in self._articles(extractor.extract_events(text))] == expected
