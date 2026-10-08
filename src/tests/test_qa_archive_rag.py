import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from src.apps.legislation.document_models import ExtracaoDocumento
from src.processing.normative_query import classify_normative_query
from src.processing.qa_archive_rag import (
    _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
    _has_partial_overview_breadth,
    _intersticio_duration_not_recovered,
    _is_whole_norm_request,
    _partial_overview_excerpts,
    _partial_overview_sample_limit,
    _sample_whole_norm_rows,
    retrieve_archive_evidence,
    stream_archive_qa_answer,
)


def _archive_document(*, number="6021", year=2009, legal_text=None):
    legal_text = legal_text or (
        "Art. 1º Fica instituído o Programa Municipal de Hortas Comunitárias.\n"
        "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação."
    )
    extraction = SimpleNamespace(
        status=ExtracaoDocumento.Status.COMPLETE,
        legal_text=legal_text,
        extraction_sha256="a" * 64,
    )
    return SimpleNamespace(
        public_id="00000000-0000-0000-0000-000000000001",
        metadata_json={
            "identity_candidate": {"type": "lei_ordinaria", "number": number, "year": year},
            "identity_key": f"BR-RN-NATAL:lei:{number}:{year}",
        },
        conflicts_json=[],
        extracoes=SimpleNamespace(order_by=lambda *_args: SimpleNamespace(first=lambda: extraction)),
    )


def _completed_generation_stream(result):
    if result.get("grounded") and result.get("source_only"):
        yield {"event": "chunk", "chunk": result["answer"], "provisional": False}
    return result


