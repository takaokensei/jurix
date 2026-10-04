from __future__ import annotations

import hashlib

import pytest
from django.core.exceptions import ValidationError

from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.models import Dispositivo, Norma
from src.processing.device_revision import legacy_device_identity_map
from src.processing.document_segmentation import SegmentationConflict, segment_document_extraction


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _accepted_document(text: str, *, metadata=None):
    norma = Norma.objects.create(tipo="Lei", numero=f"9{_sha(text)[:6]}", ano=2020)
    document = DocumentoNormativo.objects.create(
        norma=norma, document_key=_sha("doc:" + text),
        source_kind=DocumentoNormativo.SourceKind.LEGACY, source_ref="qa:document-segmentation",
        content_sha256=_sha("pdf:" + text), size_bytes=123,
        role=DocumentoNormativo.Role.ORIGINAL, metadata_json=metadata or {},
    )
    page_map = [{"start": 0, "end": len(text), "page": 1}]
    if len(text) > 180:
        page_map = [
            {"start": 0, "end": 180, "page": 1},
            {"start": 180, "end": len(text), "page": 2},
        ]
    extraction = ExtracaoDocumento.objects.create(
        documento=document, extractor_version="device-segmentation-test-v1",
        policy_fingerprint=_sha("policy-v1"), text_version="technical_text_v1",
        raw_text=text, legal_text=text, raw_text_sha256=_sha(text), legal_text_sha256=_sha(text),
        page_count=2,
        page_map_json=page_map,
        metadata_candidates_json=metadata or {}, quality_json={},
        status=ExtracaoDocumento.Status.COMPLETE, extraction_sha256=_sha("extract:" + text),
    )
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction", "updated_at"])
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    return norma, document, extraction


@pytest.mark.django_db(transaction=True)
def test_document_segmentation_offsets_exclude_colophon_and_keep_annex():
    text = (
        "--- Página 1 ---\n"
        "LEI Nº 9010, DE 2020\n"
        "Art. 1º O primeiro artigo tem texto normativo.\n"
        "§ 1º O parágrafo mantém seu próprio dispositivo.\n"
        "I - inciso preservado como filho.\n"
        "Art. 2º (VETADO) O texto vetado continua preservado.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
        "Sala das Sessões, em Natal, 1 de janeiro de 2020.\n"
        "Publicada no Diário Oficial do Município em: 02/01/2020.\n"
        "ANEXO I - TABELA\n"
        "Faixa A | Faixa B\n"
        "--- Página 2 ---\n"
    )
    _norma, _document, extraction = _accepted_document(text)
    result = segment_document_extraction(extraction.pk)
    rows = list(extraction.dispositivos_documentais.order_by("ordem"))
    assert result.created == len(rows) >= 5
    assert any(row.tipo == "artigo" and row.numero == "2º" and row.marker == DocumentoDispositivo.Marker.VETOED for row in rows)
    assert all(text[row.start_offset : row.end_offset] == row.texto for row in rows)
    final_article = next(row for row in rows if row.tipo == "artigo" and row.numero == "3º")
    assert final_article.end_offset <= text.index("Sala das Sessões")
    assert "ANEXO" not in final_article.texto
    assert result.unchanged is False
    assert segment_document_extraction(extraction.pk).unchanged is True


@pytest.mark.django_db(transaction=True)
def test_article_suffix_and_hierarchical_parent_keys_remain_distinct():
    text = "Art. 5º Caput.\nArt. 5-A O artigo acrescido.\nArt. 6º Final."
    _norma, _document, extraction = _accepted_document(text)
    result = segment_document_extraction(extraction.pk)
    articles = [item for item in result.devices if item["tipo"] == "artigo"]
    assert [item["numero"] for item in articles] == ["5º", "5-A", "6º"]
    assert len({item["structural_key"] for item in articles}) == 3
    inciso = (
        "Art. 7º Caput.\n"
        "§ 1º Parágrafo.\n"
        "I - inciso.\n"
        "a) alínea."
    )
    _norma2, _doc2, extraction2 = _accepted_document(inciso)
    rows = segment_document_extraction(extraction2.pk).devices
    by_type = {row["tipo"]: row for row in rows}
    assert by_type["paragrafo"]["parent_key"] == by_type["artigo"]["structural_key"]
    assert by_type["inciso"]["parent_key"] == by_type["paragrafo"]["structural_key"]
    assert by_type["alinea"]["parent_key"] == by_type["inciso"]["structural_key"]


@pytest.mark.django_db(transaction=True)
def test_segmentation_refuses_unaccepted_or_non_base_extraction():
    text = "Art. 1º Texto."
    _norma, document, extraction = _accepted_document(text)
    document.accepted_extraction = None
    document.save(update_fields=["accepted_extraction", "updated_at"])
    with pytest.raises(SegmentationConflict, match="explicitamente aceita"):
        segment_document_extraction(extraction.pk)


@pytest.mark.django_db(transaction=True)
def test_quoted_replacement_marker_is_flagged_without_losing_source_span():
    text = (
        "Art. 1º A redação anterior era:\n"
        "“Redação substituída:\n"
        "Art. 2º O prazo era de dez dias.\n"
        "Fim da redação citada.”\n"
        "Art. 3º O prazo atual é de vinte dias."
    )
    _norma, _document, extraction = _accepted_document(text)
    result = segment_document_extraction(extraction.pk)
    quoted = next(item for item in result.devices if item["numero"] == "2º")
    assert "marker_inside_unbalanced_quoted_text" in quoted["review_reasons"]
    stored = extraction.dispositivos_documentais.get(structural_key=quoted["structural_key"])
    assert stored.marker == DocumentoDispositivo.Marker.UNKNOWN
    assert text[stored.start_offset : stored.end_offset] == stored.texto


@pytest.mark.django_db(transaction=True)
def test_legacy_device_identity_map_preserves_primary_keys_and_rejects_cycles():
    norma = Norma.objects.create(tipo="Lei", numero="9011", ano=2020)
    article = Dispositivo.objects.create(norma=norma, tipo="artigo", numero="5-A", texto="Artigo", ordem=1)
    child = Dispositivo.objects.create(
        norma=norma, tipo="inciso", numero="I", texto="Inciso", ordem=2, dispositivo_pai=article
    )
    mapping = legacy_device_identity_map([article, child])
    assert mapping
    assert set(mapping.values()) == {article.pk, child.pk}
    Dispositivo.objects.filter(pk=article.pk).update(dispositivo_pai=child)
    article.refresh_from_db()
    child.refresh_from_db()
    with pytest.raises(ValueError, match="ciclo"):
        legacy_device_identity_map([article, child])


@pytest.mark.django_db(transaction=True)
def test_device_rows_are_immutable_and_offsets_must_match_source():
    text = "Art. 1º Texto fonte."
    _norma, _document, extraction = _accepted_document(text)
    row = segment_document_extraction(extraction.pk).devices[0]
    device = extraction.dispositivos_documentais.get(structural_key=row["structural_key"])
    device.texto = "texto adulterado"
    with pytest.raises(ValidationError):
        device.save()
