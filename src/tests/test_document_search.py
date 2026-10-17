from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.document_search import (
    _query_groups,
    _requested_archive_types,
    _without_explicit_norm_identity,
    search_archive_documents,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _document(
    index: int,
    *,
    filename: str = "Lei_Complementar_198_2021.pdf",
    text: str = "Art. 1º Texto de teste.",
    identity_type: str = "lei_complementar",
    number: str = "198",
    year: int = 2021,
    publication_date: str | None = None,
    review_status: str = DocumentoNormativo.ReviewStatus.PENDING,
    extraction_status: str | None = "complete",
):
    document = DocumentoNormativo.objects.create(
        document_key=_digest(f"document-search-key-{index}"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref=f"archive:qa:entry:{index}",
        entry_index=index,
        entry_name=f"normas/{filename}",
        original_filename=filename,
        content_sha256=_digest(f"document-search-content-{index}"),
        review_status=review_status,
        metadata_json={
            "identity_status": "candidate",
            "identity_candidate": {
                "type": identity_type,
                "number": number,
                "year": year,
            },
        },
    )
    if extraction_status:
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version=f"document-search-test-{index}",
            policy_fingerprint=_digest(f"search-policy-{index}"),
            text_version="legal-text-test-v1",
            raw_text=text,
            legal_text=text,
            page_count=2,
            metadata_candidates_json=(
                {"publication": {"data_publicacao": publication_date}}
                if publication_date
                else {}
            ),
            status=extraction_status,
            extraction_sha256="",
        )
    return document


@pytest.mark.django_db
def test_archive_filter_options_distinct_queries_clear_default_document_ordering():
    _document(0, identity_type="lei_complementar", number="258", year=2024)
    _document(1, identity_type="lei_complementar", number="259", year=2024)

    with CaptureQueriesContext(connection) as captured:
        result = search_archive_documents("", include_results=False)

    option_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "SELECT DISTINCT" in query["sql"].upper()
        and "metadata_json" in query["sql"]
    ]
    assert result["types"] == ["lei_complementar"]
    assert result["years"] == [2024]
    assert len(option_queries) == 2
    assert all('"created_at"' not in sql and '"public_id"' not in sql for sql in option_queries)


@pytest.mark.django_db
def test_unfiltered_archive_review_queue_orders_candidate_year_and_number_descending():
    oldest = _document(1, year=2004, number="900")
    lower_number = _document(2, year=2026, number="9")
    higher_number = _document(3, year=2026, number="120")
    middle_year = _document(4, year=2025, number="9999")
    unknown = _document(5, year=0, number="uncertain")

    result = search_archive_documents("")

    assert [row["document"].pk for row in result["results"]] == [
        higher_number.pk,
        lower_number.pk,
        middle_year.pk,
        oldest.pk,
        unknown.pk,
    ]


@pytest.mark.django_db
def test_unfiltered_archive_queue_orders_year_then_publication_date_then_number():
    older_date = _document(
        10, year=2025, number="900", publication_date="2025-11-09"
    )
    newest_date = _document(
        11, year=2025, number="1", publication_date="2025-11-10"
    )
    fallback_lower = _document(12, year=2025, number="9")
    fallback_higher = _document(13, year=2025, number="120")
    oldest_year = _document(14, year=2024, number="999")

    result = search_archive_documents("")

    assert [row["document"].pk for row in result["results"]] == [
        newest_date.pk,
        older_date.pk,
        fallback_higher.pk,
        fallback_lower.pk,
        oldest_year.pk,
    ]


@pytest.mark.django_db
def test_archive_search_expands_controlled_synonyms_and_returns_latest_text():
    matching = _document(
        1,
        text="Art. 1º A política ambiental disciplina a coleta de resíduos sólidos.",
    )
    _document(2, text="Art. 1º Regras administrativas sem tema ambiental.")
    _document(3, text="Art. 1º Lixo ambiental.", identity_type="lei")

    result = search_archive_documents("ambiental lixo")

    assert result["expanded"] is True
    assert result["count"] == 2
    assert result["results"][0]["document"].pk == matching.pk
    assert "resíduos" in result["results"][0]["text"]
    assert result["results"][0]["extraction_status"] == "complete"
    assert result["results"][0]["page_count"] == 2


