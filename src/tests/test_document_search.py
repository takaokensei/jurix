from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.document_search import (
    _query_groups,
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
            status=extraction_status,
            extraction_sha256="",
        )
    return document


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
    assert "destinação final de resíduos sólidos" in match["excerpt"]
    assert "apresentação institucional" not in match["excerpt"]


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