@override_settings(NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED=False)
class ArchiveQARetrievalTests(SimpleTestCase):
    def test_partial_overview_revision_explicitly_forbids_generalizing_beyond_sample(self):
        self.assertIn(
            "usando somente os excertos amostrados",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn(
            "preserve o verbo e a modalidade do texto",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn(
            "um único marcador [[N]] no fim",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn(
            "Não use negação para descrever o que a amostra não contém",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn(
            "A cobertura e os anexos serão informados pelo sistema",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn(
            "Não reescreva em outra frase a criação ou denominação já explicada",
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
        )
        self.assertIn("Pare após a última afirmação.", _PARTIAL_OVERVIEW_REVISION_INSTRUCTION)

    def test_partial_overview_sample_size_adapts_to_norm_breadth(self):
        self.assertEqual(_partial_overview_sample_limit(0), 0)
        self.assertEqual(_partial_overview_sample_limit(3), 3)
        self.assertEqual(_partial_overview_sample_limit(8), 8)
        self.assertEqual(_partial_overview_sample_limit(9), 5)
        self.assertEqual(_partial_overview_sample_limit(19), 5)
        self.assertEqual(_partial_overview_sample_limit(30), 6)
        self.assertEqual(_partial_overview_sample_limit(100), 10)

        sources = [
            {
                "citation_id": f"qa:overview-{article}",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Conteúdo verificável {article}.",
            }
            for article in range(1, 31)
        ]
        excerpts = _partial_overview_excerpts(
            sources,
            limit=_partial_overview_sample_limit(len(sources)),
            question="Quais são os principais temas desta norma?",
        )

        self.assertEqual(
            [row["device"] for row in excerpts],
            ["Art. 1º", "Art. 7º", "Art. 13º", "Art. 18º", "Art. 24º", "Art. 30º"],
        )

    def test_partial_overview_requires_distinct_valid_sources_but_allows_repeated_markers(self):
        self.assertTrue(_has_partial_overview_breadth(
            "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[3]]",
            6,
            available_sample_sources=3,
        ))
        self.assertFalse(_has_partial_overview_breadth(
            "Uma afirmação. [[1]] Outra afirmação. [[1]] Terceira afirmação. [[3]]",
            6,
            available_sample_sources=3,
        ))
        self.assertTrue(_has_partial_overview_breadth(
            "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[3]] "
            "Quarta afirmação. [[1]] Quinta afirmação. [[4]]",
            6,
            available_sample_sources=4,
        ))
        self.assertFalse(_has_partial_overview_breadth(
            "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[9]]",
            6,
            available_sample_sources=3,
        ))

    def test_partial_overview_avoids_generic_closing_clause_unless_asked(self):
        sources = [
            {
                "citation_id": f"qa:overview-{article}",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": (
                    "Art. 9º. Esta Lei Complementar entra em vigor na data de sua publicação, "
                    "revogando-se todas as disposições em contrário. Sala das Sessões, em Natal, "
                    "20 de agosto de 2026. Publicada no Diário Oficial do Município."
                    if article == 9
                    else f"Art. {article}º. Este dispositivo estabelece o tema {article}."
                ),
            }
            for article in range(1, 10)
        ]

        overview = _partial_overview_excerpts(
            sources,
            limit=5,
            question="Quais são os principais temas tratados nesta norma?",
        )
        temporal = _partial_overview_excerpts(
            sources,
            limit=5,
            question="Quando esta Lei Complementar entra em vigor?",
        )

        self.assertEqual(len(overview), 5)
        self.assertNotIn("Art. 9º", [row["device"] for row in overview])
        self.assertIn("Art. 9º", [row["device"] for row in temporal])

    def test_whole_norm_selection_keeps_all_articles_when_they_fit_budget(self):
        rows = [
            {"dispositivo_ref": f"Art. {article}º", "full_text": "x" * 300}
            for article in range(1, 40)
        ]

        selected, total = _sample_whole_norm_rows(rows)

        self.assertEqual(total, 39)
        self.assertEqual(selected, rows)

    def test_whole_norm_selection_samples_by_actual_context_budget(self):
        rows = [
            {"dispositivo_ref": f"Art. {article}º", "full_text": "x" * 1_000}
            for article in range(1, 40)
        ]

        selected, total = _sample_whole_norm_rows(rows)

        self.assertEqual(total, 39)
        self.assertLess(len(selected), total)
        self.assertLessEqual(sum(len(row["full_text"]) for row in selected), 24_000)
        self.assertEqual(selected[0]["dispositivo_ref"], "Art. 1º")
        self.assertEqual(selected[-1]["dispositivo_ref"], "Art. 39º")

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_exact_law_and_article_retrieves_only_that_article(self, filter_documents):
        document = _archive_document()
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que prevê o Art. 2º da Lei nº 6.021/2009 sobre coordenação?", limit=8
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dispositivo_ref"], "Art. 2º")
        self.assertIn("Secretaria Municipal de Educação", rows[0]["full_text"])
        self.assertIn("acervo histórico local", rows[0]["source_type"].lower())
        self.assertIsNone(rows[0]["sapl_url"])
        self.assertEqual(
            rows[0]["local_pdf_url"],
            "/normas/documentos/00000000-0000-0000-0000-000000000001/pdf/",
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_municipal_decree_reference_excludes_same_article_from_other_norms(
        self, filter_documents
    ):
        unrelated_law = _archive_document(number="5692", year=2005)
        unrelated_decree = _archive_document(number="7744", year=2005)
        requested_decree = _archive_document(number="7795", year=2005)
        unrelated_law.metadata_json["identity_candidate"]["type"] = "lei_ordinaria"
        unrelated_decree.metadata_json["identity_candidate"]["type"] = "decreto"
        requested_decree.metadata_json["identity_candidate"]["type"] = "decreto"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [
            unrelated_law,
            unrelated_decree,
            requested_decree,
        ]

        rows = retrieve_archive_evidence(
            "O que prevê o Art. 1º do Decreto municipal nº 7.795/2005?", limit=8
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norma_ref"], "Decreto nº 7795/2005")
        self.assertEqual(rows[0]["dispositivo_ref"], "Art. 1º")

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_explicit_appendix_followup_returns_only_named_appendix(self, filter_documents):
        document = _archive_document(
            number="7795",
            year=2005,
            legal_text=(
                "Art. 1º Abre crédito suplementar de R$ 12.000,00.\n"
                "Art. 2º A origem do recurso será o cancelamento de dotação.\n"
                "Sala das Sessões, Natal, 20 de agosto de 2005. Presidente.\n"
                "Publicada no Diário Oficial do Município em: 21/9/2005 Autoria: Câmara.\n"
                "ADENDO I (Incorporação)\nManutenção do FUNAM.\n"
                "ADENDO II (Redução)\nReabilitação da Ribeira e reestruturação da Cidade Alta."
            ),
        )
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que consta no Adendo I da Lei nº 7.795/2005 para esse crédito?",
            limit=8,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dispositivo_ref"], "Adendo I")
        self.assertIn("Manutenção do FUNAM", rows[0]["full_text"])
        self.assertNotIn("Reabilitação da Ribeira", rows[0]["full_text"])
        self.assertNotIn("Publicada no Diário Oficial", rows[0]["full_text"])
        self.assertEqual(rows[0]["coverage"]["evidence_kind"], "normative_appendix")
        self.assertEqual(rows[0]["coverage"]["requested_appendix"], "Adendo I")

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_appendix_followup_without_resolved_norm_does_not_guess(self, filter_documents):
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [
            _archive_document()
        ]

        rows = retrieve_archive_evidence("E o que consta no Adendo I para esse crédito?")

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_multiple_explicit_laws_do_not_fall_back_to_an_unrelated_document(self, filter_documents):
        unrelated = _archive_document(
            number="198",
            year=2021,
            legal_text=(
                "Art. 5º O órgão municipal de licenciamento tem 30 dias para "
                "estabelecer o modelo e padrão da placa informativa."
            ),
        )
        unrelated.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [unrelated]

        rows = retrieve_archive_evidence(
            "Qual era o prazo do art. 5º da Lei nº 9.001/2020 antes da alteração "
            "promovida pela Lei nº 9.002/2021 e quando ela passou a produzir efeitos?",
            limit=8,
        )

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_multiple_explicit_laws_retrieve_only_the_requested_article(self, filter_documents):
        original = _archive_document(
            number="9001", year=2020,
            legal_text=(
                "Art. 5º O prazo original para interposição de recurso administrativo "
                "será de dez dias úteis, contados da ciência oficial da decisão."
            ),
        )
        amending = _archive_document(
            number="9002", year=2021,
            legal_text=(
                "Art. 5º O prazo previsto na Lei nº 9.001/2020 passa a ser de quinze "
                "dias úteis, contados da ciência oficial da decisão administrativa."
            ),
        )
        original.public_id = "00000000-0000-0000-0000-000000000011"
        amending.public_id = "00000000-0000-0000-0000-000000000012"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [
            original, amending,
        ]

        rows = retrieve_archive_evidence(
            "Qual era o prazo do art. 5º da Lei nº 9.001/2020 antes da alteração "
            "promovida pela Lei nº 9.002/2021?",
            limit=8,
        )

        self.assertEqual({row["norma_ref"] for row in rows}, {
            "Lei Ordinária nº 9001/2020", "Lei Ordinária nº 9002/2021",
        })
        self.assertEqual({row["dispositivo_ref"] for row in rows}, {"Art. 5º"})

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_article_topic_question_rejects_an_exact_article_with_unrelated_text(
        self, filter_documents
    ):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "Art. 17. As atribuições gerais dos cargos definidos nesta Lei estão "
                "estabelecidas no Anexo III.\n"
                "Art. 18. O vencimento básico percebido pelo servidor não poderá ser "
                "inferior ao salário mínimo nacional vigente."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        irrelevant = retrieve_archive_evidence(
            "O que dispõe o art. 17º da Lei Complementar nº 120/2010 sobre gratificações?",
            limit=8,
        )
        relevant = retrieve_archive_evidence(
            "O que dispõe o art. 18º da Lei Complementar nº 120/2010 sobre vencimento básico?",
            limit=8,
        )

        self.assertEqual(irrelevant, [])
        self.assertEqual([row["dispositivo_ref"] for row in relevant], ["Art. 18"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_salary_floor_query_prefers_explicit_minimum_rule(self, filter_documents):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "Art. 18. O Vencimento Básico percebido pelo servidor não poderá ser "
                "inferior ao Salário Mínimo Nacional vigente.\n"
                "Art. 27. Os valores atualmente percebidos pelos servidores da área "
                "da saúde correspondem a gratificações específicas extintas por esta Lei.\n"
                "Art. 32. A implantação da tabela remuneratória prevista no Anexo I "
                "será feita de forma gradativa em três etapas após a publicação desta Lei."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        for question in (
            "O que prevê a Lei Complementar nº 120/2010 sobre o piso do vencimento básico?",
            "Explique o piso do vencimento básico na Lei Complementar nº 120/2010.",
        ):
            with self.subTest(question=question):
                rows = retrieve_archive_evidence(question, limit=8)
                self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 18"])
                self.assertIn("Salário Mínimo Nacional", rows[0]["full_text"])
                self.assertNotIn("corpus", rows[0]["coverage"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_article_evidence_includes_its_incisos_without_the_next_article(self, filter_documents):
        document = _archive_document(
            number="198",
            year=2021,
            legal_text=(
                "Art. 2º Dispositivo anterior.\n"
                "Art. 3º O PCCV-SAÚDE tem como princípios:\n"
                "I - valorização profissional do servidor público municipal da área de saúde;\n"
                "II - aperfeiçoamento da qualidade da atividade pública desenvolvida pelo Município; e\n"
                "III - racionalização da estrutura administrativa.\n"
                "Art. 4º Regra seguinte, que não pertence ao Art. 3º."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Quais são os princípios do Art. 3º da Lei Complementar nº 198/2021?",
            limit=8,
        )

        self.assertEqual(len(rows), 1)
        evidence = rows[0]["full_text"]
        self.assertIn("valorização profissional", evidence)
        self.assertIn("aperfeiçoamento da qualidade", evidence)
        self.assertIn("racionalização da estrutura administrativa", evidence)
        self.assertEqual(evidence.count("valorização profissional"), 1)
        self.assertEqual(evidence.count("aperfeiçoamento da qualidade"), 1)
        self.assertEqual(evidence.count("racionalização da estrutura administrativa"), 1)
        self.assertNotIn("Regra seguinte", evidence)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_article_paragraphs_are_not_duplicated_in_archive_answer(self, filter_documents):
        paragraph_texts = (
            "O tomador de serviço, quando se tratar de pessoa física, não deverá ser identificado.",
            "Considera-se administradora a pessoa jurídica responsável pela rede.",
            "Caberá ao regulamento disciplinar os prazos da obrigação.",
        )
        document = _archive_document(
            number="6021",
            year=2009,
            legal_text=(
                "Art. 1º Regra anterior.\n"
                "Art. 2º As administradoras prestarão informações sobre as operações.\n"
                f"§ 1º - {paragraph_texts[0]}\n"
                f"§ 2º - {paragraph_texts[1]}\n"
                f"§ 3º - {paragraph_texts[2]}\n"
                "Art. 3º Regra seguinte."
            ),
        )
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que prevê o Art. 2º da Lei nº 6021/2009?",
            limit=8,
        )

        self.assertEqual(len(rows), 1)
        evidence = rows[0]["full_text"]
        for paragraph in paragraph_texts:
            self.assertEqual(evidence.count(paragraph), 1)
        self.assertNotIn("Regra seguinte", evidence)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_article_evidence_stops_before_next_chapter_and_section(self, filter_documents):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "Art. 17. As atribuições gerais dos cargos definidos nesta Lei estão estabelecidas no Anexo III.\n"
                "CAPÍTULO V\n"
                "DA REMUNERAÇÃO E DA JORNADA\n"
                "Seção I\n"
                "Da Remuneração\n"
                "Art. 18. A remuneração dos servidores observará a tabela do Anexo III."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que estabelece o Art. 17 da Lei Complementar nº 120/2010?",
            limit=8,
        )

        self.assertEqual(len(rows), 1)
        evidence = rows[0]["full_text"]
        self.assertIn("Anexo III", evidence)
        self.assertNotIn("CAPÍTULO V", evidence)
        self.assertNotIn("DA REMUNERAÇÃO", evidence)
        self.assertNotIn("Seção I", evidence)
        self.assertNotIn("Art. 18", evidence)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_plural_article_question_retrieves_only_the_named_articles(self, filter_documents):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text="\n".join(
                [
                    "Art. 16. Regra anterior sem relação com a pergunta.",
                    "Art. 17. As atribuições gerais dos cargos estão estabelecidas no Anexo III.",
                    "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                    "Art. 19. Regra posterior sem relação com a pergunta.",
                ]
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Explique em linguagem simples a diferença entre as regras dos arts. 17 e 18 "
            "da Lei Complementar nº 120/2010, sem acrescentar fatos.",
            limit=8,
        )

        self.assertEqual({row["dispositivo_ref"] for row in rows}, {"Art. 17", "Art. 18"})
        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 17", "Art. 18"])
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))
        self.assertTrue(all(row["coverage"]["missing_articles"] == [] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_contextual_multi_article_topic_followup_selects_matching_prior_device(
        self, filter_documents
    ):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text="\n".join(
                [
                    "Art. 17. As atribuições gerais dos cargos estão estabelecidas no Anexo III.",
                    "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                    "Art. 33. A revisão anual poderá conceder abono se o nível ficar abaixo do salário mínimo.",
                ]
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Qual dos dois dispositivos trata do salário mínimo? "
            "(contexto normativo: Lei Complementar nº 120/2010; "
            "dispositivos de referência: Arts. 17 e 18)",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 18"])
        self.assertIn("salário mínimo nacional vigente", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_named_law_topic_query_excludes_unrelated_final_articles(self, filter_documents):
        document = _archive_document(legal_text=(
            "Art. 1º As administradoras de cartões são obrigadas a remeter declaração à Secretaria Municipal.\n"
            "Art. 2º As administradoras prestarão informações sobre operações com cartões no Município.\n"
            "Art. 3º Acrescenta os incisos XI e XII ao artigo 86 da Lei 3.882.\n"
            "Art. 4º Esta lei entrará em vigor na data de sua publicação."
        ))
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Qual é a obrigação dos administradores de cartões prevista na Lei nº 6021/2009?",
            limit=8,
        )

        self.assertEqual({row["dispositivo_ref"] for row in rows}, {"Art. 1º", "Art. 2º"})

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_contextual_topic_query_prefers_exact_legal_phrase_matches(self, filter_documents):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "Art. 18. O vencimento básico percebido pelo servidor não poderá ser inferior "
                "ao salário mínimo nacional vigente.\n"
                "Art. 21. A carga horária semanal será remunerada pelos padrões de vencimento "
                "estabelecidos nesta Lei.\n"
                "Art. 32. A implantação da tabela remuneratória preservará o vencimento básico "
                "do servidor durante as etapas de implantação."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "E qual artigo trata do vencimento básico? "
            "(contexto normativo: Lei Complementar nº 120/2010)",
            limit=8,
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 18", "Art. 32"},
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unanchored_query_does_not_match_only_generic_municipal_wording(self, filter_documents):
        document = _archive_document(legal_text=(
            "Art. 1º O programa será executado no âmbito municipal, conforme regulamento.\n"
            "Art. 2º Esta Lei entra em vigor na data de sua publicação."
        ))
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Qual será o orçamento municipal de Natal em 2030?", limit=8
        )

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unanchored_query_keeps_a_specific_topic_match(self, filter_documents):
        document = _archive_document(legal_text=(
            "Art. 1º A dotação para o orçamento anual do programa será definida em lei própria.\n"
            "Art. 2º Esta Lei entra em vigor na data de sua publicação."
        ))
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence("orçamento", limit=8)

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 1º"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unanchored_future_year_query_excludes_older_budget_laws(self, filter_documents):
        document = _archive_document(number="5741", year=2006, legal_text=(
            "Art. 1º Fica aberto crédito suplementar para reforço de dotações do orçamento municipal.\n"
            "Art. 2º Esta Lei entra em vigor na data de sua publicação."
        ))
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        future_rows = retrieve_archive_evidence(
            "Qual será o orçamento municipal de Natal em 2030?", limit=8
        )
        historical_rows = retrieve_archive_evidence(
            "Qual é o orçamento municipal em 2006?", limit=8
        )

        self.assertEqual(future_rows, [])
        self.assertEqual([row["dispositivo_ref"] for row in historical_rows], ["Art. 1º"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_named_ordinary_law_without_topic_returns_whole_norm_coverage(self, filter_documents):
        document = _archive_document()
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que estabelece a Lei Ordinária nº 6021/2009?", limit=8
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["evidence_scope"] == "isolated_qa_archive" for row in rows))
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

        self.assertTrue(all(row["coverage"]["selected_articles"] == 3 for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_natural_whole_norm_overview_uses_partial_overview_fallback(
        self, retrieve, validate, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 3,
            "total_articles": 3,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:decree-overview-{article}",
                "norma_ref": "Decreto nº 7795/2005",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article, text in (
                (1, "Art. 1º Fica aberto crédito suplementar para a Secretaria Municipal."),
                (2, "Art. 2º Constitui fonte de recursos a anulação de dotação orçamentária."),
                (3, "Art. 3º Este Decreto entra em vigor na data de sua publicação."),
            )
        ]
        validate.return_value = {"grounded": False, "failed_claims": ["unsupported"]}
        generate.return_value = _completed_generation_stream({
            "answer": "O decreto estabelece um programa municipal abrangente. [[1]]",
            "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "Em linhas gerais, quais são os principais pontos do Decreto nº 7.795/2005?",
            k=5,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertTrue(generate.call_args.kwargs["retry_after_partial_rejection"])
        self.assertTrue(generate.call_args.kwargs["revision_instruction"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertNotIn("Anexos normativos também foram detectados", final["answer"])
        self.assertIn("anexos normativos detectados ficaram fora", final["answer"])
        self.assertNotIn("Art. 3º", final["answer"])
        self.assertIn("Art. 1º", final["answer"])
        self.assertIn("Art. 2º", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_formatted_decree_number_is_not_mistaken_for_a_topic(self, filter_documents):
        document = _archive_document(number="7795", year=2005, legal_text=(
            "Art. 1º Fica aberto à Secretaria Municipal de Meio Ambiente e Urbanismo "
            "o crédito suplementar de R$ 12.000,00 para reforço de dotação orçamentária.\n"
            "Art. 2º Constitui fonte de recursos para o crédito a anulação em igual valor "
            "de dotação orçamentária consignada no orçamento vigente.\n"
            "Art. 3º Este Decreto entra em vigor na data de sua publicação."
        ))
        document.metadata_json["identity_candidate"]["type"] = "decreto"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que estabelece o Decreto nº 7.795/2005?", limit=1
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_natural_language_overview_request_uses_whole_norm_coverage(self, filter_documents):
        document = _archive_document()
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Faça uma síntese da Lei Complementar nº 6021/2009, indicando os temas centrais "
            "e quais artigos sustentam cada ponto.",
            limit=5,
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

        imperative_rows = retrieve_archive_evidence(
            "Faça uma síntese dos temas centrais da Lei Complementar nº 6021/2009 "
            "e indique quais artigos sustentam cada ponto.",
            limit=5,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in imperative_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in imperative_rows))

        coverage_request_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral dos temas "
            "identificáveis e informe claramente o que ficou fora da amostra.",
            limit=5,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in coverage_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in coverage_request_rows))

        natural_coverage_request_rows = retrieve_archive_evidence(
            "Quais são os principais temas tratados na Lei Complementar nº 6021/2009? "
            "Faça uma síntese com base no PDF e indique se a cobertura é parcial.",
            limit=5,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in natural_coverage_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in natural_coverage_request_rows))

        explicit_sample_boundary_rows = retrieve_archive_evidence(
            "O que estabelece a Lei Complementar Municipal nº 6021/2009? Faça uma síntese "
            "dos principais temas e dispositivos, indicando claramente o que foi efetivamente "
            "coberto e o que não pode ser confirmado pelo PDF.",
            limit=5,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in explicit_sample_boundary_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in explicit_sample_boundary_rows)
        )

        plain_language_overview_rows = retrieve_archive_evidence(
            "O que prevê, em linhas gerais, a Lei Complementar nº 6021/2009?",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in plain_language_overview_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in plain_language_overview_rows)
        )

        explicit_sample_limit_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral dos principais temas "
            "e indique os limites da amostra.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in explicit_sample_limit_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in explicit_sample_limit_rows))

        imperative_coverage_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral breve dos "
            "principais temas e delimite a cobertura.",
            limit=5,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in imperative_coverage_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in imperative_coverage_rows))

        pdf_completeness_request_rows = retrieve_archive_evidence(
            "Resuma o que estabelecem os artigos da Lei Complementar nº 6.021/2009 e indique "
            "se o PDF permite identificar o conteúdo completo da norma.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in pdf_completeness_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in pdf_completeness_request_rows))

        identified_themes_request_rows = retrieve_archive_evidence(
            "Em linhas gerais, o que prevê a Lei Complementar nº 6021/2009? "
            "Explique que temas foram identificados e informe as limitações da amostra.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in identified_themes_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in identified_themes_request_rows)
        )

        identified_themes_overview_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral dos principais "
            "temas identificados e informe claramente as limitações da amostra.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in identified_themes_overview_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in identified_themes_overview_rows)
        )

        objective_no_fabrication_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral objetiva "
            "dos principais temas identificáveis, sem inventar uma análise integral.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in objective_no_fabrication_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in objective_no_fabrication_rows)
        )

        extraction_qualification_rows = retrieve_archive_evidence(
            "Faça um resumo da Lei Complementar nº 6021/2009, cobrindo os principais dispositivos "
            "e deixando claro se a extração do PDF não permitir uma síntese confiável.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in extraction_qualification_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in extraction_qualification_rows)
        )

        identified_topic_rows = retrieve_archive_evidence(
            "Em linhas gerais, explique que temas foram identificados sobre a coordenação "
            "pela Secretaria Municipal de Educação na Lei Complementar nº 6021/2009.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in identified_topic_rows},
            {"Art. 2º"},
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_abbreviated_complementary_law_overview_covers_the_whole_norm(self, filter_documents):
        document = _archive_document(number="120", year=2010)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Quais são os principais eixos da LC nº 120/2010? "
            "Vincule cada afirmação aos artigos correspondentes.",
            limit=1,
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_panorama_with_coverage_and_grounding_instructions_keeps_whole_norm_scope(
        self, filter_documents
    ):
        document = _archive_document(number="120", year=2010)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "Faça um panorama dos principais temas e dispositivos da Lei Complementar nº "
            "120/2010. Informe quantos dispositivos foram identificados e as limitações da "
            "cobertura; só sintetize afirmações apoiadas pelas fontes.",
            limit=1,
        )

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_whole_norm_prompt_delegates_coverage_metadata_to_backend(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 3,
            "total_articles": 39,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:overview-meta-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Conteúdo normativo verificável do dispositivo {article}.",
                "texto": f"Texto {article}",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (1, 2, 3)
        ]
        generate.return_value = _completed_generation_stream({
            "answer": "",
            "grounding": {"grounded": False, "failed_claims": ["unverified"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 5}],
        })
        question = (
            "Faça um panorama dos principais temas e dispositivos da Lei Complementar nº "
            "120/2010. Informe quantos dispositivos foram identificados e as limitações da "
            "cobertura; só sintetize afirmações apoiadas pelas fontes."
        )

        list(stream_archive_qa_answer(
            question,
            k=1,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        self.assertEqual(classify_normative_query(question).kind, "norma_overview")
        prompt = generate.call_args.args[0]
        self.assertIn("Faça um panorama dos principais temas e dispositivos", prompt)
        self.assertNotIn("quantos dispositivos", prompt.casefold())
        self.assertNotIn("limitações da cobertura", prompt.casefold())
        self.assertNotIn("afirmações apoiadas pelas fontes", prompt.casefold())
        self.assertIn("A cobertura e os anexos serão explicados pelo sistema", prompt)
        self.assertIn("não reescreva a mesma instituição em outra frase", prompt)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_topical_query_is_not_shaped_as_a_whole_norm_overview(
        self, retrieve, generate
    ):
        question = (
            "Em linhas gerais, explique que temas foram identificados sobre a coordenação "
            "pela Secretaria Municipal de Educação na Lei Complementar nº 6021/2009."
        )
        retrieve.return_value = [{
            "citation_id": "qa:topic-coordinate",
            "norma_ref": "Lei Complementar nº 6021/2009",
            "dispositivo_ref": "Art. 2º",
            "full_text": "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.",
            "texto": "Texto do Art. 2º",
            "similarity_score": 0.8,
            "coverage": {
                "complete": False,
                "selected_articles": 1,
                "total_articles": 3,
                "annexes_present": True,
            },
        }]
        generate.return_value = _completed_generation_stream({
            "answer": "",
            "grounding": {"grounded": False, "failed_claims": ["unverified"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 5}],
        })

        list(stream_archive_qa_answer(
            question,
            k=1,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        plan = classify_normative_query(question)
        self.assertEqual(plan.kind, "norma_overview")
        self.assertFalse(_is_whole_norm_request(question, plan))
        prompt = generate.call_args.args[0]
        self.assertNotIn("INSTRUÇÃO ESPECÍFICA — VISÃO GERAL DA NORMA", prompt)
        self.assertIn("sobre a coordenação", prompt)

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED=True,
        SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api",
    )
    @patch("src.processing.qa_archive_rag.Norma.objects.filter")
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_exact_local_identity_can_link_to_existing_sapl_record(self, filter_documents, filter_normas):
        document = _archive_document(number="118", year=2010)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL|lei_complementar|municipal_lc|118|2010"
        matched = SimpleNamespace(
            identity_key=document.metadata_json["identity_key"],
            sapl_id=9076,
            sapl_url="https://sapl.natal.rn.leg.br/norma/9076",
            pdf_url="https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2010/9076/lc_118_10.pdf",
        )
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]
        filter_normas.return_value.only.return_value = [matched]

        rows = retrieve_archive_evidence(
            "O que estabelece a Lei Complementar nº 118/2010?", limit=8
        )

        self.assertEqual(rows[0]["sapl_url"], "https://sapl.natal.rn.leg.br/norma/9076")
        self.assertEqual(rows[0]["pdf_url"], matched.pdf_url)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_large_whole_norm_uses_distributed_sample_and_reports_partial_coverage(self, filter_documents):
        long_provision = (
            " Este dispositivo define regras administrativas detalhadas para o programa municipal."
            * 12
        )
        legal_text = "\n".join(
            f"Art. {number}º{long_provision}"
            for number in range(1, 31)
        )
        document = _archive_document(legal_text=legal_text)
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence(
            "O que prevê a Lei Ordinária nº 6021/2009?", limit=5
        )

        assert 5 < len(rows) < 30
        assert rows[0]["dispositivo_ref"] == "Art. 1º"
        assert rows[-1]["dispositivo_ref"] == "Art. 30º"
        assert all(row["coverage"]["complete"] is False for row in rows)
        assert all(row["coverage"]["selected_articles"] == len(rows) for row in rows)
        assert all(row["coverage"]["total_articles"] == 30 for row in rows)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_whole_norm_evidence_excludes_mayoral_signature_from_final_article(self, filter_documents):
        document = _archive_document(legal_text=(
            "Art. 1º Objeto da Lei.\n"
            "Art. 4º. Esta lei entrará em vigor na data de sua publicação, revogando todas as disposições em contrário.\n"
            "Palácio Felipe Camarão, em Natal, 28 de dezembro de 2009.\n"
            "Micarla de Sousa\nPrefeita"
        ))
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence("O que estabelece a Lei nº 6021/2009?", limit=8)

        final_article = next(row for row in rows if row["dispositivo_ref"] == "Art. 4º")
        assert "entra" in final_article["full_text"] or "entrará" in final_article["full_text"]
        assert "Palácio Felipe Camarão" not in final_article["full_text"]
        assert "Micarla de Sousa" not in final_article["full_text"]
        assert "Prefeita" not in final_article["full_text"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_final_article_stops_before_normative_annex_after_colophon(self, filter_documents):
        document = _archive_document(legal_text=(
            "Art. 1º Objeto da Lei.\n"
            "Art. 39 Esta Lei Complementar entra em vigor na data de sua publicação, "
            "revogando todas as disposições em contrário.\n"
            "Sala das Sessões, em Natal, 20 de agosto de 2010.\n"
            "Eriko Jácome — Presidente\n"
            "Publicada no Diário Oficial do Município em: 21/09/2010\n"
            "Autoria: Hermes Câmara.\n"
            "ESTADO DO RIO GRANDE DO NORTE\n"
            "ANEXO – I\n"
            "TABELAS REMUNERATÓRIAS POR NÍVEIS E CLASSES\n"
            "CARGO: AUXILIAR EM SAÚDE\n"
            "Art. 1º Vencimento-base: R$ 525,00."
        ))
        document.metadata_json["identity_candidate"].update({
            "type": "lei_complementar", "number": "120", "year": 2010,
        })
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]

        rows = retrieve_archive_evidence("O que estabelece a Lei Complementar nº 120/2010?", limit=8)

        final_article = next(row for row in rows if row["dispositivo_ref"].startswith("Art. 39"))
        assert "entra em vigor na data de sua publicação" in final_article["full_text"]
        assert "TABELAS REMUNERATÓRIAS" not in final_article["full_text"]
        assert "Vencimento-base" not in final_article["full_text"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=False)
    def test_archive_is_not_retrievable_when_qa_flag_is_off(self):
        with patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter") as query:
            self.assertEqual(retrieve_archive_evidence("hortas comunitárias"), [])
        query.assert_not_called()

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_archive_temporal_scope_abstains_without_using_current_pdf(self, retrieve, validate, generate):
        events = list(stream_archive_qa_answer(
            "O que previa o art. 5º da Lei Complementar nº 120/2010?",
            k=8,
            model="llama3",
            temperature=0.2,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
            temporal_scope_requested=True,
        ))

        retrieve.assert_not_called()
        validate.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(events[-1]["reason_code"], "historical_evidence_unavailable")
        self.assertFalse(events[-1]["grounded"])
        self.assertEqual(events[-1]["sources"], [])
        self.assertIn("redação atual", events[-1]["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_requested_intersticio_duration_abstains_with_scoped_citation(
        self, retrieve, generate
    ):
        source = {
            "citation_id": "qa:lc120-art4",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 4º",
            "full_text": "Art. 4º A progressão funcional será respeitado o interstício mínimo.",
            "similarity_score": 0.91,
        }
        retrieve.return_value = [source]

        events = list(stream_archive_qa_answer(
            "Qual interstício mínimo a Lei Complementar nº 120/2010 exige para progressão funcional?",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_requested_detail_not_in_retrieved_evidence")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["sources"], [source])
        self.assertIn("não informa sua duração", final["answer"])
        self.assertIn("não permite concluir se outro dispositivo define o prazo", final["answer"])
        self.assertEqual(re.findall(r"\[\[(\d+)\]\]", final["answer"]), ["1"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    def test_intersticio_duration_gap_does_not_trigger_when_excerpt_has_a_period(self):
        source = {
            "citation_id": "qa:lc120-art9",
            "full_text": "A progressão respeitará o interstício mínimo de 24 (vinte e quatro) meses.",
        }

        self.assertIsNone(_intersticio_duration_not_recovered(
            "Qual interstício mínimo a lei exige?",
            [source],
        ))
        self.assertIsNone(_intersticio_duration_not_recovered(
            "Quais são as regras de progressão funcional?",
            [source],
        ))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_stream_emits_sources_before_final_answer(self, retrieve, validate, generate):
        retrieve.return_value = [{
            "norma_ref": "Lei nº 6021/2009",
            "dispositivo_ref": "Art. 2º",
            "full_text": "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.",
            "texto": "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.",
            "similarity_score": 1.0,
            "source_type": "Acervo histórico local — extração pendente de revisão",
        }]
        validate.return_value = {}
        generate.return_value = _completed_generation_stream({
            "answer": "A coordenação cabe à Secretaria Municipal de Educação. [[1]]",
            "grounding": {"grounded": True, "claims": [], "failed_claims": []},
            "source_only": True,
            "generation_attempts": [{"duration_ms": 4}],
        })

        events = list(stream_archive_qa_answer(
            "Quem coordena o programa?", k=5, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))
        types = [event.get("event") for event in events]

        self.assertLess(types.index("sources"), types.index("chunk"))
        self.assertLess(types.index("chunk"), types.index("done"))
        self.assertEqual(
            "".join(event["chunk"] for event in events if event.get("event") == "chunk"),
            events[-1]["answer"],
        )
        self.assertTrue(events[-1]["grounded"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_cross_reference_scan_lists_only_articles_with_literal_reference(
        self, retrieve, generate
    ):
        sources = [
            {
                "citation_id": f"qa:lc198-{article}",
                "norma_ref": "Lei Complementar nº 198/2021",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.8,
            }
            for article, text in (
                (1, "Art. 1º As obras devem expor placa conforme o artigo 21 da Lei Complementar nº 055/2004."),
                (2, "Art. 2º A placa seguirá o artigo 44 da Lei Complementar nº 055/2004."),
                (4, "Art. 4º O descumprimento configura infração, conforme o artigo 88 da Lei Complementar nº 055/2004."),
                (6, "Art. 6º Aplicam-se subsidiariamente a Lei Complementar nº 055/2004 e a Lei Complementar nº 082/2007."),
            )
        ]
        sources.append({
            "citation_id": "qa:lc55-88",
            "norma_ref": "Lei Complementar nº 55/2004",
            "dispositivo_ref": "Art. 88",
            "full_text": "Art. 88 As infrações serão apuradas pela autoridade competente.",
            "texto": "Art. 88 As infrações serão apuradas pela autoridade competente.",
            "similarity_score": 0.7,
        })
        retrieve.return_value = sources

        events = list(stream_archive_qa_answer(
            "Quais artigos da Lei Complementar nº 198/2021 mencionam dispositivos "
            "da Lei Complementar nº 55/2004?",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_cross_reference_scan")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["sources"], sources[:4])
        self.assertEqual(
            [source["dispositivo_ref"] for source in final["sources"]],
            ["Art. 1º", "Art. 2º", "Art. 4º", "Art. 6º"],
        )
        self.assertEqual(
            re.findall(r"\[\[(\d+)\]\]", final["answer"]),
            ["1", "2", "3", "4"],
        )
        self.assertNotIn("Art. 3º", final["answer"])
        self.assertIn("não confirma que os demais dispositivos", final["answer"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_relation_query_does_not_present_original_article_as_proof_of_current_status(
        self, retrieve, generate
    ):
        retrieve.return_value = [{
            "citation_id": "qa:lc120-art18",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 18º",
            "full_text": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
            "texto": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
            "similarity_score": 1.0,
        }]

        events = list(stream_archive_qa_answer(
            "O corpus permite confirmar se o Art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado por atos posteriores?",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_unavailable")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertIn("não permite confirmar se o dispositivo foi alterado ou revogado", final["answer"])
        self.assertIn("nem concluir que continua vigente", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_cross_reference_scan_does_not_turn_missing_match_into_whole_norm_claim(
        self, retrieve, generate
    ):
        retrieve.return_value = [{
            "citation_id": "qa:lc198-2",
            "norma_ref": "Lei Complementar nº 198/2021",
            "dispositivo_ref": "Art. 2º",
            "full_text": "Art. 2º A unidade terá organização própria e funcionamento regular.",
            "texto": "Art. 2º A unidade terá organização própria e funcionamento regular.",
            "similarity_score": 0.8,
        }]

        events = list(stream_archive_qa_answer(
            "Quais artigos da Lei Complementar nº 198/2021 mencionam dispositivos "
            "da Lei Complementar nº 55/2004?",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertFalse(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_cross_reference_not_found")
        self.assertEqual(final["sources"], [])
        self.assertIn("Não identifiquei referência literal", final["answer"])
        self.assertIn("não permite concluir", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_exact_article_question_quotes_pdf_without_llm(self, retrieve, generate):
        retrieve.return_value = [{
            "citation_id": "qa:article-1",
            "norma_ref": "Lei Ordinária nº 6021/2009",
            "dispositivo_ref": "Art. 1º",
            "full_text": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
            "texto": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
            "similarity_score": 1.0,
            "source_type": "Acervo histórico local — extração pendente de revisão",
        }]

        events = list(stream_archive_qa_answer(
            "O que prevê o Art. 1º da Lei nº 6.021/2009?", k=5, model="llama3",
            temperature=0.1, text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        generate.assert_not_called()
        self.assertLess(
            [event["event"] for event in events].index("sources"),
            [event["event"] for event in events].index("chunk"),
        )
        self.assertTrue(events[-1]["grounded"])
        self.assertIn("Programa Municipal de Hortas Comunitárias", events[-1]["answer"])
        self.assertIn("No PDF arquivado", events[-1]["answer"])
        self.assertIn("**Art. 1º** da **Lei Ordinária nº 6021/2009** estabelece", events[-1]["answer"])
        self.assertNotIn("O trecho extraído como", events[-1]["answer"])
        self.assertIn("[[1]]", events[-1]["answer"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_exact_article_quote_does_not_repeat_norm_in_citation(self, retrieve, generate):
        retrieve.return_value = [{
            "citation_id": "qa:decree-article-2",
            "norma_ref": "Decreto nº 7.795/2005",
            "dispositivo_ref": "Art. 2º",
            "full_text": "Art. 2º Constitui fonte de recursos para o crédito.",
            "texto": "Art. 2º Constitui fonte de recursos para o crédito.",
            "similarity_score": 1.0,
            "source_type": "Acervo histórico local — extração pendente de revisão",
        }]

        events = list(stream_archive_qa_answer(
            "O que estabelece o Art. 2º do Decreto nº 7.795/2005?", k=5,
            model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        answer = events[-1]["answer"]
        generate.assert_not_called()
        self.assertIn("**Art. 2º** do **Decreto nº 7.795/2005** estabelece", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("metadados e segmentação ainda estão sob revisão", answer)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_stream_refuses_an_article_excerpt_that_does_not_support_requested_topic(
        self, retrieve, generate
    ):
        retrieve.return_value = [{
            "citation_id": "qa:lc120-art17",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 17º",
            "full_text": "As atribuições gerais dos cargos definidos nesta Lei estão estabelecidas no Anexo III.",
            "texto": "As atribuições gerais dos cargos definidos nesta Lei estão estabelecidas no Anexo III.",
            "similarity_score": 1.0,
        }]

        events = list(stream_archive_qa_answer(
            "O que dispõe o art. 17º da Lei Complementar nº 120/2010 sobre gratificações?",
            k=8, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        generate.assert_not_called()
        sources_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(sources_event["sources"], [])
        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [])
        self.assertIn("Não encontrei um trecho legível correspondente", final["answer"])
        self.assertNotIn("atribuições gerais", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_contextual_device_followup_quotes_exact_source_without_llm(
        self, retrieve
    ):
        source = {
            "citation_id": "qa:lc120-art19",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 19º",
            "full_text": "Art. 19º A estrutura de cargos está baseada em classes e níveis, descritos no Anexo I.",
            "texto": "Art. 19º A estrutura de cargos está baseada em classes e níveis, descritos no Anexo I.",
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]
        events = list(stream_archive_qa_answer(
            "Com base no trecho citado, explique isso "
            "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 19º)",
            k=8, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        self.assertEqual(events[-1]["reason_code"], "qa_archive_contextual_device_verbatim")
        self.assertIn(source["full_text"], events[-1]["answer"])
        self.assertIn("No PDF arquivado", events[-1]["answer"])
        self.assertIn("**Art. 19º** da **Lei Complementar nº 120/2010** estabelece", events[-1]["answer"])
        self.assertNotIn("O trecho extraído como", events[-1]["answer"])
        self.assertNotIn("O trecho, por si só", events[-1]["answer"])
        self.assertIn("[[1]]", events[-1]["answer"])
        self.assertEqual(events[-1]["grounding"]["claims"][0]["text"], source["full_text"])
        self.assertEqual(events[-1]["sources"], [source])
        self.assertTrue(events[-1]["grounded"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_art_18_followup_never_substitutes_another_hardcoded_device_summary(
        self, retrieve
    ):
        source = {
            "citation_id": "qa:lc120-art18",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 18º",
            "full_text": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]
        events = list(stream_archive_qa_answer(
            "E qual é o valor mínimo mencionado? "
            "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 18º)",
            k=8, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        self.assertIn(source["full_text"], events[-1]["answer"])
        self.assertNotIn("classes e níveis", events[-1]["answer"])
        self.assertEqual(events[-1]["sources"], [source])
        self.assertTrue(events[-1]["grounded"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_exact_phrase_article_lookup_returns_only_literal_matches_without_llm(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "O vencimento básico percebido pelo servidor não poderá ser inferior ao salário mínimo.",
                "similarity_score": 1.0,
            },
            {
                "citation_id": "qa:article-32",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 32",
                "full_text": "A implantação da tabela preservará o vencimento básico do servidor.",
                "similarity_score": 0.9,
            },
        ]

        events = list(stream_archive_qa_answer(
            "E qual artigo trata do vencimento básico? "
            "(contexto normativo: Lei Complementar nº 120/2010)",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_exact_phrase_lookup")
        self.assertIn("A expressão consultada **“vencimento básico”**", final["answer"])
        self.assertIn("- [[1]]", final["answer"])
        self.assertIn("- [[2]]", final["answer"])
        self.assertIn("extração ainda está sob revisão", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(len(final["grounding"]["claims"]), 2)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_multi_article_transcription_quotes_only_requested_sources_without_llm(
        self, retrieve, generate
    ):
        coverage = {
            "requested_articles": ["17", "18"],
            "missing_articles": [],
            "complete": True,
        }
        retrieve.return_value = [
            {
                "citation_id": "qa:article-17",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17",
                "full_text": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "texto": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "coverage": coverage,
            },
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "texto": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "coverage": coverage,
            },
        ]

        events = list(stream_archive_qa_answer(
            "Transcreva os arts. 17 e 18 da Lei Complementar nº 120/2010.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_explicit_article_transcription")
        self.assertIn("atribuições gerais dos cargos", final["answer"])
        self.assertIn("vencimento básico", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("pendentes de revisão", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_multi_article_comparison_uses_grounded_generation(
        self, retrieve, generate
    ):
        coverage = {"requested_articles": ["18", "19"], "missing_articles": [], "complete": True}
        retrieve.return_value = [
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "texto": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
            {
                "citation_id": "qa:article-19",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 19",
                "full_text": "Art. 19. A estrutura de cargos efetivos está baseada em classes e níveis, descritos no Anexo I.",
                "texto": "Art. 19. A estrutura de cargos efetivos está baseada em classes e níveis, descritos no Anexo I.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
        ]
        generated_answer = (
            "O Art. 18 fixa um piso para o vencimento básico, enquanto o Art. 19 organiza "
            "os cargos efetivos em classes e níveis descritos no Anexo I. São assuntos "
            "diferentes nos trechos recuperados. [[1]] [[2]]"
        )
        generate.return_value = _completed_generation_stream({
            "answer": generated_answer,
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": [
                    {"text": "O Art. 18 fixa um piso.", "citation_ids": ["qa:article-18"]},
                    {"text": "O Art. 19 organiza cargos.", "citation_ids": ["qa:article-19"]},
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 25}],
        })

        events = list(stream_archive_qa_answer(
            "Compare em linguagem simples o conteúdo dos arts. 18 e 19 da "
            "Lei Complementar nº 120/2010.",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_called_once()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertIsNone(final["reason_code"])
        self.assertEqual(final["answer"], generated_answer)
        self.assertIn("fixa um piso", final["answer"])
        self.assertIn("organiza", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_grounded_but_incomplete_multi_article_answer_is_replaced_by_cited_evidence_map(
        self, retrieve, generate
    ):
        coverage = {"requested_articles": ["17", "18"], "missing_articles": [], "complete": True}
        retrieve.return_value = [
            {
                "citation_id": "qa:article-17",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17",
                "full_text": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
        ]
        incomplete_answer = (
            "O Art. 17 estabelece que as atribuições gerais dos cargos estão no Anexo III. [[1]]"
        )
        generate.return_value = _completed_generation_stream({
            "answer": incomplete_answer,
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": [{"text": "O Art. 17 trata das atribuições.", "citation_ids": ["qa:article-17"]}],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 25}],
        })

        events = list(stream_archive_qa_answer(
            "Na Lei Complementar nº 120/2010, explique separadamente o conteúdo dos Arts. 17 e 18 "
            "e compare o tema de cada um. Use somente os trechos recuperados do PDF, cite cada "
            "afirmação pelo artigo correspondente e diga se a extração não permitir uma conclusão.",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_comparison_evidence_fallback")
        self.assertIn("**Art. 17**", final["answer"])
        self.assertIn("**Art. 18**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertNotEqual(final["answer"], incomplete_answer)
        self.assertFalse(any(
            event.get("event") == "chunk" and event.get("chunk") == incomplete_answer
            for event in events
        ))
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_followup_selects_the_matching_article_from_prior_same_norm_device_set(
        self, retrieve, generate
    ):
        retrieve.return_value = [{
            "citation_id": "qa:article-18",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 18",
            "full_text": "O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
            "similarity_score": 1.0,
            "coverage": {"requested_articles": ["17", "18"], "complete": True},
        }]

        events = list(stream_archive_qa_answer(
            "Qual dos dois dispositivos trata do salário mínimo? "
            "(contexto normativo: Lei Complementar nº 120/2010; "
            "dispositivos de referência: Arts. 17 e 18)",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        generate.assert_not_called()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_exact_phrase_lookup")
        self.assertIn("A expressão consultada **“salário mínimo”**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(final["sources"][0]["dispositivo_ref"], "Art. 18")

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_rejected_article_comparison_falls_back_to_cited_excerpts(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": {"complete": True, "requested_articles": ["18", "19"]},
            },
            {
                "citation_id": "qa:article-19",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 19",
                "full_text": "Art. 19. A estrutura de cargos efetivos está baseada em classes e níveis, descritos no Anexo I.",
                "similarity_score": 1.0,
                "coverage": {"complete": True, "requested_articles": ["18", "19"]},
            },
        ]
        generate.return_value = _completed_generation_stream({
            "answer": "Paráfrase rejeitada.",
            "grounding": {"grounded": False, "claims": [], "failed_claims": ["unverified"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 30}],
        })

        events = list(stream_archive_qa_answer(
            "Compare em linguagem simples os arts. 18 e 19 da Lei Complementar nº 120/2010.",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_comparison_evidence_fallback")
        self.assertIn("**Art. 18**", final["answer"])
        self.assertIn("**Art. 19**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("não mostram referência expressa", final["answer"])
        self.assertNotIn("Localizei dispositivos que podem ajudar", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_rejected_partial_overview_uses_concise_guidance_and_preserves_sources(
        self, retrieve, validate, generate
    ):
        source = {
            "citation_id": "qa:article-1",
            "norma_ref": "Lei nº 6021/2009",
            "dispositivo_ref": "Art. 1º",
            "full_text": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
            "texto": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
            "similarity_score": 0.8,
            "source_type": "Acervo histórico local — extração pendente de revisão",
            "coverage": {
                "corpus": "acervo histórico local (lote de 40 documentos)",
                "complete": False,
                "selected_articles": 3,
                "total_articles": 16,
                "annexes_present": True,
            },
        }
        retrieve.return_value = [source]
        validate.return_value = {"grounded": False}
        generate.return_value = _completed_generation_stream({
            "answer": "fallback do validador",
            "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 5}],
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei nº 6021/2009?", k=5, model="llama3",
            temperature=0.1, text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        prompt = generate.call_args.args[0]
        self.assertIn("INSTRUÇÃO ESPECÍFICA — VISÃO GERAL DA NORMA", prompt)
        self.assertIn("escreva exatamente 1", prompt)
        self.assertIn("um artigo e um marcador distinto por frase", prompt)
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertEqual(final["sources"], [source])
        self.assertIn("cobre 3 de 16 artigos", final["answer"])
        self.assertIn("Anexos normativos também foram detectados", final["answer"])
        self.assertIn("Fontes Consultadas", final["answer"])
        self.assertIn("trechos literais e abreviados", final["answer"])
        self.assertIn("O Município institui", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        source_event = next(event for event in events if event["event"] == "sources")
        self.assertEqual(source_event["coverage"]["selected_articles"], 3)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_overview_fallback_skips_generic_vigency_but_keeps_source(
        self, retrieve, validate, generate
    ):
        coverage = {
            "corpus": "acervo histórico local",
            "complete": False,
            "selected_articles": 8,
            "total_articles": 9,
            "annexes_present": False,
        }
        sources = [
            {
                "citation_id": f"qa:overview-{article}",
                "norma_ref": "Lei nº 6021/2009",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": (
                    "Esta Lei entra em vigor na data de sua publicação, "
                    "revogando-se todas as disposições em contrário."
                    if article == 9
                    else f"Art. {article}º O dispositivo estabelece o tema substantivo {article}."
                ),
                "texto": f"Art. {article}º Texto {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (*range(1, 6), 9)
        ]
        retrieve.return_value = sources
        validate.return_value = {"grounded": False}
        generate.return_value = _completed_generation_stream({
            "answer": "A síntese inclui uma afirmação não sustentada.",
            "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 5}],
        })

        events = list(stream_archive_qa_answer(
            "Quais são os principais temas da Lei nº 6021/2009? Informe se a cobertura é parcial.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertEqual(final["sources"], sources)
        self.assertIn("Art. 9º", [source["dispositivo_ref"] for source in final["sources"]])
        self.assertNotIn("entra em vigor", final["answer"].casefold())
        self.assertNotIn("disposições em contrário", final["answer"].casefold())
        self.assertEqual(final["answer"].count("[["), 5)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_grounded_partial_overview_always_discloses_scope_and_annexes(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 19,
            "total_articles": 39,
            "annexes_present": True,
        }
        sources = [
            {
                "citation_id": f"qa:overview-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Tema comprovado {article}.",
                "texto": f"Art. {article}º Tema comprovado {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (1, 10, 19)
        ]
        retrieve.return_value = sources
        candidate = "A norma trata dos temas A, B e C. [[1]] [[2]] [[3]]"
        generate.return_value = _completed_generation_stream({
            "answer": candidate,
            "grounding": {
                "grounded": True,
                "claims": [
                    {"text": f"Tema {article}.", "citation_ids": [f"qa:overview-{article}"]}
                    for article in (1, 10, 19)
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertIsNone(final["reason_code"])
        self.assertTrue(final["answer"].startswith(candidate))
        self.assertIn("A amostra consultada cobre 19 de 39 artigos identificados.", final["answer"])
        self.assertIn("Esta resposta é parcial e não representa uma análise integral da norma.", final["answer"])
        self.assertIn("Anexos normativos também foram detectados", final["answer"])
        self.assertTrue(all(marker in final["answer"] for marker in ("[[1]]", "[[2]]", "[[3]]")))
        self.assertEqual(final["sources"], sources)
        self.assertEqual("".join(event.get("chunk", "") for event in events if event["event"] == "chunk"), final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_overview_with_all_articles_but_omitted_annexes_uses_partial_scope(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 3,
            "total_articles": 3,
            "annexes_present": True,
        }
        sources = [
            {
                "citation_id": f"qa:decree-overview-{article}",
                "norma_ref": "Decreto nº 7795/2005",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Trecho literal do dispositivo {article}.",
                "texto": f"Art. {article}º Trecho literal do dispositivo {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (1, 2, 3)
        ]
        retrieve.return_value = sources
        candidate = "O decreto abre crédito suplementar e define sua fonte. [[1]] [[2]] [[3]]"
        generate.return_value = _completed_generation_stream({
            "answer": candidate,
            "grounding": {
                "grounded": True,
                "claims": [{
                    "text": "O decreto abre crédito suplementar.",
                    "citation_ids": ["qa:decree-overview-1"],
                }],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "O que prevê o Decreto municipal nº 7795/2005? Faça uma visão geral dos artigos.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        self.assertTrue(generate.call_args.kwargs["retry_after_partial_rejection"])
        self.assertIn("VISÃO GERAL PARCIAL", generate.call_args.kwargs["revision_instruction"])
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertTrue(final["answer"].startswith(candidate))
        self.assertIn("Os 3 artigos identificados foram recuperados", final["answer"])
        self.assertIn("a visão geral é parcial", final["answer"])
        self.assertNotIn("Anexos normativos também foram detectados", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_rejected_norm_overview_returns_cited_pdf_excerpts_not_only_article_labels(
        self, retrieve, validate, generate
    ):
        sources = [
            {
                "citation_id": f"qa:decree-{article}",
                "norma_ref": "Decreto nº 7795/2005",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.8,
                "coverage": {"complete": True},
            }
            for article, text in (
                (1, "Fica aberto à Secretaria Municipal de Meio Ambiente o crédito suplementar de R$ 12.000,00."),
                (2, "Constitui fonte de recursos para o crédito a anulação de dotação orçamentária."),
                (3, "Este Decreto entra em vigor na data de sua publicação."),
            )
        ]
        retrieve.return_value = sources
        validate.return_value = {"grounded": False}
        generate.return_value = _completed_generation_stream({
            "answer": "O decreto parece autorizar um crédito especial no orçamento.",
            "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "O que estabelece o Decreto nº 7795/2005?",
            k=5,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_evidence_map_fallback")
        self.assertEqual(final["sources"], sources)
        self.assertEqual(streamed_text, final["answer"])
        self.assertNotIn("crédito especial", final["answer"])
        self.assertTrue(final["answer"].startswith(
            "No PDF do acervo, estes são os trechos relacionados à pergunta"
        ))
        self.assertNotIn("Não consegui validar uma síntese", final["answer"])
        self.assertIn("**Art. 1º**", final["answer"])
        self.assertIn("crédito suplementar de R$ 12.000,00", final["answer"])
        self.assertIn("**Art. 2º**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("extração e segmentação ainda estão sob revisão", final["answer"])
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "verbatim_sampled_excerpts_from_unreviewed_archive_pdf",
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_norm_overview_rejects_narrow_grounded_answer_before_streaming(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 19,
            "total_articles": 39,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:article-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Texto do dispositivo {article}.",
                "texto": f"Art. {article}º Texto do dispositivo {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in range(1, 20)
        ]
        candidate = (
            "A Lei Complementar nº 120/2010 estabelece regras para o PCCV-Saúde. [[18]]"
        )
        generate.return_value = _completed_generation_stream({
            "answer": candidate,
            "grounding": {
                "grounded": True,
                "claims": [{"text": candidate, "citation_ids": ["qa:article-18"]}],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma síntese dos principais temas.",
            k=8, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        source_event_index = next(i for i, event in enumerate(events) if event["event"] == "sources")
        first_chunk_index = next(i for i, event in enumerate(events) if event["event"] == "chunk")
        self.assertLess(source_event_index, first_chunk_index)
        streamed_text = "".join(event.get("chunk", "") for event in events if event["event"] == "chunk")
        final = events[-1]
        self.assertNotIn("estabelece regras para o PCCV-Saúde", streamed_text)
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("trechos literais e abreviados", final["answer"])
        self.assertIn("cobre 19 de 39 artigos", final["answer"])
        self.assertIn("não representa uma análise integral", final["answer"])
        self.assertIn("Esta resposta é parcial e não representa uma análise integral da norma.", final["answer"])
        self.assertNotIn("**Art. 1º**", final["answer"])
        self.assertNotIn("**Art. 5º**", final["answer"])
        self.assertNotIn("**Art. 10º**", final["answer"])
        self.assertNotIn("**Art. 15º**", final["answer"])
        self.assertNotIn("**Art. 19º**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[5]]", final["answer"])
        self.assertIn("[[10]]", final["answer"])
        self.assertIn("[[15]]", final["answer"])
        self.assertIn("[[19]]", final["answer"])
        self.assertNotIn("[[18]]", final["answer"])
        self.assertEqual(len(final["sources"]), 19)
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_overview_keeps_broad_grounded_prefix_without_model_notice(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 19,
            "total_articles": 39,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:partial-prefix-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º O programa trata do tema {article} e suas regras.",
                "texto": f"Art. {article}º O programa trata do tema {article} e suas regras.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in range(1, 20)
        ]
        prefix = (
            "O programa é tratado no Art. 1º. [[1]] "
            "Os critérios aparecem no Art. 10º. [[10]] "
            "A execução é descrita no Art. 19º. [[19]]"
        )
        narrower_prefix = "O programa é tratado no Art. 1º. [[1]] Os critérios aparecem no Art. 10º. [[10]]"
        generate.return_value = _completed_generation_stream({
            "answer": narrower_prefix + "\n\nA resposta foi limitada ao que as fontes consultadas permitem confirmar.",
            "validated_prefix": narrower_prefix,
            "validated_prefix_candidates": [
                {
                    "answer": (
                        "A progressão funcional dos servidores é tratada no Art. 1º [[1]], "
                        "enquanto a progressão funcional e seus critérios aparecem nos Arts. "
                        "10º [[10]] e 19º [[19]], com outras regras detalhadas sobre a organização "
                        "administrativa da norma."
                    ),
                    "grounding": {
                        "grounded": True,
                        "claims": [
                            {"text": "claim 1", "citation_ids": ["qa:partial-prefix-1"]},
                            {"text": "claim 2", "citation_ids": ["qa:partial-prefix-10"]},
                            {"text": "claim 3", "citation_ids": ["qa:partial-prefix-19"]},
                        ],
                        "failed_claims": [],
                    },
                    "source_only": True,
                },
                {
                    "answer": prefix,
                    "grounding": {
                        "grounded": True,
                        "claims": [
                            {"text": "claim 1", "citation_ids": ["qa:partial-prefix-1"]},
                            {"text": "claim 2", "citation_ids": ["qa:partial-prefix-10"]},
                            {"text": "claim 3", "citation_ids": ["qa:partial-prefix-19"]},
                        ],
                        "failed_claims": [],
                    },
                    "source_only": True,
                },
                {
                    "answer": narrower_prefix,
                    "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                    "source_only": True,
                },
            ],
            "grounding": {
                "grounded": True,
                "claims": [
                    {"text": "claim 1", "citation_ids": ["qa:partial-prefix-1"]},
                    {"text": "claim 2", "citation_ids": ["qa:partial-prefix-10"]},
                    {"text": "claim 3", "citation_ids": ["qa:partial-prefix-19"]},
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
            "partial": True,
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos principais temas.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        streamed_text = "".join(event.get("chunk", "") for event in events if event["event"] == "chunk")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "generation_partial_after_grounded_prefix")
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "grounded_generated_claims_against_sampled_excerpts_from_unreviewed_archive_pdf",
        )
        self.assertTrue(final["answer"].startswith(prefix))
        self.assertNotIn("[[1]] [[10]]", final["answer"][: len(prefix)])
        self.assertIn("A amostra consultada cobre 19 de 39 artigos", final["answer"])
        self.assertNotIn("A resposta foi limitada", final["answer"])
        self.assertEqual(streamed_text, final["answer"])
        self.assertEqual(len(final["sources"]), 19)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_overview_releases_grounded_prefix_before_generation_finishes(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 19,
            "total_articles": 39,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:progressive-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º conteúdo verificável {article}.",
                "texto": f"Art. {article}º conteúdo verificável {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in range(1, 20)
        ]
        prefix = (
            "O Art. 1º institui o programa municipal. [[1]] "
            "O Art. 10º define os critérios de seleção. [[10]] "
            "O Art. 19º organiza a execução administrativa. [[19]]"
        )
        result = {
            "answer": prefix,
            "grounding": {
                "grounded": True,
                "claims": [
                    {"text": "claim 1", "citation_ids": ["qa:progressive-1"]},
                    {"text": "claim 2", "citation_ids": ["qa:progressive-10"]},
                    {"text": "claim 3", "citation_ids": ["qa:progressive-19"]},
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 4000}],
            "partial": False,
        }
        state = {"generation_finished": False}

        def progressive_generation(*_args, **_kwargs):
            yield {"event": "chunk", "chunk": "O Art. 1º institui o programa municipal. [[1]] "}
            yield {"event": "chunk", "chunk": "O Art. 10º define os critérios de seleção. [[10]] "}
            yield {"event": "chunk", "chunk": "O Art. 19º organiza a execução administrativa. [[19]]"}
            state["generation_finished"] = True
            return result

        generate.side_effect = progressive_generation
        events = stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos principais temas.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        )

        first_visible_chunk = None
        for event in events:
            if event["event"] == "chunk":
                first_visible_chunk = event
                break

        self.assertIsNotNone(first_visible_chunk)
        self.assertFalse(state["generation_finished"])
        self.assertEqual(first_visible_chunk["chunk"], prefix)
        remaining = list(events)
        final = remaining[-1]
        streamed_text = first_visible_chunk["chunk"] + "".join(
            event.get("chunk", "")
            for event in remaining
            if event["event"] == "chunk"
        )
        self.assertTrue(state["generation_finished"])
        self.assertEqual(final["event"], "done")
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("cobre 19 de 39 artigos", final["answer"])
        self.assertEqual(len(final["sources"]), 19)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_overview_generates_from_distributed_excerpt_context(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 19,
            "total_articles": 39,
            "annexes_present": True,
        }
        sources = [
            {
                "citation_id": f"qa:distributed-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": (
                    f"Art. {article}º O dispositivo estabelece o assunto específico "
                    f"identificável de número {article}, com detalhes de implementação."
                ),
                "texto": f"Texto {article}",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in range(1, 20)
        ]
        retrieve.return_value = sources
        candidate = "A amostra aborda os temas 1, 10 e 19. [[1]] [[10]] [[19]]"
        ollama_client = MagicMock()
        generate.return_value = _completed_generation_stream({
            "answer": candidate,
            "grounding": {"grounded": True, "claims": [], "failed_claims": []},
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos temas.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=ollama_client,
        ))

        prompt = generate.call_args.args[0]
        generate.call_args.kwargs["stream_attempt"]("probe")
        self.assertEqual(ollama_client.stream_text.call_args.kwargs["temperature"], 0.0)
        self.assertIn("[[1]] Lei Complementar nº 120/2010, Art. 1º", prompt)
        self.assertIn("[[5]] Lei Complementar nº 120/2010, Art. 5º", prompt)
        self.assertIn("[[10]] Lei Complementar nº 120/2010, Art. 10º", prompt)
        self.assertIn("[[15]] Lei Complementar nº 120/2010, Art. 15º", prompt)
        self.assertIn("[[19]] Lei Complementar nº 120/2010, Art. 19º", prompt)
        self.assertNotIn("Art. 2º O dispositivo estabelece", prompt)
        self.assertIn("A geração recebeu 5 excertos distribuídos entre 19 dispositivos", prompt)
        self.assertIn("anexos normativos", prompt.casefold())
        self.assertIn("escreva exatamente 3", prompt.casefold())
        self.assertIn("um artigo e um marcador distinto por frase", prompt.casefold())
        self.assertIn("não use heading, lista, conclusão", prompt.casefold())
        self.assertIn("paráfrase mínima, preserve o verbo operativo e a modalidade", prompt.casefold())
        self.assertIn("não infira obrigação, permissão, proibição, condição", prompt.casefold())
        self.assertIn("não repita tema ou denominação", prompt.casefold())
        self.assertIn("pare após a terceira afirmação sustentada", prompt.casefold())
        validate_attempt = generate.call_args.kwargs["validate_attempt"]
        supported = validate_attempt(
            "O dispositivo estabelece o assunto específico identificável de número 1, "
            "com detalhes de implementação. [[1]]"
        )
        hidden_source = validate_attempt(
            "O dispositivo estabelece o assunto específico identificável de número 2, "
            "com detalhes de implementação. [[2]]"
        )
        self.assertTrue(supported["grounded"])
        self.assertFalse(hidden_source["grounded"])
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["answer"].split("\n\n")[0], candidate)
        self.assertIn(
            "a geração recebeu uma amostra de 5 excertos entre 19 dispositivos recuperados",
            final["answer"],
        )
        self.assertIn(
            "A resposta cita apenas os excertos que sustentam as afirmações apresentadas",
            final["answer"],
        )
        self.assertEqual(len(re.findall(r"\[\[\d+\]\]", final["answer"])), 3)
        self.assertEqual(len(final["sources"]), 19)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_generation_for_whole_norm_uses_literal_evidence_map(
        self, retrieve, generate
    ):
        coverage = {
            "complete": False,
            "selected_articles": 5,
            "total_articles": 39,
            "annexes_present": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:partial-{article}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Evidência literal do tema {article}.",
                "texto": f"Art. {article}º Evidência literal do tema {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (1, 10, 19, 28, 37)
        ]
        partial_answer = (
            "A norma trata de estrutura, carreira e gratificações. [[1]] [[2]] [[3]]"
        )
        generate.return_value = _completed_generation_stream({
            "answer": partial_answer + " A síntese ficou incompleta.",
            "grounding": {
                "grounded": True,
                "claims": [
                    {"text": "A norma trata de estrutura.", "citation_ids": ["qa:partial-1"]},
                    {"text": "Também trata de carreira.", "citation_ids": ["qa:partial-10"]},
                    {"text": "Há gratificações.", "citation_ids": ["qa:partial-19"]},
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 10}],
            "partial": True,
        })

        events = list(stream_archive_qa_answer(
            "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos temas.",
            k=8,
            model="llama3",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        ))

        final = events[-1]
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertNotIn("A norma trata de estrutura, carreira", final["answer"])
        self.assertNotIn("A síntese ficou incompleta", streamed_text)
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("A amostra consultada cobre 5 de 39 artigos", final["answer"])
        self.assertIn("não representa uma análise integral da norma", final["answer"])
        self.assertNotIn("**Art. 1º**", final["answer"])
        self.assertNotIn("**Art. 10º**", final["answer"])
        self.assertNotIn("**Art. 19º**", final["answer"])
        self.assertTrue(all(source in final["sources"] for source in retrieve.return_value))
        self.assertIn("VISÃO GERAL PARCIAL", generate.call_args.kwargs["revision_instruction"])
