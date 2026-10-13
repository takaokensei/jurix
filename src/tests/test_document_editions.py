from __future__ import annotations

import hashlib
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from src.apps.ingestion.management.commands.seed_normative_qa import _ensure_reviewed_document
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.document_metadata import parse_filename_metadata
from src.processing.document_segmentation import (
    _mask_normative_appendices,
    segment_document_extraction,
)
from src.processing.legal_parser import extract_publication_metadata


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_edition_roles_are_preserved_as_candidates_not_inferred_from_latest_date():
    assert parse_filename_metadata("Lei_8206_2026_original.pdf").role == "original"
    assert parse_filename_metadata("Lei_8206_2026_republicacao.pdf").role == "republicacao"
    assert parse_filename_metadata("Lei_8206_2026_retificacao.pdf").role == "retificacao"
    assert parse_filename_metadata("Lei_8206_2026_anexo.pdf").role == "anexo"


def test_annex_is_not_absorbed_into_last_article_but_remains_in_frozen_source():
    text = (
        "Art. 3º O Poder Executivo regulamentará esta Lei.\n"
        "Art. 4º Esta Lei entra em vigor na data de sua publicação.\n"
        "ANEXO I\nTabela de valores\nArt. 1º Este é um artigo do anexo."
    )

    masked, appendix_start = _mask_normative_appendices(text)
    last_article = text.index("Art. 4º")
    article_end = appendix_start

    assert appendix_start == text.index("ANEXO I")
    assert text[last_article:article_end].strip() == (
        "Art. 4º Esta Lei entra em vigor na data de sua publicação."
    )
    assert "Art. 1º Este é um artigo do anexo." in text
    assert "Art. 1º Este é um artigo do anexo." not in masked


def test_publication_metadata_remains_available_after_article_boundary_detection():
    text = (
        "Art. 4º Esta Lei entra em vigor na data de sua publicação.\n"
        "Sala das Sessões, em Natal, 20 de agosto de 2026.\n"
        "Publicada no Diário Oficial do Município em: 21/9/2026.\n"
        "ANEXO I\nTabela de valores"
    )

    metadata = extract_publication_metadata(text)

    assert metadata["data_publicacao"].isoformat() == "2026-09-21"
    assert metadata["vigencia_na_publicacao"] is True


@pytest.mark.django_db
def test_segmented_final_article_stops_before_colophon_and_annex():
    reviewer = get_user_model().objects.create_user(
        username="edition-boundary-fixture-reviewer", is_active=True
    )
    text = (
        "Art. 3º O Poder Executivo regulamentará esta Lei.\n"
        "Art. 4º Esta Lei entra em vigor na data de sua publicação.\n"
        "Sala das Sessões, em Natal, 20 de agosto de 2026.\n"
        "Eriko Jácome - Presidente.\n"
        "Publicada no Diário Oficial do Município em: 21/9/2026.\n"
        "ANEXO I\nTabela de valores\nArt. 1º Este é um artigo do anexo."
    )

    _norma, _document, extraction, _legacy = _ensure_reviewed_document(
        slug="edition-colophon-annex-boundary",
        label="Lei",
        number="9917",
        year=2026,
        text=text,
        published=date(2026, 9, 21),
        reviewer=reviewer,
    )

    final_article = extraction.dispositivos_documentais.get(tipo="artigo", numero="4º")

    assert final_article.texto == "Art. 4º Esta Lei entra em vigor na data de sua publicação.\n"
    assert "Sala das Sessões" not in final_article.texto
    assert "ANEXO I" not in final_article.texto
    assert "Art. 1º Este é um artigo do anexo." not in list(
        extraction.dispositivos_documentais.values_list("texto", flat=True)
    )


@pytest.mark.django_db
def test_non_original_edition_cannot_be_segmented_as_norma_base():
    document = DocumentoNormativo.objects.create(
        document_key=_sha("republication-document-key"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:republication-edition",
        content_sha256=_sha("republication-pdf"),
        role=DocumentoNormativo.Role.REPUBLICATION,
        original_filename="Lei_8206_2026_republicacao.pdf",
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="edition-guard-test-v1",
        policy_fingerprint=_sha("edition-guard-policy"),
        text_version="legal-text-v1",
        raw_text="Art. 1º Texto de republicação.",
        legal_text="Art. 1º Texto de republicação.",
        raw_text_sha256="",
        legal_text_sha256="",
        extraction_sha256="",
        status=ExtracaoDocumento.Status.COMPLETE,
    )

    with pytest.raises(ValidationError, match="documento original"):
        segment_document_extraction(extraction.pk)

    assert extraction.dispositivos_documentais.count() == 0
