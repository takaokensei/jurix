import hashlib
import json

from scripts.validate_municipal_corpus import validate_corpus


def _write_case(tmp_path, *, bad_span=False):
    text = "Art. 1º Norma municipal de exemplo."
    (tmp_path / "norma.txt").write_text(text, encoding="utf-8")
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    record = {
        "schema_version": 1,
        "record_id": "sapl-123",
        "sapl_id": 123,
        "norma": {"tipo": "Lei", "numero": "100", "ano": 2026, "ementa": "Exemplo"},
        "document": {
            "official_url": "https://sapl.natal.rn.leg.br/norma/normajuridica/123",
            "sha256": "a" * 64,
        },
        "text": {"path": "norma.txt", "sha256": text_hash, "ocr_status": "native"},
        "provenance": {
            "source": "SAPL Natal",
            "retrieved_at": "2026-10-01T12:00:00Z",
            "selection_rationale": "Fixture sintética para teste de contrato",
        },
        "license": {"status": "public_record_reviewed", "terms_url": None},
        "pilot": "approved",
        "human_review": {
            "status": "approved",
            "reviewer_id": "reviewer-test",
            "reviewed_at": "2026-10-01T12:00:00Z",
        },
    }
    quote = "Art. 1º"
    annotation = {
        "schema_version": 1,
        "case_id": "case-123",
        "sapl_id": 123,
        "source_text_sha256": text_hash,
        "annotator_id": "annotator-test",
        "reviewer_id": "reviewer-test",
        "adjudication_status": "adjudicated",
        "spans": [
            {
                "span_id": "art-1",
                "label": "artigo",
                "start": 0,
                "end": len(quote) if not bad_span else 40,
                "quote": quote,
            }
        ],
        "events": [],
    }
    manifest_path = tmp_path / "manifest.jsonl"
    annotations_path = tmp_path / "annotations.jsonl"
    manifest_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    annotations_path.write_text(json.dumps(annotation) + "\n", encoding="utf-8")
    return manifest_path, annotations_path


def test_synthetic_example_is_valid_but_does_not_unlock_human_gate(tmp_path):
    manifest, annotations = _write_case(tmp_path)

    report = validate_corpus(manifest, annotations, min_reviewed_pilot=20)

    assert report["valid"] is True
    assert report["release_ready"] is False
    assert report["reviewed_pilot_norms"] == 1
    assert "gate científico bloqueado" in report["warnings"][0]


def test_validator_rejects_span_outside_frozen_source_text(tmp_path):
    manifest, annotations = _write_case(tmp_path, bad_span=True)

    report = validate_corpus(manifest, annotations, min_reviewed_pilot=1)

    assert report["valid"] is False
    assert any("span fora dos limites" in error for error in report["errors"])


def test_validator_rejects_text_path_escape(tmp_path):
    manifest, annotations = _write_case(tmp_path)
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["text"]["path"] = "../outside.txt"
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is False
    assert any("sai do diretório" in error for error in report["errors"])
