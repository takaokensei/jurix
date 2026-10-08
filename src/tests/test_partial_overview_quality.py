from django.test import SimpleTestCase

from src.processing.partial_overview_quality import (
    has_redundant_content_phrase,
    has_repeated_citation_marker,
)


class PartialOverviewQualityTests(SimpleTestCase):
    def test_rejects_a_device_cited_by_multiple_claims_in_partial_overview(self):
        self.assertTrue(has_repeated_citation_marker(
            "A norma cria o plano. [[1]] A implantação do plano segue a lei. [[1]] [[2]] [[3]]"
        ))

    def test_allows_distinct_devices_in_partial_overview(self):
        self.assertFalse(has_repeated_citation_marker(
            "A norma cria o plano. [[1]] A carreira progride. [[2]] Os critérios constam no Art. 3º. [[3]]"
        ))

    def test_rejects_repeated_content_phrase_inside_one_sentence(self):
        answer = (
            "A progressão funcional dos servidores ocorre por meio da "
            "progressão funcional e da promoção. [[1]]"
        )

        self.assertTrue(has_redundant_content_phrase(answer))

    def test_allows_same_phrase_in_separate_sentences(self):
        answer = "A progressão funcional é prevista no Art. 2º. [[1]] A progressão funcional segue critérios próprios. [[2]]"

        self.assertFalse(has_redundant_content_phrase(answer))

    def test_rejects_repeated_specific_topic_across_separate_sentences(self):
        answer = (
            "A lei institui o Plano de Cargos, Carreiras e Vencimentos dos profissionais da Saúde. [[1]] "
            "O Plano de Cargos, Carreiras e Vencimentos dos profissionais da Saúde terá implantação gradual. [[2]]"
        )

        self.assertTrue(has_redundant_content_phrase(answer))

    def test_rejects_repeated_long_topic_inside_one_sentence(self):
        answer = (
            "A lei estabelece o Plano de Cargos, Carreiras e Vencimentos dos profissionais da Saúde, "
            "servidores estatutários da Secretaria Municipal, denominado Plano de Cargos, Carreiras "
            "e Vencimentos da Saúde. [[1]]"
        )

        self.assertTrue(has_redundant_content_phrase(answer))

    def test_ignores_repeated_generic_legal_labels(self):
        answer = "A Lei Complementar cita o Art. 1º e o Art. 2º da norma. [[1]]"

        self.assertFalse(has_redundant_content_phrase(answer))