@pytest.mark.django_db
def test_natural_cosip_query_ignores_question_verbs_but_preserves_negative_scope():
    unbuilt_units = _document(
        250,
        filename="Decreto_COSIP_nao_edificadas.pdf",
        identity_type="decreto",
        number="8355",
        year=2024,
        text=(
            "Art. 3º Os recolhimentos do IPTU, TLP e da Contribuição de Iluminação Pública "
            "COSIP incidente sobre unidades imobiliárias não edificadas podem ser realizados em parcelas."
        ),
    )
    built_units = _document(
        251,
        filename="Decreto_COSIP_edificadas.pdf",
        identity_type="decreto",
        number="8356",
        year=2024,
        text=(
            "Art. 3º O pagamento da Contribuição de Iluminação Pública COSIP incidente sobre "
            "unidades imobiliárias edificadas será feito em parcela única."
        ),
    )
    unrelated = _document(
        252,
        filename="Lei_COSIP.pdf",
        identity_type="lei",
        number="8357",
        year=2024,
        text="Art. 1º A contribuição de iluminação pública financia a rede municipal.",
    )

    result = search_archive_documents(
        "Quais atos tratam da cobrança da COSIP em unidades imobiliárias não edificadas?"
    )

    assert result["count"] == 1
    assert result["results"][0]["document"].pk == unbuilt_units.pk
    assert built_units.pk not in {row["document"].pk for row in result["results"]}
    assert unrelated.pk not in {row["document"].pk for row in result["results"]}


@pytest.mark.django_db
def test_number_only_archive_search_uses_norm_identity_not_incidental_digits():
    matching = _document(
        200,
        filename="Decreto_8206.pdf",
        identity_type="decreto",
        number="8206",
        year=2007,
        text="Decreto nº 8.206, de 18 de julho de 2007. Abre crédito suplementar.",
    )
    _document(
        201,
        filename="Lei_6481_2014.pdf",
        identity_type="lei",
        number="6481",
        year=2014,
        text="Anexo orçamentário: código 1001008206 e dotação municipal.",
    )

    result = search_archive_documents("8206")

    assert result["count"] == 1
    assert result["results"][0]["document"].pk == matching.pk
    assert result["results"][0]["identity"]["number"] == "8206"


@pytest.mark.django_db
def test_lixo_expansion_avoids_financial_residuo_but_keeps_solid_waste():
    financial_residue = _document(
        101,
        text="Art. 27 O valor terá caráter de resíduo a ser absorvido gradativamente.",
    )
    solid_waste = _document(
        102,
        text="Art. 1º A gestão de resíduo sólido será regulamentada pelo Município.",
    )
    literal_waste = _document(103, text="Art. 1º A coleta de lixo ocorrerá semanalmente.")

    result = search_archive_documents("lixo")

    result_ids = {row["document"].pk for row in result["results"]}
    assert financial_residue.pk not in result_ids
    assert {solid_waste.pk, literal_waste.pk} <= result_ids


@pytest.mark.django_db
def test_archive_search_matches_accented_portuguese_text_when_query_is_folded():
    solid_waste = _document(
        104,
        text="Art. 1º A coleta e a destinação de resíduos sólidos serão regulamentadas.",
    )

    result = search_archive_documents("sólidos")

    assert result["count"] == 1
    assert result["results"][0]["document"].pk == solid_waste.pk


@pytest.mark.django_db
def test_archive_search_matches_unaccented_query_against_portuguese_text():
    document = _document(
        107,
        text="Art. 1º A taxa de iluminação pública será regulamentada por esta Lei.",
    )

    result = search_archive_documents("iluminacao publica")

    assert result["count"] == 1
    assert result["results"][0]["document"].pk == document.pk


@pytest.mark.django_db
def test_archive_search_ignores_matching_text_from_superseded_extraction():
    document = _document(
        108,
        text="Art. 1º A taxa de iluminação pública será regulamentada por esta Lei.",
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="document-search-test-latest-108",
        policy_fingerprint=_digest("search-policy-latest-108"),
        text_version="legal-text-test-v2",
        raw_text="Art. 1º Regras administrativas sem relação com iluminação.",
        legal_text="Art. 1º Regras administrativas sem relação com iluminação.",
        page_count=1,
        status="complete",
        extraction_sha256="",
    )

    result = search_archive_documents("iluminação pública")

    assert result["count"] == 0


