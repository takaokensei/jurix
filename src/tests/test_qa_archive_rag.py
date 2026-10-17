import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.normative_query import classify_normative_query, parse_normative_references
from src.processing.qa_archive_rag import (
    _PARTIAL_OVERVIEW_REVISION_INSTRUCTION,
    _PROCESS_TRANSITION_EVIDENCE_RE,
    _PROCESS_TRANSITION_SCOPE_REQUEST_RE,
    _WHOLE_NORM_CONTEXT_BUDGET_CHARS,
    _archive_explicit_repeal_scope_synthesis,
    _archive_explicit_transition_pair_synthesis,
    _archive_relation_candidate_sources,
    _archive_requested_paragraphs,
    _archive_retrieval_candidates,
    _archive_search_tokens,
    _archive_transition_commencement_synthesis,
    _archive_transition_synthesis,
    _article_reference_mentions,
    _article_rows,
    _article_topic_phrase,
    _dedupe_relation_candidate_sources,
    _enumerated_topic_facets,
    _explicit_article_norm_pairs,
    _facet_evidence_map,
    _facet_excerpt,
    _has_ambiguous_multi_norm_article_scope,
    _has_cited_facet_coverage,
    _has_partial_overview_breadth,
    _intersticio_duration_not_recovered,
    _is_whole_norm_request,
    _matching_archive_article_sources,
    _metadata_only_sapl_norma_source,
    _multi_norm_synthesis_instruction,
    _official_dom_article_source,
    _official_dom_articles_sources,
    _official_sapl_publication_source,
    _page_index_for_excerpt,
    _partial_overview_evidence_narrative,
    _partial_overview_excerpts,
    _partial_overview_sample_limit,
    _partial_overview_triage_checklist,
    _related_matter_search_limit,
    _requested_archive_norm_title,
    _requested_topic_facets,
    _sample_whole_norm_rows,
    _select_facet_sources,
    _source_matches_facet,
    _strong_topic_phrase_rows,
    _supplement_missing_explicit_official_articles,
    _tokens,
    _vacatio_counting_rule_source,
    _vacatio_effective_date,
    _whole_norm_topic_tokens,
    retrieve_archive_evidence,
    stream_archive_qa_answer,
)


def test_vacatio_count_includes_publication_date_and_effective_day_follows_period():
    effective_date = _vacatio_effective_date(
        "Esta Lei entra em vigor 90 (noventa) dias após a data de sua publicação.",
        date(2024, 12, 27),
    )

    assert effective_date == date(2025, 3, 27)
    assert "último dia" in _vacatio_counting_rule_source()["full_text"]


@patch("src.processing.qa_archive_rag.Norma")
def test_official_sapl_publication_source_requires_one_exact_nonsynthetic_identity(norma_model):
    norma = SimpleNamespace(
        identity_json={"jurisdiction": "BR-RN-NATAL"},
        numero="258",
        ano=2024,
        sapl_id=4052,
        sapl_metadata={"data_publicacao": "2024-12-27", "veiculo_publicacao": "DOM"},
        data_publicacao=None,
        get_tipo_display_name=MagicMock(return_value="Lei Complementar"),
    )
    queryset = MagicMock()
    queryset.order_by.return_value = queryset
    queryset.__getitem__.return_value = [norma]
    norma_model.objects.filter.return_value = queryset
    reference = SimpleNamespace(
        ambiguous=False,
        type_key="lei_complementar",
        number="258",
        year=2024,
    )

    source = _official_sapl_publication_source(reference)

    assert source["citation_id"] == "sapl:publication-metadata:4052"
    assert source["data_publicacao"] == "2024-12-27"
    assert source["source_url"] == "https://sapl.natal.rn.leg.br/norma/4052"
    norma_model.objects.filter.assert_called_once_with(ano=2024, sapl_id__isnull=False)

    queryset.__getitem__.return_value = [norma, norma]
    assert _official_sapl_publication_source(reference) is None


def test_whole_norm_empty_sapl_search_does_not_claim_article_level_coverage():
    message = _related_matter_search_limit("searched", article_scope=False)

    assert "identidade da norma" in message
    assert "completude do cadastro" in message
    assert "inexistem alterações posteriores" in message
    assert "este artigo" not in message


@patch(
    "src.processing.qa_archive_rag.canonical_sapl_url",
    return_value="https://sapl.natal.rn.leg.br/norma/9382",
)
@patch("src.processing.qa_archive_rag.Norma.objects.filter")
def test_metadata_only_catalog_lookup_requires_one_exact_typed_norm(filter_normas, canonical_url):
    norma = SimpleNamespace(
        tipo="1",
        numero="8.201",
        ano=2026,
        sapl_id=9382,
        sapl_metadata={"data_publicacao": "2026-09-10"},
        data_publicacao=date(2026, 9, 9),
        get_tipo_display_name=lambda: "Lei Ordinária",
    )
    queryset = MagicMock()
    queryset.order_by.return_value.__getitem__.return_value = [norma]
    filter_normas.return_value = queryset
    reference = classify_normative_query(
        "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026?"
    ).reference

    source = _metadata_only_sapl_norma_source(reference)

    assert source["citation_id"] == "sapl:norma-catalog:9382"
    assert source["source_kind"] == "sapl_normative_catalog"
    assert source["evidence_scope"] == "official_normative_catalog_metadata"
    assert source["metadata_only"] is True
    assert source["sapl_url"] == "https://sapl.natal.rn.leg.br/norma/9382"
    assert source["data_publicacao"] == "2026-09-10"
    filter_kwargs = filter_normas.call_args.kwargs
    assert filter_kwargs["numero__in"] == {"8201", "8.201"}
    assert filter_kwargs["sapl_metadata__has_key"] == "_jurix_source_hash"
    canonical_url.assert_called_once_with(sapl_id=9382)


def test_official_dom_article_lookup_requires_exact_act_identity_and_returns_only_requested_article():
    degree = chr(186)
    reference = classify_normative_query(
        "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026?"
    ).reference
    edition = SimpleNamespace(
        identity="natal-dom:2026:6189:2026-09-10:regular",
        publication_date=date(2026, 9, 10),
        special=False,
        official_url="https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20260910_"
        + "a" * 32
        + ".pdf",
    )
    client = MagicMock()
    client.list_editions.return_value = [edition]
    client.download_edition.return_value = SimpleNamespace(content=b"%PDF-test")
    pdf = MagicMock()
    pdf.__len__.return_value = 2
    pdf.load_page.side_effect = [
        SimpleNamespace(
            get_text=lambda: "\n".join(
                [
                    "LEI ORDINARIA No 8201, DE 09 DE SETEMBRO DE 2026",
                    f"Art. 1{degree} Fica criado o Cadastro Protetor para animais.",
                    "Paragrafo unico. A plataforma sera digital.",
                    f"Art. 2{degree} O cadastro tera objetivos proprios.",
                ]
            )
        ),
        SimpleNamespace(get_text=lambda: f"Art. 3{degree} Norma seguinte."),
    ]

    with (
        patch("src.clients.dom_natal.client.DomNatalClient", return_value=client),
        patch("pymupdf.open", return_value=pdf),
    ):
        source = _official_dom_article_source(reference, "1", "2026-09-10")

    assert source is not None
    assert source["source_kind"] == "official_gazette_extraction"
    assert source["evidence_scope"] == "official_gazette_unreviewed_extraction"
    assert source["full_text"] == (
        f"Art. 1{degree} Fica criado o Cadastro Protetor para animais.\n"
        "Paragrafo unico. A plataforma sera digital."
    )
    assert "Art. 2º" not in source["full_text"]
    assert source["pdf_url"] == edition.official_url
    client.session.close.assert_called_once()


def test_official_dom_article_lookup_rejects_pdf_with_wrong_norm_number():
    degree = chr(186)
    reference = classify_normative_query(
        "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026?"
    ).reference
    edition = SimpleNamespace(
        identity="natal-dom:2026:6189:2026-09-10:regular",
        publication_date=date(2026, 9, 10),
        special=False,
        official_url="https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20260910_"
        + "b" * 32
        + ".pdf",
    )
    client = MagicMock()
    client.list_editions.return_value = [edition]
    client.download_edition.return_value = SimpleNamespace(content=b"%PDF-test")
    pdf = MagicMock()
    pdf.__len__.return_value = 1
    pdf.load_page.return_value.get_text.return_value = (
        "LEI ORDINARIA No 8200, DE 09 DE SETEMBRO DE 2026\n" f"Art. 1{degree} Texto de outra lei."
    )

    with (
        patch("src.clients.dom_natal.client.DomNatalClient", return_value=client),
        patch("pymupdf.open", return_value=pdf),
    ):
        source = _official_dom_article_source(reference, "1", "2026-09-10")

    assert source is None
    client.session.close.assert_called_once()


def test_official_dom_articles_lookup_extracts_multiple_devices_from_one_exact_issue():
    degree = chr(186)
    reference = classify_normative_query(
        "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026?"
    ).reference
    edition = SimpleNamespace(
        identity="natal-dom:2026:6189:2026-09-10:regular",
        publication_date=date(2026, 9, 10),
        special=False,
        official_url="https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20260910_"
        + "c" * 32
        + ".pdf",
    )
    client = MagicMock()
    client.list_editions.return_value = [edition]
    client.download_edition.return_value = SimpleNamespace(content=b"%PDF-test")
    pdf = MagicMock()
    pdf.__len__.return_value = 1
    pdf.load_page.return_value.get_text.return_value = "\n".join(
        [
            "LEI ORDINARIA No 8201, DE 09 DE SETEMBRO DE 2026",
            f"Art. 1{degree} Fica criado o Cadastro Protetor para animais.",
            f"Art. 2{degree} O cadastro tera objetivos proprios.",
            f"Art. 3{degree} Esta Lei entra em vigor na data de sua publicacao.",
        ]
    )

    with (
        patch("src.clients.dom_natal.client.DomNatalClient", return_value=client),
        patch("pymupdf.open", return_value=pdf),
    ):
        sources = _official_dom_articles_sources(reference, ["1", "3"], "2026-09-10")

    assert [source["dispositivo_ref"] for source in sources] == ["Art. 1º", "Art. 3º"]
    assert sources[0]["full_text"].startswith("Art. 1º Fica criado")
    assert sources[1]["full_text"].startswith("Art. 3º Esta Lei entra em vigor")
    assert all(source["pdf_url"] == edition.official_url for source in sources)
    assert client.download_edition.call_count == 1
    client.session.close.assert_called_once()


def test_missing_explicit_transition_article_is_recovered_from_exact_official_issue():
    question = (
        "Em um processo de licenciamento protocolado antes da entrada em vigor da LC 258/2024 "
        "e ainda sem despacho decisório, como devo conferir a aplicação da regra do Art. 21 da "
        "Lei Complementar nº 55/2004? Considere o Art. 260, inciso IV, e o Art. 262 da LC 258/2024."
    )
    existing = [
        {
            "citation_id": "qa:lc258-art262",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 262",
            "source_kind": "archive",
        },
        {
            "citation_id": "qa:lc55-art21",
            "norma_ref": "Lei Complementar nº 55/2004",
            "dispositivo_ref": "Art. 21",
            "source_kind": "archive",
        },
    ]
    reference = parse_normative_references("LC 258/2024")[0]
    official_source = {
        "citation_id": "dom:lc258-art260",
        "norma_ref": "Lei Complementar nº 258/2024",
        "dispositivo_ref": "Art. 260",
        "full_text": "Art. 260. Ficam revogados, inclusive, a Lei Complementar nº 55/2004.",
        "source_kind": "official_gazette_extraction",
        "data_publicacao": "2024-12-27",
    }

    with (
        patch(
            "src.processing.qa_archive_rag._official_sapl_publication_source",
            return_value={"data_publicacao": "2024-12-27"},
        ) as publication_lookup,
        patch(
            "src.processing.qa_archive_rag._official_dom_article_source",
            return_value=official_source,
        ) as article_lookup,
    ):
        additions = _supplement_missing_explicit_official_articles(question, existing)

    assert additions == [official_source]
    publication_lookup.assert_called_once_with(reference)
    article_lookup.assert_called_once_with(reference, "260", "2024-12-27")


def _archive_document(*, number="6021", year=2009, legal_text=None, metadata_candidates_json=None):
    legal_text = legal_text or (
        "Art. 1º Fica instituído o Programa Municipal de Hortas Comunitárias.\n"
        "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação."
    )
    extraction = SimpleNamespace(
        status=ExtracaoDocumento.Status.COMPLETE,
        legal_text=legal_text,
        extraction_sha256="a" * 64,
        metadata_candidates_json=metadata_candidates_json or {},
    )
    return SimpleNamespace(
        public_id="00000000-0000-0000-0000-000000000001",
        metadata_json={
            "identity_candidate": {"type": "lei_ordinaria", "number": number, "year": year},
            "identity_key": f"BR-RN-NATAL:lei:{number}:{year}",
        },
        conflicts_json=[],
        extracoes=SimpleNamespace(
            order_by=lambda *_args: SimpleNamespace(first=lambda: extraction)
        ),
    )


def _mock_archive_candidates(filter_documents, documents):
    queryset = filter_documents.return_value
    queryset.filter.return_value = queryset
    queryset.annotate.return_value = queryset
    queryset.order_by.return_value = queryset
    queryset.__getitem__.return_value = documents
    queryset.__iter__.side_effect = lambda: iter(documents)


def _completed_generation_stream(result):
    if result.get("grounded") and result.get("source_only"):
        yield {"event": "chunk", "chunk": result["answer"], "provisional": False}
    return result


