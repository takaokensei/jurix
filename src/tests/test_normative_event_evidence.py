from __future__ import annotations

import hashlib

import pytest

from src.apps.ingestion.ner_tasks import _map_event_evidence
from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.models import Dispositivo, Norma
from src.processing.device_revision import structural_key
from src.processing.event_revision import event_revision_identity
from src.processing.ner_extractor import LegalNERExtractor


def test_event_evidence_spans_are_exact_unicode_slices_and_bind_lc_target():
    text = (
        "O art. 1º da Lei Complementar nº 198/2021 faz referência ao art. 21 "
        "da Lei Complementar nº 55/2004."
    )
    events = LegalNERExtractor().extract_events(text)
    reference = next(event for event in events if event["acao"] == "REFERENCIA")
    evidence = reference["evidence"]
    assert evidence["offset_unit"] == "python_unicode_codepoint"
    assert text[evidence["start_offset"] : evidence["end_offset"]] == evidence["quote"]
    assert text[evidence["target_start_offset"] : evidence["target_end_offset"]] == evidence["target_quote"]
    assert "Lei Complementar nº 55/2004" in evidence["quote"]
    assert reference["referencia_numero"].rstrip("º°ª") == "21"


def test_generic_revocation_clause_does_not_invent_a_target():
    events = LegalNERExtractor().extract_events("Ficam revogadas as disposições em contrário.")
    revocation = next(event for event in events if event["acao"] == "REVOGA")
    assert revocation["norma_referenciada"] is None
    assert revocation["target_resolution"] == "unresolved"
    assert revocation["evidence"]["target_quote"]


def test_multiple_statute_references_are_candidates_not_a_cartesian_resolution():
    text = "Esta norma faz referência à Lei nº 55/2004 e à Lei Complementar nº 55/2004."
    events = LegalNERExtractor().extract_events(text)
    references = [event for event in events if event["acao"] == "REFERENCIA"]
    assert len(references) >= 2
    assert all(event["target_resolution"] == "ambiguous_multiple_normas" for event in references)


def test_normative_reference_parses_common_years_written_out_in_portuguese():
    extractor = LegalNERExtractor()
    first = extractor._extract_references(
        "Faz referência à Lei Complementar nº 55, de mil novecentos e oitenta e oito."
    )
    second = extractor._extract_references("Faz referência à Lei nº 123, de dois mil e quatro.")
    assert first[0]["norma_info"]["ano"] == "1988"
    assert second[0]["norma_info"]["ano"] == "2004"


def test_article_range_remains_one_unresolved_candidate_and_not_partial_events():
    events = LegalNERExtractor().extract_events(
        "Ficam revogados os arts. 9º a 5º da Lei nº 123/2020."
    )
    articles = [event for event in events if event["acao"] == "REVOGA" and event["referencia_tipo"] == "artigo"]
    assert len(articles) == 1
    assert articles[0]["referencia_numero"] == "9º a 5º"
    assert articles[0]["target_resolution"] == "range_unresolved"


def test_event_fingerprint_v2_changes_when_literal_evidence_changes():
    common = {
        "source_identity": "device:abc", "source_revision": "revision-1", "action": "ALTERA",
        "target_text": "Art. 5º", "reference_type": "artigo", "reference_number": "5º",
        "target_norma_id": 7, "occurrence": 0,
    }
    first, provenance = event_revision_identity(**common, evidence={"quote": "redação um", "start_offset": 5})
    second, _ = event_revision_identity(**common, evidence={"quote": "redação dois", "start_offset": 5})
    assert first != second
    assert provenance["schema_version"] == 2


@pytest.mark.django_db(transaction=True)
def test_event_evidence_maps_to_exact_selected_document_and_extraction_span():
    def sha(value):
        return hashlib.sha256(value.encode()).hexdigest()

    source = "Art. 1º Fica alterado o art. 2º da Lei nº 9002/2021.\nArt. 2º Texto base."
    norma = Norma.objects.create(tipo="Lei", numero="9001", ano=2020)
    document = DocumentoNormativo.objects.create(
        norma=norma, document_key=sha("event-evidence-doc"),
        source_kind=DocumentoNormativo.SourceKind.LEGACY, source_ref="qa:event-evidence",
        role=DocumentoNormativo.Role.ORIGINAL, content_sha256=sha("event-evidence-bytes"),
        size_bytes=100,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document, extractor_version="event-evidence-test-v1",
        policy_fingerprint=sha("event-policy"), text_version="technical_text_v1",
        raw_text=source, legal_text=source, raw_text_sha256=sha(source), legal_text_sha256=sha(source),
        page_count=1, page_map_json=[{"start": 0, "end": len(source), "page": 1}],
        metadata_candidates_json={}, quality_json={}, status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256=sha("event-extraction"),
    )
    key = structural_key("root", "artigo", "1º")
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction", "updated_at"])
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    DocumentoDispositivo.objects.create(
        extracao=extraction, structural_key=key, tipo="artigo", numero="1º", ordem=1,
        texto=source[:source.index("\n")], start_offset=0, end_offset=source.index("\n"),
        page_index=1,
    )
    legacy = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Fica alterado o art. 2º da Lei nº 9002/2021.",
        ordem=1, structural_key=key,
    )
    event = next(item for item in LegalNERExtractor().extract_events(legacy.texto) if item["acao"] == "ALTERA")
    evidence = _map_event_evidence(legacy, event["evidence"])
    assert evidence["source_status"] == "verified_span"
    assert evidence["document_key"] == document.document_key
    assert evidence["extraction_sha256"] == extraction.extraction_sha256
    assert source[evidence["source_start_offset"] : evidence["source_end_offset"]] == evidence["source_quote"]
