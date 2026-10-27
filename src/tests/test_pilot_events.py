import hashlib
from datetime import date

from src.processing.pilot_events import (
    _new_text,
    build_pilot_events,
    device_span,
    temporal_evidence,
)


def source(key, text, *, role="primary", kind="reproduction", devices=None):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {
        "norma_key": key, "source_role": role, "edition_kind": kind,
        "pdf_sha256": digest, "text_sha256": digest, "text": text,
        "page_map": [{"page": 1, "start": 0, "end": len(text)}],
        "devices": devices or [], "coverage": {"act_spans": [[0, len(text)]]},
    }


def adoption(modifier, quote, *, target="Natal|lei|20|2020|art1", action="ALTERA"):
    start = modifier["text"].index(quote)
    return {
        "case_key": "test-chain", "revision": 1, "limitations_json": [],
        "review_draft_sha256": "a" * 64, "review_report_sha256": "b" * 64,
        "source_manifest_sha256": "c" * 64,
        "evidence_json": {
            "sources": [{"source_id": "source", "pdf_sha256": modifier["pdf_sha256"]}],
            "events": [{
                "relation_key": "test-relation", "target": target, "action": action,
                "target_resolution": "documentary_match",
                "evidence": {"source_id": "source", "quote": quote, "start": start,
                             "end": start + len(quote), "article": "9", "text_sha256": modifier["text_sha256"]},
            }],
        },
    }


def test_adoption_is_validated_against_exact_current_text_not_a_boolean_claim():
    base = source("BR-RN-NATAL|lei|20|2020", "Art. 1º Antigo.", devices=[{
        "device_key": "a1", "type": "artigo", "number": "1", "start": 0, "end": 14, "parent_key": None,
    }])
    modifier = source("BR-RN-NATAL|lei|30|2025", "Art. 9º Nova redação: “Art. 1º Novo.”")
    accepted = adoption(modifier, "“Art. 1º Novo.”")
    result = build_pilot_events([base, modifier], [accepted])
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["resolution"] == "resolved"
    assert event["target_device_path"] == "art:1"
    assert event["new_text"] == "Art. 1º Novo."
    accepted["evidence_json"]["events"][0]["evidence"]["quote"] = "a different quotation"
    rejected = build_pilot_events([base, modifier], [accepted])
    assert not rejected["events"]
    assert rejected["rejected"][0]["reason"] == "adopted_source_fingerprint_mismatch"


def test_species_collision_does_not_resolve_to_another_norm():
    base = source("BR-RN-NATAL|lei_complementar|20|2020", "Art. 1º Outro tipo.")
    modifier = source("BR-RN-NATAL|lei|30|2025", "Art. 9º Nova redação: “Art. 1º Novo.”")
    result = build_pilot_events([base, modifier], [adoption(modifier, "“Art. 1º Novo.”")])
    assert result["events"][0]["resolution"] == "unresolved"
    assert result["events"][0]["base_evidence"] is None


def test_native_multiline_ordinal_is_not_invented_as_letter_suffix():
    quote = "§3º\n-\nA\nlocalização depende de licença."
    assert _new_text(quote, "art:34/par:3", "ADICIONA") == quote
    assert _new_text("§3-A Outra regra.", "art:34/par:3", "ADICIONA") is None
    assert _new_text("§4º - A regulamentação será definida.", "art:34/par:4", "ADICIONA") == "§4º - A regulamentação será definida."
    assert _new_text("Art. 1º ... § 2º Outro trecho.", "art:1", "ALTERA") is None


def test_date_uses_same_official_edition_and_own_commencement_not_session():
    key = "BR-RN-NATAL|lei_complementar|30|2024"
    header = "Diário Oficial do Município\nNATAL, SEXTA-FEIRA, 27 DE DEZEMBRO DE 2024\n"
    text = header + "Art. 9º Esta Lei Complementar entra em vigor 90 (noventa) dias após a data de sua publicação."
    edition = source(key, text, role="supporting", kind="official_publication", devices=[{
        "type": "artigo", "number": "9", "start": len(header), "end": len(text),
    }])
    result = temporal_evidence(key, [edition])
    assert result["publication_on"] == "2024-12-27"
    assert result["effective_on"] == date(2025, 3, 27).isoformat()
    assert result["special_effects_on"] is None
    session_only = source(key, "Sala das Sessões, 27 de dezembro de 2024.")
    assert temporal_evidence(key, [session_only])["effective_on"] is None


def test_target_span_does_not_include_neighboring_article():
    text = "Art. 1 A.\n§ 1 B.\nArt. 2 C."
    record = source("BR-RN-NATAL|lei|20|2020", text, devices=[
        {"type": "artigo", "number": "1", "device_key": "a1", "parent_key": None, "start": 0, "end": 9},
        {"type": "paragrafo", "number": "1", "device_key": "p1", "parent_key": "a1", "start": 9, "end": 17},
        {"type": "artigo", "number": "2", "device_key": "a2", "parent_key": None, "start": 17, "end": len(text)},
    ])
    assert device_span(record, "art:1") == (0, 17)
    assert device_span(record, "art:1/par:1") == (9, 17)


def test_alternative_edition_is_evidence_without_reassigning_target_number():
    base = source("BR-RN-NATAL|lei|20|2020", "Art. 1º Anterior.", devices=[{
        "device_key": "a1", "type": "artigo", "number": "1", "start": 0, "end": 16, "parent_key": None,
    }])
    alternative = source(base["norma_key"], "Art. 1º Compilação divergente.", role="supporting", devices=[{
        "device_key": "a1", "type": "artigo", "number": "1", "start": 0, "end": len("Art. 1º Compilação divergente."), "parent_key": None,
    }])
    modifier = source("BR-RN-NATAL|lei|30|2025", "“Art. 1º Novo.”")
    result = build_pilot_events([base, alternative, modifier], [adoption(modifier, modifier["text"])])
    item = result["events"][0]
    assert item["target_device_path"] == "art:1"
    assert item["target_edition_evidence"][0]["document_sha256"] == alternative["pdf_sha256"]
    assert item["target_edition_evidence"][0]["quote"] == alternative["text"]