@pytest.mark.django_db
def test_archive_search_excerpt_shows_late_matching_passage_and_page_number():
    document = _document(
        105,
        text=(
            "--- Página 1 --- Cabeçalho e apresentação institucional. "
            + ("Texto introdutório sem relação com a consulta. " * 18)
            + "--- Página 4 --- Art. 12º A destinação final de resíduos sólidos deve observar o plano municipal."
        ),
    )

    result = search_archive_documents("destinação final de resíduos sólidos")

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_matched"] is True
    assert match["excerpt_page"] == 4
    assert match["excerpt_matched_group_count"] == match["excerpt_total_group_count"]
    assert "destinação final de resíduos sólidos" in match["excerpt"]
    assert "apresentação institucional" not in match["excerpt"]


@pytest.mark.django_db
def test_archive_excerpt_reports_partial_query_coverage_when_terms_are_far_apart():
    document = _document(
        110,
        text=(
            "--- Página 1 --- A entidade ambiental promove atividades públicas. "
            + ("Texto institucional sem outros termos de busca. " * 12)
            + "A coleta de lixo é organizada pelos serviços municipais."
        ),
    )

    result = search_archive_documents("ambiental lixo")

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_matched"] is True
    assert match["excerpt_matched_group_count"] == 1
    assert match["excerpt_total_group_count"] == 2
    assert not ("ambiental" in match["excerpt"].casefold() and "lixo" in match["excerpt"].casefold())


@pytest.mark.django_db
def test_archive_excerpt_marks_matches_in_entity_name_before_first_article():
    document = _document(
        111,
        text=(
            "--- Página 1 --- LEI Nº 5.791. Reconhece a Rede Sociedade Ambiental Cultural "
            "Lixo e Cidadania.\n\nArt. 1º Fica reconhecida a entidade como de utilidade pública."
        ),
    )

    result = search_archive_documents("ambiental lixo")

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_match_region"] == "before_first_article"
    assert match["excerpt_matched_group_count"] == 2


@pytest.mark.django_db
def test_archive_excerpt_marks_matches_after_first_article():
    document = _document(
        112,
        text=(
            "--- Página 1 --- LEI Nº 6.881. Dispõe sobre publicidade municipal.\n\n"
            "Art. 1º A educação ambiental orientará a destinação de lixo."
        ),
    )

    result = search_archive_documents("ambiental lixo")

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_match_region"] == "after_first_article"


@pytest.mark.django_db
def test_archive_search_prefers_article_body_match_over_preamble_entity_match():
    preamble_match = _document(
        130,
        filename="LeiOrdinaria_5791.pdf",
        identity_type="lei",
        number="5791",
        year=2007,
        text=(
            "--- Página 1 --- Reconhece a Rede Sociedade Ambiental Lixo e Cidadania.\n\n"
            "Art. 1º Fica reconhecida a entidade como de utilidade pública."
        ),
    )
    dispositive_match = _document(
        131,
        filename="LeiOrdinaria_6881.pdf",
        identity_type="lei",
        number="6881",
        year=2019,
        text=(
            "--- Página 1 --- Dispõe sobre ações de educação ambiental.\n\n"
            "Art. 1º A destinação de lixo observará a política municipal de educação ambiental."
        ),
    )

    result = search_archive_documents("ambiental lixo")

    assert result["count"] == 2
    assert [row["document"].pk for row in result["results"]] == [
        dispositive_match.pk,
        preamble_match.pk,
    ]
    assert result["results"][0]["excerpt_match_region"] == "after_first_article"
    assert result["results"][1]["excerpt_match_region"] == "before_first_article"


@pytest.mark.django_db
def test_archive_search_prefers_excerpts_covering_more_query_groups_within_article_body():
    partial_excerpt = _document(
        132,
        filename="LeiOrdinaria_7400.pdf",
        number="7400",
        year=2020,
        text=(
            "Art. 1º A educação ambiental orientará o programa municipal.\n"
            + ("Texto genérico sem correspondência temática. " * 14)
            + "\nArt. 2º A destinação de lixo será disciplinada em regulamento."
        ),
    )
    complete_excerpt = _document(
        133,
        filename="LeiOrdinaria_7401.pdf",
        number="7401",
        year=2020,
        text="Art. 1º A educação ambiental orientará a destinação de lixo.",
    )

    result = search_archive_documents("ambiental lixo")

    assert result["count"] == 2
    assert {row["document"].pk for row in result["results"]} == {
        partial_excerpt.pk,
        complete_excerpt.pk,
    }
    assert result["results"][0]["document"].pk == complete_excerpt.pk
    assert result["results"][0]["excerpt_match_region"] == "after_first_article"
    assert result["results"][0]["excerpt_matched_group_count"] == 2
    assert result["results"][1]["excerpt_matched_group_count"] == 1


