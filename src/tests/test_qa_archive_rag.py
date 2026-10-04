from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from src.apps.legislation.document_models import ExtracaoDocumento
from src.processing.qa_archive_rag import retrieve_archive_evidence, stream_archive_qa_answer


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


@override_settings(NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED=False)
class ArchiveQARetrievalTests(SimpleTestCase):
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
            sapl_url="https://sapl.natal.rn.leg.br/norma/9076/",
            pdf_url="https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2010/9076/lc_118_10.pdf",
        )
        filter_documents.return_value.order_by.return_value.__getitem__.return_value = [document]
        filter_normas.return_value.only.return_value = [matched]

        rows = retrieve_archive_evidence(
            "O que estabelece a Lei Complementar nº 118/2010?", limit=8
        )

        self.assertEqual(rows[0]["sapl_url"], "https://sapl.natal.rn.leg.br/norma/9076/")
        self.assertEqual(rows[0]["pdf_url"], matched.pdf_url)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_large_whole_norm_uses_distributed_sample_and_reports_partial_coverage(self, filter_documents):
        legal_text = "\n".join(
            f"Art. {number}º Este dispositivo define as regras administrativas para o programa municipal número {number}."
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
    @patch("src.processing.qa_archive_rag.run_grounded_generation")
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
        generate.return_value = {
            "answer": "A coordenação cabe à Secretaria Municipal de Educação. [[1]]",
            "grounding": {"grounded": True, "claims": [], "failed_claims": []},
            "source_only": True,
            "generation_attempts": [{"duration_ms": 4}],
        }

        events = list(stream_archive_qa_answer(
            "Quem coordena o programa?", k=5, model="llama3", temperature=0.1,
            text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))
        types = [event.get("event") for event in events]

        self.assertLess(types.index("sources"), types.index("chunk"))
        self.assertTrue(events[-1]["grounded"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.run_grounded_generation")
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
        self.assertIn("[[1]]", events[-1]["answer"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.run_grounded_generation")
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
        generate.return_value = {
            "answer": "fallback do validador",
            "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
            "source_only": False,
            "generation_attempts": [{"duration_ms": 5}],
        }

        events = list(stream_archive_qa_answer(
            "Qual é a finalidade da Lei nº 6021/2009?", k=5, model="llama3",
            temperature=0.1, text_provider={"provider": "ollama"}, ollama=MagicMock(),
        ))

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_evidence_only_fallback")
        self.assertEqual(final["sources"], [source])
        self.assertIn("Não consegui montar uma síntese confiável", final["answer"])
        self.assertIn("3 dos 16 artigos", final["answer"])
        self.assertIn("anexos que não entraram", final["answer"])
        self.assertIn("Fontes Consultadas", final["answer"])
        self.assertNotIn("[[1]]", final["answer"])
        self.assertNotIn("O Município institui", final["answer"])
        source_event = next(event for event in events if event["event"] == "sources")
        self.assertEqual(source_event["coverage"]["selected_articles"], 3)