@override_settings(
    NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED=False,
    SAPL_MATTER_LOOKUP_ENABLED=False,
    JURIX_BUILD_PROFILE="",
)
class ArchiveQARetrievalTests(SimpleTestCase):
    def test_archive_shortlist_drops_question_framing_but_keeps_legal_topic_terms(self):
        tokens = _tokens(
            "Em qual ato municipal disponível no acervo consta que a COSIP incide "
            "sobre unidades imobiliárias não edificadas, e esse ato permite concluir "
            "que ele instituiu a contribuição ou apenas disciplina a arrecadação?"
        )

        shortlist_tokens = _archive_search_tokens(tokens)

        self.assertTrue(
            {"cosip", "incide", "unidades", "imobiliarias", "edificadas"} <= shortlist_tokens
        )
        self.assertTrue(
            {"ato", "acervo", "disponivel", "consta", "permite", "concluir", "nao"}.isdisjoint(
                shortlist_tokens
            )
        )

    def test_repeal_scope_synthesis_separates_bare_acts_from_article_target(self):
        source = {
            "citation_id": "qa:lc258-art260",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260",
            "full_text": (
                "Art. 260. Ficam revogados: I - Lei Complementar nº 1.894 de 31 de dezembro de 1969; "
                "II - Lei Nº 4.566 de 19 de maio de 1992; III - Lei nº 4.885 de 07 de outubro de 1997; "
                "IV - Lei Complementar nº 055 de 27 de janeiro de 2004; "
                "V - Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009; "
                "VI - Lei Promulgada nº 562 de 14 de setembro de 2018; "
                "VII - Lei nº 198 de 12 de novembro de 2021."
            ),
        }
        question = (
            "Quais normas anteriores o art. 260 da Lei Complementar nº 258/2024 "
            "expressamente revoga?"
        )

        result = _archive_explicit_repeal_scope_synthesis(question, [source])

        self.assertIsNotNone(result)
        answer, claims = result
        self.assertIn("atos sem artigo individual especificado", answer)
        self.assertIn("Lei Complementar nº 1.894/1969", answer)
        self.assertIn("Art. 21 da Lei Promulgada nº 275/2009", answer)
        self.assertIn("dispositivo(s) com artigo expressamente delimitado", answer)
        self.assertIn("No alcance literal da cláusula", answer)
        self.assertIn("sem limitar o texto a um dispositivo específico", answer)
        self.assertIn("delimita expressamente o alvo àquele dispositivo", answer)
        self.assertIn("não confirma a eficácia jurídica da revogação", answer)
        self.assertIn("vigência atual de cada norma", answer)
        self.assertNotIn("estão revogadas atualmente", answer)
        self.assertTrue(all(claim["citation_ids"] == ["qa:lc258-art260"] for claim in claims))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_repeal_scope_synthesis_is_used_by_archive_stream(self, retrieve):
        source = {
            "citation_id": "qa:lc258-art260",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260",
            "full_text": (
                "Art. 260. Ficam revogadas: I - Lei Complementar nº 1.894 de 31 de dezembro de 1969; "
                "V - Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009."
            ),
            "texto": "Art. 260. Ficam revogadas.",
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]

        events = list(
            stream_archive_qa_answer(
                "Quais normas anteriores o art. 260 da Lei Complementar nº 258/2024 "
                "expressamente revoga?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_explicit_repeal_scope_text")
        self.assertIn("Art. 21 da Lei Promulgada nº 275/2009", final["answer"])
        self.assertIn("No alcance literal da cláusula", final["answer"])
        self.assertIn("não confirma a eficácia jurídica", final["answer"])
        self.assertTrue(final["source_only"])
        self.assertEqual(final["sources"], [source])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_explicit_archive_title_shortlists_before_broad_lexical_fallback(
        self, filter_documents
    ):
        candidates = MagicMock()
        candidates.annotate.return_value = candidates
        title_candidates = MagicMock()
        title_candidates.exists.return_value = True
        title_candidates.order_by.return_value = title_candidates
        expected = [object()]
        title_candidates.__getitem__.return_value = expected
        candidates.filter.return_value = title_candidates
        filter_documents.return_value = candidates

        result = _archive_retrieval_candidates(
            exact_ref=None,
            explicit_references=[],
            query_tokens={"acessibilidade", "edificações", "codigo", "obras"},
            required_title="codigo de obras",
        )

        self.assertEqual(result, expected)
        title_query = candidates.filter.call_args.args[0]
        self.assertIn("latest_legal_text__icontains", str(title_query))
        self.assertIn("Código de Obras", str(title_query))
        self.assertEqual(title_candidates.__getitem__.call_args.args[0].stop, 40)

    @override_settings(JURIX_BUILD_PROFILE="qa")
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_pending_sapl_norms_are_searchable_only_in_qa_profile(self, filter_documents):
        candidates = MagicMock()
        candidates.filter.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []
        filter_documents.return_value = candidates

        _archive_retrieval_candidates(
            exact_ref=None,
            explicit_references=[],
            query_tokens={"tributário"},
        )

        source_kinds = filter_documents.call_args.kwargs["source_kind__in"]
        self.assertIn(DocumentoNormativo.SourceKind.ARCHIVE, source_kinds)
        self.assertIn(DocumentoNormativo.SourceKind.SAPL, source_kinds)

    @override_settings(JURIX_BUILD_PROFILE="production")
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_pending_sapl_norms_are_not_searchable_outside_qa(self, filter_documents):
        candidates = MagicMock()
        candidates.filter.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = []
        filter_documents.return_value = candidates

        _archive_retrieval_candidates(
            exact_ref=None,
            explicit_references=[],
            query_tokens={"tributário"},
        )

        source_kinds = filter_documents.call_args.kwargs["source_kind__in"]
        self.assertEqual(source_kinds, (DocumentoNormativo.SourceKind.ARCHIVE,))

    def test_retrieved_topic_excerpt_uses_page_with_most_of_its_text(self):
        body = "Art. 26. Regra geral. II – Gratificação de Vigilância Sanitária atribuída aos servidores."
        excerpt = "II – Gratificação de Vigilância Sanitária atribuída aos servidores."
        body_start = 100
        excerpt_start = body_start + body.index(excerpt)

        page_index = _page_index_for_excerpt(
            {"texto": body, "text_start_pos": body_start},
            excerpt,
            [
                {"start": 80, "end": excerpt_start + 12, "page": 6},
                {"start": excerpt_start + 12, "end": body_start + len(body), "page": 7},
            ],
        )

        self.assertEqual(page_index, 6)

    def test_article_rows_preserve_offsets_and_map_articles_to_original_pdf_pages(self):
        text = (
            "--- Página 1 ---\n"
            "Art. 1º Primeiro dispositivo.\n"
            "--- Página 2 ---\n"
            "CÂMARA MUNICIPAL DE NATAL\n"
            "Art. 2º Segundo dispositivo.\n"
        )
        first_page_start = len("--- Página 1 ---\n")
        first_start = text.index("Art. 1º")
        second_page_start = text.index("--- Página 2 ---\n") + len("--- Página 2 ---\n")
        second_start = text.index("Art. 2º")
        page_map = [
            {"start": first_page_start, "end": text.index("--- Página 2 ---\n"), "page": 1},
            {"start": second_page_start, "end": len(text), "page": 2},
        ]

        rows = _article_rows(text, page_map=page_map)

        self.assertEqual([row["numero"] for row in rows], ["1º", "2º"])
        self.assertEqual(
            [row["page_index"] for row in rows],
            [0, 1],
            msg=f"page map={page_map!r}; article starts={[row['start_pos'] for row in rows]!r}",
        )
        self.assertEqual(rows[0]["start_pos"], first_start)
        self.assertEqual(rows[1]["start_pos"], second_start)
        self.assertIn("Segundo dispositivo.", rows[1]["texto"])

    def test_strong_multiterm_subject_match_excludes_generic_health_and_budget_hits(self):
        question = (
            "Quais critérios de elegibilidade e limites de acumulação devo verificar "
            "para a Gratificação de Vigilância Sanitária de um servidor da saúde? "
            "Responda em poucas frases com base nos PDFs recuperados e diga o que "
            "a documentação não comprova."
        )
        relevant = {
            "dispositivo_ref": "Art. 26",
            "full_text": (
                "Aos servidores da área da Saúde poderão ser concedidas gratificações: "
                "II – Gratificação de Vigilância Sanitária (GVISA), atribuída aos servidores "
                "com experiência mínima de dois anos ou especialização."
            ),
        }
        unrelated_health = {
            "dispositivo_ref": "Art. 11",
            "full_text": (
                "A contagem de tempo do servidor da saúde para evolução na carreira "
                "não incluirá afastamentos."
            ),
        }
        unrelated_budget = {
            "dispositivo_ref": "Art. 1º",
            "full_text": (
                "Fica aprovada a revisão do Plano Plurianual Participativo da Cidade do Natal."
            ),
        }

        selected = _strong_topic_phrase_rows(
            question, [relevant, unrelated_health, unrelated_budget]
        )

        self.assertEqual(selected, [relevant])

    def test_paired_eligibility_and_accumulation_question_requires_both_facets(self):
        question = (
            "Quais critérios de elegibilidade e limites de acumulação devo verificar "
            "para a Gratificação de Vigilância Sanitária?"
        )
        source = {
            "full_text": (
                "I – Gratificação de Plantão. II – Gratificação de Vigilância Sanitária, atribuída aos servidores com "
                "experiência mínima de dois anos ou especialização e dedicação exclusiva. "
                "carga horária de 40 horas semanais, estabelecida em valores. § 1º - É vedada a percepção da GVISA "
                "em conjunto com qualquer outra gratificação específica da Saúde. § 2º - outra regra."
            )
        }

        facets = _requested_topic_facets(question)

        self.assertEqual(facets, ("elegibilidade", "acumulação"))
        self.assertTrue(all(_source_matches_facet(facet, source) for facet in facets))
        excerpt = _facet_excerpt("elegibilidade", source)
        self.assertIn("Gratificação de Vigilância Sanitária", excerpt)
        self.assertIn("experiência mínima", excerpt)
        self.assertIn("40 horas semanais", excerpt)
        self.assertNotIn("Gratificação de Plantão", excerpt)
        accumulation_excerpt = _facet_excerpt("acumulação", source)
        self.assertIn("É vedada a percepção", accumulation_excerpt)
        self.assertNotIn("§ 2º", accumulation_excerpt)

    def test_plain_language_grant_criteria_question_requests_eligibility_facet(self):
        question = "gratificação vigilância sanitária experiência mínima " "dedicação exclusiva"
        source = {
            "dispositivo_ref": "Art. 26",
            "full_text": (
                "Aos servidores da área da Saúde poderão ser concedidas as seguintes "
                "gratificações: I – Gratificação de Plantão, devida aos servidores em "
                "regime de plantão; II – Gratificação de Vigilância Sanitária (GVISA), "
                "atribuída aos servidores com experiência mínima de dois anos ou "
                "especialização nessa área e dedicação exclusiva, estabelecida em "
                "40 horas semanais."
            ),
        }

        facets = _requested_topic_facets(question)
        excerpt = _facet_excerpt("elegibilidade", source)

        self.assertEqual(facets, ("elegibilidade",))
        self.assertTrue(_source_matches_facet("elegibilidade", source))
        self.assertIn("experiência mínima", excerpt)
        self.assertIn("dedicação exclusiva", excerpt)
        self.assertNotIn("Gratificação de Plantão", excerpt)

    def test_dedication_phrase_without_grant_question_does_not_infer_eligibility(self):
        self.assertEqual(
            _requested_topic_facets("Como funciona a dedicação exclusiva no setor?"),
            (),
        )

    def test_eligibility_answer_must_preserve_threshold_alternative_and_workload(self):
        source = {
            "citation_id": "qa:lc120-art26",
            "full_text": (
                "II – Gratificação de Vigilância Sanitária (GVISA), atribuída aos servidores "
                "com experiência mínima de 2 (dois) anos consecutivos no serviço ou com curso "
                "de especialização nessa área, desde que prestem seus serviços em regime de "
                "dedicação exclusiva e carga horária de 40 (quarenta) horas semanais."
            ),
        }

        generic_answer = "A GVISA exige experiência mínima e dedicação exclusiva. [[1]]"
        complete_answer = (
            "A GVISA exige experiência mínima de 2 anos ou curso de especialização, "
            "dedicação exclusiva e carga horária de 40 horas semanais. [[1]]"
        )

        self.assertFalse(_has_cited_facet_coverage(generic_answer, [source], ("elegibilidade",)))
        self.assertTrue(_has_cited_facet_coverage(complete_answer, [source], ("elegibilidade",)))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_inferred_eligibility_query_replaces_generic_grounded_draft_with_exact_evidence(
        self, retrieve, generate
    ):
        question = "gratificação vigilância sanitária experiência mínima dedicação exclusiva"
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art26",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 26",
                "full_text": (
                    "Aos servidores da área da Saúde poderão ser concedidas gratificações: "
                    "I – Gratificação de Plantão, devida aos servidores em regime de plantão. "
                    "II – Gratificação de Vigilância Sanitária (GVISA), atribuída aos servidores "
                    "com experiência mínima de 2 (dois) anos consecutivos no serviço ou com "
                    "curso de especialização nessa área, desde que prestem seus serviços em "
                    "regime de dedicação exclusiva e carga horária de 40 (quarenta) horas "
                    "semanais, estabelecida em valores."
                ),
                "texto": "Art. 26. Gratificações municipais.",
                "similarity_score": 0.9,
            }
        ]
        generic_answer = (
            "Conclusão jurídica: A GVISA exige experiência mínima e dedicação exclusiva. [[1]]"
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": generic_answer,
                "grounded": True,
                "source_only": True,
                "grounding": {
                    "grounded": True,
                    "claims": [{"text": generic_answer, "citation_ids": ["qa:lc120-art26"]}],
                    "failed_claims": [],
                },
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_facet_evidence_map")
        self.assertIn("experiência mínima de 2 (dois) anos", final["answer"])
        self.assertIn("curso de especialização", final["answer"])
        self.assertIn("dedicação exclusiva", final["answer"])
        self.assertIn("40 (quarenta) horas", final["answer"])
        self.assertNotIn("Gratificação de Plantão", final["answer"])

    def test_enumerated_facets_are_extracted_from_explicit_scope_list(self):
        facets = _enumerated_topic_facets(
            "Na LC 120/2010, quais aspectos aparecem — ingresso, jornada, remuneração "
            "e desenvolvimento funcional? Explique e separe a redação arquivada da vigente."
        )
        self.assertEqual(
            facets,
            ("ingresso", "jornada", "remuneração", "desenvolvimento funcional"),
        )

    def test_natural_which_provisions_question_extracts_distinct_topics(self):
        facets = _enumerated_topic_facets(
            "Na triagem de uma obra municipal, quais dispositivos da LC nº 258/2024 "
            "tratam do objeto do Código, de complementações ou notificações e de "
            "processos antigos sem despacho? Explique em poucas frases as regras distintas, "
            "cite cada artigo e diga o que um PDF extraído não confirma sobre alterações posteriores."
        )

        self.assertEqual(
            facets,
            (
                "objeto do Código",
                "complementações ou notificações",
                "processos antigos sem despacho",
            ),
        )

    def test_compound_facet_does_not_match_a_single_generic_word(self):
        self.assertFalse(
            _source_matches_facet(
                "objeto do Código",
                {
                    "full_text": (
                        "O documento descreve o objeto do licenciamento e cita o Código Civil."
                    ),
                },
            )
        )
        self.assertTrue(
            _source_matches_facet(
                "objeto do Código",
                {"full_text": "Art. 1º. Este Código tem por objeto disciplinar o licenciamento."},
            )
        )
        self.assertTrue(
            _source_matches_facet(
                "objeto do Código",
                {
                    "full_text": (
                        "A aplicação do Código de Obras e Edificações do Município do Natal "
                        "\nreger-se-á pelos seguintes objetivos e princípios:"
                    ),
                },
            )
        )
        self.assertTrue(
            _source_matches_facet(
                "processos antigos sem despacho",
                {
                    "full_text": (
                        "Processos protocolados antes da lei e sem despacho decisório "
                        "seguem a legislação da data do protocolo."
                    ),
                },
            )
        )

    def test_whole_norm_summary_with_colon_is_not_misread_as_topic_facet_list(self):
        question = (
            "Faça uma síntese curta da Lei Complementar nº 258/2024 para triagem inicial "
            "de um processo de licenciamento: quais assuntos e dispositivos do PDF são "
            "relevantes, e o que não posso concluir sem conferir os autos e a publicação oficial?"
        )

        self.assertEqual(_enumerated_topic_facets(question), ())
        self.assertTrue(_is_whole_norm_request(question, classify_normative_query(question)))

    def test_facet_source_selection_reserves_distinct_matching_provisions(self):
        facets = ("ingresso", "jornada", "remuneração", "desenvolvimento funcional")
        rows = [
            {
                "citation_id": f"art-{index}",
                "dispositivo_ref": f"Art. {index}",
                "full_text": text,
                "similarity_score": score,
            }
            for index, (text, score) in enumerate(
                [
                    ("O plano de carreira dos profissionais da saúde é instituído.", 1.0),
                    ("O ingresso nos cargos da carreira ocorrerá por concurso público.", 0.2),
                    ("A jornada semanal dos servidores será de 40 horas.", 0.1),
                    ("A remuneração será composta pelo vencimento básico e vantagens.", 0.1),
                    ("O desenvolvimento funcional ocorrerá por progressão na carreira.", 0.1),
                ],
                1,
            )
        ]

        selected = _select_facet_sources(rows, facets, limit=2)

        self.assertEqual(
            {row["citation_id"] for row in selected},
            {"art-2", "art-3", "art-4", "art-5"},
        )

    def test_facet_source_selection_handles_unmatched_facets_without_reusing_previous_row(self):
        rows = [
            {
                "citation_id": "ingresso",
                "dispositivo_ref": "Art. 1º",
                "full_text": "O ingresso nos cargos ocorrerá por concurso público.",
                "similarity_score": 1.0,
            },
            {
                "citation_id": "organization",
                "dispositivo_ref": "Art. 2º",
                "full_text": "A Secretaria organiza o programa municipal.",
                "similarity_score": 0.8,
            },
        ]

        selected = _select_facet_sources(rows, ("ingresso", "regularidade da obra"), limit=2)

        self.assertEqual(
            [row["citation_id"] for row in selected],
            ["ingresso", "organization"],
        )

    def test_facet_ranking_prefers_specific_weekly_hours_over_shift_gratuity(self):
        selected = _select_facet_sources(
            [
                {
                    "citation_id": "plantao",
                    "dispositivo_ref": "Art. 26",
                    "full_text": "Gratificação de plantão por doze horas seguidas.",
                    "similarity_score": 1.0,
                },
                {
                    "citation_id": "jornada",
                    "dispositivo_ref": "Art. 21",
                    "full_text": "A carga horária semanal de trabalho dos servidores é de 40 horas.",
                    "similarity_score": 0.2,
                },
            ],
            ("jornada",),
            limit=1,
        )

        self.assertEqual([row["citation_id"] for row in selected], ["jornada"])

    def test_ingresso_facet_recognizes_common_normative_terms(self):
        self.assertTrue(
            _source_matches_facet(
                "ingresso",
                {"full_text": "O ingresso depende de concurso público."},
            )
        )
        self.assertFalse(
            _source_matches_facet(
                "ingresso",
                {"full_text": "Exercício de cargo de provimento em comissão."},
            )
        )

    def test_accessibility_facet_recognizes_plain_language_and_legal_synonyms(self):
        question = (
            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras?"
        )

        self.assertIn("acessibilidade", _requested_topic_facets(question))
        self.assertEqual(_requested_archive_norm_title(question), "codigo de obras")
        self.assertIsNone(_requested_archive_norm_title("Quais exigências de acessibilidade?"))
        self.assertTrue(
            _source_matches_facet(
                "acessibilidade",
                {"full_text": "A rota acessível deve atender às pessoas com deficiência."},
            )
        )
        self.assertTrue(
            _source_matches_facet(
                "acessibilidade",
                {"full_text": "As instalações observarão as necessidades de mobilidade reduzida."},
            )
        )
        self.assertFalse(
            _source_matches_facet(
                "acessibilidade",
                {"full_text": "A expedição do alvará depende de requerimento e taxa."},
            )
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unscoped_accessibility_search_returns_only_directly_supporting_articles(
        self, filter_documents
    ):
        code = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 1º Esta Lei institui o Código de Obras e Edificações do Município.\n"
                "Art. 68 O alvará depende da apresentação do requerimento e das taxas.\n"
                "Art. 167 As dependências de uso coletivo devem garantir acessibilidade, "
                "com rota acessível e condições para pessoas com deficiência."
            ),
        )
        code.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        code.metadata_json["identity_key"] = "BR-RN-NATAL:lei_complementar:258:2024"
        unrelated = _archive_document(
            number="197",
            year=2021,
            legal_text=(
                "Art. 1º As dependências de uso coletivo devem garantir acessibilidade "
                "para pessoas com deficiência.\n"
                "Art. 4º O programa será organizado pela Secretaria Municipal. "
                "O órgão emitirá alvará após o requerimento."
            ),
        )
        unrelated.public_id = "00000000-0000-0000-0000-000000000002"
        _mock_archive_candidates(filter_documents, [code, unrelated])

        rows = retrieve_archive_evidence(
            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal?",
            limit=8,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norma_ref"], "Lei Complementar nº 258/2024")
        self.assertEqual(rows[0]["dispositivo_ref"], "Art. 167")
        self.assertTrue(_source_matches_facet("acessibilidade", rows[0]))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_named_code_search_uses_newest_non_amendment_candidate(self, filter_documents):
        old_code = _archive_document(
            number="55",
            year=2004,
            legal_text=(
                "Art. 1º Institui o Código de Obras e Edificações do Município de Natal.\n"
                "Art. 167 As dependências de uso coletivo devem atender às exigências de acessibilidade."
            ),
        )
        old_code.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        old_code.public_id = "00000000-0000-0000-0000-000000000055"
        new_code = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 1º Esta Lei disciplina as regras para construção, fiscalização e licenciamento urbanístico e ambiental.\n"
                "Art. 2º A aplicação do Código de Obras e Edificações do Município do Natal reger-se-á pelos seguintes princípios.\n"
                "Art. 38 No licenciamento de obras deverá compor o processo atestado do atendimento às regras de acessibilidade.\n"
                "Art. 169 Será admitida margem de tolerância para elementos de acessibilidade."
            ),
        )
        new_code.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        new_code.metadata_json["identity_key"] = "BR-RN-NATAL:lei_complementar:258:2024"
        new_code.public_id = "00000000-0000-0000-0000-000000000258"
        amendment = _archive_document(
            number="173",
            year=2017,
            legal_text=(
                "Art. 1º Altera a Lei Complementar nº 55/2004, Código de Obras e Edificações.\n"
                "Art. 2º Acessibilidade deverá ser considerada nos projetos."
            ),
        )
        amendment.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        amendment.public_id = "00000000-0000-0000-0000-000000000173"
        amended_by_other_law = _archive_document(
            number="7739",
            year=2024,
            legal_text=(
                "Art. 1º Fica alterado o parágrafo único da Lei supramencionada, "
                "considerando as edificações regidas pela Lei Complementar nº 258/2024 "
                "(Código de Obras e Edificações).\n"
                "Art. 2º Esta Lei entra em vigor na data de sua publicação."
            ),
        )
        amended_by_other_law.metadata_json["identity_candidate"]["type"] = "lei_ordinaria"
        amended_by_other_law.public_id = "00000000-0000-0000-0000-000000000739"
        _mock_archive_candidates(
            filter_documents,
            [old_code, amendment, new_code, amended_by_other_law],
        )

        rows = retrieve_archive_evidence(
            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal?",
            limit=8,
        )

        self.assertTrue(rows)
        self.assertEqual({row["norma_ref"] for row in rows}, {"Lei Complementar nº 258/2024"})
        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 38", "Art. 169"},
        )

    def test_plan_name_does_not_count_as_remuneration_evidence(self):
        self.assertFalse(
            _source_matches_facet(
                "remuneração",
                {"full_text": "Plano de cargos, carreiras e vencimentos dos servidores."},
            )
        )

    def test_facet_excerpt_centers_the_supporting_clause(self):
        text = "Preâmbulo genérico. " + ("Texto não relacionado. " * 40)
        text += "A jornada semanal dos servidores será de 40 horas."

        excerpt = _facet_excerpt("jornada", {"full_text": text}, max_chars=140)

        self.assertIn("jornada semanal", excerpt)
        self.assertNotIn("Preâmbulo genérico", excerpt)

    def test_cited_facet_coverage_requires_a_cited_source_for_each_topic(self):
        facets = ("ingresso", "jornada", "remuneração")
        sources = [
            {"citation_id": "one", "full_text": "O ingresso ocorre por concurso."},
            {"citation_id": "two", "full_text": "A jornada semanal será de 40 horas."},
            {"citation_id": "three", "full_text": "A remuneração inclui vencimento básico."},
        ]

        self.assertFalse(
            _has_cited_facet_coverage("A lei trata do ingresso [[1]].", sources, facets)
        )
        self.assertTrue(
            _has_cited_facet_coverage(
                "Ingresso [[1]], jornada [[2]] e remuneração [[3]].", sources, facets
            )
        )

    def test_facet_evidence_map_names_uncovered_topics_without_overclaiming(self):
        facets = ("ingresso", "jornada", "remuneração")
        sources = [
            {
                "citation_id": "qa:jornada",
                "dispositivo_ref": "Art. 21",
                "full_text": "Art. 21. A jornada semanal dos servidores será de 40 horas.",
            }
        ]

        answer, claims = _facet_evidence_map(facets, sources)

        self.assertIn("Quanto a ingresso, não localizei evidência direta", answer)
        self.assertIn("Quanto a jornada, o trecho recuperado dispõe:", answer)
        self.assertIn("Quanto a remuneração, não localizei evidência direta", answer)
        self.assertNotIn("- **", answer)
        self.assertIn("[[1]]", answer)
        self.assertEqual([claim["citation_ids"] for claim in claims], [["qa:jornada"]])

    def test_archive_article_match_requires_both_explicit_norm_identity_and_article(self):
        requested = _explicit_article_norm_pairs(
            "O que prevê o Art. 18 da Lei Complementar nº 120/2010?"
        )
        law_first_requested = _explicit_article_norm_pairs(
            "A Lei Complementar Municipal nº 120/2010, Art. 18, foi alterada ou revogada?"
        )
        sources = [
            {
                "citation_id": "lc120-art18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
            },
            {
                "citation_id": "lc55-art18",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 18",
            },
            {
                "citation_id": "lc120-art17",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17",
            },
        ]

        matched = _matching_archive_article_sources(requested, sources)
        law_first_matched = _matching_archive_article_sources(law_first_requested, sources)

        self.assertEqual([row["citation_id"] for row in matched], ["lc120-art18"])
        self.assertEqual([row["citation_id"] for row in law_first_matched], ["lc120-art18"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_matter_answer_cites_exact_archive_article_and_sapl_records(self, retrieve, lookup):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art18",
                "citation_label": "Lei Complementar nº 120/2010, Art. 18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "evidence_scope": "isolated_qa_archive",
            },
            {
                "citation_id": "qa:lc55-art18",
                "citation_label": "Lei Complementar nº 55/2004, Art. 18",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 18",
                "full_text": "Trecho de outra norma, sem associação explícita à pergunta.",
                "evidence_scope": "isolated_qa_archive",
            },
        ]
        lookup.return_value = [
            {
                "citation_id": "sapl:materia:54742",
                "citation_label": "Projeto de Lei Complementar nº 9/2026",
                "norma_ref": "Projeto de Lei Complementar nº 9/2026",
                "dispositivo_ref": "Matéria legislativa",
                "source_kind": "sapl_legislative_matter",
                "source_type": "Matéria legislativa — registro oficial SAPL",
                "evidence_scope": "official_legislative_matter",
                "contribution": "Ementa e metadados; não comprova vigência.",
                "status_label": "Fora de tramitação no SAPL",
                "consulted_at": "2026-10-09T18:00:00-03:00",
                "consulted_at_label": "09/10/2026 18:00 -03",
                "matter_status": False,
                "matter_result": None,
                "data_publicacao": None,
                "full_text": "Altera a Lei Complementar nº 120/2010.",
                "sapl_url": "https://sapl.natal.rn.leg.br/materia/54742",
            },
            {
                "citation_id": "sapl:materia:54885",
                "citation_label": "Emenda Supressiva nº 1/2026",
                "norma_ref": "Emenda Supressiva nº 1/2026",
                "dispositivo_ref": "Matéria legislativa",
                "source_kind": "sapl_legislative_matter",
                "source_type": "Matéria legislativa — registro oficial SAPL",
                "evidence_scope": "official_legislative_matter",
                "contribution": "Ementa e metadados; não comprova vigência.",
                "status_label": "Fora de tramitação no SAPL",
                "matter_status": False,
                "matter_result": None,
                "data_publicacao": None,
                "full_text": "Suprime o Art. 3º do projeto para preservar o Art. 18 da LC 120/2010.",
                "sapl_url": "https://sapl.natal.rn.leg.br/materia/54885",
            },
        ]

        events = list(
            stream_archive_qa_answer(
                "O PLC 9/2026 e a Emenda Supressiva 1/2026 afetam o Art. 18 da "
                "Lei Complementar nº 120/2010?",
                k=8,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )
        sources = next(event for event in events if event["event"] == "sources")["sources"]
        done = next(event for event in events if event["event"] == "done")

        self.assertEqual(
            [source["citation_id"] for source in sources],
            ["qa:lc120-art18", "sapl:materia:54742", "sapl:materia:54885"],
        )
        self.assertTrue(all(f"[[{index}]]" in done["answer"] for index in (1, 2, 3)))
        self.assertIn("pendente de revisão", done["answer"])
        self.assertIn("não demonstram, por si", done["answer"])
        self.assertIn("Consulta feita ao SAPL em 09/10/2026 18:00 -03", done["answer"])
        self.assertIn("não é a data de atualização do cadastro", done["answer"])
        self.assertNotIn("Trecho de outra norma", done["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.sapl_matter_lookup.lookup_related_matter_result")
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources", return_value=[])
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_exact_article_question_does_not_automatically_add_proposal_sources(
        self, retrieve, _explicit_lookup, related_lookup, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art26",
                "citation_label": "Lei Complementar nº 120/2010, Art. 26",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 26",
                "full_text": (
                    "II – Gratificação de Vigilância Sanitária (GVISA), atribuída aos servidores "
                    "com experiência mínima de dois anos ou especialização, dedicação exclusiva "
                    "e quarenta horas semanais. § 1º É vedada a percepção da GVISA em conjunto "
                    "com qualquer outra gratificação específica da Saúde."
                ),
                "similarity_score": 0.9,
            }
        ]
        related_lookup.return_value = SimpleNamespace(
            status="searched",
            sources=(
                {
                    "citation_id": "sapl:materia:57679",
                    "citation_label": "Projeto de Lei Complementar nº 21/2026",
                    "norma_ref": "Projeto de Lei Complementar nº 21/2026",
                    "dispositivo_ref": "Matéria legislativa",
                    "source_kind": "sapl_legislative_matter",
                    "relation_label": "Lei Complementar nº 120/2010, Art. 26",
                    "contribution": "Cadastro SAPL; não comprova promulgação ou vigência.",
                    "full_text": "Altera o inciso VII para reajustar valores da GEO.",
                    "sapl_url": "https://sapl.natal.rn.leg.br/materia/57679",
                },
            ),
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": (
                    "O inciso II condiciona a GVISA à experiência ou especialização, "
                    "dedicação exclusiva e quarenta horas semanais. [[1]] "
                    "O § 1º veda acumulá-la com outra gratificação específica da Saúde. [[1]]"
                ),
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "source_only": True,
                "generation_attempts": [{"duration_ms": 12}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Quais requisitos o Art. 26 da Lei Complementar nº 120/2010 define para a GVISA "
                "e qual regra de acumulação se aplica?",
                k=8,
                model="qwen3:8b",
                temperature=0,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        related_lookup.assert_not_called()
        sources = next(event for event in events if event["event"] == "sources")["sources"]
        done = next(event for event in events if event["event"] == "done")
        assert [source["citation_id"] for source in sources] == ["qa:lc120-art26"]
        assert "Gratificação de Vigilância Sanitária (GVISA)" in done["answer"]
        assert "É vedada a percepção da GVISA" in done["answer"]
        assert "Altera o inciso VII" not in done["answer"]
        assert "[[2]]" not in done["answer"]
        assert [source["citation_id"] for source in done["sources"]] == ["qa:lc120-art26"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_related_matter_result")
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources", return_value=[])
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_relation_question_automatically_finds_proposal_without_explicit_matter_number(
        self, retrieve, _explicit_lookup, related_lookup
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art59",
                "citation_label": "Lei Complementar nº 258/2024, Art. 59",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 59",
                "full_text": "As inconformidades serão tratadas conforme o Art. 54.",
                "evidence_scope": "isolated_qa_archive",
            }
        ]
        related_lookup.return_value = SimpleNamespace(
            status="searched",
            sources=(
                {
                    "citation_id": "sapl:materia:48759",
                    "citation_label": "Projeto de Lei Complementar nº 12/2025",
                    "norma_ref": "Projeto de Lei Complementar nº 12/2025",
                    "dispositivo_ref": "Matéria legislativa",
                    "source_kind": "sapl_legislative_matter",
                    "source_type": "Matéria legislativa — registro oficial SAPL",
                    "evidence_scope": "official_legislative_matter",
                    "contribution": "Ementa cita expressamente a norma e o dispositivo.",
                    "relation_label": "Lei Complementar nº 258/2024, Art. 59",
                    "status_label": "Em tramitação no SAPL",
                    "consulted_at": "2026-10-09T18:00:00-03:00",
                    "consulted_at_label": "09/10/2026 18:00 -03",
                    "matter_status": True,
                    "matter_result": None,
                    "data_publicacao": None,
                    "matter_updated_at": "2026-10-08T13:08:57-03:00",
                    "full_text": "Altera o art. 59 da Lei Complementar nº 258/2024.",
                    "sapl_url": "https://sapl.natal.rn.leg.br/materia/48759",
                },
            ),
        )

        events = list(
            stream_archive_qa_answer(
                "O texto do Art. 59 da LC nº 258/2024 é atual? Verifique se existe "
                "proposição posterior sobre esse artigo.",
                k=8,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )
        sources = next(event for event in events if event["event"] == "sources")["sources"]
        done = next(event for event in events if event["event"] == "done")

        related_lookup.assert_called_once()
        assert "Art. 59" in related_lookup.call_args.args[0]
        assert [source["citation_id"] for source in sources] == [
            "qa:lc258-art59",
            "sapl:materia:48759",
        ]
        assert "ementa da matéria menciona Lei Complementar nº 258/2024, Art. 59" in done["answer"]
        assert done["answer"].startswith(
            "Com as evidências disponíveis, não foi possível confirmar se o dispositivo "
            "consultado foi alterado ou revogado."
        )
        assert "Em tramitação no SAPL" in done["answer"]
        assert "Última atualização do cadastro informada pelo SAPL" in done["answer"]
        assert (
            "não demonstram, por si, aprovação, promulgação, vigência ou validade" in done["answer"]
        )
        assert "[[1]]" in done["answer"] and "[[2]]" in done["answer"]

        plain_article_question = "O que prevê o Art. 59 da LC nº 258/2024?"
        plain_article_events = list(
            stream_archive_qa_answer(
                plain_article_question,
                k=8,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )
        plain_sources = next(
            event for event in plain_article_events if event["event"] == "sources"
        )["sources"]
        plain_done = next(event for event in plain_article_events if event["event"] == "done")

        related_lookup.assert_called_once()
        assert [source["citation_id"] for source in plain_sources] == ["qa:lc258-art59"]
        assert "No PDF arquivado" in plain_done["answer"]
        assert "Projeto de Lei Complementar nº 12/2025" not in plain_done["answer"]
        assert "Como alerta de conferência" not in plain_done["answer"]
        assert "Em tramitação no SAPL" not in plain_done["answer"]
        assert "[[1]]" in plain_done["answer"] and "[[2]]" not in plain_done["answer"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_related_matter_result")
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources", return_value=[])
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_archive_excerpt_does_not_hide_empty_or_failed_sapl_relation_search(
        self, retrieve, _explicit_lookup, related_lookup
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art59",
                "citation_label": "Lei Complementar nº 258/2024, Art. 59",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 59",
                "full_text": "As inconformidades serão tratadas conforme o Art. 54.",
                "evidence_scope": "isolated_qa_archive",
            }
        ]
        question = (
            "A Lei Complementar Municipal nº 258/2024, Art. 59, é atual? Verifique se existe "
            "proposição posterior sobre esse artigo."
        )

        for status, expected in (
            ("searched", "não encontrou matéria com associação explícita"),
            ("unavailable", "Não foi possível concluir a consulta complementar ao SAPL"),
        ):
            related_lookup.return_value = SimpleNamespace(status=status, sources=())
            events = list(
                stream_archive_qa_answer(
                    question,
                    k=8,
                    model="test-model",
                    temperature=0,
                    text_provider=None,
                    ollama=None,
                )
            )
            done = next(event for event in events if event["event"] == "done")
            assert expected in done["answer"]
            assert (
                "não conclua que inexiste proposição" in done["answer"] or status == "unavailable"
            )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_related_matter_result")
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources", return_value=[])
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_related_matter_answer_renders_original_pdf_without_matter_status(
        self, _retrieve, _explicit_lookup, related_lookup
    ):
        related_lookup.return_value = SimpleNamespace(
            status="partial",
            sources=(
                {
                    "citation_id": "sapl:materia:54885",
                    "citation_label": "Emenda Supressiva nº 1/2026",
                    "source_kind": "sapl_legislative_matter",
                    "full_text": "Suprime o Art. 3º do PLC 9/2026.",
                    "status_label": "Fora de tramitação no SAPL",
                    "matter_result": None,
                    "data_publicacao": None,
                },
                {
                    "citation_id": "sapl:materia:54742",
                    "citation_label": "Projeto de Lei Complementar nº 9/2026",
                    "source_kind": "sapl_legislative_matter",
                    "full_text": "Altera o Anexo I da LC 120/2010.",
                    "status_label": "Fora de tramitação no SAPL",
                    "matter_result": None,
                    "data_publicacao": None,
                },
                {
                    "citation_id": "sapl:materia:54742:texto-original:art-3",
                    "citation_label": "Projeto de Lei Complementar nº 9/2026, Art. 3 (texto proposto)",
                    "source_kind": "sapl_matter_original_pdf",
                    "full_text": "Art. 3º Fica revogado o Art. 18 da Lei Complementar nº 120/2010.",
                    "pdf_url": "https://sapl.natal.rn.leg.br/media/projeto-original.pdf",
                },
            ),
        )

        events = list(
            stream_archive_qa_answer(
                "O texto do Art. 18 da Lei Complementar nº 120/2010 é atual? Verifique se existe "
                "PLC ou proposição posterior sobre esse artigo.",
                k=5,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )

        source_event = next(event for event in events if event["event"] == "sources")
        done = next(event for event in events if event["event"] == "done")
        assert [source["citation_id"] for source in source_event["sources"]] == [
            "sapl:materia:54885",
            "sapl:materia:54742",
            "sapl:materia:54742:texto-original:art-3",
        ]
        assert "como proposta" in done["answer"]
        assert "Fica revogado o Art. 18" in done["answer"]
        assert "não comprova aprovação, promulgação, vigência ou efeito jurídico" in done["answer"]
        assert "Situação no SAPL" in done["answer"]
        assert "[[3]]" in done["answer"]
        assert done["sources"] == source_event["sources"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_explicit_sapl_matter_answer_streams_structured_source_and_unknown_fields(
        self, _retrieve, lookup
    ):
        lookup.return_value = [
            {
                "citation_id": "sapl:materia:54742",
                "citation_label": "Projeto de Lei Complementar nº 9/2026",
                "norma_ref": "Projeto de Lei Complementar nº 9/2026",
                "dispositivo_ref": "Matéria legislativa",
                "source_kind": "sapl_legislative_matter",
                "source_type": "Matéria legislativa — registro oficial SAPL",
                "evidence_scope": "official_legislative_matter",
                "contribution": "Ementa e metadados; não é norma promulgada.",
                "status_label": "Fora de tramitação no SAPL",
                "matter_status": False,
                "matter_result": None,
                "data_publicacao": None,
                "full_text": "Dispõe sobre tema público.",
                "sapl_url": "https://sapl.natal.rn.leg.br/materia/54742",
                "_matter_id": 54742,
                "_original_document": {
                    "citation_id": "sapl:materia:54742:texto-original",
                    "citation_label": "Projeto de Lei Complementar nº 9/2026, Texto Original",
                    "norma_ref": "Projeto de Lei Complementar nº 9/2026",
                    "dispositivo_ref": "Texto Original — redação proposta",
                    "source_kind": "sapl_matter_original_pdf",
                    "source_type": "Texto original da proposição — PDF oficial SAPL",
                    "evidence_scope": "official_legislative_matter_document",
                    "contribution": "Redação proposta; não é norma promulgada.",
                    "full_text": "Art. 59. A redação proposta altera o texto anterior.",
                    "pdf_url": "https://sapl.natal.rn.leg.br/media/original.pdf",
                    "sapl_url": "https://sapl.natal.rn.leg.br/materia/54742",
                    "matter_id": 54742,
                },
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Qual é a redação nova proposta pelo PLC 9/2026?",
                k=5,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )

        source_event = next(event for event in events if event["event"] == "sources")
        done = next(event for event in events if event["event"] == "done")
        assert source_event["sources"][0]["source_kind"] == "sapl_legislative_matter"
        assert source_event["sources"][1]["source_kind"] == "sapl_matter_original_pdf"
        assert "[[1]]" in done["answer"]
        assert "Art. 59. A redação proposta altera o texto anterior." in done["answer"]
        assert "[[2]]" in done["answer"]
        assert done["sources"] == source_event["sources"]
        assert "Resultado e data de publicação não informados no cadastro." in done["answer"]
        assert (
            "proposta legislativa, não uma norma promulgada nem prova de vigência" in done["answer"]
        )
        assert "não demonstram, por si" in done["answer"]
        _retrieve.assert_not_called()

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, SAPL_MATTER_LOOKUP_ENABLED=True)
    @patch("src.processing.sapl_matter_lookup.lookup_explicit_matter_sources", return_value=[])
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_proposed_bill_text_abstains_without_scanning_unrelated_archive(
        self, retrieve, matter_lookup
    ):
        events = list(
            stream_archive_qa_answer(
                "Qual é a redação proposta no Art. 59 do PLC 12/2025? "
                "Se o anexo oficial não estiver disponível, informe essa lacuna; "
                "não trate a proposta como lei vigente.",
                k=8,
                model="test-model",
                temperature=0,
                text_provider=None,
                ollama=None,
            )
        )

        source_event = next(event for event in events if event["event"] == "sources")
        done = next(event for event in events if event["event"] == "done")
        matter_lookup.assert_called_once()
        retrieve.assert_not_called()
        assert source_event["sources"] == []
        assert source_event["coverage"]["unrelated_archive_search_skipped"] is True
        assert done["reason_code"] == "explicit_matter_source_unavailable"
        assert done["grounded"] is False
        assert "fonte oficial verificável" in done["answer"]
        assert "não vou inferir o conteúdo" in done["answer"]
        assert "proposta como lei vigente" in done["answer"]

    def test_shared_norm_reference_pairs_only_explicitly_coordinated_articles(self):
        question = "O que estabelecem o Art. 262 e o Art. 260, IV, da Lei Complementar nº 258/2024?"

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual([article for _identity, article in pairs], ["262", "260"])
        self.assertEqual(pairs[0][0], pairs[1][0])
        self.assertEqual(
            _explicit_article_norm_pairs(
                "O que estabelecem o Art. 262. E o Art. 260, IV, da LC 258/2024?"
            ),
            ((("lei_complementar", "258", 2024), "260"),),
        )

    def test_plural_article_list_pairs_every_article_to_its_explicit_norm(self):
        question = (
            "No Código de Obras da Lei Complementar nº 258/2024, o que dizem os arts. "
            "259, 260 e 262 sobre processos anteriores e revogação da LC 55/2004?"
        )

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual(
            pairs,
            (
                (("lei_complementar", "258", 2024), "259"),
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "258", 2024), "262"),
            ),
        )
        self.assertFalse(_has_ambiguous_multi_norm_article_scope(question))

    def test_qualified_plural_article_list_pairs_every_article_to_its_norm(self):
        question = (
            "O que estabelecem os arts. 260, inciso IV, e 262 da Lei Complementar nº 258/2024?"
        )

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual(
            pairs,
            (
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "258", 2024), "262"),
            ),
        )

    def test_repeal_and_transition_relation_pairs_final_article_to_repealing_norm(self):
        question = (
            "Como o Art. 260, inciso IV, da LC 258/2024, que revoga a LC 55/2004, "
            "se articula com a regra de transição do Art. 262? O que o procurador "
            "precisa verificar nos autos, sem presumir fatos do processo?"
        )

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual(
            pairs,
            (
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "258", 2024), "262"),
            ),
        )
        self.assertFalse(_has_ambiguous_multi_norm_article_scope(question))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_repeal_transition_synthesis_uses_both_pending_pdf_articles_without_overclaiming(
        self, retrieve, generate
    ):
        question = (
            "Como o Art. 260, inciso IV, da LC 258/2024, que revoga a LC 55/2004, "
            "se articula com a regra de transição do Art. 262? O que o procurador "
            "precisa verificar nos autos, sem presumir fatos do processo?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art260",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260, inciso IV",
                "full_text": ("Art. 260. Ficam revogadas: IV — a Lei Complementar nº 55/2004."),
                "texto": "Ficam revogadas a Lei Complementar nº 55/2004.",
                "coverage": {"complete": False},
                "similarity_score": 0.95,
            },
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": (
                    "Art. 262. Os processos de licenciamento de obras e edificações "
                    "protocolados até a data de entrada em vigor desta Lei e sem despacho "
                    "decisório serão apreciados integralmente de acordo com a legislação "
                    "em vigor à época do protocolo, exceto nos casos de manifestação formal "
                    "do interessado, optando pela análise integral nos termos desta Lei."
                ),
                "texto": "Os processos de licenciamento protocolados até a entrada em vigor...",
                "coverage": {"complete": False},
                "similarity_score": 0.94,
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = next(event for event in events if event.get("event") == "done")
        answer = final["answer"]
        self.assertEqual(final["reason_code"], "qa_archive_repeal_transition_text_synthesis")
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "archive_repeal_transition_text_only_no_case_adjudication",
        )
        self.assertIn("Lei Complementar nº 55/2004", answer)
        self.assertIn("Art. 262", answer)
        self.assertIn("data do protocolo", answer)
        self.assertIn("despacho decisório", answer)
        self.assertIn("manifestação formal", answer)
        self.assertIn("pendente de revisão", answer)
        self.assertIn("não determinam, por si sós, o regime aplicável", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("[[2]]", answer)
        self.assertEqual(final["sources"], retrieve.return_value)

    def test_consider_also_follow_up_articles_inherit_last_norm_named_in_previous_question(self):
        question = (
            "Estou conferindo uma fundamentação antiga que usa o Art. 21 da Lei Complementar nº "
            "55/2004. A LC 258/2024 menciona esse artigo? Considere também o Art. 260, inciso IV, "
            "e o Art. 262. Explique o que cada dispositivo informa."
        )

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual(
            pairs,
            (
                (("lei_complementar", "55", 2004), "21"),
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "258", 2024), "262"),
            ),
        )
        self.assertFalse(_has_ambiguous_multi_norm_article_scope(question))

    def test_repeated_article_follow_up_keeps_its_single_explicit_norm_identity(self):
        question = (
            "Estou conferindo uma fundamentação antiga que usa o Art. 21 da Lei Complementar nº "
            "55/2004. A LC 258/2024 menciona esse artigo? Considere também o Art. 260, inciso IV, "
            "e o Art. 262. Explique o que cada dispositivo informa e se o Art. 21 ainda se aplica."
        )

        pairs = _explicit_article_norm_pairs(question)

        self.assertEqual(
            pairs,
            (
                (("lei_complementar", "55", 2004), "21"),
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "258", 2024), "262"),
                (("lei_complementar", "55", 2004), "21"),
            ),
        )
        self.assertFalse(_has_ambiguous_multi_norm_article_scope(question))

    def test_multi_norm_style_instruction_requires_explicit_article_norm_pairing(self):
        question = (
            "O que estabelece o Art. 262 da Lei Complementar nº 258/2024 para processos "
            "sem despacho? Considere também o Art. 260, IV, da Lei Complementar nº 258/2024, "
            "que revoga a Lei Complementar nº 55/2004. O Art. 21 da LC 55/2004 continua vigente?"
        )
        instruction = _multi_norm_synthesis_instruction(question)

        self.assertIn("em até dois parágrafos", instruction)
        self.assertIn("nem repita aberturas como ‘No PDF local’", instruction)
        self.assertIn("regra de transição", instruction)
        self.assertIn("prova de vigência atual", instruction)
        self.assertEqual(
            _multi_norm_synthesis_instruction(
                "O que prevê o Art. 21 da Lei Complementar nº 55/2004?"
            ),
            "",
        )

    def test_archive_transition_synthesis_requires_repeal_transition_and_old_article_evidence(self):
        question = (
            "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem "
            "despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda "
            "pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024."
        )
        sources = [
            {
                "citation_id": "qa:lc258-art260",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260",
                "full_text": (
                    "Ficam revogados: IV - Lei Complementar nº 055 de 27 de janeiro de 2004."
                ),
            },
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": (
                    "Os processos de licenciamento protocolados até a data de entrada em vigor "
                    "desta Lei e sem despacho decisório serão apreciados integralmente de acordo "
                    "com a legislação em vigor à época do protocolo, exceto nos casos de "
                    "manifestação formal do interessado, optando pela análise integral nos termos desta Lei."
                ),
            },
            {
                "citation_id": "qa:lc55-art21",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 21",
                "full_text": (
                    "Toda obra só pode começar após o licenciamento municipal. O § 1º prevê "
                    "prazo para aprovação dos projetos e o § 3º trata dos efeitos do decurso "
                    "desse prazo sem conclusão."
                ),
            },
            {
                "citation_id": "qa:lc258-art266",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "full_text": "Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação.",
            },
        ]

        result = _archive_transition_synthesis(question, sources)

        self.assertIsNotNone(result)
        answer, claims = result
        self.assertIn("lista expressamente", answer)
        self.assertIn("manifestação formal", answer)
        self.assertIn("Para o cenário descrito", answer)
        self.assertIn("pode ser considerada nesse regime transitório", answer)
        self.assertIn("se integrava a legislação vigente na data do protocolo", answer)
        self.assertIn("não valida os fatos de um processo real", answer)
        self.assertNotIn("No PDF local", answer)
        self.assertNotIn("Art. 260", answer)
        self.assertNotIn("Art. 262", answer)
        self.assertNotIn("Art. 21", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("[[2]]", answer)
        self.assertIn("[[3]]", answer)
        self.assertNotIn("Art. 266", answer)
        self.assertIn("[[4]]", answer)
        self.assertEqual(
            [claim["citation_ids"] for claim in claims],
            [["qa:lc258-art260"], ["qa:lc258-art262"], ["qa:lc55-art21"], ["qa:lc258-art266"]],
        )

        without_transition = [
            sources[0],
            {**sources[1], "full_text": "Artigo sobre vigência."},
            sources[2],
        ]
        self.assertIsNone(_archive_transition_synthesis(question, without_transition))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._official_sapl_publication_source")
    @patch("src.processing.qa_archive_rag._official_dom_articles_sources")
    def test_archive_transition_question_streams_concise_three_source_synthesis_without_llm(
        self, dom_article_lookup, publication_lookup, retrieve, generate
    ):
        question = (
            "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem "
            "despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda "
            "pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art260",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260",
                "full_text": "Ficam revogados: IV - Lei Complementar nº 055 de 27 de janeiro de 2004.",
                "source_kind": "archive",
            },
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": "Os processos de licenciamento protocolados até a data de entrada em vigor "
                "desta Lei e sem despacho decisório serão apreciados integralmente de acordo "
                "com a legislação em vigor à época do protocolo, exceto nos casos de "
                "manifestação formal do interessado, optando pela análise integral nos termos desta Lei.",
                "source_kind": "archive",
            },
            {
                "citation_id": "qa:lc55-art21",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 21",
                "full_text": "Toda obra só pode começar após o licenciamento municipal. O § 1º prevê "
                "prazo para aprovação dos projetos e o § 3º trata dos efeitos do decurso "
                "desse prazo sem conclusão.",
            },
            {
                "citation_id": "qa:lc258-art266",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "full_text": (
                    "Esta Lei Complementar entra em vigor 90 (noventa) dias após a data de sua publicação."
                ),
                "source_kind": "archive",
            },
        ]
        publication_lookup.return_value = {
            "citation_id": "sapl:publication-metadata:4052",
            "data_publicacao": "2024-12-27",
        }
        dom_article_lookup.return_value = [
            {
                "citation_id": "dom:lc258-art260-official",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260",
                "source_kind": "official_gazette_extraction",
                "data_publicacao": "2024-12-27",
                "full_text": "Art. 260. Ficam revogados: IV — Lei Complementar nº 55/2004.",
            },
            {
                "citation_id": "dom:lc258-art262-official",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "source_kind": "official_gazette_extraction",
                "data_publicacao": "2024-12-27",
                "full_text": (
                    "Art. 262. Os processos de licenciamento protocolados até a data de entrada "
                    "em vigor desta Lei e sem despacho decisório serão apreciados integralmente "
                    "de acordo com a legislação em vigor à época do protocolo, salvo manifestação formal."
                ),
            },
            {
                "citation_id": "dom:lc258-art266-official",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "source_kind": "official_gazette_extraction",
                "data_publicacao": "2024-12-27",
                "full_text": (
                    "Art. 266. Esta Lei Complementar entra em vigor 90 (noventa) dias "
                    "após a data de sua publicação."
                ),
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        answer = events[-1]
        self.assertEqual(answer["reason_code"], "qa_archive_transition_relation_synthesis")
        self.assertTrue(answer["grounding"]["grounded"])
        self.assertEqual(len(answer["grounding"]["claims"]), 5, answer["answer"])
        self.assertIn("se integrava a legislação vigente na data do protocolo", answer["answer"])
        self.assertIn("manifestação formal do interessado", answer["answer"])
        self.assertIn("extração ainda pendente de revisão", answer["answer"])
        self.assertIn("confira o texto oficial e o histórico do dispositivo", answer["answer"])
        self.assertIn("não valida os fatos de um processo real", answer["answer"])
        self.assertIn("27/12/2024", answer["answer"])
        self.assertIn("27/03/2025", answer["answer"])
        source_event = next(event for event in events if event["event"] == "sources")
        self.assertTrue(
            all(source in source_event["sources"] for source in dom_article_lookup.return_value)
        )
        self.assertTrue(
            any(
                source.get("evidence_scope") == "official_vacatio_counting_rule"
                for source in source_event["sources"]
            )
        )
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer["answer"],
        )

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._official_sapl_publication_source")
    def test_explicit_temporal_pair_adds_exact_historical_work_licensing_device(
        self, publication_metadata_lookup, retrieve, generate, relation_candidates
    ):
        question = (
            "A Lei Complementar nº 258/2024 revoga a Lei Complementar nº 55/2004? "
            "Em processo de licenciamento de obra protocolado em 20/03/2025 e sem despacho "
            "em 27/03/2025, quais evidências tratam da regra de transição e da entrada em vigor?"
        )
        relation_candidate = {
            "citation_id": "qa:lc258-art260-iv-candidate",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260, inciso IV",
            "citation_label": "LC 258/2024, Art. 260, IV",
            "full_text": "IV — Lei Complementar nº 55/2004.",
            "action_quote": "Ficam revogados",
            "target_text": "Lei Complementar nº 55/2004",
            "relation_action_candidate": "REVOGA",
            "relation_candidate": {
                "fingerprint": "lc258-art260-iv-lc55",
                "action": "REVOGA",
                "target_identity": {
                    "type": "lei_complementar",
                    "number": "55",
                    "year": 2004,
                },
            },
        }
        relation_candidates.return_value = [relation_candidate]
        lc258_repeal = {
            "citation_id": "qa:lc258-art260",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260",
            "full_text": "Ficam revogados: IV — Lei Complementar nº 55/2004.",
        }
        irrelevant_licensing_article = {
            "citation_id": "qa:lc258-art241-unrelated",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 241",
            "full_text": (
                "A suspensão de embargo depende de termo de compromisso e de análise preliminar "
                "do processo de licenciamento da obra."
            ),
        }
        lc258_transition = {
            "citation_id": "qa:lc258-art262",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 262",
            "full_text": (
                "Os processos de licenciamento de obras e edificações protocolados até a data "
                "de entrada em vigor desta Lei e sem despacho decisório serão apreciados "
                "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
                "nos casos de manifestação formal do interessado, optando pela análise integral "
                "nos termos desta Lei."
            ),
        }
        lc258_commencement = {
            "citation_id": "qa:lc258-art266",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 266",
            "full_text": (
                "Esta Lei Complementar entra em vigor 90 (noventa) dias após a data de sua publicação."
            ),
            "source_kind": "archive",
            "document_id": "doc:lc258",
        }
        publication_metadata_lookup.return_value = {
            "citation_id": "sapl:publication-metadata:4052",
            "citation_label": "Lei Complementar nº 258/2024 — data de publicação no SAPL",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Metadado de publicação",
            "source_kind": "sapl_publication_metadata",
            "full_text": "O cadastro oficial do SAPL registra publicação em 27/12/2024. Veículo registrado: DOM.",
            "data_publicacao": "2024-12-27",
            "source_url": "https://sapl.natal.rn.leg.br/norma/4052",
        }
        lc55_art21 = {
            "citation_id": "qa:lc55-art21-exact",
            "norma_ref": "Lei Complementar nº 55/2004",
            "dispositivo_ref": "Art. 21",
            "full_text": (
                "Toda e qualquer obra e/ou serviço só pode ser iniciado após obter "
                "licenciamento pelo Município, através da expedição do respectivo Alvará de construção."
            ),
            "coverage": {"epigraph_identity_status": "match", "identity_conflict": False},
        }
        unresolved_duplicate = {
            **lc55_art21,
            "citation_id": "qa:lc55-art21-unresolved-copy",
            "coverage": {"epigraph_identity_status": "unresolved", "identity_conflict": False},
        }

        def retrieve_for_query(query, *, limit):
            if "Qual dispositivo da Lei Complementar nº 55/2004" in query:
                return [unresolved_duplicate, lc55_art21]
            if "determina quando esta Lei Complementar entra em vigor" in query:
                return [lc258_commencement]
            if "Quais dispositivos da Lei Complementar nº 258/2024" in query:
                return [lc258_transition, lc258_commencement]
            return [lc258_repeal, irrelevant_licensing_article]

        retrieve.side_effect = retrieve_for_query
        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = next(event for event in events if event.get("event") == "done")
        self.assertIn(lc55_art21, final["sources"])
        self.assertNotIn(unresolved_duplicate, final["sources"])
        self.assertNotIn(irrelevant_licensing_article, final["sources"])
        self.assertIn("Lei Complementar nº 55/2004", final["answer"])
        self.assertIn("Art. 21", final["answer"])
        self.assertIn("não prova de que ela vigorava na data do protocolo", final["answer"])
        self.assertIn("Art. 262", final["answer"])
        self.assertIn("Art. 266", final["answer"])
        self.assertIn("27/12/2024", final["answer"])
        self.assertIn("27/03/2025", final["answer"])
        self.assertIn("Art. 8º, § 1º, da LC nº 95/1998", final["answer"])
        self.assertIn("sapl:publication-metadata:4052", [s["citation_id"] for s in final["sources"]])
        self.assertIn("official:lc95-art8-paragraph1", [s["citation_id"] for s in final["sources"]])
        self.assertIn("temporalmente compatíveis com as condições descritas no Art. 262", final["answer"])
        self.assertIn("Isso não basta para decidir o processo", final["answer"])
        self.assertTrue(
            any(
                "Qual dispositivo da Lei Complementar nº 55/2004" in call.args[0]
                for call in retrieve.call_args_list
            )
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_multi_norm_generation_receives_relational_style_contract(self, retrieve, generate):
        retrieve.return_value = [
            {
                "citation_id": f"qa:multi-norm-{article}",
                "norma_ref": norma,
                "dispositivo_ref": f"Art. {article}",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.9,
                "coverage": {"complete": False},
            }
            for article, norma, text in (
                (260, "Lei Complementar nº 258/2024", "Art. 260 revoga a LC 55/2004."),
                (262, "Lei Complementar nº 258/2024", "Art. 262 preserva regra temporal."),
                (21, "Lei Complementar nº 55/2004", "Art. 21 disciplina o licenciamento."),
            )
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "A relação está delimitada pelos dispositivos citados. [[1]] [[2]] [[3]]",
                "grounding": {"grounded": False, "failed_claims": ["unverified"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )
        question = (
            "O que estabelece o Art. 262 da Lei Complementar nº 258/2024? Considere o Art. 260, "
            "IV, da Lei Complementar nº 258/2024 e o Art. 21 da LC 55/2004."
        )

        list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        prompt = generate.call_args.args[0]
        self.assertIn("INSTRUÇÃO ESPECÍFICA — ARTIGOS DE MAIS DE UMA NORMA", prompt)
        self.assertIn("em até dois parágrafos", prompt)
        self.assertIn("regra de transição", prompt)
        self.assertIn("prova de vigência atual", prompt)

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

    def test_partial_overview_fallback_formats_verbatim_evidence_as_list(self):
        entries = _partial_overview_evidence_narrative(
            [
                {
                    "device": f"Art. {article}º",
                    "text": f"Art. {article}º conteúdo literal.",
                    "citation_index": article,
                }
                for article in (1, 2, 3, 4)
            ]
        )

        self.assertEqual(len(entries), 4)
        self.assertTrue(all(entry.startswith("- “") for entry in entries))
        self.assertIn("Art. 1º conteúdo literal.", entries[0])
        self.assertIn("[[1]]", entries[0])
        self.assertIn("Art. 4º conteúdo literal.", entries[3])
        self.assertIn("[[4]]", entries[3])
        self.assertFalse(any("O dispositivo registra:" in entry for entry in entries))
        self.assertEqual(
            [re.findall(r"\[\[(\d+)\]\]", entry) for entry in entries],
            [["1"], ["2"], ["3"], ["4"]],
        )

    def test_partial_overview_triage_checklist_is_explicit_and_not_attributed_to_the_norm(self):
        checklist = _partial_overview_triage_checklist(
            "Quais três cautelas devo observar antes de aplicar esses excertos a um processo?"
        )

        self.assertIsNotNone(checklist)
        self.assertIn("não como requisitos atribuídos a esta lei", checklist)
        self.assertIn("**Texto e vigência:**", checklist)
        self.assertIn("**Fatos e estágio dos autos:**", checklist)
        self.assertIn("**Contexto normativo:**", checklist)
        self.assertEqual(checklist.count("\n1."), 1)
        self.assertEqual(checklist.count("\n2."), 1)
        self.assertEqual(checklist.count("\n3."), 1)
        self.assertIsNone(
            _partial_overview_triage_checklist(
                "O que prevê, em linhas gerais, a Lei Complementar nº 258/2024?"
            )
        )

    def test_partial_overview_requires_distinct_valid_sources_but_allows_repeated_markers(self):
        self.assertTrue(
            _has_partial_overview_breadth(
                "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[3]]",
                6,
                available_sample_sources=3,
            )
        )
        self.assertFalse(
            _has_partial_overview_breadth(
                "Uma afirmação. [[1]] Outra afirmação. [[1]] Terceira afirmação. [[3]]",
                6,
                available_sample_sources=3,
            )
        )
        self.assertTrue(
            _has_partial_overview_breadth(
                "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[3]] "
                "Quarta afirmação. [[1]] Quinta afirmação. [[4]]",
                6,
                available_sample_sources=4,
            )
        )
        self.assertFalse(
            _has_partial_overview_breadth(
                "Uma afirmação. [[1]] Outra afirmação. [[2]] Terceira afirmação. [[9]]",
                6,
                available_sample_sources=3,
            )
        )

    def test_partial_overview_allows_resolved_markers_and_rejects_visible_article_mismatch(self):
        sources = [
            {"dispositivo_ref": "Art. 1º"},
            {"dispositivo_ref": "Art. 10º"},
            {"dispositivo_ref": "Art. 19º"},
        ]
        self.assertTrue(
            _has_partial_overview_breadth(
                "O Art. 1º institui a regra. [[1]] O artigo 10º prevê o critério. [[2]] "
                "O Art. 19º trata da execução. [[3]]",
                3,
                available_sample_sources=3,
                sources=sources,
            )
        )
        self.assertTrue(
            _has_partial_overview_breadth(
                "A regra é instituída aqui. [[1]] O Art. 10º prevê o critério. [[2]] "
                "O Art. 19º trata da execução. [[3]]",
                3,
                available_sample_sources=3,
                sources=sources,
            )
        )
        self.assertFalse(
            _has_partial_overview_breadth(
                "O Art. 10º institui a regra. [[1]] O Art. 10º prevê o critério. [[2]] "
                "O Art. 19º trata da execução. [[3]]",
                3,
                available_sample_sources=3,
                sources=sources,
            )
        )
        self.assertTrue(
            _has_partial_overview_breadth(
                "O Art. 1º institui e organiza a regra [[1]], com previsão adicional [[1]]. "
                "O Art. 10º define o critério [[2]]. O Art. 19º trata da execução [[3]].",
                3,
                available_sample_sources=3,
                sources=sources,
            )
        )

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

    def test_topical_evidence_map_selects_the_specific_term_not_spread_samples(self):
        question = (
            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal? "
            "Resuma apenas o que os dispositivos recuperados dizem, cite cada artigo e explique "
            "o que ainda não se pode concluir sobre uma obra específica."
        )
        sources = [
            {
                "citation_id": f"qa:topic-{index}",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": f"Art. {index}º",
                "full_text": f"Art. {index}º disposição sem relação direta com o tema.",
            }
            for index in range(1, 13)
        ]
        sources[2]["full_text"] = (
            "Art. 3º Para os fins desta Lei considera-se: abertura destinada à ventilação "
            "e iluminação de edificações."
        )
        sources[6].update(
            {
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 68",
                "full_text": "Art. 68 O alvará depende do atendimento às seguintes condições.",
            }
        )
        sources[11].update(
            {
                "dispositivo_ref": "Art. 167",
                "full_text": (
                    "Art. 167 O gabarito máximo permitido para edificação residencial é de "
                    "quatro pavimentos. Atendidas também, as exigências de acessibilidade "
                    "às dependências de uso coletivo."
                ),
            }
        )

        excerpts = _partial_overview_excerpts(
            sources,
            limit=3,
            max_chars=120,
            question=question,
            topical_only=True,
        )

        self.assertEqual([row["device"] for row in excerpts], ["Art. 167"])
        self.assertIn("acessibilidade", excerpts[0]["text"])
        self.assertNotIn("Art. 3º", [row["device"] for row in excerpts])
        self.assertNotIn("Art. 68", [row["device"] for row in excerpts])

    def test_topical_evidence_map_respects_excerpt_limit_when_many_sources_match(self):
        sources = [
            {
                "citation_id": f"qa:cosip-{index}",
                "dispositivo_ref": f"Art. {index}º",
                "full_text": (
                    f"Art. {index}º A COSIP incidente sobre unidades imobiliárias "
                    "não edificadas pode ser recolhida em parcelas."
                ),
            }
            for index in range(1, 6)
        ]

        excerpts = _partial_overview_excerpts(
            sources,
            limit=2,
            question="Quais regras de recolhimento da COSIP incidem sobre unidades imobiliárias não edificadas?",
            topical_only=True,
        )

        self.assertEqual(len(excerpts), 2)
        self.assertEqual([item["citation_index"] for item in excerpts], [1, 2])

    def test_topical_evidence_map_returns_no_excerpt_without_its_specific_subject(self):
        excerpts = _partial_overview_excerpts(
            [
                {
                    "citation_id": "qa:generic-building-definition",
                    "dispositivo_ref": "Art. 3º",
                    "full_text": "Art. 3º Para os fins desta Lei, consideram-se edificações os prédios destinados ao uso público.",
                },
                {
                    "citation_id": "qa:permit-conditions",
                    "dispositivo_ref": "Art. 68",
                    "full_text": "Art. 68 O alvará será emitido mediante atendimento às condições previstas.",
                },
            ],
            limit=3,
            question=(
                "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal? "
                "Resuma apenas os dispositivos recuperados."
            ),
            topical_only=True,
        )

        self.assertEqual(excerpts, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_rejected_thematic_answer_abstains_instead_of_citing_peripheral_articles(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:definitions",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 3º",
                "full_text": "Art. 3º Para os fins desta Lei considera-se edificação o prédio destinado ao uso público.",
                "similarity_score": 0.8,
            },
            {
                "citation_id": "qa:permit",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 68",
                "full_text": "Art. 68 O alvará será emitido mediante atendimento às condições previstas.",
                "similarity_score": 0.7,
            },
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "As normas exigem acessibilidade nas edificações. [[1]]",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        final = list(
            stream_archive_qa_answer(
                "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )[-1]

        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [])
        self.assertEqual(final["reason_code"], "qa_archive_topical_evidence_insufficient")
        self.assertIn("Não encontrei evidência direta suficiente", final["answer"])
        self.assertIn("não vou associar fontes", final["answer"])
        self.assertNotIn("[[1]]", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_thematic_fallback_separates_norms_and_explains_case_specific_limits(
        self, retrieve, generate
    ):
        question = (
            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal? "
            "Resuma apenas o que os dispositivos recuperados dizem, cite cada artigo e explique "
            "o que ainda não se pode concluir sobre uma obra específica."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc55-accessibility",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 167",
                "full_text": (
                    "Art. 167 As dependências de uso coletivo devem atender às exigências "
                    "de acessibilidade."
                ),
                "similarity_score": 0.9,
            },
            {
                "citation_id": "qa:lc258-accessibility",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 169",
                "full_text": (
                    "Art. 169 Elementos de acessibilidade incluem barras de apoio, rampas, "
                    "corrimãos e vãos de portas, conforme normas técnicas."
                ),
                "similarity_score": 0.8,
            },
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "As normas exigem acessibilidade para toda edificação. [[1]]",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        final = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )[-1]

        self.assertTrue(final["grounded"])
        self.assertEqual(len(final["sources"]), 2)
        self.assertIn("normas distintas", final["answer"])
        self.assertIn("Lei Complementar nº 55/2004", final["answer"])
        self.assertIn("Lei Complementar nº 258/2024", final["answer"])
        self.assertIn("não permitem concluir se uma obra específica", final["answer"])
        self.assertIn("redação oficial aplicável", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])

    def test_whole_norm_selection_keeps_all_articles_when_they_fit_budget(self):
        rows = [
            {"dispositivo_ref": f"Art. {article}º", "full_text": "x" * 300}
            for article in range(1, 40)
        ]

        selected, total = _sample_whole_norm_rows(rows)

        self.assertEqual(total, 39)
        self.assertEqual(selected, rows)

    def test_whole_norm_selection_keeps_39_article_law_at_observed_size(self):
        # Mirrors the aggregate-only QA diagnostic: 39 articles / 29,222 chars.
        rows = [
            {
                "dispositivo_ref": f"Art. {article}º",
                "full_text": "x" * (722 if article == 39 else 750),
            }
            for article in range(1, 40)
        ]

        selected, total = _sample_whole_norm_rows(rows)

        self.assertEqual(sum(len(row["full_text"]) for row in rows), 29_222)
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
        self.assertLessEqual(
            sum(len(row["full_text"]) for row in selected),
            _WHOLE_NORM_CONTEXT_BUDGET_CHARS,
        )
        self.assertEqual(selected[0]["dispositivo_ref"], "Art. 1º")
        self.assertEqual(selected[-1]["dispositivo_ref"], "Art. 39º")

    def test_whole_norm_practical_scope_extracts_only_substantive_topic_terms(self):
        question = (
            "Faça uma síntese curta da Lei Complementar nº 258/2024 para triagem inicial "
            "de um processo de licenciamento: quais assuntos e dispositivos do PDF são "
            "relevantes, e o que não posso concluir sem conferir os autos e a publicação oficial?"
        )

        self.assertEqual(_whole_norm_topic_tokens(question), {"licenciamento"})

        procedural_question = (
            "Quais etapas do licenciamento de obras a LC nº 258/2024 prevê? Faça uma síntese "
            "dos dispositivos pertinentes e diga quais documentos ou fatos do processo eu "
            "teria de conferir antes de orientar um caso concreto."
        )
        self.assertEqual(_whole_norm_topic_tokens(procedural_question), {"licenciamento", "obras"})

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_norm_organization_overview_uses_multiple_topically_relevant_articles(
        self, filter_documents
    ):
        articles = []
        padding = " Regras gerais de organização administrativa e procedimentos municipais." * 12
        for article in range(1, 41):
            if article == 3:
                topic = " O licenciamento de obras exige análise do projeto e atendimento aos parâmetros urbanísticos."
            elif article == 17:
                topic = " No licenciamento de obras, a documentação técnica deve ser apresentada pelo interessado."
            elif article == 31:
                topic = " A fiscalização acompanha obras licenciadas e verifica o cumprimento das condições."
            elif article == 20:
                topic = " A abertura voltada para o exterior deve observar iluminação e ventilação."
            else:
                topic = " A administração municipal observará seus procedimentos internos."
            articles.append(f"Art. {article}º{topic}{padding}")
        document = _archive_document(
            number="258",
            year=2024,
            legal_text="\n".join(articles),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL:lei_complementar:258:2024"
        _mock_archive_candidates(filter_documents, [document])
        question = (
            "Em linhas gerais, como a LC nº 258/2024 organiza o licenciamento de obras e "
            "quais três cautelas um procurador deve observar antes de aplicar esses excertos a um processo?"
        )

        rows = retrieve_archive_evidence(question, limit=8)

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 3º", "Art. 17º", "Art. 31º"},
        )
        self.assertTrue(
            all(row["coverage"]["selection_strategy"] == "topic_ranked" for row in rows)
        )
        self.assertTrue(all(row["coverage"]["selected_articles"] == 3 for row in rows))

        procedural_question = (
            "Quais etapas do licenciamento de obras a LC nº 258/2024 prevê? Faça uma síntese "
            "dos dispositivos pertinentes e diga quais documentos ou fatos do processo eu "
            "teria de conferir antes de orientar um caso concreto."
        )
        procedural_plan = classify_normative_query(procedural_question)
        procedural_rows = retrieve_archive_evidence(procedural_question, limit=8)

        self.assertEqual(procedural_plan.kind, "norma_overview")
        self.assertTrue(procedural_plan.broad_topical_scope)
        self.assertEqual(
            {row["dispositivo_ref"] for row in procedural_rows},
            {"Art. 3º", "Art. 17º", "Art. 31º"},
        )
        self.assertTrue(
            all(row["coverage"]["selection_strategy"] == "topic_ranked" for row in procedural_rows)
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_natural_multifacet_retrieval_keeps_object_notice_and_transition_articles(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 1º Esta Lei Complementar institui o Código de Obras e Edificações.\n"
                "Art. 2º A aplicação do Código de Obras e Edificações do Município do Natal "
                "\nreger-se-á pelos seguintes objetivos e princípios: simplificação do "
                "licenciamento, proteção do ambiente urbano e segurança dos usuários.\n"
                "Art. 22. A análise poderá exigir correções, esclarecimentos e/ou "
                "complementações, com notificação ao interessado.\n"
                "Art. 262. Os processos protocolados antes da entrada em vigor desta Lei e "
                "sem despacho decisório serão apreciados conforme a legislação da época do "
                "protocolo, ressalvada manifestação formal do interessado."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL:lei_complementar:258:2024"
        _mock_archive_candidates(filter_documents, [document])
        question = (
            "Na triagem de uma obra municipal, quais dispositivos da LC nº 258/2024 "
            "tratam do objeto do Código, de complementações ou notificações e de "
            "processos antigos sem despacho? Explique as regras distintas e as limitações "
            "da extração pendente."
        )

        rows = retrieve_archive_evidence(question, limit=8)

        devices = {row["dispositivo_ref"] for row in rows}
        self.assertIn("Art. 2º", devices)
        self.assertIn("Art. 22", devices)
        self.assertIn("Art. 262", devices)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_large_whole_norm_with_practical_topic_prioritizes_matching_articles(
        self, filter_documents
    ):
        articles = []
        relevant_articles = {3, 17, 31}
        padding = " Texto geral com competência administrativa. " * 20
        for article in range(1, 41):
            topic = (
                " Regras de licenciamento urbanístico para obras no Município."
                if article in relevant_articles
                else " Regras administrativas de organização municipal."
            )
            articles.append(f"Art. {article}º{topic}{padding}")
        document = _archive_document(
            number="6021",
            year=2009,
            legal_text="\n".join(articles),
        )
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "Faça uma síntese curta da Lei nº 6021/2009 para triagem inicial "
            "de um processo de licenciamento: quais assuntos e dispositivos são relevantes?",
            limit=8,
        )

        self.assertEqual(
            {row["dispositivo_ref"].split()[1].rstrip("º°ª") for row in rows},
            {"3", "17", "31"},
        )
        self.assertTrue(all(row["coverage"]["selected_articles"] == 3 for row in rows))
        self.assertTrue(all(row["coverage"]["total_articles"] == 40 for row in rows))
        self.assertTrue(all(row["coverage"]["complete"] is False for row in rows))
        self.assertTrue(
            all(row["coverage"]["selection_strategy"] == "topic_ranked" for row in rows)
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_exact_law_and_article_retrieves_only_that_article(self, filter_documents):
        document = _archive_document()
        _mock_archive_candidates(filter_documents, [document])

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
    def test_exact_reference_is_withheld_when_pdf_epigraph_disagrees_with_filename_year(
        self, filter_documents
    ):
        document = _archive_document(
            number="219",
            year=2023,
            metadata_candidates_json={
                "epigraph": {
                    "status": "candidate",
                    "candidates": [
                        {
                            "type_key": "lei_complementar",
                            # Current PyMuPDF extraction of the authentic QA PDF
                            # reads a truncated/misdecoded epigraph as "21" and
                            # cannot recover its year; it must fail closed.
                            "number": "21",
                            "year": None,
                        }
                    ],
                },
            },
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("O que prevê a Lei Complementar nº 219/2023?", limit=8)

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_exact_pdf_epigraph_resolves_mislabeled_archive_filename_year(self, filter_documents):
        legal_text = (
            "--- Página 1 ---\n"
            "LEI COMPLEMENTAR Nº 21\n9 DE\n22 DE DEZEMBRO DE 2022\n\n"
            "Altera e revoga artigos da Lei nº 3.882 de 11 de dezembro de 1989, "
            "bem como revoga a Lei nº 6.535/2015.\n"
            "Art. 1º Os artigos 25, 31, 38 e 41 da Lei 3.882 de 11 de dezembro de 1989 "
            "passam a vigorar com as seguintes redações: texto do dispositivo.\n"
            "Art. 2º Esta lei entra em vigor na data de sua publicação, revogando-se "
            "os §§ 1º, 2º e 3º do artigo 83 da Lei 3.882 de 11 de dezembro de 1989 "
            "e a Lei n. 6.535/2015."
        )
        document = _archive_document(number="219", year=2023, legal_text=legal_text)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL:lc:219:2023"
        verified_candidate = _archive_document(number="219", year=2022, legal_text=legal_text)
        verified_candidate.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        verified_candidate.metadata_json["identity_key"] = "BR-RN-NATAL:lc:219:2022"
        verified_candidate.public_id = "00000000-0000-0000-0000-000000000219"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "O que prevê o Art. 1º da Lei Complementar nº 219/2022?", limit=8
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norma_ref"], "Lei Complementar nº 219/2022")
        self.assertEqual(rows[0]["dispositivo_ref"], "Art. 1º")
        self.assertIn("artigos 25, 31, 38 e 41", rows[0]["full_text"])
        self.assertEqual(rows[0]["coverage"]["epigraph_identity_status"], "conflict")
        self.assertTrue(rows[0]["coverage"]["identity_conflict"])
        self.assertIn("pendente de revisão", rows[0]["source_type"])

        _mock_archive_candidates(filter_documents, [document, verified_candidate])
        inventory_rows = retrieve_archive_evidence(
            "O que a Lei Complementar nº 219/2022 alterou ou revogou?", limit=8
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in inventory_rows}, {"Art. 1º", "Art. 2º"}
        )
        self.assertTrue(
            all(row["source_id"] == verified_candidate.public_id for row in inventory_rows)
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_explicit_consolidation_exercise_excludes_other_editions(self, filter_documents):
        law_2022 = _archive_document(
            number="3882",
            year=1989,
            legal_text=(
                "Art. 31 A área construída bruta inclui as áreas de sacadas cobertas ou descobertas."
            ),
        )
        law_2022.public_id = "00000000-0000-0000-0000-000000003882"
        law_2022.metadata_json["identity_candidate"]["type"] = "lei"
        law_2022.metadata_json["edition_candidate"] = {
            "kind": "official_consolidated_text",
            "declared_value_year": 2022,
        }
        law_2024 = _archive_document(
            number="3882",
            year=1989,
            legal_text=(
                "Art. 31 A área construída bruta considera as áreas definidas para o exercício 2024."
            ),
        )
        law_2024.public_id = "00000000-0000-0000-0000-000000003884"
        law_2024.metadata_json["identity_candidate"]["type"] = "lei"
        law_2024.metadata_json["edition_candidate"] = {
            "kind": "official_consolidated_text",
            "declared_value_year": 2024,
        }
        amendment = _archive_document(
            number="219",
            year=2022,
            legal_text=(
                "Art. 1º Os artigos 25, 31, 38 e 41 da Lei 3.882/1989 passam a vigorar com "
                "novas redações, incluindo o tratamento das áreas de terraços e quadras."
            ),
        )
        amendment.public_id = "00000000-0000-0000-0000-000000000219"
        amendment.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [amendment, law_2022, law_2024])

        rows = retrieve_archive_evidence(
            "Compare o Art. 31 da Lei nº 3.882/1989 na consolidação declarada como exercício "
            "de 2022 com a alteração introduzida pelo Art. 1º da Lei Complementar nº 219/2022.",
            limit=8,
        )

        assert {row["source_id"] for row in rows} == {
            law_2022.public_id,
            amendment.public_id,
        }
        assert not any(row["source_id"] == law_2024.public_id for row in rows)
        assert {row["dispositivo_ref"] for row in rows} == {"Art. 1º", "Art. 31"}

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_explicit_norm_after_first_forty_candidates_is_retrieved(self, filter_documents):
        decoys = [_archive_document(number=str(7000 + index), year=2020) for index in range(40)]
        target = _archive_document(number="198", year=2021)
        target.public_id = "00000000-0000-0000-0000-000000000198"
        target.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        target.metadata_json["identity_key"] = "BR-RN-NATAL:lc:198:2021"
        _mock_archive_candidates(filter_documents, [*decoys, target])

        rows = retrieve_archive_evidence(
            "O que prevê o Art. 1º da Lei Complementar nº 198/2021?", limit=8
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["norma_ref"], "Lei Complementar nº 198/2021")
        self.assertEqual(rows[0]["dispositivo_ref"], "Art. 1º")

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
        _mock_archive_candidates(
            filter_documents,
            [
                unrelated_law,
                unrelated_decree,
                requested_decree,
            ],
        )

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
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [_archive_document()])

        rows = retrieve_archive_evidence("E o que consta no Adendo I para esse crédito?")

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_multiple_explicit_laws_do_not_fall_back_to_an_unrelated_document(
        self, filter_documents
    ):
        unrelated = _archive_document(
            number="198",
            year=2021,
            legal_text=(
                "Art. 5º O órgão municipal de licenciamento tem 30 dias para "
                "estabelecer o modelo e padrão da placa informativa."
            ),
        )
        unrelated.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [unrelated])

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
            number="9001",
            year=2020,
            legal_text=(
                "Art. 5º O prazo original para interposição de recurso administrativo "
                "será de dez dias úteis, contados da ciência oficial da decisão."
            ),
        )
        amending = _archive_document(
            number="9002",
            year=2021,
            legal_text=(
                "Art. 5º O prazo previsto na Lei nº 9.001/2020 passa a ser de quinze "
                "dias úteis, contados da ciência oficial da decisão administrativa."
            ),
        )
        original.public_id = "00000000-0000-0000-0000-000000000011"
        amending.public_id = "00000000-0000-0000-0000-000000000012"
        _mock_archive_candidates(filter_documents, [original, amending])

        rows = retrieve_archive_evidence(
            "Qual era o prazo do art. 5º da Lei nº 9.001/2020 antes da alteração "
            "promovida pela Lei nº 9.002/2021?",
            limit=8,
        )

        self.assertEqual(
            {row["norma_ref"] for row in rows},
            {
                "Lei Ordinária nº 9001/2020",
                "Lei Ordinária nº 9002/2021",
            },
        )
        self.assertEqual({row["dispositivo_ref"] for row in rows}, {"Art. 5º"})

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_cross_reference_scan_retrieves_the_first_norm_and_filters_literal_mentions(
        self, filter_documents
    ):
        source = _archive_document(
            number="198",
            year=2021,
            legal_text=(
                "Art. 1º Conforme a Lei Complementar nº 55/2004, será exibida placa.\n"
                "Art. 2º A placa será definida pelo órgão municipal.\n"
                "Art. 3º Aplicam-se subsidiariamente a LC nº 055/2004.\n"
                "Art. 4º Esta Lei entra em vigor na data de sua publicação."
            ),
        )
        source.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        source.metadata_json["identity_key"] = "BR-RN-NATAL:lc:198:2021"
        _mock_archive_candidates(filter_documents, [source])

        rows = retrieve_archive_evidence(
            "A Lei Complementar nº 198/2021 cita ou faz remissão à Lei Complementar nº 55/2004? "
            "Liste todos os artigos do PDF arquivado que mencionam a LC 55/2004 e esclareça "
            "se isso comprova alteração normativa.",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 1º", "Art. 3º"])
        self.assertTrue(all(row["norma_ref"] == "Lei Complementar nº 198/2021" for row in rows))
        self.assertTrue(all("55/2004" in row["full_text"] for row in rows))

        status_rows = retrieve_archive_evidence(
            "A Lei Complementar nº 198/2021 remete aos arts. 21, 44 e 88 da LC nº 55/2004. "
            "No acervo disponível, há evidência de que esses artigos foram alterados ou "
            "revogados? Separe o que está comprovado do que permanece inconclusivo e cite os PDFs.",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in status_rows], ["Art. 1º", "Art. 3º"])
        self.assertTrue(
            all(row["norma_ref"] == "Lei Complementar nº 198/2021" for row in status_rows)
        )

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
        _mock_archive_candidates(filter_documents, [document])

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
    def test_contextual_followup_for_effective_date_returns_only_operative_clause(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 262. Os processos protocolados até a data de entrada em vigor desta Lei "
                "e sem despacho decisório serão apreciados conforme a legislação vigente à época.\n"
                "Art. 266. Esta Lei Complementar entra em vigor 90 (noventa) dias após a data "
                "de sua publicação, revogadas as disposições em contrário.\n"
                "Art. 50. A edificação poderá ser legalizada conforme a legislação vigente na "
                "data de protocolo do processo."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL:lc:258:2024"
        _mock_archive_candidates(filter_documents, [document])

        questions = (
            "E qual artigo define a data de entrada em vigor?",
            "Qual dispositivo da Lei Complementar nº 258/2024 estabelece sua entrada em vigor, e o que diz o trecho do PDF local?",
            "E quando a lei passou a vigorar?",
            "Em que data entrou em vigor?",
        )
        for question in questions:
            with self.subTest(question=question):
                rows = retrieve_archive_evidence(
                    f"{question} (contexto normativo: Lei Complementar nº 258/2024)",
                    limit=8,
                )

                self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 266"])
                self.assertIn("entra em vigor 90", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_compound_norm_identification_adds_supporting_article_and_excludes_unrelated_norms(
        self, filter_documents
    ):
        health_pccv = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "Art. 1º Esta Lei Complementar institui o Plano de Cargos, Carreiras e "
                "Vencimentos dos profissionais da saúde do Município de Natal.\n"
                "Art. 18. O vencimento básico percebido pelo servidor não poderá ser "
                "inferior ao salário mínimo nacional vigente."
            ),
        )
        health_pccv.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        unrelated_decree = _archive_document(
            number="9365",
            year=2011,
            legal_text=(
                "Art. 18. Os Secretários Municipais responsáveis pela coordenação dos "
                "núcleos de convergência supervisionarão o fiel cumprimento das metas "
                "e diretrizes estabelecidas neste Decreto."
            ),
        )
        unrelated_decree.metadata_json["identity_candidate"]["type"] = "decreto"
        unrelated_decree.public_id = "00000000-0000-0000-0000-000000000036"
        _mock_archive_candidates(
            filter_documents,
            [
                health_pccv,
                unrelated_decree,
            ],
        )

        rows = retrieve_archive_evidence(
            "Qual norma institui o Plano de Cargos, Carreiras e Vencimentos dos "
            "profissionais da saúde de Natal e o que prevê o art. 18 sobre vencimento básico?",
            limit=8,
        )

        self.assertEqual(
            {(row["norma_ref"], row["dispositivo_ref"]) for row in rows},
            {
                ("Lei Complementar nº 120/2010", "Art. 1º"),
                ("Lei Complementar nº 120/2010", "Art. 18"),
            },
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_compound_norm_and_article_question_cites_both_supported_claims(
        self, retrieve, generate
    ):
        question = (
            "Qual norma institui o Plano de Cargos, Carreiras e Vencimentos dos "
            "profissionais da saúde de Natal e o que prevê o art. 18 sobre vencimento básico?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:health-pccv-art1",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 1º",
                "full_text": (
                    "Art. 1º Fica criado o Plano de Cargos, Carreiras e Vencimentos dos "
                    "profissionais da Área de Saúde, servidores estatutários da Secretaria "
                    "Municipal de Saúde."
                ),
                "similarity_score": 0.9,
                "coverage": {},
            },
            {
                "citation_id": "qa:health-pccv-art18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": (
                    "Art. 18. O vencimento básico percebido pelo servidor não poderá ser "
                    "inferior ao salário mínimo nacional vigente."
                ),
                "similarity_score": 0.8,
                "coverage": {},
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )
        done = events[-1]

        self.assertEqual(done["event"], "done")
        self.assertEqual(done["reason_code"], "archive_compound_norm_identity")
        self.assertIn("Lei Complementar nº 120/2010", done["answer"])
        self.assertIn("Art. 1º", done["answer"])
        self.assertIn("Art. 18", done["answer"])
        self.assertIn("Quanto ao tema **vencimento básico**", done["answer"])
        self.assertIn("inferior ao salário mínimo nacional vigente", done["answer"])
        self.assertEqual(
            {claim["citation_ids"][0] for claim in done["grounding"]["claims"]},
            {"qa:health-pccv-art1", "qa:health-pccv-art18"},
        )
        generate.assert_not_called()

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
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

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
    def test_explicit_lc_article_262_retrieves_the_requested_transitional_provision(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "--- Página 60 ---\n"
                "TÍTULO V\nDAS DISPOSIÇÕES FINAIS E TRANSITÓRIAS\n"
                "Art. 237. O auto deverá ser publicado no Diário Oficial do Município em até 30 dias.\n"
                "Art. 257. O cumprimento das normas fixadas na presente Lei não exime o empreendedor "
                "do atendimento às prescrições específicas fixadas pela legislação federal, estadual e municipal pertinente.\n"
                "Art. 258. Fica recepcionado nesta Lei, o Decreto Municipal 12.789 de 02 de maio de 2023, "
                "o qual estabelece a classificação das atividades pelo grau de risco ambiental/sanitário e pelo porte "
                "e define procedimento de licenciamento.\n"
                "Art. 259. Serão aplicadas, na análise do processo de licenciamento, as legislações vigentes "
                "na data do protocolo do processo.\n"
                "Art. 260. Ficam revogados:\nIV - Lei Complementar nº 055 de 27 de janeiro de 2004;\n"
                "Art. 261. O artigo 14 da Lei Complementar nº 208, de 07 de março de 2022, passa a ter a seguinte redação: "
                "Para cálculo do coeficiente de aproveitamento, serão consideradas as áreas computáveis.\n"
                "--- Página 61 ---\n"
                "Art. 262. Os processos de licenciamento de obras e edificações protocolados até a data de entrada em vigor "
                "desta Lei e sem despacho decisório, serão apreciados integralmente de acordo com a legislação em vigor "
                "à época do protocolo, exceto nos casos de manifestação formal do interessado, optando pela análise "
                "integral nos termos desta Lei.\n"
                "Art. 263. As contrapartidas e multas previstas nesta lei são reajustadas anualmente.\n"
                "Art. 266. Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação.\n"
                "Sala das Sessões, em Natal, 05 de dezembro de 2024.\n"
                "Publicado no Diário Oficial do Município em: 27/12/2024\n"
                "Autoria: Chefe do Executivo\nANEXO I\nTabela de dimensões."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "O que dispõe o Art. 262 da Lei Complementar nº 258/2024?",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 262"])
        self.assertIn("sem despacho decisório", rows[0]["full_text"])
        self.assertTrue(rows[0]["coverage"]["complete"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_general_pre_effective_date_question_prioritizes_transition_article(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 54. Não poderão ser objeto de regularização as edificações em áreas públicas.\n"
                "Art. 75. Os prazos de validade das licenças ambientais serão definidos conforme o cronograma.\n"
                "Art. 242. O relaxamento do embargo não poderá ocorrer em obra interditada.\n"
                "Art. 262. Os processos de licenciamento de obras e edificações protocolados até "
                "a data de entrada em vigor desta Lei e sem despacho decisório, serão apreciados "
                "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
                "nos casos de manifestação formal do interessado, optando pela análise integral "
                "nos termos desta Lei."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "Um processo de licenciamento de obra foi protocolado antes da vigência da Lei "
            "Complementar nº 258/2024. O que o texto da lei prevê para processos anteriores? "
            "Cite os dispositivos e indique o que não pode ser concluído apenas com o PDF local.",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 262"])
        self.assertIn("manifestação formal", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_transition_question_also_retrieves_the_law_commencement_clause(self, filter_documents):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 262. Os processos de licenciamento protocolados até a data de entrada em vigor "
                "desta Lei e sem despacho decisório serão apreciados segundo a legislação da data "
                "do protocolo, exceto se houver manifestação formal pela lei nova.\n"
                "Art. 263. As contrapartidas e multas serão reajustadas anualmente.\n"
                "Art. 266. Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "Em um processo de licenciamento urbanístico protocolado antes da vigência da "
            "LC nº 258/2024, quais dispositivos da lei tratam da transição e quais documentos "
            "preciso conferir antes de definir a redação aplicável?",
            limit=8,
        )

        by_article = {row["dispositivo_ref"]: row["full_text"] for row in rows}
        self.assertEqual(set(by_article), {"Art. 262", "Art. 266"})
        self.assertIn("sem despacho decisório", by_article["Art. 262"])
        self.assertIn("entra em vigor 90 dias", by_article["Art. 266"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_multi_norm_transition_retrieval_adds_commencement_article_from_new_law(
        self, filter_documents
    ):
        newer = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 260. Ficam revogadas a Lei Complementar nº 55/2004.\n"
                "Art. 262. Os processos de licenciamento protocolados até a data de entrada em vigor "
                "desta Lei e sem despacho decisório serão apreciados integralmente de acordo com "
                "a legislação em vigor à época do protocolo, exceto nos casos de manifestação "
                "formal do interessado, optando pela análise integral nos termos desta Lei.\n"
                "Art. 266. Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação."
            ),
        )
        older = _archive_document(
            number="55",
            year=2004,
            legal_text=(
                "Art. 21. Toda obra só pode começar após o licenciamento municipal. "
                "A autoridade competente analisará o pedido conforme a documentação apresentada."
            ),
        )
        newer.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        older.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [newer, older])
        question = (
            "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem "
            "despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda "
            "pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024."
        )

        rows = retrieve_archive_evidence(question, limit=8)

        retrieved = {(row["norma_ref"], row["dispositivo_ref"]) for row in rows}
        self.assertIn(("Lei Complementar nº 258/2024", "Art. 266"), retrieved)
        self.assertIn(("Lei Complementar nº 258/2024", "Art. 262"), retrieved)
        self.assertIn(("Lei Complementar nº 55/2004", "Art. 21"), retrieved)

    def test_transition_commencement_synthesis_cites_both_related_devices(self):
        question = (
            "Em um processo de licenciamento urbanístico protocolado antes da vigência da "
            "LC nº 258/2024, quais dispositivos da lei tratam da transição e quais documentos "
            "preciso conferir antes de definir a redação aplicável?"
        )
        sources = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": (
                    "Os processos de licenciamento protocolados até a data de entrada em vigor "
                    "desta Lei e sem despacho decisório serão apreciados conforme a legislação "
                    "vigente à época do protocolo, exceto se houver manifestação formal pela lei nova."
                ),
            },
            {
                "citation_id": "qa:lc258-art266",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "full_text": "Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação.",
            },
        ]

        result = _archive_transition_commencement_synthesis(question, sources)

        self.assertIsNotNone(result)
        answer, claims = result
        self.assertIn("Art. 262", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("Art. 266", answer)
        self.assertIn("[[2]]", answer)
        self.assertIn("não permite concluir qual regime se aplica", answer)
        self.assertEqual(
            [claim["citation_ids"] for claim in claims],
            [["qa:lc258-art262"], ["qa:lc258-art266"]],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_transition_and_commencement_response_is_concise_and_cited_without_llm(
        self, retrieve, generate
    ):
        question = (
            "Em um processo de licenciamento urbanístico protocolado antes da vigência da "
            "LC nº 258/2024, quais dispositivos da lei tratam da transição e quais documentos "
            "preciso conferir antes de definir a redação aplicável?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": (
                    "Os processos de licenciamento protocolados até a data de entrada em vigor "
                    "desta Lei e sem despacho decisório serão apreciados conforme a legislação "
                    "vigente à época do protocolo, exceto se houver manifestação formal pela lei nova."
                ),
            },
            {
                "citation_id": "qa:lc258-art266",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "full_text": "Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação.",
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        answer = next(event for event in events if event["event"] == "done")
        self.assertEqual(
            answer["reason_code"], "qa_archive_transition_and_commencement_text_synthesis"
        )
        self.assertEqual(len(answer["sources"]), 2)
        self.assertIn("[[1]]", answer["answer"])
        self.assertIn("[[2]]", answer["answer"])
        self.assertEqual(len(answer["grounding"]["claims"]), 2)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_transition_question_returns_no_unrelated_articles_when_rule_is_absent(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 54. Não poderão ser objeto de regularização as edificações em áreas públicas.\n"
                "Art. 75. Os prazos de validade das licenças ambientais serão definidos conforme o cronograma."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "Um processo de licenciamento foi protocolado antes da vigência da Lei "
            "Complementar nº 258/2024. O que a norma prevê para processos anteriores?",
            limit=8,
        )

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_directly_paired_cross_norm_articles_retrieve_only_their_named_norm(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 259. Aplicam-se as regras vigentes na data do protocolo do processo.\n"
                "Art. 260. Ficam revogados:\n"
                "IV - Lei Complementar nº 055 de 27 de janeiro de 2004.\n"
                "Art. 262. Processos sem despacho seguem a regra de transição desta Lei."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])
        question = (
            "Para avaliar um processo, posso tratar o Art. 21 da LC 55/2004 como vigente hoje, "
            "já que o Art. 260, IV, da LC 258/2024 revoga a LC 55/2004?"
        )

        rows = retrieve_archive_evidence(question, limit=8)

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 260"])
        self.assertIn("055", rows[0]["full_text"])
        self.assertFalse(rows[0]["coverage"]["complete"])
        self.assertEqual(
            rows[0]["coverage"]["missing_article_norm_pairs"],
            [{"normative_identity": ["lei_complementar", "55", 2004], "article": "21"}],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_historical_wording_question_keeps_explicit_repeal_article_evidence(
        self, filter_documents
    ):
        repeal_law = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "Art. 260. Ficam revogados: inciso IV - Lei Complementar nº 055 de 27 de janeiro de 2004."
            ),
        )
        repeal_law.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        historical_law = _archive_document(
            number="55",
            year=2004,
            legal_text=(
                "Art. 21. Redação histórica do dispositivo sobre o procedimento de obras, "
                "com tramitação e análise dos pedidos administrativos municipais."
            ),
        )
        historical_law.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [repeal_law, historical_law])
        question = (
            "Em uma fundamentação hipotética, foi citado o art. 21 da Lei Complementar nº 55/2004. "
            "O que o art. 260, inciso IV, da LC nº 258/2024 diz sobre essa lei, e as fontes disponíveis "
            "permitem afirmar qual redação do art. 21 estava vigente em 2024?"
        )

        self.assertEqual(
            _explicit_article_norm_pairs(question),
            (
                (("lei_complementar", "55", 2004), "21"),
                (("lei_complementar", "258", 2024), "260"),
                (("lei_complementar", "55", 2004), "21"),
            ),
        )

        rows = retrieve_archive_evidence(question, limit=8)

        self.assertEqual(
            {(row["norma_ref"], row["dispositivo_ref"]) for row in rows},
            {
                ("Lei Complementar nº 258/2024", "Art. 260"),
                ("Lei Complementar nº 55/2004", "Art. 21"),
            },
        )

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
        _mock_archive_candidates(filter_documents, [document])

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
    def test_qualified_plural_article_question_retrieves_each_named_article(self, filter_documents):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text="\n".join(
                [
                    "Art. 259. Regra sobre processos protocolados.",
                    "Art. 260. Ficam revogados: inciso IV - Lei Complementar nº 055/2004.",
                    "Art. 261. Regra intermediária sem pertinência.",
                    "Art. 262. Processos sem despacho decisório serão apreciados pela lei da data do protocolo.",
                ]
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "O que estabelecem os arts. 260, inciso IV, e 262 da Lei Complementar nº 258/2024?",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 260", "Art. 262"])
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))
        self.assertTrue(all(row["coverage"]["missing_articles"] == [] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_explicit_article_list_survives_topic_filter_and_excludes_contextual_law(
        self, filter_documents
    ):
        current_law = _archive_document(
            number="258",
            year=2024,
            legal_text="\n".join(
                [
                    "Art. 259. Processos protocolados antes da vigência serão analisados conforme a regra temporal.",
                    "Art. 260. Ficam revogados: IV - Lei Complementar nº 055/2004.",
                    "Art. 262. Processos sem despacho decisório serão apreciados pela lei da data do protocolo.",
                ]
            ),
        )
        current_law.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        contextual_law = _archive_document(
            number="55",
            year=2004,
            legal_text="\n".join(
                [
                    "Art. 259. Antigo procedimento administrativo.",
                    "Art. 260. Antiga regra de protocolo.",
                    "Art. 262. Antiga regra de revogação.",
                ]
            ),
        )
        contextual_law.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [current_law, contextual_law])

        rows = retrieve_archive_evidence(
            "No Código de Obras da Lei Complementar nº 258/2024, o que dizem os arts. "
            "259, 260 e 262 sobre processos anteriores e revogação da LC 55/2004?",
            limit=8,
        )

        self.assertEqual(
            [row["dispositivo_ref"] for row in rows], ["Art. 259", "Art. 260", "Art. 262"]
        )
        self.assertTrue(all(row["norma_ref"] == "Lei Complementar nº 258/2024" for row in rows))
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

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
        _mock_archive_candidates(filter_documents, [document])

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
        document = _archive_document(
            legal_text=(
                "Art. 1º As administradoras de cartões são obrigadas a remeter declaração à Secretaria Municipal.\n"
                "Art. 2º As administradoras prestarão informações sobre operações com cartões no Município.\n"
                "Art. 3º Acrescenta os incisos XI e XII ao artigo 86 da Lei 3.882.\n"
                "Art. 4º Esta lei entrará em vigor na data de sua publicação."
            )
        )
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

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
        document = _archive_document(
            legal_text=(
                "Art. 1º O programa será executado no âmbito municipal, conforme regulamento.\n"
                "Art. 2º Esta Lei entra em vigor na data de sua publicação."
            )
        )
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "Qual será o orçamento municipal de Natal em 2030?", limit=8
        )

        self.assertEqual(rows, [])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unanchored_query_keeps_a_specific_topic_match(self, filter_documents):
        document = _archive_document(
            legal_text=(
                "Art. 1º A dotação para o orçamento anual do programa será definida em lei própria.\n"
                "Art. 2º Esta Lei entra em vigor na data de sua publicação."
            )
        )
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("orçamento", limit=8)

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 1º"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_unanchored_future_year_query_excludes_older_budget_laws(self, filter_documents):
        document = _archive_document(
            number="5741",
            year=2006,
            legal_text=(
                "Art. 1º Fica aberto crédito suplementar para reforço de dotações do orçamento municipal.\n"
                "Art. 2º Esta Lei entra em vigor na data de sua publicação."
            ),
        )
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("O que estabelece a Lei Ordinária nº 6021/2009?", limit=8)

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["evidence_scope"] == "isolated_qa_archive" for row in rows))
        self.assertTrue(all(row["source_kind"] == "archive" for row in rows))
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

        self.assertTrue(all(row["coverage"]["selected_articles"] == 3 for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_named_norm_change_inventory_returns_all_amendatory_and_repeal_articles(
        self, filter_documents
    ):
        document = _archive_document(
            number="219",
            year=2023,
            legal_text=(
                "Art. 1º Os arts. 25, 31 e 38 da Lei 3.882/1989 passam a vigorar com novas redações.\n"
                "Art. 2º Ficam revogadas as disposições em contrário e a Lei 6.535/2015.\n"
                "Art. 3º Esta Lei Complementar entra em vigor na data de sua publicação."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "O que foi alterado e revogado pela Lei Complementar nº 219/2023?", limit=8
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 1º", "Art. 2º"])
        self.assertTrue(
            all(row["coverage"].get("inventory_scope") == "normative_changes" for row in rows)
        )
        self.assertTrue(all(row["coverage"].get("inventory_complete") for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_later_change_history_lookup_keeps_original_requested_article_as_context(
        self, filter_documents
    ):
        document = _archive_document(
            number="120",
            year=2010,
            legal_text=(
                "LEI COMPLEMENTAR Nº 120/2010.\n"
                "Art. 21. A jornada semanal dos servidores da área de Saúde será de 40 horas.\n"
                "Art. 22. Esta Lei entra em vigor na data de sua publicação."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = "BR-RN-NATAL:lei_complementar:120:2010"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "E quanto ao Art. 21: quais alterações posteriores da Lei Complementar nº "
            "120/2010 consigo verificar no acervo, e o que ainda falta para concluir a redação vigente?",
            limit=8,
        )

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 21"])
        self.assertIn("jornada semanal", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_currentness_and_change_question_keeps_explicit_original_article(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "LEI COMPLEMENTAR Nº 258/2024.\n"
                "Art. 59. As inconformidades listadas no art. 54, com existência comprovada "
                "na base cartográfica do ano de 2006, serão tratadas como legalização.\n"
                "Art. 60. Os recursos oriundos dos procedimentos de regularização serão "
                "destinados ao Fundo de Urbanização."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        question = (
            "Para um processo de licenciamento municipal, posso citar o Art. 59 da Lei "
            "Complementar nº 258/2024 como redação atual? Verifique se houve alteração "
            "posterior do dispositivo e diferencie lei aprovada de proposição em tramitação."
        )
        self.assertIsNone(_article_topic_phrase(question))
        self.assertEqual(classify_normative_query(question).article_targets, ("59",))
        self.assertEqual(len(_explicit_article_norm_pairs(question)), 1)
        rows = retrieve_archive_evidence(question, limit=8)

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 59"])
        self.assertIn("inconformidades listadas no art. 54", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_article_application_limits_question_does_not_filter_requested_evidence(
        self, filter_documents
    ):
        document = _archive_document(
            number="258",
            year=2024,
            legal_text=(
                "LEI COMPLEMENTAR Nº 258/2024.\n"
                "Art. 59. As inconformidades listadas no art. 54, com existência comprovada "
                "na base cartográfica do ano de 2006, serão tratadas como legalização.\n"
                "Art. 60. Os recursos oriundos dos procedimentos de regularização serão "
                "destinados ao Fundo de Urbanização."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

        question = (
            "Com base no PDF local da Lei Complementar nº 258/2024, explique o que prevê "
            "o Art. 59 e o que esse trecho não permite concluir sobre a regularidade atual "
            "de uma obra específica."
        )
        self.assertIsNone(_article_topic_phrase(question))
        self.assertEqual(classify_normative_query(question).article_targets, ("59",))

        rows = retrieve_archive_evidence(question, limit=8)

        self.assertEqual([row["dispositivo_ref"] for row in rows], ["Art. 59"])
        self.assertIn("base cartográfica do ano de 2006", rows[0]["full_text"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_change_inventory_uses_verbatim_citations_and_keeps_unreviewed_scope_caveat(
        self, retrieve, validate, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc219-art1",
                "norma_ref": "Lei Complementar nº 219/2023",
                "dispositivo_ref": "Art. 1º",
                "full_text": "Art. 1º Os arts. 25 e 31 da Lei 3.882/1989 passam a vigorar com novas redações.",
                "texto": "Art. 1º Os arts. 25 e 31 da Lei 3.882/1989 passam a vigorar com novas redações.",
                "similarity_score": 1.0,
                "coverage": {
                    "inventory_scope": "normative_changes",
                    "inventory_selected": 2,
                    "inventory_total": 2,
                    "inventory_complete": True,
                    "complete": True,
                },
            },
            {
                "citation_id": "qa:lc219-art2",
                "norma_ref": "Lei Complementar nº 219/2023",
                "dispositivo_ref": "Art. 2º",
                "full_text": "Art. 2º Ficam revogadas a Lei 6.535/2015 e as disposições em contrário.",
                "texto": "Art. 2º Ficam revogadas a Lei 6.535/2015 e as disposições em contrário.",
                "similarity_score": 1.0,
                "coverage": {
                    "inventory_scope": "normative_changes",
                    "inventory_selected": 2,
                    "inventory_total": 2,
                    "inventory_complete": True,
                    "complete": True,
                },
            },
        ]
        validate.return_value = {"grounded": True, "source_only": True, "failed_claims": []}
        generate.return_value = _completed_generation_stream(
            {
                "answer": "O Art. 1º altera dispositivos da Lei 3.882/1989. [[1]] O Art. 2º revoga a Lei 6.535/2015. [[2]]",
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "source_only": True,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que foi alterado e revogado pela Lei Complementar nº 219/2023?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_normative_change_inventory")
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "verbatim_change_inventory_in_unreviewed_archive_extraction",
        )
        self.assertIn("**Art. 1º**", final["answer"])
        self.assertIn("**Art. 2º**", final["answer"])
        self.assertIn("passam a vigorar com novas redações", final["answer"])
        self.assertIn("Ficam revogadas a Lei 6.535/2015", final["answer"])
        self.assertIn("pendente de revisão", final["answer"])
        self.assertIn("não confirma efeitos posteriores", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )
        generate.assert_not_called()
        validate.assert_not_called()

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
        generate.return_value = _completed_generation_stream(
            {
                "answer": "O decreto estabelece um programa municipal abrangente. [[1]]",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Em linhas gerais, quais são os principais pontos do Decreto nº 7.795/2005?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertTrue(generate.call_args.kwargs["retry_after_partial_rejection"])
        self.assertTrue(generate.call_args.kwargs["revision_instruction"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertNotIn("Anexos normativos também foram detectados", final["answer"])
        self.assertIn("anexos identificados que não foram incluídos", final["answer"])
        self.assertNotIn("Art. 3º", final["answer"])
        self.assertIn("Art. 1º", final["answer"])
        self.assertIn("Art. 2º", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_formatted_decree_number_is_not_mistaken_for_a_topic(self, filter_documents):
        document = _archive_document(
            number="7795",
            year=2005,
            legal_text=(
                "Art. 1º Fica aberto à Secretaria Municipal de Meio Ambiente e Urbanismo "
                "o crédito suplementar de R$ 12.000,00 para reforço de dotação orçamentária.\n"
                "Art. 2º Constitui fonte de recursos para o crédito a anulação em igual valor "
                "de dotação orçamentária consignada no orçamento vigente.\n"
                "Art. 3º Este Decreto entra em vigor na data de sua publicação."
            ),
        )
        document.metadata_json["identity_candidate"]["type"] = "decreto"
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("O que estabelece o Decreto nº 7.795/2005?", limit=1)

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
        _mock_archive_candidates(filter_documents, [document])

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

        explicitly_scoped_rows = retrieve_archive_evidence(
            "O que previa cada artigo da Lei Complementar nº 6021/2009, indicada como "
            "revogada pelo Art. 2º da LC nº 219/2022? Liste os textos recuperados.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in explicitly_scoped_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in explicitly_scoped_rows))

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
        self.assertTrue(all(row["coverage"]["complete"] for row in explicit_sample_boundary_rows))

        plain_language_overview_rows = retrieve_archive_evidence(
            "O que prevê, em linhas gerais, a Lei Complementar nº 6021/2009?",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in plain_language_overview_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in plain_language_overview_rows))

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

        article_count_and_annex_request_rows = retrieve_archive_evidence(
            "Faça uma visão geral da Lei Complementar nº 6021/2009 e informe quantos artigos "
            "foram recuperados e se os anexos foram considerados.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in article_count_and_annex_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(
            all(row["coverage"]["complete"] for row in article_count_and_annex_request_rows)
        )

        identified_themes_request_rows = retrieve_archive_evidence(
            "Em linhas gerais, o que prevê a Lei Complementar nº 6021/2009? "
            "Explique que temas foram identificados e informe as limitações da amostra.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in identified_themes_request_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in identified_themes_request_rows))

        identified_themes_overview_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral dos principais "
            "temas identificados e informe claramente as limitações da amostra.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in identified_themes_overview_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in identified_themes_overview_rows))

        objective_no_fabrication_rows = retrieve_archive_evidence(
            "O que prevê a Lei Complementar nº 6021/2009? Faça uma visão geral objetiva "
            "dos principais temas identificáveis, sem inventar uma análise integral.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in objective_no_fabrication_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in objective_no_fabrication_rows))

        extraction_qualification_rows = retrieve_archive_evidence(
            "Faça um resumo da Lei Complementar nº 6021/2009, cobrindo os principais dispositivos "
            "e deixando claro se a extração do PDF não permitir uma síntese confiável.",
            limit=1,
        )
        self.assertEqual(
            {row["dispositivo_ref"] for row in extraction_qualification_rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in extraction_qualification_rows))

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
    def test_natural_main_themes_synthesis_is_not_narrowed_by_coverage_caveats(
        self, filter_documents
    ):
        document = _archive_document(number="6021", year=2009)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])
        question = (
            "Faça uma síntese dos principais temas e dispositivos encontrados na Lei "
            "Complementar nº 6021/2009. Cite os artigos correspondentes e informe "
            "expressamente se a recuperação cobre a norma inteira ou apenas parte dela. "
            "Não trate a extração local como texto revisado."
        )

        query_plan = classify_normative_query(question)
        self.assertEqual(query_plan.kind, "norma_overview")
        self.assertTrue(_is_whole_norm_request(question, query_plan))
        self.assertEqual(_whole_norm_topic_tokens(question), set())

        rows = retrieve_archive_evidence(question, limit=1)

        self.assertEqual(
            {row["dispositivo_ref"] for row in rows},
            {"Art. 1º", "Art. 2º", "Art. 3º"},
        )
        self.assertTrue(all(row["coverage"]["complete"] for row in rows))

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_abbreviated_complementary_law_overview_covers_the_whole_norm(self, filter_documents):
        document = _archive_document(number="120", year=2010)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        _mock_archive_candidates(filter_documents, [document])

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
        _mock_archive_candidates(filter_documents, [document])

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
    def test_whole_norm_prompt_delegates_coverage_metadata_to_backend(self, retrieve, generate):
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
        generate.return_value = _completed_generation_stream(
            {
                "answer": "",
                "grounding": {"grounded": False, "failed_claims": ["unverified"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )
        question = (
            "Faça um panorama dos principais temas e dispositivos da Lei Complementar nº "
            "120/2010. Informe quantos dispositivos foram identificados e as limitações da "
            "cobertura; só sintetize afirmações apoiadas pelas fontes."
        )

        list(
            stream_archive_qa_answer(
                question,
                k=1,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
    def test_topical_query_is_not_shaped_as_a_whole_norm_overview(self, retrieve, generate):
        question = (
            "Em linhas gerais, explique que temas foram identificados sobre a coordenação "
            "pela Secretaria Municipal de Educação na Lei Complementar nº 6021/2009."
        )
        retrieve.return_value = [
            {
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
            }
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "",
                "grounding": {"grounded": False, "failed_claims": ["unverified"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        list(
            stream_archive_qa_answer(
                question,
                k=1,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
    def test_exact_local_identity_can_link_to_existing_sapl_record(
        self, filter_documents, filter_normas
    ):
        document = _archive_document(number="118", year=2010)
        document.metadata_json["identity_candidate"]["type"] = "lei_complementar"
        document.metadata_json["identity_key"] = (
            "BR-RN-NATAL|lei_complementar|municipal_lc|118|2010"
        )
        matched = SimpleNamespace(
            identity_key=document.metadata_json["identity_key"],
            sapl_id=9076,
            sapl_url="https://sapl.natal.rn.leg.br/norma/9076",
            pdf_url="https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2010/9076/lc_118_10.pdf",
        )
        _mock_archive_candidates(filter_documents, [document])
        filter_normas.return_value.only.return_value = [matched]

        rows = retrieve_archive_evidence(
            "O que estabelece a Lei Complementar nº 118/2010?", limit=8
        )

        self.assertEqual(rows[0]["sapl_url"], "https://sapl.natal.rn.leg.br/norma/9076")
        self.assertEqual(rows[0]["pdf_url"], matched.pdf_url)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_large_whole_norm_uses_distributed_sample_and_reports_partial_coverage(
        self, filter_documents
    ):
        long_provision = (
            " Este dispositivo define regras administrativas detalhadas para o programa municipal."
            * 16
        )
        legal_text = "\n".join(f"Art. {number}º{long_provision}" for number in range(1, 31))
        document = _archive_document(legal_text=legal_text)
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("O que prevê a Lei Ordinária nº 6021/2009?", limit=5)

        assert 5 < len(rows) < 30
        assert rows[0]["dispositivo_ref"] == "Art. 1º"
        assert rows[-1]["dispositivo_ref"] == "Art. 30º"
        assert all(row["coverage"]["complete"] is False for row in rows)
        assert all(row["coverage"]["selected_articles"] == len(rows) for row in rows)
        assert all(row["coverage"]["total_articles"] == 30 for row in rows)
        assert all(row["coverage"]["selection_strategy"] == "distributed" for row in rows)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_whole_norm_evidence_excludes_mayoral_signature_from_final_article(
        self, filter_documents
    ):
        document = _archive_document(
            legal_text=(
                "Art. 1º Objeto da Lei.\n"
                "Art. 4º. Esta lei entrará em vigor na data de sua publicação, revogando todas as disposições em contrário.\n"
                "Palácio Felipe Camarão, em Natal, 28 de dezembro de 2009.\n"
                "Micarla de Sousa\nPrefeita"
            )
        )
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence("O que estabelece a Lei nº 6021/2009?", limit=8)

        final_article = next(row for row in rows if row["dispositivo_ref"] == "Art. 4º")
        assert "entra" in final_article["full_text"] or "entrará" in final_article["full_text"]
        assert "Palácio Felipe Camarão" not in final_article["full_text"]
        assert "Micarla de Sousa" not in final_article["full_text"]
        assert "Prefeita" not in final_article["full_text"]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.DocumentoNormativo.objects.filter")
    def test_final_article_stops_before_normative_annex_after_colophon(self, filter_documents):
        document = _archive_document(
            legal_text=(
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
            )
        )
        document.metadata_json["identity_candidate"].update(
            {
                "type": "lei_complementar",
                "number": "120",
                "year": 2010,
            }
        )
        _mock_archive_candidates(filter_documents, [document])

        rows = retrieve_archive_evidence(
            "O que estabelece a Lei Complementar nº 120/2010?", limit=8
        )

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
    def test_archive_temporal_scope_abstains_without_using_current_pdf(
        self, retrieve, validate, generate
    ):
        events = list(
            stream_archive_qa_answer(
                "O que previa o art. 5º da Lei Complementar nº 120/2010?",
                k=8,
                model="llama3",
                temperature=0.2,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
                temporal_scope_requested=True,
            )
        )

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
    def test_requested_intersticio_duration_abstains_with_scoped_citation(self, retrieve, generate):
        source = {
            "citation_id": "qa:lc120-art4",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 4º",
            "full_text": "Art. 4º A progressão funcional será respeitado o interstício mínimo.",
            "similarity_score": 0.91,
        }
        retrieve.return_value = [source]

        events = list(
            stream_archive_qa_answer(
                "Qual interstício mínimo a Lei Complementar nº 120/2010 exige para progressão funcional?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(
            final["reason_code"], "qa_archive_requested_detail_not_in_retrieved_evidence"
        )
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

        self.assertIsNone(
            _intersticio_duration_not_recovered(
                "Qual interstício mínimo a lei exige?",
                [source],
            )
        )
        self.assertIsNone(
            _intersticio_duration_not_recovered(
                "Quais são as regras de progressão funcional?",
                [source],
            )
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_stream_emits_sources_before_final_answer(self, retrieve, validate, generate):
        retrieve.return_value = [
            {
                "norma_ref": "Lei nº 6021/2009",
                "dispositivo_ref": "Art. 2º",
                "full_text": "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.",
                "texto": "Art. 2º O programa será coordenado pela Secretaria Municipal de Educação.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]
        validate.return_value = {}
        generate.return_value = _completed_generation_stream(
            {
                "answer": "A coordenação cabe à Secretaria Municipal de Educação. [[1]]",
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "source_only": True,
                "generation_attempts": [{"duration_ms": 4}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Quem coordena o programa?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )
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
                (
                    1,
                    "Art. 1º As obras devem expor placa conforme o artigo 21 da Lei Complementar nº 055/2004.",
                ),
                (2, "Art. 2º A placa seguirá o artigo 44 da Lei Complementar nº 055/2004."),
                (
                    4,
                    "Art. 4º O descumprimento configura infração, conforme o artigo 88 da Lei Complementar nº 055/2004.",
                ),
                (
                    6,
                    "Art. 6º Aplicam-se subsidiariamente a Lei Complementar nº 055/2004 e a Lei Complementar nº 082/2007.",
                ),
            )
        ]
        sources.append(
            {
                "citation_id": "qa:lc55-88",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 88",
                "full_text": "Art. 88 As infrações serão apuradas pela autoridade competente.",
                "texto": "Art. 88 As infrações serão apuradas pela autoridade competente.",
                "similarity_score": 0.7,
            }
        )
        retrieve.return_value = sources

        events = list(
            stream_archive_qa_answer(
                "Quais dispositivos da Lei Complementar nº 198/2021 fazem remissão "
                "à Lei Complementar nº 55/2004? Isso prova que ela alterou essa norma?",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
        for article, index in ((1, 1), (2, 2), (4, 3), (6, 4)):
            self.assertIn(f"- **Art. {article}º** [[{index}]]", final["answer"])
        self.assertNotIn("Art. 3º", final["answer"])
        self.assertIn("não confirma que os demais dispositivos", final["answer"])
        self.assertIn("não comprova alteração ou revogação", final["answer"])
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
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18º",
                "full_text": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
                "texto": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
                "similarity_score": 1.0,
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "O corpus permite confirmar se o Art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado por atos posteriores?",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_unavailable")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertTrue(
            final["answer"].startswith(
                "Com as evidências disponíveis, não foi possível confirmar se o dispositivo consultado foi alterado ou revogado"
            )
        )
        self.assertIn("O PDF arquivado registra a redação de origem", final["answer"])
        self.assertLess(
            final["answer"].index("não foi possível confirmar"),
            final["answer"].index("O PDF arquivado registra"),
        )

    def test_relation_candidate_dedup_prefers_sapl_but_preserves_distinct_evidence(self):
        def source(citation_id, source_kind, *, quote="LC 55/2004", edition=""):
            return {
                "citation_id": citation_id,
                "source_kind": source_kind,
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260, inciso IV",
                "relation_action_candidate": "REVOGA",
                "action_quote": "Ficam revogados",
                "target_text": quote,
                "evidence_text": f"IV — {quote}",
                "edition_label": edition,
                "relation_candidate": {
                    "action": "REVOGA",
                    "target_identity": {
                        "type": "lei_complementar",
                        "number": "55",
                        "year": 2004,
                        "structural_type": "artigo",
                        "structural_number": "21",
                        "structural_article_number": "21",
                    },
                },
            }

        archive_copy = source("archive-copy", "archive")
        official_copy = source("sapl-copy", "sapl")
        different_text = source("different-text", "archive", quote="LC 56/2004")
        different_edition = source(
            "different-edition", "archive", edition="consolidação 2025"
        )

        actual = _dedupe_relation_candidate_sources(
            [archive_copy, official_copy, different_text, different_edition]
        )

        self.assertEqual(
            [item["citation_id"] for item in actual],
            ["sapl-copy", "different-text", "different-edition"],
        )

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    def test_relation_query_streams_matching_candidate_without_claiming_legal_effect(
        self, generate, candidate_lookup, retrieve
    ):
        original = {
            "citation_id": "qa:lc55-art21",
            "norma_ref": "Lei Complementar nº 55/2004",
            "dispositivo_ref": "Art. 21",
            "full_text": "Art. 21. Texto original do dispositivo.",
            "texto": "Art. 21. Texto original do dispositivo.",
            "similarity_score": 0.9,
        }
        relation = {
            "citation_id": "relation-candidate:lc258-art260-iv",
            "citation_label": "Lei Complementar nº 258/2024, Art. 260, inciso IV",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260, inciso IV",
            "full_text": "IV — Lei Complementar nº 055 de 27 de janeiro de 2004",
            "action_quote": "Ficam revogados",
            "target_text": "Lei Complementar nº 055 de 27 de janeiro de 2004",
            "relation_review_status": "candidate_unreviewed",
            "source_kind": "sapl",
            "pdf_url": "https://sapl.natal.rn.leg.br/media/example.pdf",
        }
        retrieve.return_value = [original]
        candidate_lookup.return_value = [relation]
        question = (
            "O Art. 21 da Lei Complementar nº 55/2004 sofreu alteração ou "
            "revogação expressa em ato posterior?"
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        candidate_lookup.assert_called_once()
        source_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(source_event["sources"], [original, relation])
        self.assertEqual(final["sources"], [original, relation])
        self.assertEqual(final["reason_code"], "qa_archive_relation_candidate_unreviewed")
        self.assertIn("“Ficam revogados”", final["answer"])
        self.assertIn("Lei Complementar nº 055 de 27 de janeiro de 2004", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("não confirma, por si só, a revogação", final["answer"])
        self.assertNotIn("não está associada a uma cadeia", final["answer"])
        self.assertNotIn("a Lei Complementar nº 55/2004 foi revogada", final["answer"])
        self.assertIn(
            "relation-candidate:lc258-art260-iv",
            final["grounding"]["claims"][1]["citation_ids"],
        )

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    def test_act_pair_question_surfaces_exact_repeal_candidate_with_retrieved_source(
        self, generate, candidate_lookup, retrieve
    ):
        source = {
            "citation_id": "qa:lc258-art262",
            "citation_label": "Lei Complementar nº 258/2024, Art. 262",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 262",
            "full_text": "Os processos sem despacho seguem a lei vigente na data do protocolo.",
            "similarity_score": 0.9,
        }
        relation = {
            "citation_id": "relation-candidate:lc258-art260-iv",
            "citation_label": "Lei Complementar nº 258/2024, Art. 260, inciso IV",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260, inciso IV",
            "action_quote": "Ficam revogados",
            "target_text": "Lei Complementar nº 055 de 27 de janeiro de 2004",
            "relation_review_status": "candidate_unreviewed",
            "source_kind": "sapl",
            "pdf_url": "https://sapl.natal.rn.leg.br/media/example.pdf#page=60",
        }
        retrieve.return_value = [source]
        candidate_lookup.side_effect = [[relation], []]
        question = "A LC nº 258/2024 revogou a LC nº 55/2004?"

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        self.assertEqual(candidate_lookup.call_count, 2)
        self.assertEqual(candidate_lookup.call_args_list[0].args[1], ())
        self.assertEqual(candidate_lookup.call_args_list[0].kwargs["source_reference"].number, "258")
        source_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(source_event["sources"], [source, relation])
        self.assertEqual(final["reason_code"], "qa_archive_explicit_act_relation_candidate")
        self.assertIn("Art. 262", final["answer"])
        self.assertIn("“Ficam revogados”", final["answer"])
        self.assertIn("Lei Complementar nº 055 de 27 de janeiro de 2004", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("não certificam vigência", final["answer"])
        self.assertFalse(final["grounding"]["claims"] == [])

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    def test_act_pair_transition_question_adds_same_act_temporal_articles(
        self, generate, candidate_lookup, retrieve
    ):
        repeal_clause = {
            "citation_id": "qa:lc258-art260-relation",
            "citation_label": "Lei Complementar nº 258/2024, Art. 260, inciso IV",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260, inciso IV",
            "action_quote": "Ficam revogados",
            "target_text": "Lei Complementar nº 055 de 27 de janeiro de 2004",
            "relation_review_status": "candidate_unreviewed",
            "source_kind": "sapl",
            "pdf_url": "https://sapl.natal.rn.leg.br/media/example.pdf#page=59",
            "relation_candidate": {
                "target_identity": {
                    "type": "lei_complementar",
                    "number": "055",
                    "year": 2004,
                    "structural_type": "lei complementar",
                }
            },
        }
        transition = {
            "citation_id": "qa:lc258-art262",
            "citation_label": "Lei Complementar nº 258/2024, Art. 262",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 262",
            "full_text": (
                "Os processos de licenciamento de obras e edificações protocolados até a data "
                "de entrada em vigor desta Lei e sem despacho decisório serão apreciados "
                "integralmente de acordo com a legislação em vigor à época do protocolo, "
                "exceto nos casos de manifestação formal do interessado, optando pela análise "
                "integral nos termos desta Lei."
            ),
        }
        commencement = {
            "citation_id": "qa:lc258-art266",
            "citation_label": "Lei Complementar nº 258/2024, Art. 266",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 266",
            "full_text": "Esta Lei Complementar entra em vigor 90 (noventa) dias após a data de sua publicação.",
        }
        retrieve.side_effect = [[transition], [transition], [commencement]]
        candidate_lookup.side_effect = [[repeal_clause], []]
        question = (
            "A LC nº 258/2024 revogou a LC nº 55/2004? Explique também a transição dos "
            "processos sem despacho e a data de entrada em vigor indicada pela norma."
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        self.assertEqual(retrieve.call_count, 3)
        source_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(
            [source["citation_id"] for source in source_event["sources"]],
            ["qa:lc258-art262", "qa:lc258-art266", "qa:lc258-art260-relation"],
        )
        self.assertIn("Art. 262", final["answer"])
        self.assertIn("Art. 266", final["answer"])
        self.assertIn("90 (noventa) dias", final["answer"])
        self.assertIn("Art. 260, inciso IV", final["answer"])
        self.assertIn("não reconstruo uma consolidação", final["answer"])
        self.assertIn("não certificam vigência", final["answer"])
        self.assertIn("Regra transitória", final["answer"])
        self.assertIn("não permite calcular aqui o dia exato", final["answer"])
        self.assertIn("não concluo se a regra de transição alcança o processo", final["answer"])
        self.assertEqual(source_event["coverage"]["scope"], "explicit_pair_of_acts")

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("django.apps.apps.get_model")
    def test_relation_candidate_lookup_uses_initialized_django_model_registry(self, get_model):
        queryset = MagicMock()
        queryset.filter.return_value = queryset
        queryset.select_related.return_value = queryset
        queryset.prefetch_related.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.__getitem__.return_value = []
        manager = MagicMock()
        manager.filter.return_value = queryset
        get_model.return_value = SimpleNamespace(objects=manager)

        result = _archive_relation_candidate_sources(
            SimpleNamespace(
                type_key="lei_complementar",
                number="208",
                year=2022,
                ambiguous=True,
            ),
            ("18",),
        )

        assert result == []
        get_model.assert_called_once_with("legislation", "EventoNormativoCandidato")

    @override_settings(
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        JURIX_BUILD_PROFILE="qa",
    )
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag._target_normative_device_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    def test_comparison_question_includes_prior_device_and_later_amendment_sources(
        self, generate, prior_lookup, relation_lookup, retrieve
    ):
        relation = {
            "citation_id": "relation-candidate:lc261-art118",
            "citation_label": "Lei Complementar nº 261/2025, Art. 118",
            "norma_ref": "Lei Complementar nº 261/2025",
            "dispositivo_ref": "Art. 118",
            "full_text": (
                "Art. 118. O §2° do Art. 18 da lei complementar 208/2022 passa a vigorar "
                "com a seguinte redação:\n\n--- Página 35 ---\n“Acrescer à Subzona de Uso Restrito da ZPA-1 "
                "os lotes contidos na faixa marginal de 100 metros ao sul da Avenida da Integração, "
                "os lotes do lado sudeste da Avenida Omar O´Grady, entre as Avenidas dos Xavantes "
                "e Antoine de Saint Exupery e área delimitada na Tabela de vértices como SUR-1B.”"
            ),
            "texto": "Art. 118. ...",
            "action_quote": "passa a vigorar",
            "target_text": "§2° do Art. 18 da lei complementar 208/2022",
            "relation_review_status": "candidate_unreviewed",
            "source_kind": "sapl",
            "pdf_url": "https://sapl.natal.rn.leg.br/media/example-261.pdf#page=34",
            "relation_candidate": {
                "target_identity": {
                    "type": "lei_complementar",
                    "number": "208",
                    "year": 2022,
                    "structural_type": "paragrafo",
                    "structural_number": "2º",
                    "structural_article_number": "18",
                }
            },
        }
        prior = {
            "citation_id": "target-device:lc208-art18-p2",
            "citation_label": "Lei Complementar nº 208/2022, Art. 18, § 2º",
            "full_text": "§ 2º Acrescer à Subzona de Uso Restrito (SZ-2) da ZPA-1.",
            "texto": "§ 2º Acrescer à Subzona de Uso Restrito (SZ-2) da ZPA-1.",
            "evidence_scope": "unreviewed_target_device_extraction",
            "source_kind": "sapl",
            "pdf_url": "https://sapl.natal.rn.leg.br/media/example-208.pdf#page=11",
        }
        relation_lookup.side_effect = [[relation], []]
        prior_lookup.return_value = [prior]
        question = (
            "A redação do § 2º do Art. 18 da Lei Complementar nº 208/2022 foi alterada pela "
            "LC nº 261/2025? Compare a redação anterior com a redação nova e cite os PDFs oficiais."
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        source_event = next(event for event in events if event["event"] == "sources")
        self.assertEqual(source_event["sources"], [relation, prior])
        self.assertIn("SZ-2", final["answer"])
        self.assertIn("SUR-1B", final["answer"])
        self.assertIn(
            "faixa marginal de 100 metros ao sul da Avenida da Integração", final["answer"]
        )
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertIn("não certifica a redação vigente hoje", final["answer"])
        self.assertFalse(final["coverage"]["legal_effect_reviewed"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_topical_synthesis_keeps_relation_qualifier_from_short_circuiting_generation(
        self, retrieve, generate
    ):
        question = (
            "Na Lei Complementar nº 120/2010, quais aspectos do plano de carreira dos "
            "profissionais da saúde aparecem nos PDFs do acervo — ingresso, jornada, "
            "remuneração e desenvolvimento funcional? Explique em poucos parágrafos, cite "
            "os artigos que sustentam cada afirmação e separe a redação arquivada da "
            "vigência atual, que pode não estar confirmada."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art21",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 21",
                "full_text": "A jornada semanal dos servidores da Saúde é de 40 horas.",
                "texto": "A jornada semanal dos servidores da Saúde é de 40 horas.",
                "similarity_score": 0.9,
            },
            {
                "citation_id": "qa:lc120-art26",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 26",
                "full_text": "A remuneração dos servidores da Saúde inclui gratificações.",
                "texto": "A remuneração dos servidores da Saúde inclui gratificações.",
                "similarity_score": 0.8,
            },
            {
                "citation_id": "qa:lc120-ingresso",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 10",
                "full_text": "O ingresso na carreira da Saúde ocorrerá por concurso público.",
                "texto": "O ingresso na carreira da Saúde ocorrerá por concurso público.",
                "similarity_score": 0.7,
            },
            {
                "citation_id": "qa:lc120-desenvolvimento",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 30",
                "full_text": "O desenvolvimento funcional dos servidores ocorrerá por progressão.",
                "texto": "O desenvolvimento funcional dos servidores ocorrerá por progressão.",
                "similarity_score": 0.6,
            },
        ]
        answer = (
            "O ingresso ocorre por concurso [[3]], a jornada é semanal [[1]], a remuneração "
            "inclui gratificações [[2]] e o desenvolvimento funcional ocorre por progressão [[4]]."
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": answer,
                "grounded": True,
                "source_only": True,
                "grounding": {
                    "grounded": True,
                    "claims": [
                        {"text": "Jornada", "citation_ids": ["qa:lc120-art21"]},
                        {"text": "Gratificações", "citation_ids": ["qa:lc120-art26"]},
                    ],
                    "failed_claims": [],
                },
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        self.assertTrue(generate.called)
        final = events[-1]
        self.assertTrue(final["answer"].startswith(answer))
        self.assertNotIn("consulta complementar ao SAPL está desativada", final["answer"])
        self.assertNotIn("proposição posterior", final["answer"])
        self.assertNotEqual(final["reason_code"], "qa_archive_relation_history_unavailable")
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_multi_facet_question_does_not_finalize_a_narrow_grounded_draft(
        self, retrieve, generate
    ):
        question = (
            "Na Lei Complementar nº 120/2010, quais aspectos aparecem — ingresso, jornada, "
            "remuneração e desenvolvimento funcional? Separe a redação arquivada da vigência atual."
        )
        retrieve.return_value = [
            {
                "citation_id": f"qa:facet-{index}",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": f"Art. {index}",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.5,
            }
            for index, text in enumerate(
                [
                    "Art. 1. Fica instituído o plano de carreira da saúde.",
                    "Art. 2. O ingresso ocorrerá por concurso público.",
                    "Art. 3. A jornada semanal será de 40 horas.",
                    "Art. 4. A remuneração inclui vencimento básico.",
                    "Art. 5. O desenvolvimento funcional ocorrerá por progressão.",
                ],
                1,
            )
        ]
        narrow_answer = "A lei institui o plano de carreira da saúde [[1]]."
        generate.return_value = _completed_generation_stream(
            {
                "answer": narrow_answer,
                "grounded": True,
                "source_only": True,
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=2,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertNotEqual(final["answer"], narrow_answer)
        for facet in ("ingresso", "jornada", "remuneração", "desenvolvimento funcional"):
            self.assertIn(f"Quanto a {facet},", final["answer"])
        self.assertEqual(final["reason_code"], "qa_archive_facet_evidence_map")
        self.assertEqual(len(final["sources"]), 5)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_natural_multitopic_history_question_keeps_facet_coverage(self, retrieve, generate):
        question = (
            "Na triagem de uma obra municipal, quais dispositivos da LC nº 258/2024 "
            "tratam do objeto do Código, de complementações ou notificações e de "
            "processos antigos sem despacho? Explique em poucas frases as regras distintas, "
            "cite cada artigo e diga o que um PDF extraído não confirma sobre alterações posteriores."
        )
        retrieve.return_value = [
            {
                "citation_id": f"qa:lc258-art{article}",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": f"Art. {article}",
                "full_text": text,
                "texto": text,
                "similarity_score": 0.6,
            }
            for article, text in (
                (1, "Art. 1º. Este Código tem por objeto disciplinar o licenciamento municipal."),
                (23, "Art. 23. As complementações e notificações serão registradas no processo."),
                (
                    262,
                    "Art. 262. Os processos antigos sem despacho decisório observarão a regra de transição.",
                ),
            )
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "O Código disciplina o licenciamento [[1]].",
                "grounded": True,
                "source_only": True,
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=2,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertNotEqual(final["reason_code"], "qa_archive_relation_history_unavailable")
        self.assertEqual(final["reason_code"], "qa_archive_facet_evidence_map")
        self.assertIn("Quanto a objeto do Código,", final["answer"])
        self.assertIn("Quanto a complementações ou notificações,", final["answer"])
        self.assertIn("Quanto a processos antigos sem despacho,", final["answer"])
        self.assertNotIn("- **", final["answer"])
        self.assertIn("não confirma a redação vigente, os fatos dos autos", final["answer"])
        self.assertIn("cadeia de alterações e revogações", final["answer"])
        self.assertEqual(len(final["sources"]), 3)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.rag_service.RAGService._validate_answer")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_article_change_history_followup_does_not_repeat_original_text_as_change(
        self, retrieve, validate, generate
    ):
        question = (
            "E quanto ao Art. 21: quais alterações posteriores da Lei Complementar nº "
            "120/2010 consigo verificar no acervo, e o que ainda falta para concluir a redação vigente?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art21-original",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 21",
                "full_text": (
                    "Art. 21. A carga horária semanal dos profissionais será de 30 horas, "
                    "na forma prevista nesta Lei."
                ),
                "texto": (
                    "Art. 21. A carga horária semanal dos profissionais será de 30 horas, "
                    "na forma prevista nesta Lei."
                ),
                "similarity_score": 1.0,
                "coverage": {"complete": True},
            }
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        retrieve.assert_called_once_with(question, limit=8)
        generate.assert_not_called()
        validate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_change_history_no_clause")
        self.assertFalse(final["grounded"])
        self.assertIn("não encontrei um ato posterior", final["answer"].lower())
        self.assertIn("redação arquivada de origem, não o ato alterador", final["answer"])
        self.assertIn("localizar e conferir os atos posteriores", final["answer"])
        self.assertIn("não prova que ele não exista", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_missing_legislative_matter_sources_are_disclosed_for_proposal_query(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
            }
        ]
        question = (
            "O PLC 9/2026 e a Emenda Supressiva 1/2026 alteraram ou revogaram "
            "o Art. 18 da Lei Complementar nº 120/2010? Diferencie proposta legislativa "
            "de lei publicada e indique o limite das evidências disponíveis."
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_unavailable")
        self.assertTrue(final["grounded"])
        self.assertIn("não trouxe documentos oficiais sobre a tramitação", final["answer"])
        self.assertIn("não permite dizer se a proposta foi aprovada, sancionada", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    @patch("src.processing.qa_archive_rag._metadata_only_sapl_norma_source", return_value=None)
    def test_missing_amendment_chain_is_explained_without_asking_user_to_rephrase(
        self, catalog_lookup, retrieve, generate
    ):
        question = "Quem alterou o art. 21 da Lei Complementar nº 55/2004 e em que data?"
        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        retrieve.assert_called_once_with(question, limit=8)
        generate.assert_not_called()
        final = events[-1]
        self.assertFalse(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_no_match")
        self.assertEqual(final["sources"], [])
        self.assertIn(
            "Não localizei no acervo evidência legível do texto de Art. 21", final["answer"]
        )
        self.assertIn("ato alterador", final["answer"])
        self.assertIn("A ausência de resultado não prova", final["answer"])
        self.assertIn("O status permanece inconclusivo", final["answer"])
        self.assertNotIn("tente outra formulação", final["answer"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_missing_amendment_chain_answers_yes_no_comparison_without_claiming_author_or_date(
        self, retrieve, generate
    ):
        question = (
            "A Lei Complementar nº 198/2021 alterou o art. 21 da Lei Complementar nº 55/2004? "
            "Compare a redação anterior e posterior ou informe a lacuna."
        )
        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        retrieve.assert_called_once_with(question, limit=8)
        generate.assert_not_called()
        final = events[-1]
        self.assertFalse(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_no_match")
        self.assertEqual(final["sources"], [])
        self.assertIn("se o dispositivo foi alterado ou revogado", final["answer"])
        self.assertIn("redações anterior e posterior", final["answer"])
        self.assertNotIn("quem alterou", final["answer"])
        self.assertNotIn("em que data", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    @patch("src.processing.qa_archive_rag._metadata_only_sapl_norma_source", return_value=None)
    def test_current_article_question_with_missing_evidence_says_text_and_vigency_are_unknown(
        self, catalog_lookup, retrieve, generate
    ):
        question = (
            "O que prevê o Art. 21 da Lei Complementar nº 55/2004? "
            "Indique se a resposta confirma a vigência atual."
        )
        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_no_match")
        self.assertEqual(final["sources"], [])
        self.assertIn("não posso informar a redação", final["answer"])
        self.assertIn("nem confirmar se o dispositivo foi alterado ou revogado", final["answer"])
        self.assertIn("O status permanece inconclusivo", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_ambiguous_multi_norm_article_question_explains_safe_separate_lookup(
        self, retrieve, generate
    ):
        question = (
            "Para avaliar um processo, compare Art. 21 e Art. 260 entre a LC nº 55/2004 "
            "e a LC nº 258/2024."
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_ambiguous_multi_norm_article_scope")
        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [])
        self.assertIn("informe cada referência completa", final["answer"])
        self.assertIn("histórico oficial de alterações", final["answer"])
        self.assertNotIn("Art. 21 da LC nº 55/2004", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True, JURIX_BUILD_PROFILE="qa")
    @patch("src.processing.qa_archive_rag._archive_relation_candidate_sources")
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_ambiguous_multi_norm_question_ignores_tangential_relation_candidate(
        self, retrieve, generate, relation_candidates
    ):
        question = (
            "A LC nº 219/2022 revogou os §§ 1º a 3º do Art. 83 da Lei nº 3.882/1989 "
            "e a Lei nº 6.535/2015. Confronte a cláusula do Art. 2º com os trechos "
            "disponíveis e explique se é possível afirmar a vigência hoje."
        )
        relation_candidates.return_value = [
            {
                "citation_id": "unrelated-candidate",
                "citation_label": "LC nº 164/2016, Art. 1º",
                "action_quote": "revogam-se",
                "target_text": "Lei nº 3.882/1989",
                "full_text": "Trecho não relacionado à cláusula consultada.",
                "relation_candidate": {"target_identity": {}},
            }
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_ambiguous_multi_norm_article_scope")
        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [])
        self.assertIn("associar com segurança cada artigo", final["answer"])
        self.assertNotIn("LC nº 164/2016", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_target_norm_overview_quotes_all_retrieved_articles_without_llm(
        self, retrieve, generate
    ):
        question = (
            "O que previa cada artigo da Lei nº 6.535/2015, indicada como revogada "
            "pelo Art. 2º da LC nº 219/2022? Liste os textos recuperados."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:law6535:art1",
                "norma_ref": "Lei nº 6.535/2015",
                "dispositivo_ref": "Art. 1º",
                "full_text": "Art. 1º Institui a regra A.",
                "coverage": {"selected_articles": 2, "total_articles": 2, "complete": True},
            },
            {
                "citation_id": "qa:law6535:art2",
                "norma_ref": "Lei nº 6.535/2015",
                "dispositivo_ref": "Art. 2º",
                "full_text": "Art. 2º Esta Lei entra em vigor na publicação.",
                "coverage": {"selected_articles": 2, "total_articles": 2, "complete": True},
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=1,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(
            final["reason_code"], "qa_archive_explicit_target_norm_verbatim_inventory"
        )
        self.assertEqual(len(final["sources"]), 2)
        self.assertIn("Art. 1º Institui a regra A.", final["answer"])
        self.assertIn("Art. 2º Esta Lei entra em vigor", final["answer"])
        self.assertIn("não confirmam efeitos posteriores nem a vigência atual", final["answer"])
        self.assertTrue(final["coverage"]["complete"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    def test_unmatched_repeal_transition_relation_does_not_invent_article_examples(
        self, retrieve, generate
    ):
        question = (
            "Como o Art. 260, inciso IV, da LC 258/2024, que revoga a LC 55/2004, "
            "se articula com a regra de transição do Art. 262? O que o procurador "
            "precisa verificar nos autos, sem presumir fatos do processo?"
        )

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_relation_history_no_match")
        self.assertEqual(final["sources"], [])
        self.assertIn("Não localizei no acervo evidência legível", final["answer"])
        self.assertIn("Art. 260", question)
        self.assertIn("Art. 262", question)
        self.assertNotIn("Art. 21 da LC nº 55/2004", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_paired_multi_norm_relation_returns_grounded_partial_evidence_without_overclaiming(
        self, retrieve, generate
    ):
        question = (
            "Para avaliar um processo, posso tratar o Art. 21 da LC 55/2004 como vigente hoje, "
            "já que o Art. 260, IV, da LC 258/2024 revoga a LC 55/2004?"
        )
        source = {
            "citation_id": "qa:lc258-art260",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 260",
            "full_text": (
                "Art. 260. Ficam revogados: IV - Lei Complementar nº 055 de 27 de janeiro de 2004."
            ),
            "coverage": {"extraction_status": "complete", "complete": False},
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_partial_multi_norm_article_scope")
        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [source])
        self.assertIn("Art. 260", final["answer"])
        self.assertIn("055", final["answer"])
        self.assertIn("Não localizei no acervo pesquisável o texto de Art. 21", final["answer"])
        self.assertIn("não bastam, por si sós, para confirmar a vigência", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_paired_article_question_with_historical_wording_uses_both_sources(
        self, retrieve, generate
    ):
        question = (
            "Em uma fundamentação hipotética, foi citado o art. 21 da Lei Complementar nº 55/2004. "
            "O que o art. 260, inciso IV, da LC nº 258/2024 diz sobre essa lei, e as fontes disponíveis "
            "permitem afirmar qual redação do art. 21 estava vigente em 2024?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art260",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260",
                "full_text": (
                    "Art. 260. Ficam revogados: IV - Lei Complementar nº 055 de 27 de janeiro de 2004."
                ),
                "similarity_score": 1.0,
            },
            {
                "citation_id": "qa:lc55-art21",
                "norma_ref": "Lei Complementar nº 55/2004",
                "dispositivo_ref": "Art. 21",
                "full_text": (
                    "Art. 21. A obra depende de licenciamento municipal e alvará de construção."
                ),
                "similarity_score": 0.9,
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        generate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_multi_norm_article_evidence_only")
        self.assertTrue(final["grounded"])
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertIn("Art. 260", final["answer"])
        self.assertIn("Art. 21", final["answer"])
        self.assertEqual(final["answer"].count("A obra depende"), 1)
        self.assertIn("não bastam, por si sós, para confirmar a vigência", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_promulgated_law_source_identity_pairs_with_later_explicit_repeal_clause(
        self, retrieve, generate
    ):
        question = (
            "A Lei Complementar nº 258/2024, Art. 260, inciso V, revoga expressamente "
            "o Art. 21 da Lei Promulgada nº 275/2009? O que os documentos disponíveis "
            "permitem afirmar e o que permanece pendente de confirmação jurídica?"
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art260-v",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 260, inciso V",
                "full_text": (
                    "Art. 260. Ficam revogados: V - Art. 21 da Lei Promulgada nº 275 "
                    "de 12 de março de 2009."
                ),
                "source_type": "PDF oficial — relação textual candidata, extração não revisada",
                "similarity_score": 1.0,
            },
            {
                "citation_id": "qa:lp275-art21",
                "norma_ref": "Lei Promulgada nº 275/2009",
                "dispositivo_ref": "Art. 21",
                "full_text": (
                    "Art. 21. O rebaixamento de guias para os fins de garantir a "
                    "acessibilidade é de responsabilidade do Executivo Municipal, "
                    "na forma estabelecida pela legislação vigente."
                ),
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "similarity_score": 0.9,
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_multi_norm_article_evidence_only")
        self.assertTrue(final["grounded"])
        self.assertIn("Lei Promulgada nº 275/2009", final["answer"])
        self.assertIn("O rebaixamento de guias", final["answer"])
        self.assertNotIn("Não localizei no acervo pesquisável", final["answer"])
        self.assertIn("pendentes de revisão", final["answer"])
        self.assertIn("não bastam, por si sós, para confirmar a vigência", final["answer"])
        self.assertEqual(len(final["grounding"]["claims"]), 2)

    def test_archive_requested_paragraph_range_excludes_adjacent_text(self):
        excerpt = (
            "Art. 83 São isentos do imposto. § 1º Texto antigo sobre receita bruta. "
            "(Revogado pela Lei Complementar nº 219 de 22/12/2022) § 2º Texto antigo "
            "sobre primeiro ano de atividade. (Revogado pela Lei Complementar nº 219 "
            "de 22/12/2022) § 3º Texto antigo sobre perda do benefício. (Revogado pela "
            "Lei Complementar nº 219 de 22/12/2022) § 4º Regra distinta não incluída "
            "no comando revogatório citado."
        )
        result = _archive_requested_paragraphs(
            "Compare os §§ 1º a 3º do Art. 83 da Lei nº 3.882/1989.",
            "83",
            excerpt,
        )

        self.assertIsNotNone(result)
        label, scoped_excerpt = result
        self.assertEqual(label, "§§ 1º–3º")
        self.assertIn("§ 1º Texto antigo", scoped_excerpt)
        self.assertIn("§ 3º Texto antigo", scoped_excerpt)
        self.assertNotIn("§ 4º Regra distinta", scoped_excerpt)
        self.assertIsNone(
            _archive_requested_paragraphs(
                "Compare os §§ 1º a 3º do Art. 83 da Lei nº 3.882/1989.",
                "84",
                excerpt,
            )
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_amendment_comparison_summarizes_changes_without_dumping_pdf(
        self, retrieve, generate
    ):
        question = (
            "Compare o texto do Art. 20 da Lei nº 3.882/1989 na consolidação municipal "
            "de 2024 com a redação substitutiva transcrita no "
            "Art. 1º da LC nº 271/2025. "
            "Em até três frases, explique somente as diferenças textuais, cite as fontes "
            "e não conclua vigência atual."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc271-art1",
                "norma_ref": "Lei Complementar nº 271/2025",
                "dispositivo_ref": "Art. 1º",
                "citation_label": "Lei Complementar nº 271/2025, Art. 1º",
                "full_text": (
                    "Os arts. 20 e 23 da Lei nº 3.882, de 11 de dezembro de 1989, "
                    "passam a vigorar com as seguintes redações: “Art. 20. Considera-se "
                    "ocorrido o fato gerador em primeiro (1º) de janeiro do exercício "
                    "a que corresponder o lançamento, nos prédios construídos ou ampliados "
                    "a partir da emissão da Certidão de Conclusão de Obra. Parágrafo único. "
                    "Quando se tratar de condomínio vertical, considera-se ocorrido o fato "
                    "gerador ... ........................................................................…"
                ),
                "similarity_score": 1.0,
            },
            {
                "citation_id": "qa:ctm-3882-art20-2022",
                "norma_ref": "Lei nº 3.882/1989",
                "dispositivo_ref": "Art. 20",
                "citation_label": "Lei nº 3.882/1989, Art. 20",
                "edition_label": "Consolidação municipal · exercício 2022 · revisão pendente",
                "full_text": (
                    "Art. 20 – Considera-se ocorrido o fato gerador a primeiro (1º) de "
                    "janeiro do exercício a que corresponder o lançamento, nos prédios "
                    "construídos durante o exercício anterior."
                ),
                "similarity_score": 0.92,
            },
            {
                "citation_id": "qa:ctm-3882-art20-2024",
                "norma_ref": "Lei nº 3.882/1989",
                "dispositivo_ref": "Art. 20",
                "citation_label": "Lei nº 3.882/1989, Art. 20",
                "edition_label": "Consolidação municipal · exercício 2024 · revisão pendente",
                "full_text": (
                    "Art. 20 – Considera-se ocorrido o fato gerador a primeiro (1º) de "
                    "janeiro do exercício a que corresponder o lançamento, nos prédios "
                    "construídos durante o exercício anterior."
                ),
                "similarity_score": 0.9,
            },
            {
                "citation_id": "qa:unrelated-lc219-art1",
                "norma_ref": "Lei Complementar nº 219/2023",
                "dispositivo_ref": "Art. 1º",
                "citation_label": "Lei Complementar nº 219/2023, Art. 1º",
                "full_text": "Art. 1º Dispositivo não relacionado à alteração tributária consultada.",
                "similarity_score": 0.7,
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        generate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_explicit_textual_amendment_comparison")
        self.assertTrue(final["source_only"])
        self.assertEqual(
            [source["citation_id"] for source in final["sources"]],
            ["qa:ctm-3882-art20-2024", "qa:lc271-art1"],
        )
        source_event = next(event for event in events if event["event"] == "sources")
        self.assertEqual(source_event["sources"], final["sources"])
        self.assertIn("exercício 2024", final["answer"])
        self.assertNotIn("exercício 2022", final["answer"])
        self.assertIn("a formulação da data-base", final["answer"])
        self.assertIn("prédios ampliados", final["answer"])
        self.assertIn("Certidão de Conclusão de Obra", final["answer"])
        self.assertIn("condomínios verticais", final["answer"])
        self.assertIn("termina com reticências", final["answer"])
        self.assertIn("não confirma vigência", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertNotIn("[[3]]", final["answer"])
        self.assertNotIn("a que corresponder o lançamento, nos prédios", final["answer"])
        self.assertEqual(final["coverage"]["coverage_status"], "textual_comparison_only")
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_comparison_isolates_amended_paragraph_and_prior_veto(self, retrieve, generate):
        question = (
            "Compare o Art. 31 da Lei nº 3.882/1989 na consolidação declarada como "
            "exercício de 2022 com o § 4º transcrito no Art. 1º da LC nº 219/2022. "
            "Mostre somente o cotejo textual e não conclua vigência atual."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc219-art1",
                "norma_ref": "Lei Complementar nº 219/2022",
                "dispositivo_ref": "Art. 1º",
                "citation_label": "Lei Complementar nº 219/2022, Art. 1º",
                "full_text": (
                    "Os artigos 25, 31, 38 e 41 da Lei 3.882, de 11 de dezembro de 1989, "
                    "passam a vigorar com as seguintes redações: “Art. 25 ... “Art. 31 "
                    "........................................................................ "
                    "§ 4º As áreas de terraços descobertos e quadras poliesportivas cujos "
                    "pisos sejam de grama natural ou sintética, areia ou terra serão "
                    "tributadas, para fins de IPTU e Taxa de Lixo, como terrenos. "
                    "........................................................................ “Art. 38 ..."
                ),
            },
            {
                "citation_id": "qa:ctm-art31-before-amendment",
                "norma_ref": "Lei nº 3.882/1989",
                "dispositivo_ref": "Art. 31",
                "citation_label": "Lei nº 3.882/1989, Art. 31",
                "edition_label": "Consolidação municipal · exercício 2022 · revisão pendente",
                "full_text": (
                    "Art. 31 A base de cálculo inclui a área do terreno e áreas construídas. "
                    "§ 4º Texto anterior deste dispositivo."
                ),
            },
            {
                "citation_id": "qa:ctm-art31-vetoed-occurrence",
                "norma_ref": "Lei nº 3.882/1989",
                "dispositivo_ref": "Art. 31",
                "citation_label": "Lei nº 3.882/1989, Art. 31",
                "edition_label": "Consolidação municipal · exercício 2022 · revisão pendente",
                "full_text": (
                    "Art. 31 A base de cálculo inclui a área do terreno e áreas construídas. "
                    "§ 4º VETADO (Incluído pela Lei Complementar nº 217, de 02/09/2022)."
                ),
            },
            {
                "citation_id": "qa:ctm-art31-2024",
                "norma_ref": "Lei nº 3.882/1989",
                "dispositivo_ref": "Art. 31",
                "citation_label": "Lei nº 3.882/1989, Art. 31",
                "edition_label": "Consolidação municipal · exercício 2024 · revisão pendente",
                "full_text": "Art. 31 Texto de edição posterior, fora do escopo pedido.",
            },
        ]

        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        generate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_explicit_textual_amendment_comparison")
        self.assertEqual(
            [source["citation_id"] for source in final["sources"]],
            ["qa:ctm-art31-vetoed-occurrence", "qa:lc219-art1"],
        )
        self.assertIn("§ 4º VETADO", final["answer"])
        self.assertIn("na edição anterior, o § 4º do Art. 31", final["answer"])
        self.assertIn("[[1]] [[2]]", final["answer"])
        self.assertIn("terraços descobertos", final["answer"])
        self.assertIn("exercício 2022", final["answer"])
        self.assertNotIn("edição posterior", final["answer"])
        self.assertNotIn("§ 4º Texto anterior deste dispositivo", final["answer"])
        self.assertIn("não confirma vigência", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_cross_reference_scan_does_not_turn_missing_match_into_whole_norm_claim(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc198-2",
                "norma_ref": "Lei Complementar nº 198/2021",
                "dispositivo_ref": "Art. 2º",
                "full_text": "Art. 2º A unidade terá organização própria e funcionamento regular.",
                "texto": "Art. 2º A unidade terá organização própria e funcionamento regular.",
                "similarity_score": 0.8,
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Quais artigos da Lei Complementar nº 198/2021 mencionam dispositivos "
                "da Lei Complementar nº 55/2004?",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
        retrieve.return_value = [
            {
                "citation_id": "qa:article-1",
                "norma_ref": "Lei Ordinária nº 6021/2009",
                "dispositivo_ref": "Art. 1º",
                "full_text": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
                "texto": "Art. 1º O Município institui o Programa Municipal de Hortas Comunitárias.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "O que prevê o Art. 1º da Lei nº 6.021/2009?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        self.assertLess(
            [event["event"] for event in events].index("sources"),
            [event["event"] for event in events].index("chunk"),
        )
        self.assertTrue(events[-1]["grounded"])
        self.assertIn("Programa Municipal de Hortas Comunitárias", events[-1]["answer"])
        self.assertIn("No PDF arquivado", events[-1]["answer"])
        self.assertIn(
            "**Art. 1º** da **Lei Ordinária nº 6021/2009** estabelece", events[-1]["answer"]
        )
        self.assertNotIn("O trecho extraído como", events[-1]["answer"])
        self.assertIn("[[1]]", events[-1]["answer"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_article_cannot_certify_case_document_sufficiency(self, retrieve, generate):
        provision = (
            "Art. 23. Durante a análise do processo administrativo de licenciamento, caso haja "
            "necessidade de solicitar correções, esclarecimentos e complementações, deverá ser "
            "expedida notificação para providências, contendo tais pendências urbanísticas, "
            "ambientais e/ou fundiárias existentes no processo."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art23",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 23",
                "full_text": provision,
                "texto": provision,
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Com base só no art. 23, posso concluir que a documentação deste processo está suficiente? "
                "(contexto normativo: Lei Complementar nº 258/2024; dispositivo de referência: Art. 23)",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_article_application_limits")
        self.assertIn(
            "não informa quais documentos foram juntados aos autos", final["answer"].lower()
        )
        self.assertIn("completa ou suficiente", final["answer"])
        self.assertIn("não examina os autos", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

        explicit_question = (
            "Com base só no Art. 23 da Lei Complementar nº 258/2024, posso concluir que "
            "a documentação deste processo está suficiente?"
        )
        explicit_events = list(
            stream_archive_qa_answer(
                explicit_question,
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )
        explicit_final = explicit_events[-1]
        self.assertEqual(explicit_final["reason_code"], "qa_archive_article_application_limits")
        self.assertIn(
            "não informa quais documentos foram juntados aos autos",
            explicit_final["answer"].lower(),
        )
        self.assertEqual(explicit_final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_transition_article_scope_question_explains_criteria_and_case_limits(
        self, retrieve, generate
    ):
        provision = (
            "Art. 262. Os processos de licenciamento de obras e edificações protocolados até "
            "a data de entrada em vigor desta Lei e sem despacho decisório, serão apreciados "
            "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
            "nos casos de manifestação formal do interessado, optando pela análise integral "
            "nos termos desta Lei."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": provision,
                "texto": provision,
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Qual regra o Art. 262 da Lei Complementar nº 258/2024 estabelece para "
                "processos protocolados antes da entrada em vigor e sem despacho? Explique o "
                "alcance e o que não é possível concluir sem dados do processo.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        answer = events[-1]["answer"]
        generate.assert_not_called()
        self.assertTrue(events[-1]["grounded"])
        self.assertEqual(events[-1]["sources"], retrieve.return_value)
        self.assertIn("legislação vigente na data do protocolo", answer)
        self.assertIn("manifestação formal do interessado", answer)
        self.assertIn("não concluo qual regime rege um processo concreto", answer)
        self.assertIn("data do protocolo", answer)
        self.assertIn("data oficial de entrada em vigor", answer)
        self.assertIn("se já havia despacho decisório", answer)
        self.assertIn("[[1]]", answer)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer,
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_transition_scope_takes_precedence_over_general_amendment_fallback(
        self, retrieve, generate
    ):
        provision = (
            "Art. 262. Os processos de licenciamento de obras e edificações protocolados até "
            "a data de entrada em vigor desta Lei e sem despacho decisório, serão apreciados "
            "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
            "nos casos de manifestação formal do interessado, optando pela análise integral "
            "nos termos desta Lei."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": provision,
                "texto": provision,
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Para triagem de um processo municipal de licenciamento protocolado antes da entrada "
                "em vigor da LC nº 258/2024: o que o art. 262 prevê? O PDF arquivado, sozinho, "
                "permite afirmar qual redação se aplica e se houve alterações posteriores? Separe "
                "o que o documento sustenta do que ainda precisa ser conferido.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        answer = final["answer"]
        generate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_transition_scope_explanation")
        self.assertIn("data do protocolo", answer)
        self.assertIn("data oficial de entrada em vigor", answer)
        self.assertIn("despacho decisório", answer)
        self.assertIn("manifestação formal", answer)
        self.assertIn("não contém uma cadeia de alterações e revogações revisada", answer)
        self.assertIn("não permite afirmar se este dispositivo mudou depois", answer)
        self.assertIn("não concluo qual regime rege um processo concreto", answer)
        self.assertIn("[[1]]", answer)
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer,
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_contextual_followup_about_decided_case_does_not_return_quote_only(
        self, retrieve, generate
    ):
        provision = (
            "Art. 262. Os processos de licenciamento de obras e edificações protocolados até "
            "a data de entrada em vigor desta Lei e sem despacho decisório, serão apreciados "
            "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
            "nos casos de manifestação formal do interessado, optando pela análise integral "
            "nos termos desta Lei."
        )
        source = {
            "citation_id": "qa:lc258-art262",
            "norma_ref": "Lei Complementar nº 258/2024",
            "dispositivo_ref": "Art. 262",
            "full_text": provision,
            "texto": provision,
            "similarity_score": 1.0,
            "source_type": "Acervo histórico local — extração pendente de revisão",
        }
        retrieve.return_value = [source]
        generate.return_value = iter(())

        events = list(
            stream_archive_qa_answer(
                "O art. 262 determina que, havendo despacho decisório, aplica-se automaticamente "
                "a lei nova? Responda apenas com o que o texto permite afirmar e cite o artigo. "
                "(contexto normativo: Lei Complementar nº 258/2024; dispositivo de referência: "
                "Art. 262)",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        answer = final["answer"]
        generate.assert_not_called()
        self.assertEqual(final["reason_code"], "qa_archive_transition_scope_explanation")
        self.assertIn("não determina que a lei nova se aplique automaticamente", answer)
        self.assertIn("ainda sem despacho", answer)
        self.assertIn("não define o regime aplicável a um processo que já tinha despacho", answer)
        self.assertNotIn("No PDF arquivado", answer)
        self.assertIn("[[1]]", answer)
        self.assertEqual(final["sources"], [source])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer,
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_transition_overview_without_explicit_article_gives_checklist_not_quote_only(
        self, retrieve, generate
    ):
        provision = (
            "Art. 262. Os processos de licenciamento de obras e edificações protocolados até "
            "a data de entrada em vigor desta Lei e sem despacho decisório, serão apreciados "
            "integralmente de acordo com a legislação em vigor à época do protocolo, exceto "
            "nos casos de manifestação formal do interessado, optando pela análise integral "
            "nos termos desta Lei."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": provision,
                "texto": provision,
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Em um processo de licenciamento de obra protocolado antes da LC 258/2024 e ainda "
                "sem despacho decisório, quais dispositivos da regra de transição devo conferir "
                "e quais fatos do processo o texto não resolve? Use apenas o PDF local e indique "
                "as limitações.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        answer = final["answer"]
        generate.assert_not_called()
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_transition_scope_explanation")
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "single_unreviewed_transition_article_with_case_fact_checklist",
        )
        self.assertIn("**Art. 262**", answer)
        self.assertIn("data do protocolo", answer)
        self.assertIn("data oficial de entrada em vigor", answer)
        self.assertIn("despacho decisório", answer)
        self.assertIn("manifestação formal", answer)
        self.assertIn("não comprova esses fatos", answer)
        self.assertIn("não concluo qual regime rege um processo concreto", answer)
        self.assertIn("[[1]]", answer)
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer,
        )

    def test_general_licensing_overview_is_not_misclassified_as_transition_request(self):
        general_question = (
            "Quais etapas do licenciamento de obras a LC nº 258/2024 prevê? Faça uma síntese "
            "dos dispositivos pertinentes e diga quais documentos ou fatos do processo eu "
            "teria de conferir antes de orientar um caso concreto."
        )
        explicit_transition_question = "Quais fatos do processo devo conferir para aplicar a regra de transição da LC 258/2024?"

        self.assertIsNone(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(general_question))
        self.assertIsNotNone(
            _PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(explicit_transition_question)
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_exact_article_quote_does_not_repeat_norm_in_citation(self, retrieve, generate):
        retrieve.return_value = [
            {
                "citation_id": "qa:decree-article-2",
                "norma_ref": "Decreto nº 7.795/2005",
                "dispositivo_ref": "Art. 2º",
                "full_text": "Art. 2º Constitui fonte de recursos para o crédito.",
                "texto": "Art. 2º Constitui fonte de recursos para o crédito.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "O que estabelece o Art. 2º do Decreto nº 7.795/2005?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        answer = events[-1]["answer"]
        generate.assert_not_called()
        self.assertIn("**Art. 2º** do **Decreto nº 7.795/2005** estabelece", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("metadados e segmentação ainda estão sob revisão", answer)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    @patch("src.processing.qa_archive_rag._metadata_only_sapl_norma_source", return_value=None)
    def test_stream_refuses_an_article_excerpt_that_does_not_support_requested_topic(
        self, catalog_lookup, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc120-art17",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17º",
                "full_text": "As atribuições gerais dos cargos definidos nesta Lei estão estabelecidas no Anexo III.",
                "texto": "As atribuições gerais dos cargos definidos nesta Lei estão estabelecidas no Anexo III.",
                "similarity_score": 1.0,
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "O que dispõe o art. 17º da Lei Complementar nº 120/2010 sobre gratificações?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        sources_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(sources_event["sources"], [])
        self.assertEqual(sources_event["reason_code"], "qa_archive_no_match")
        self.assertEqual(sources_event["coverage"]["coverage_status"], "unknown")
        self.assertFalse(final["grounded"])
        self.assertEqual(final["sources"], [])
        self.assertIn("Não localizei uma evidência legível", final["answer"])
        self.assertIn("não confirma que a norma ou o dispositivo não exista", final["answer"])
        self.assertIn("nem que esteja vigente", final["answer"])
        self.assertNotIn("atribuições gerais", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    @patch("src.processing.qa_archive_rag._metadata_only_sapl_norma_source")
    def test_explicit_norm_without_archive_text_links_catalog_as_metadata_only(
        self, catalog_lookup, retrieve, generate
    ):
        catalog_source = {
            "citation_id": "sapl:norma-catalog:9382",
            "citation_index": 1,
            "citation_label": "Lei Ordinária nº 8.201/2026 — cadastro no SAPL",
            "norma_ref": "Lei Ordinária nº 8.201/2026",
            "source_kind": "sapl_normative_catalog",
            "source_type": "Cadastro oficial SAPL — somente metadados",
            "evidence_scope": "official_normative_catalog_metadata",
            "sapl_url": "https://sapl.natal.rn.leg.br/norma/9382",
            "metadata_only": True,
        }
        catalog_lookup.return_value = catalog_source

        events = list(
            stream_archive_qa_answer(
                "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026?",
                k=5,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        catalog_lookup.assert_called_once()
        sources_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_catalog_metadata_only")
        self.assertFalse(final["grounded"])
        self.assertEqual(sources_event["sources"], [catalog_source])
        self.assertEqual(final["sources"], [catalog_source])
        self.assertIn("texto de Art. 1º não está integrado", final["answer"])
        self.assertIn("não o conteúdo do dispositivo", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertNotIn("8201/2026.pdf", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence", return_value=[])
    @patch("src.processing.qa_archive_rag._metadata_only_sapl_norma_source")
    @patch("src.processing.qa_archive_rag._official_dom_article_source")
    def test_exact_article_falls_back_to_official_gazette_without_claiming_currentness(
        self, gazette_lookup, catalog_lookup, retrieve, generate
    ):
        catalog_source = {
            "citation_id": "sapl:norma-catalog:9382",
            "citation_index": 1,
            "citation_label": "Lei Ordinária nº 8.201/2026 — cadastro no SAPL",
            "norma_ref": "Lei Ordinária nº 8.201/2026",
            "source_kind": "sapl_normative_catalog",
            "source_type": "Cadastro oficial SAPL — somente metadados",
            "evidence_scope": "official_normative_catalog_metadata",
            "sapl_url": "https://sapl.natal.rn.leg.br/norma/9382",
            "data_publicacao": "2026-09-10",
            "metadata_only": True,
        }
        article_source = {
            "citation_id": "dom:verified-article-1",
            "citation_label": "Lei Ordinária nº 8.201/2026, Art. 1º",
            "norma_ref": "Lei Ordinária nº 8.201/2026",
            "dispositivo_ref": "Art. 1º",
            "full_text": "Art. 1º Fica criado o Cadastro Protetor.",
            "source_kind": "official_gazette_extraction",
            "evidence_scope": "official_gazette_unreviewed_extraction",
            "pdf_url": "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20260910_"
            + "c" * 32
            + ".pdf",
        }
        catalog_lookup.return_value = catalog_source
        gazette_lookup.return_value = article_source

        events = list(
            stream_archive_qa_answer(
                "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026? Cite o dispositivo e mostre as fontes usadas.",
                k=5,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        gazette_lookup.assert_called_once_with(
            classify_normative_query(
                "O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026? Cite o dispositivo e mostre as fontes usadas."
            ).reference,
            "1",
            "2026-09-10",
        )
        source_event = next(event for event in events if event["event"] == "sources")
        final = events[-1]
        assert final["reason_code"] == "qa_archive_official_gazette_extraction_unreviewed"
        assert final["grounded"] is False
        assert "Art. 1º Fica criado o Cadastro Protetor." in final["answer"]
        assert "não verifica alterações posteriores" in final["answer"]
        assert "[[1]]" in final["answer"]
        assert source_event["sources"] == [article_source, catalog_source]
        assert final["sources"] == [article_source, catalog_source]

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_contextual_device_followup_quotes_exact_source_without_llm(self, retrieve):
        source = {
            "citation_id": "qa:lc120-art19",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 19º",
            "full_text": "Art. 19º A estrutura de cargos está baseada em classes e níveis, descritos no Anexo I.",
            "texto": "Art. 19º A estrutura de cargos está baseada em classes e níveis, descritos no Anexo I.",
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]
        events = list(
            stream_archive_qa_answer(
                "Com base no trecho citado, explique isso "
                "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 19º)",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        self.assertEqual(events[-1]["reason_code"], "qa_archive_contextual_device_verbatim")
        self.assertIn(source["full_text"], events[-1]["answer"])
        self.assertIn("No PDF arquivado", events[-1]["answer"])
        self.assertIn(
            "**Art. 19º** da **Lei Complementar nº 120/2010** estabelece", events[-1]["answer"]
        )
        self.assertNotIn("O trecho extraído como", events[-1]["answer"])
        self.assertNotIn("O trecho, por si só", events[-1]["answer"])
        self.assertIn("[[1]]", events[-1]["answer"])
        self.assertEqual(events[-1]["grounding"]["claims"][0]["text"], source["full_text"])
        self.assertEqual(events[-1]["sources"], [source])
        self.assertTrue(events[-1]["grounded"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_art_18_followup_never_substitutes_another_hardcoded_device_summary(self, retrieve):
        source = {
            "citation_id": "qa:lc120-art18",
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 18º",
            "full_text": "O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.",
            "similarity_score": 1.0,
        }
        retrieve.return_value = [source]
        events = list(
            stream_archive_qa_answer(
                "E qual é o valor mínimo mencionado? "
                "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 18º)",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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

        events = list(
            stream_archive_qa_answer(
                "E qual artigo trata do vencimento básico? "
                "(contexto normativo: Lei Complementar nº 120/2010)",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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

        events = list(
            stream_archive_qa_answer(
                "Transcreva os arts. 17 e 18 da Lei Complementar nº 120/2010.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
    def test_contextual_norm_does_not_prevent_transcribing_all_paired_articles(
        self, retrieve, generate
    ):
        coverage = {
            "requested_article_norm_pairs": [
                {"normative_identity": ["lei_complementar", "258", 2024], "article": article}
                for article in ("259", "260", "262")
            ],
            "missing_article_norm_pairs": [],
            "complete": True,
        }
        retrieve.return_value = [
            {
                "citation_id": f"qa:lc258-art{article}",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": f"Art. {article}",
                "full_text": text,
                "texto": text,
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "coverage": coverage,
            }
            for article, text in (
                ("259", "Art. 259. Processos anteriores serão apreciados pela regra temporal."),
                ("260", "Art. 260. Ficam revogados: IV - Lei Complementar nº 055/2004."),
                ("262", "Art. 262. Processos sem despacho serão apreciados pela lei do protocolo."),
            )
        ]

        events = list(
            stream_archive_qa_answer(
                "No Código de Obras da Lei Complementar nº 258/2024, o que dizem os arts. "
                "259, 260 e 262 sobre processos anteriores e revogação da LC 55/2004?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_multi_norm_article_evidence_only")
        self.assertTrue(final["grounded"])
        for article in ("259", "260", "262"):
            self.assertIn(f"Art. {article}", final["answer"])
        self.assertEqual(len(final["sources"]), 3)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_protocol_and_transition_articles_are_synthesized_with_case_limits(
        self, retrieve, generate
    ):
        question = (
            "Em um caso hipotético de licenciamento, se o processo foi protocolado antes da "
            "entrada em vigor da LC nº 258/2024 e ainda estava sem despacho decisório, qual "
            "regra de análise aparece nos arts. 259 e 262? Há alguma opção formal do "
            "interessado? Indique o que os trechos permitem concluir e o que ainda precisa "
            "ser conferido."
        )
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art259",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 259",
                "full_text": (
                    "Art. 259. Serão aplicadas, na análise do processo de licenciamento, "
                    "as legislações vigentes na data do protocolo do processo."
                ),
                "texto": "Art. 259. Serão aplicadas as legislações vigentes na data do protocolo do processo.",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            },
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": (
                    "Art. 262. Os processos de licenciamento protocolados até a data de entrada "
                    "em vigor desta Lei e sem despacho decisório serão apreciados integralmente "
                    "de acordo com a legislação em vigor à época do protocolo, exceto nos casos "
                    "de manifestação formal do interessado, optando pela análise integral nos "
                    "termos desta Lei."
                ),
                "texto": "Art. 262. Os processos de licenciamento protocolados até a entrada em vigor...",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            },
        ]

        self.assertTrue(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question))
        self.assertTrue(
            _PROCESS_TRANSITION_EVIDENCE_RE.search(retrieve.return_value[1]["full_text"])
        )
        self.assertEqual(
            len(_explicit_article_norm_pairs(question)),
            len(_article_reference_mentions(question)),
        )
        self.assertIsNotNone(
            _archive_explicit_transition_pair_synthesis(question, retrieve.return_value)
        )
        events = list(
            stream_archive_qa_answer(
                question,
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = next(event for event in events if event.get("event") == "done")
        answer = final["answer"]
        self.assertEqual(final["reason_code"], "qa_archive_explicit_transition_pair_synthesis")
        self.assertIn("legislação vigente na data do protocolo", answer)
        self.assertIn("sem despacho decisório", answer)
        self.assertIn("manifestação formal", answer)
        self.assertIn("não verifica os fatos dos autos", answer)
        self.assertIn("[[1]]", answer)
        self.assertIn("[[2]]", answer)
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "explicit_protocol_and_transition_articles_only_no_case_adjudication",
        )
        self.assertEqual(final["sources"], retrieve.return_value)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            answer,
        )

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_article_application_limits_answer_quotes_source_and_states_what_it_cannot_prove(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art59",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 59",
                "full_text": (
                    "Art. 59. As inconformidades listadas no art. 54, com existência comprovada "
                    "na base cartográfica do ano de 2006, serão tratadas como legalização."
                ),
                "texto": "Art. 59. As inconformidades listadas no art. 54...",
                "similarity_score": 1.0,
                "source_type": "Acervo histórico local — extração pendente de revisão",
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Com base no PDF local da Lei Complementar nº 258/2024, explique o que prevê "
                "o Art. 59 e o que esse trecho não permite concluir sobre a regularidade atual "
                "de uma obra específica.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_not_called()
        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_article_application_limits")
        self.assertIn("base cartográfica do ano de 2006", final["answer"])
        self.assertIn(
            "não permite concluir se uma obra específica está regular hoje", final["answer"]
        )
        self.assertIn("[[1]]", final["answer"])
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_explicit_multi_article_comparison_uses_grounded_generation(self, retrieve, generate):
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

        def partial_grounded_generation():
            yield {"event": "chunk", "chunk": generated_answer, "provisional": False}
            return {
                "answer": generated_answer,
                "validated_prefix": generated_answer,
                "partial": True,
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
            }

        generate.return_value = partial_grounded_generation()

        events = list(
            stream_archive_qa_answer(
                "Compare em linguagem simples o conteúdo dos arts. 18 e 19 da "
                "Lei Complementar nº 120/2010.",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        generate.assert_called_once()
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "generation_partial_after_grounded_prefix")
        self.assertEqual(final["answer"], generated_answer)
        self.assertIn("fixa um piso", final["answer"])
        self.assertIn("organiza", final["answer"])
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
            "buffered model output must be re-emitted only after the validated answer is final",
        )
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_multi_article_stream_releases_first_cited_article_while_generation_continues(
        self, retrieve, generate
    ):
        coverage = {"requested_articles": ["17", "18"], "missing_articles": [], "complete": True}
        retrieve.return_value = [
            {
                "citation_id": "qa:article-17-stream",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17",
                "full_text": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "texto": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
            {
                "citation_id": "qa:article-18-stream",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "texto": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
        ]
        first_claim = "O Art. 17 trata das atribuições dos cargos. [[1]] "
        second_claim = "O Art. 18 fixa o piso do vencimento básico. [[2]] "
        closing_claim = "Os dispositivos regulam aspectos distintos. [[1]] [[2]]"
        final_answer = first_claim + second_claim + closing_claim
        state = {"coverage_complete": False, "generation_finished": False}
        result = {
            "answer": final_answer,
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": [
                    {"text": "Atribuições dos cargos.", "citation_ids": ["qa:article-17-stream"]},
                    {"text": "Piso do vencimento.", "citation_ids": ["qa:article-18-stream"]},
                ],
                "failed_claims": [],
            },
            "source_only": True,
            "generation_attempts": [{"duration_ms": 4000}],
            "partial": False,
        }

        def progressive_generation(*_args, **_kwargs):
            yield {"event": "chunk", "chunk": first_claim, "provisional": False}
            state["coverage_complete"] = True
            yield {"event": "chunk", "chunk": second_claim, "provisional": False}
            yield {"event": "chunk", "chunk": closing_claim, "provisional": False}
            state["generation_finished"] = True
            return result

        generate.side_effect = progressive_generation
        events = stream_archive_qa_answer(
            "Na Lei Complementar nº 120/2010, compare os Arts. 17 e 18 e cite cada dispositivo.",
            k=8,
            model="qwen3:8b",
            temperature=0.1,
            text_provider={"provider": "ollama"},
            ollama=MagicMock(),
        )

        first_visible_chunk = next(event for event in events if event["event"] == "chunk")

        self.assertFalse(state["coverage_complete"])
        self.assertFalse(state["generation_finished"])
        self.assertEqual(first_visible_chunk["chunk"], first_claim)
        remaining = list(events)
        final = remaining[-1]
        visible_answer = first_visible_chunk["chunk"] + "".join(
            event.get("chunk", "") for event in remaining if event["event"] == "chunk"
        )
        self.assertTrue(state["generation_finished"])
        self.assertEqual(final["event"], "done")
        self.assertTrue(final["grounded"])
        self.assertEqual(visible_answer, final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_multi_article_stream_explains_the_uncovered_requested_article(
        self, retrieve, generate
    ):
        coverage = {"requested_articles": ["17", "18"], "missing_articles": [], "complete": True}
        retrieve.return_value = [
            {
                "citation_id": "qa:article-17-partial-stream",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 17",
                "full_text": "Art. 17. As atribuições gerais dos cargos estão no Anexo III.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
            {
                "citation_id": "qa:article-18-partial-stream",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "Art. 18. O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": coverage,
            },
        ]
        visible_claim = "O Art. 17 trata das atribuições dos cargos. [[1]]"

        def partial_generation():
            yield {"event": "chunk", "chunk": visible_claim, "provisional": False}
            return {
                "answer": visible_claim
                + "\n\nA resposta foi limitada ao que as fontes consultadas permitem confirmar.",
                "validated_prefix": visible_claim,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": "Atribuições dos cargos.",
                            "citation_ids": ["qa:article-17-partial-stream"],
                        }
                    ],
                    "failed_claims": [],
                },
                "source_only": True,
                "generation_attempts": [{"duration_ms": 50}],
                "partial": True,
            }

        generate.return_value = partial_generation()
        events = list(
            stream_archive_qa_answer(
                "Na Lei Complementar nº 120/2010, compare os Arts. 17 e 18 e cite cada dispositivo.",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        visible_answer = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "generation_partial_missing_requested_article")
        self.assertIn("Art. 18", final["answer"])
        self.assertIn("não entrou na síntese validada", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertEqual(visible_answer, final["answer"])
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
        generate.return_value = _completed_generation_stream(
            {
                "answer": incomplete_answer,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": "O Art. 17 trata das atribuições.",
                            "citation_ids": ["qa:article-17"],
                        }
                    ],
                    "failed_claims": [],
                },
                "source_only": True,
                "generation_attempts": [{"duration_ms": 25}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Na Lei Complementar nº 120/2010, explique separadamente o conteúdo dos Arts. 17 e 18 "
                "e compare o tema de cada um. Use somente os trechos recuperados do PDF, cite cada "
                "afirmação pelo artigo correspondente e diga se a extração não permitir uma conclusão.",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_comparison_evidence_fallback")
        self.assertIn("**Art. 17**", final["answer"])
        self.assertIn("**Art. 18**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
        self.assertNotEqual(final["answer"], incomplete_answer)
        self.assertFalse(
            any(
                event.get("event") == "chunk" and event.get("chunk") == incomplete_answer
                for event in events
            )
        )
        self.assertEqual(final["sources"], retrieve.return_value)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_followup_selects_the_matching_article_from_prior_same_norm_device_set(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:article-18",
                "norma_ref": "Lei Complementar nº 120/2010",
                "dispositivo_ref": "Art. 18",
                "full_text": "O vencimento básico não poderá ser inferior ao salário mínimo nacional vigente.",
                "similarity_score": 1.0,
                "coverage": {"requested_articles": ["17", "18"], "complete": True},
            }
        ]

        events = list(
            stream_archive_qa_answer(
                "Qual dos dois dispositivos trata do salário mínimo? "
                "(contexto normativo: Lei Complementar nº 120/2010; "
                "dispositivos de referência: Arts. 17 e 18)",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
    def test_rejected_article_comparison_falls_back_to_cited_excerpts(self, retrieve, generate):
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
        generate.return_value = _completed_generation_stream(
            {
                "answer": "Paráfrase rejeitada.",
                "grounding": {"grounded": False, "claims": [], "failed_claims": ["unverified"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 30}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Compare em linguagem simples os arts. 18 e 19 da Lei Complementar nº 120/2010.",
                k=8,
                model="qwen3:8b",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

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
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_rejected_two_article_followup_returns_both_explicitly_scoped_sources(
        self, retrieve, generate
    ):
        retrieve.return_value = [
            {
                "citation_id": "qa:lc258-art262",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 262",
                "full_text": "Art. 262. Processos protocolados antes da vigência e sem despacho seguem a legislação da data do protocolo, salvo opção formal pela lei nova.",
                "similarity_score": 1.0,
                "coverage": {"complete": True, "requested_articles": ["262", "266"]},
            },
            {
                "citation_id": "qa:lc258-art266",
                "norma_ref": "Lei Complementar nº 258/2024",
                "dispositivo_ref": "Art. 266",
                "full_text": "Art. 266. Esta Lei Complementar entra em vigor 90 dias após a data de sua publicação.",
                "similarity_score": 1.0,
                "coverage": {"complete": True, "requested_articles": ["262", "266"]},
            },
        ]
        generate.return_value = _completed_generation_stream(
            {
                "answer": "A relação entre os dois artigos está demonstrada. [[1]] [[2]]",
                "grounding": {
                    "grounded": False,
                    "claims": [],
                    "failed_claims": ["relação não sustentada"],
                },
                "source_only": False,
                "generation_attempts": [{"duration_ms": 25}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Resuma a relação entre o Art. 262 (regra transitória) e o Art. 266 (vigência) da Lei Complementar nº 258/2024. Cite os dois dispositivos separadamente e não calcule a data em calendário.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_comparison_evidence_fallback")
        self.assertIn("**Art. 262**", final["answer"])
        self.assertIn("**Art. 266**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[2]]", final["answer"])
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
        generate.return_value = _completed_generation_stream(
            {
                "answer": "fallback do validador",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que prevê a Lei nº 6021/2009?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        prompt = generate.call_args.args[0]
        self.assertIn("INSTRUÇÃO ESPECÍFICA — VISÃO GERAL DA NORMA", prompt)
        self.assertIn("escreva exatamente 1", prompt)
        self.assertIn("um artigo e um marcador distinto por frase", prompt)
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertEqual(final["sources"], [source])
        self.assertIn("3 dos 16 artigos identificados na extração", final["answer"])
        self.assertIn("1 excerto selecionado", final["answer"])
        self.assertNotIn("a geração usou", final["answer"])
        self.assertIn("anexos identificados que não foram incluídos", final["answer"])
        self.assertIn("Fontes Consultadas", final["answer"])
        self.assertIn("excertos literais e abreviados", final["answer"])
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
        generate.return_value = _completed_generation_stream(
            {
                "answer": "A síntese inclui uma afirmação não sustentada.",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 5}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Quais são os principais temas da Lei nº 6021/2009? Informe se a cobertura é parcial.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertEqual(final["sources"], sources)
        self.assertIn("Art. 9º", [source["dispositivo_ref"] for source in final["sources"]])
        self.assertNotIn("entra em vigor", final["answer"].casefold())
        self.assertNotIn("disposições em contrário", final["answer"].casefold())
        self.assertEqual(final["answer"].count("[["), 3)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_grounded_partial_overview_always_discloses_scope_and_annexes(self, retrieve, generate):
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
        candidate = (
            "O Art. 1º trata do tema A. [[1]] O Art. 10º trata do tema B. [[2]] "
            "O Art. 19º trata do tema C. [[3]]"
        )
        generate.return_value = _completed_generation_stream(
            {
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
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertIsNone(final["reason_code"])
        self.assertTrue(final["answer"].startswith(candidate))
        self.assertIn(
            "A recuperação encontrou evidências em 19 de 39 artigos identificados.", final["answer"]
        )
        self.assertIn("não representa uma análise integral da norma", final["answer"])
        self.assertIn("Anexos normativos também foram detectados", final["answer"])
        self.assertTrue(all(marker in final["answer"] for marker in ("[[1]]", "[[2]]", "[[3]]")))
        self.assertEqual(final["sources"], sources)
        self.assertEqual(
            "".join(event.get("chunk", "") for event in events if event["event"] == "chunk"),
            final["answer"],
        )

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
        candidate = (
            "O Art. 1º abre crédito suplementar. [[1]] O Art. 2º define sua fonte. [[2]] "
            "O Art. 3º disciplina a vigência. [[3]]"
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": candidate,
                "grounding": {
                    "grounded": True,
                    "claims": [
                        {
                            "text": "O decreto abre crédito suplementar.",
                            "citation_ids": ["qa:decree-overview-1"],
                        }
                    ],
                    "failed_claims": [],
                },
                "source_only": True,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que prevê o Decreto municipal nº 7795/2005? Faça uma visão geral dos artigos.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        self.assertTrue(generate.call_args.kwargs["retry_after_partial_rejection"])
        self.assertIn("VISÃO GERAL PARCIAL", generate.call_args.kwargs["revision_instruction"])
        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertTrue(final["answer"].startswith(candidate))
        self.assertIn(
            "A recuperação encontrou evidências em 3 de 3 artigos identificados", final["answer"]
        )
        self.assertIn(
            "anexos normativos detectados não foram incluídos nesta seleção", final["answer"]
        )
        self.assertIn("a visão geral é parcial", final["answer"])
        self.assertNotIn("Anexos normativos também foram detectados", final["answer"])

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_whole_norm_coverage_question_gets_deterministic_article_and_annex_counts(
        self, retrieve, generate
    ):
        coverage = {
            "complete": True,
            "selected_articles": 3,
            "total_articles": 3,
            "annexes_present": False,
        }
        sources = [
            {
                "citation_id": f"qa:coverage-{article}",
                "norma_ref": "Lei nº 6021/2009",
                "dispositivo_ref": f"Art. {article}º",
                "full_text": f"Art. {article}º Texto normativo verificável {article}.",
                "texto": f"Art. {article}º Texto normativo verificável {article}.",
                "similarity_score": 0.8,
                "coverage": coverage,
            }
            for article in (1, 2, 3)
        ]
        retrieve.return_value = sources
        candidate = (
            "O Art. 1º define o objeto. [[1]] O Art. 2º define os componentes. [[2]] "
            "O Art. 3º indica a vigência. [[3]]"
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": candidate,
                "grounding": {
                    "grounded": True,
                    "claims": [
                        {
                            "text": f"O artigo {article} define seu conteúdo.",
                            "citation_ids": [f"qa:coverage-{article}"],
                        }
                        for article in (1, 2, 3)
                    ],
                    "failed_claims": [],
                },
                "source_only": True,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Faça uma visão geral da Lei nº 6021/2009 e informe quantos artigos foram "
                "recuperados e se os anexos foram considerados.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        self.assertTrue(final["grounded"])
        self.assertIn(
            "A extração identificou 3 artigos, e a busca recuperou todos.", final["answer"]
        )
        self.assertIn("O parser não detectou anexos normativos", final["answer"])
        self.assertIn("pendente de revisão", final["answer"])
        self.assertTrue(all(marker in final["answer"] for marker in ("[[1]]", "[[2]]", "[[3]]")))

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
                (
                    1,
                    "Fica aberto à Secretaria Municipal de Meio Ambiente o crédito suplementar de R$ 12.000,00.",
                ),
                (
                    2,
                    "Constitui fonte de recursos para o crédito a anulação de dotação orçamentária.",
                ),
                (3, "Este Decreto entra em vigor na data de sua publicação."),
            )
        ]
        retrieve.return_value = sources
        validate.return_value = {"grounded": False}
        generate.return_value = _completed_generation_stream(
            {
                "answer": "O decreto parece autorizar um crédito especial no orçamento.",
                "grounding": {"grounded": False, "failed_claims": ["unsupported"]},
                "source_only": False,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que estabelece o Decreto nº 7795/2005?",
                k=5,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_evidence_map_fallback")
        self.assertEqual(final["sources"], sources)
        self.assertEqual(streamed_text, final["answer"])
        self.assertNotIn("crédito especial", final["answer"])
        self.assertTrue(
            final["answer"].startswith(
                "A busca local recuperou estes trechos relacionados à pergunta."
            )
        )
        self.assertIn(
            "não comprovam que todos os dispositivos pertinentes foram encontrados",
            final["answer"],
        )
        self.assertNotIn("Não consegui validar uma síntese", final["answer"])
        self.assertIn("Art. 1º", final["answer"])
        self.assertIn("crédito suplementar de R$ 12.000,00", final["answer"])
        self.assertIn("Art. 2º", final["answer"])
        self.assertNotIn("**Art. 1º**:", final["answer"])
        self.assertNotIn("**Art. 2º**:", final["answer"])
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
        candidate = "A Lei Complementar nº 120/2010 estabelece regras para o PCCV-Saúde. [[18]]"
        generate.return_value = _completed_generation_stream(
            {
                "answer": candidate,
                "grounding": {
                    "grounded": True,
                    "claims": [{"text": candidate, "citation_ids": ["qa:article-18"]}],
                    "failed_claims": [],
                },
                "source_only": True,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Em linhas gerais, como a Lei Complementar nº 120/2010 organiza o PCCV e quais "
                "três cautelas devo observar antes de aplicar esses excertos a um processo?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        source_event_index = next(
            i for i, event in enumerate(events) if event["event"] == "sources"
        )
        first_chunk_index = next(i for i, event in enumerate(events) if event["event"] == "chunk")
        self.assertLess(source_event_index, first_chunk_index)
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        final = events[-1]
        self.assertNotIn("estabelece regras para o PCCV-Saúde", streamed_text)
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("excertos literais e abreviados", final["answer"])
        self.assertIn("19 dos 39 artigos identificados na extração", final["answer"])
        self.assertIn("3 excertos selecionados", final["answer"])
        self.assertIn("este mapa é parcial e não é uma síntese integral", final["answer"])
        self.assertIn("Como roteiro geral de triagem", final["answer"])
        self.assertIn("não como requisitos atribuídos a esta lei", final["answer"])
        self.assertIn("**Texto e vigência:**", final["answer"])
        self.assertIn("**Fatos e estágio dos autos:**", final["answer"])
        self.assertIn("**Contexto normativo:**", final["answer"])
        self.assertNotIn("**Art. 1º**", final["answer"])
        self.assertNotIn("**Art. 10º**", final["answer"])
        self.assertNotIn("**Art. 19º**", final["answer"])
        self.assertNotIn("**Art. 5º**", final["answer"])
        self.assertNotIn("**Art. 15º**", final["answer"])
        self.assertIn("[[1]]", final["answer"])
        self.assertIn("[[19]]", final["answer"])
        self.assertIn("[[10]]", final["answer"])
        self.assertNotIn("[[5]]", final["answer"])
        self.assertNotIn("[[15]]", final["answer"])
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
        narrower_prefix = (
            "O programa é tratado no Art. 1º. [[1]] Os critérios aparecem no Art. 10º. [[10]]"
        )
        generate.return_value = _completed_generation_stream(
            {
                "answer": narrower_prefix
                + "\n\nA resposta foi limitada ao que as fontes consultadas permitem confirmar.",
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
            }
        )

        events = list(
            stream_archive_qa_answer(
                "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos principais temas.",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "generation_partial_after_grounded_prefix")
        self.assertEqual(
            final["grounding"]["validation_scope"],
            "grounded_generated_claims_against_sampled_excerpts_from_unreviewed_archive_pdf",
        )
        self.assertTrue(final["answer"].startswith(prefix))
        self.assertNotIn("[[1]] [[10]]", final["answer"][: len(prefix)])
        self.assertIn("A recuperação encontrou evidências em 19 de 39 artigos", final["answer"])
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
            yield {
                "event": "chunk",
                "chunk": "O Art. 19º organiza a execução administrativa. [[19]]",
            }
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
            event.get("chunk", "") for event in remaining if event["event"] == "chunk"
        )
        self.assertTrue(state["generation_finished"])
        self.assertEqual(final["event"], "done")
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("recuperação encontrou evidências em 19 de 39 artigos", final["answer"])
        self.assertEqual(len(final["sources"]), 19)

    @override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
    @patch("src.processing.qa_archive_rag.stream_grounded_generation")
    @patch("src.processing.qa_archive_rag.retrieve_archive_evidence")
    def test_partial_overview_generates_from_distributed_excerpt_context(self, retrieve, generate):
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
        candidate = (
            "O Art. 1º aborda o tema 1. [[1]] O Art. 10º aborda o tema 10. [[10]] "
            "O Art. 19º aborda o tema 19. [[19]]"
        )
        ollama_client = MagicMock()
        generate.return_value = _completed_generation_stream(
            {
                "answer": candidate,
                "grounding": {"grounded": True, "claims": [], "failed_claims": []},
                "source_only": True,
                "generation_attempts": [{"duration_ms": 10}],
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Faça uma síntese curta da Lei Complementar nº 120/2010 para triagem de um "
                "processo de licenciamento: o que não posso concluir sem conferir os autos "
                "e a publicação oficial?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=ollama_client,
            )
        )

        prompt = generate.call_args.args[0]
        generate.call_args.kwargs["stream_attempt"]("probe")
        self.assertEqual(ollama_client.stream_text.call_args.kwargs["temperature"], 0.0)
        self.assertIn("[[1]] Lei Complementar nº 120/2010, Art. 1º", prompt)
        self.assertIn("[[10]] Lei Complementar nº 120/2010, Art. 10º", prompt)
        self.assertIn("[[19]] Lei Complementar nº 120/2010, Art. 19º", prompt)
        self.assertNotIn("Art. 2º O dispositivo estabelece", prompt)
        self.assertNotIn("Art. 5º O dispositivo estabelece", prompt)
        self.assertIn("A geração recebeu 3 excertos distribuídos entre 19 dispositivos", prompt)
        self.assertIn("anexos normativos", prompt.casefold())
        self.assertIn("escreva exatamente 3", prompt.casefold())
        self.assertIn("um artigo e um marcador distinto por frase", prompt.casefold())
        self.assertIn("não use heading, lista, conclusão", prompt.casefold())
        self.assertIn(
            "paráfrase mínima, preserve o verbo operativo e a modalidade", prompt.casefold()
        )
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
            "a geração usou 3 excertos de 19 dispositivos recuperados",
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
    def test_partial_generation_for_whole_norm_uses_literal_evidence_map(self, retrieve, generate):
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
        partial_answer = "A norma trata de estrutura, carreira e gratificações. [[1]] [[2]] [[3]]"
        generate.return_value = _completed_generation_stream(
            {
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
            }
        )

        events = list(
            stream_archive_qa_answer(
                "Faça uma síntese curta da Lei Complementar nº 120/2010 para triagem de um "
                "processo de licenciamento: o que não posso concluir sem conferir os autos "
                "e a publicação oficial?",
                k=8,
                model="llama3",
                temperature=0.1,
                text_provider={"provider": "ollama"},
                ollama=MagicMock(),
            )
        )

        final = events[-1]
        streamed_text = "".join(
            event.get("chunk", "") for event in events if event["event"] == "chunk"
        )
        self.assertTrue(final["grounded"])
        self.assertEqual(final["reason_code"], "qa_archive_partial_overview_evidence_map")
        self.assertNotIn("A norma trata de estrutura, carreira", final["answer"])
        self.assertNotIn("A síntese ficou incompleta", streamed_text)
        self.assertEqual(streamed_text, final["answer"])
        self.assertIn("5 dos 39 artigos identificados na extração", final["answer"])
        self.assertIn("3 excertos selecionados", final["answer"])
        self.assertIn("este mapa é parcial e não é uma síntese integral", final["answer"])
        self.assertIn("correspondência textual ao assunto indicado", final["answer"])
        self.assertIn("Esses excertos não trazem os fatos dos autos", final["answer"])
        self.assertIn(
            "não permitem concluir a situação de uma obra ou processo concreto", final["answer"]
        )
        self.assertIn("histórico de alterações", final["answer"])
        self.assertNotIn("**Art. 1º**", final["answer"])
        self.assertNotIn("**Art. 19º**", final["answer"])
        self.assertNotIn("**Art. 37º**", final["answer"])
        self.assertNotIn("**Art. 10º**", final["answer"])
        self.assertEqual(len(re.findall(r"\[\[\d+\]\]", final["answer"])), 3)
        self.assertTrue(all(source in final["sources"] for source in retrieve.return_value))
        self.assertIn("VISÃO GERAL PARCIAL", generate.call_args.kwargs["revision_instruction"])