@pytest.mark.django_db
def test_archive_search_excerpt_prefers_denser_later_match_over_first_complete_window():
    document = _document(
        109,
        text=(
            "--- Página 1 --- Destinação final de resíduos sólidos. "
            + ("Apresentação genérica sem relação direta. " * 20)
            + "--- Página 8 --- Parágrafo temático: "
            + ("destinação final de resíduos sólidos; " * 6)
        ),
    )

    result = search_archive_documents("destinação final de resíduos sólidos")

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_matched"] is True
    assert match["excerpt_page"] == 8
    assert "Parágrafo temático" in match["excerpt"]


@pytest.mark.django_db
def test_explicit_norm_and_article_query_prefers_the_matching_page_over_the_epigraph():
    document = _document(
        106,
        filename="LeiComplementar20101203_120.pdf",
        identity_type="lei_complementar",
        number="120",
        year=2010,
        text=(
            "--- Página 1 --- LEI COMPLEMENTAR Nº. 120 DE 03 DE DEZEMBRO DE 2010. "
            "Cria e implanta o Plano de Cargos e Carreiras dos Profissionais da Área de Saúde. "
            + ("Apresentação institucional sem relação com a consulta. " * 18)
            + "--- Página 5 --- CAPÍTULO V DA REMUNERAÇÃO E DA JORNADA. "
            "Art. 21 - A carga horária semanal dos servidores da área de Saúde é de 40 horas. "
            "A Lei Municipal nº 6.070/2010 fixa jornada de 30 horas para categorias específicas."
        ),
    )

    result = search_archive_documents(
        "Lei Complementar nº 120/2010 Art. 21 jornada semanal"
    )

    assert result["count"] == 1
    match = result["results"][0]
    assert match["document"].pk == document.pk
    assert match["excerpt_matched"] is True
    assert match["excerpt_page"] == 5
    assert "Art. 21" in match["excerpt"]
    assert match["excerpt"].startswith("Art. 21")
    assert "Cria e implanta o Plano de Cargos" not in match["excerpt"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "Lei Complementar nº 120/2010 Art. 21 jornada semanal",
            (("21",), ("jornada",), ("semanal",)),
        ),
        (
            "Lei nº 8.205/2026 Art. 1º educação popular",
            (("1",), ("educacao",), ("popular",)),
        ),
    ],
)
def test_excerpt_query_keeps_article_and_topic_but_removes_norm_identity(query, expected):
    excerpt_query = _without_explicit_norm_identity(query)

    assert _query_groups(excerpt_query) == expected


def test_norm_identity_only_query_does_not_claim_a_relevant_excerpt():
    assert _query_groups(
        _without_explicit_norm_identity("Lei Complementar nº 120/2010")
    ) == ()


@pytest.mark.django_db
def test_archive_search_requires_each_meaningful_query_group_to_match():
    _document(7, text="Art. 1º A política ambiental.")
    _document(8, text="Art. 1º Regras para resíduos sólidos.")

    result = search_archive_documents("ambiental resíduos")

    assert result["results"] == []
    assert result["count"] == 0


@pytest.mark.django_db
def test_archive_search_ranks_terms_found_together_above_terms_scattered_across_document():
    near_match = _document(
        91,
        filename="Lei_Complementar_91_2020.pdf",
        text=(
            "--- Página 1 --- A destinação final de resíduos sólidos exige plano municipal. "
            + ("Disposição administrativa sem relação direta. " * 12)
        ),
    )
    scattered_match = _document(
        92,
        filename="Lei_Complementar_92_2020.pdf",
        text=(
            "--- Página 1 --- Destinação administrativa. "
            + ("Disposição administrativa sem relação direta. " * 10)
            + "Finalidade do órgão. "
            + ("Disposição administrativa sem relação direta. " * 10)
            + "Resíduos gerais. "
            + ("Disposição administrativa sem relação direta. " * 10)
            + "Sólidos em sentido diverso."
        ),
    )

    result = search_archive_documents("destinação final de resíduos sólidos")

    assert [row["document"].pk for row in result["results"]] == [
        near_match.pk,
        scattered_match.pk,
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Qual lei institui a COSIP em Natal?", ("lei", "lei_complementar", "lei_organica", "lei_promulgada")),
        ("Encontre a Lei Complementar que disciplina a COSIP", ("lei_complementar",)),
        ("Quais decretos legislativos tratam do tema?", ("decreto_legislativo",)),
        ("Como funciona a COSIP em Natal?", ()),
    ],
)
def test_archive_search_recognizes_explicit_requested_act_kind(query, expected):
    assert _requested_archive_types(query) == expected


