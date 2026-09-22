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
        assert events[0]['acao'] == 'REVOGA'
        assert events[0]['referencia_tipo'] == 'artigo'
        assert events[0]['referencia_numero'] == '1º'

        # Second event must be ALTERA -> art 2º
        assert events[1]['acao'] == 'ALTERA'
        assert events[1]['referencia_tipo'] == 'artigo'
        assert events[1]['referencia_numero'] == '2º'
        assert events[1]['norma_referenciada'] is not None
        assert events[1]['norma_referenciada']['numero'] == '100'
        assert events[1]['norma_referenciada']['ano'] == '2020'

    def test_self_reference_vs_external_law(self, extractor):
        """
        'desta Lei' should be self_reference; 'da Lei 500/2021' must NOT be classified as self_reference.
        """
        text_self = "Fica alterado o art. 5º desta Lei."
        events_self = extractor.extract_events(text_self)
        assert len(events_self) == 1
        assert events_self[0]['acao'] == 'ALTERA'
        assert events_self[0]['referencia_numero'] == '5º'

        # External law should not produce a separate self_reference token
        text_ext = "Fica revogado o art. 12 da Lei nº 4.567/2022."
        events_ext = extractor.extract_events(text_ext)
        assert len(events_ext) == 1
        assert events_ext[0]['acao'] == 'REVOGA'
        assert events_ext[0]['referencia_numero'] == '12'
        assert events_ext[0]['norma_referenciada']['numero'] == '4.567'
        assert events_ext[0]['norma_referenciada']['ano'] == '2022'

        # Verify no self_reference event was spuriously generated
        assert not any(e['referencia_tipo'] == 'self_reference' for e in events_ext)

    def test_structural_elements_extraction(self, extractor):
        """Verify extraction of parágrafo único, inciso, and alínea."""
        text = "Fica alterado o § único, o inciso III e a alínea a) do art. 8º."
        events = extractor.extract_events(text)

        types_extracted = {e['referencia_tipo']: e['referencia_numero'] for e in events}
        assert 'paragrafo' in types_extracted
        assert 'inciso' in types_extracted
        assert types_extracted['inciso'] == 'III'
        assert 'artigo' in types_extracted
        assert types_extracted['artigo'] == '8º'

    def test_suffixed_article_number_is_preserved(self, extractor):
        """'Art. 2º-A' must not collapse into 'Art. 2º' (a different article)."""
        events = extractor.extract_events("Fica adicionado o art. 2º-A à Lei 100/2020.")
        artigos = [e for e in events if e['referencia_tipo'] == 'artigo']
        assert [e['referencia_numero'] for e in artigos] == ['2º-A']

    def test_revocation_of_suffixed_article_does_not_target_base_article(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º-B da Lei 100/2020.")
        artigos = [e for e in events if e['referencia_tipo'] == 'artigo']
        assert [e['referencia_numero'] for e in artigos] == ['5º-B']

    def test_plain_article_followed_by_dash_and_word_is_not_suffixed(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º-Aplicam-se demais regras.")
        artigos = [e for e in events if e['referencia_tipo'] == 'artigo']
        assert [e['referencia_numero'] for e in artigos] == ['5º']

    # ---- the most common amendment wordings used to produce NO event at all ----
    @pytest.mark.parametrize("text", [
        "O art. 5º da Lei nº 123/2020 passa a vigorar com a seguinte redação: “Art. 5º O prazo é de 30 dias.”",
        "O art. 5º da Lei nº 123/2020 passa a ter a seguinte redação: “Art. 5º Novo texto.”",
        "Dê-se ao art. 5º da Lei nº 123/2020 a seguinte redação: “Art. 5º Novo texto.”",
        "Dá-se nova redação ao art. 5º da Lei nº 123/2020.",
        "Fica dada nova redação ao art. 5º da Lei nº 123/2020.",
    ])
    def test_common_amendment_wordings_yield_an_alteration(self, extractor, text):
        events = extractor.extract_events(text)
        altera = [e for e in events if e['acao'] == 'ALTERA' and e['referencia_tipo'] == 'artigo']
        assert altera, f"no ALTERA event for: {text}"
        assert altera[0]['referencia_numero'] == '5º'
        assert (altera[0]['norma_referenciada'] or {}).get('numero') == '123'

    def test_entry_into_force_is_not_an_alteration(self, extractor):
        events = extractor.extract_events("Esta Lei entra em vigor na data de sua publicação.")
        assert [e for e in events if e['acao'] == 'ALTERA'] == []

    def test_plain_citation_stays_a_reference_not_an_alteration(self, extractor):
        events = extractor.extract_events("Nos termos do art. 5º da Lei nº 123/2020, o prazo é de 30 dias.")
        assert {e['acao'] for e in events} == {'REFERENCIA'}

    def test_revocation_wording_is_unchanged(self, extractor):
        events = extractor.extract_events("Fica revogado o art. 5º da Lei nº 123/2020.")
        assert [(e['acao'], e['referencia_numero']) for e in events] == [('REVOGA', '5º')]

    # ---- lists and ranges of articles (a partial extraction silently leaves articles in force) ----
    @staticmethod
    def _articles(events):
        return [(e['acao'], e['referencia_numero']) for e in events if e['referencia_tipo'] == 'artigo']

    @pytest.mark.parametrize("text,expected", [
        ("Ficam revogados os arts. 5º e 6º da Lei nº 123/2020.", ["5º", "6º"]),
        ("Ficam revogados os artigos 5º e 6º da Lei nº 123/2020.", ["5º", "6º"]),
        ("Revogam-se os arts. 5º, 6º e 7º da Lei nº 123/2020.", ["5º", "6º", "7º"]),
        ("Ficam revogados o art. 5º, 6º e 7º da Lei nº 123/2020.", ["5º", "6º", "7º"]),
        ("Ficam revogados o art. 5º e os arts. 7º e 8º da Lei nº 123/2020.", ["5º", "7º", "8º"]),
        ("Ficam revogados os arts. 7º e 8º e o art. 5º da Lei nº 123/2020.", ["7º", "8º", "5º"]),
        ("Fica revogado o art. 5º, bem como os arts. 7º a 9º da Lei nº 123/2020.", ["5º", "7º a 9º"]),
        ("Ficam revogados os arts. 5º a 8º da Lei nº 123/2020.", ["5º a 8º"]),
        ("Ficam revogados os arts. 5º ao 8º da Lei nº 123/2020.", ["5º a 8º"]),
        ("Ficam revogados os arts. 10 a 12 da Lei nº 123/2020.", ["10 a 12"]),
        ("Ficam revogados os arts. 5º-A e 5º-B da Lei nº 123/2020.", ["5º-A", "5º-B"]),
    ])
    def test_lists_and_ranges_of_articles_are_fully_extracted(self, extractor, text, expected):
        assert [n for _, n in self._articles(extractor.extract_events(text))] == expected

    @pytest.mark.parametrize("text,expected", [
        ("Fica revogado o art. 5º e 10 dias de prazo.", ["5º"]),
        ("Fica revogado o art. 5º, 2020 conforme registro.", ["5º"]),
        ("Fica revogado o art. 5º e 30% do valor.", ["5º"]),
        ("Fica revogado o art. 5º a Lei nº 123/2020.", ["5º"]),
        ("Fica revogado o art. 5º, § 1º da Lei nº 123/2020.", ["5º"]),
    ])
    def test_numbers_that_are_not_articles_are_not_swallowed_into_the_list(self, extractor, text, expected):
        assert [n for _, n in self._articles(extractor.extract_events(text))] == expected

    def test_an_inverted_or_huge_range_is_kept_verbatim_for_the_resolver_to_refuse(self, extractor):
        inverted = self._articles(extractor.extract_events("Ficam revogados os arts. 9º a 5º da Lei nº 123/2020."))
        assert inverted == [("REVOGA", "9º a 5º")]