@pytest.mark.django_db
def test_requested_act_kind_is_intent_not_a_required_term_in_extracted_text():
    ordinary = _document(
        620,
        filename="Lei_620.pdf",
        identity_type="lei",
        number="620",
        text="A norma disciplina a contribuição para custeio da iluminação pública COSIP.",
    )
    complementary = _document(
        621,
        filename="Lei_Complementar_621.pdf",
        identity_type="lei_complementar",
        number="621",
        text="A norma disciplina a contribuição para custeio da iluminação pública COSIP.",
    )
    decree = _document(
        622,
        filename="Decreto_622.pdf",
        identity_type="decreto",
        number="622",
        text="A norma disciplina a contribuição para custeio da iluminação pública COSIP.",
    )

    result = search_archive_documents(
        "Encontre a Lei Complementar que disciplina a COSIP"
    )

    assert result["count"] == 3
    assert result["requested_types"] == ("lei_complementar",)
    assert result["requested_type_found"] is True
    assert [row["document"].pk for row in result["results"]] == [
        complementary.pk,
        ordinary.pk,
        decree.pk,
    ]


@pytest.mark.django_db
def test_archive_search_boosts_requested_laws_without_hiding_decree_candidates():
    matching_text = "O Município institui a Contribuição de Iluminação Pública COSIP."
    decree = _document(610, identity_type="decreto", text=matching_text)
    ordinary_law = _document(611, identity_type="lei", text=matching_text)
    complementary_law = _document(612, identity_type="lei_complementar", text=matching_text)

    result = search_archive_documents("Qual lei institui a COSIP em Natal?")

    assert [row["document"].pk for row in result["results"]] == [
        ordinary_law.pk,
        complementary_law.pk,
        decree.pk,
    ]
    assert result["count"] == 3


@pytest.mark.django_db
def test_archive_search_groups_exact_duplicate_bytes_but_preserves_each_pdf_link():
    shared_hash = _digest("same PDF bytes")
    first = _document(
        630,
        filename="Lei_630.pdf",
        identity_type="lei",
        number="630",
        text="A norma disciplina a contribuição COSIP municipal.",
    )
    second = _document(
        631,
        filename="Lei_Promulgada_630.pdf",
        identity_type="lei_promulgada",
        number="630",
        text="A norma disciplina a contribuição COSIP municipal.",
    )
    DocumentoNormativo.objects.filter(pk__in=(first.pk, second.pk)).update(
        content_sha256=shared_hash
    )

    with CaptureQueriesContext(connection) as captured:
        result = search_archive_documents("contribuição COSIP municipal")

    assert result["count"] == 1
    assert result["record_count"] == 2
    assert len(result["results"]) == 1
    assert {
        source.pk for source in result["results"][0]["identical_sources"]
    } == {first.pk, second.pk}
    candidate_count_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "COUNT(DISTINCT" in query["sql"].upper()
        and "LEGISLATION_DOCUMENTONORMATIVO" in query["sql"].upper()
    ]
    assert len(candidate_count_queries) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "Lei Complementar 198 2021",
        "O que diz a Lei Complementar nº 198/2021?",
    ],
)
def test_explicit_norm_identity_uses_exact_type_number_and_year(query):
    expected = _document(
        4,
        filename="LeiComplementar_20211220_198_.pdf",
        identity_type="lei_complementar",
        number="198",
        year=2021,
    )
    _document(
        5,
        filename="LeiOrdinaria_198_2021.pdf",
        identity_type="lei",
        number="198",
        year=2021,
    )
    _document(
        6,
        filename="LeiComplementar_198_2020.pdf",
        identity_type="lei_complementar",
        number="198",
        year=2020,
    )

    result = search_archive_documents(query)

    assert [row["document"].pk for row in result["results"]] == [expected.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query_number", "stored_number"),
    [("055", "55"), ("55", "055")],
)
def test_explicit_norm_identity_ignores_numeric_zero_padding_without_mixing_type(
    query_number, stored_number
):
    expected = _document(
        61,
        identity_type="lei_complementar",
        number=stored_number,
        year=2004,
    )
    _document(
        62,
        identity_type="lei",
        number=stored_number,
        year=2004,
    )

    result = search_archive_documents(f"Lei Complementar {query_number}/2004")

    assert [row["document"].pk for row in result["results"]] == [expected.pk]


@pytest.mark.django_db
def test_archive_search_filters_type_year_review_and_extraction_state():
    match = _document(10, identity_type="lei_complementar", year=2021)
    _document(11, identity_type="lei", year=2021)
    _document(12, identity_type="lei_complementar", year=2020)
    _document(
        13,
        identity_type="lei_complementar",
        year=2021,
        review_status=DocumentoNormativo.ReviewStatus.IN_REVIEW,
    )
    _document(
        14,
        identity_type="lei_complementar",
        year=2021,
        extraction_status=None,
    )

    result = search_archive_documents(
        "lei",
        document_type="lei complementar",
        year=2021,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        extraction_status="complete",
    )

    assert [row["document"].pk for row in result["results"]] == [match.pk]


@pytest.mark.django_db
def test_archive_search_paginates_without_loading_every_document_into_results():
    documents = [_document(index, filename=f"Lei_{index}_2021.pdf") for index in range(1, 23)]

    first_page = search_archive_documents("Art", page=1)
    second_page = search_archive_documents("Art", page=2)

    assert first_page["count"] == len(documents)
    assert len(first_page["results"]) == 20
    assert second_page["page"].number == 2
    assert len(second_page["results"]) == 2
    assert {row["document"].pk for row in first_page["results"]}.isdisjoint(
        row["document"].pk for row in second_page["results"]
    )


@pytest.mark.django_db
def test_archive_search_excludes_promoted_and_non_archive_records():
    linked_norma = _document(30)
    from src.apps.legislation.models import Norma

    norma = Norma.objects.create(tipo="Lei", numero="55", ano=2021, status="consolidated")
    linked_norma.norma = norma
    linked_norma.save(update_fields=["norma", "updated_at"])
    other_source = DocumentoNormativo.objects.create(
        document_key=_digest("sapl-search-document"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:55",
        original_filename="Lei_55_2021.pdf",
        content_sha256=_digest("sapl-search-content"),
        metadata_json={"identity_candidate": {"type": "lei", "number": "55", "year": 2021}},
    )

    result = search_archive_documents("Lei")

    assert result["results"] == []
    assert result["count"] == 0
    assert other_source.source_kind == DocumentoNormativo.SourceKind.SAPL


@pytest.mark.django_db
def test_archive_search_rejects_overlong_query():
    with pytest.raises(ValueError, match="até 200 caracteres"):
        search_archive_documents("x" * 201)


@pytest.mark.django_db
@override_settings(
    DEBUG=True,
    NORMATIVE_ARCHIVE_ENABLED=True,
    NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
)
def test_legal_search_separates_local_candidates_from_consolidated_norms():
    document = _document(
        40,
        filename="Lei_Complementar_198_2021.pdf",
        text="Art. 6º Aplicam-se subsidiariamente as normas indicadas.",
    )
    with patch(
        "src.apps.legislation.workspace_views.RAGService.semantic_search",
        return_value={"results": [], "mode": "semantic"},
    ):
        response = Client().get("/pesquisa/", {"q": "subsidiariamente"})

    assert response.status_code == 200
    body = response.content.decode()
    assert document.original_filename in body
    assert "Acervo histórico local" in body
    assert "PDFs ainda não consolidados" in body
    assert "Inspecionar PDF e texto extraído" in body
    assert "Trecho coincidente" in body
    assert "extração automática" in body


@pytest.mark.django_db
@override_settings(
    DEBUG=False,
    NORMATIVE_ARCHIVE_ENABLED=True,
    NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
)
def test_legal_search_does_not_expose_candidate_documents_outside_qa_or_staff_access():
    document = _document(41, filename="candidate-private-to-review.pdf")

    response = Client().get("/pesquisa/", {"q": "Texto"})

    assert response.status_code == 200
    assert document.original_filename not in response.content.decode()
