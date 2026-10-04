import hashlib
import json
import sys
from pathlib import Path

from scripts.validate_municipal_corpus import main, validate_corpus

HASH = "a" * 64


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


def _v2_case(tmp_path, *, sapl_id=None, review_kind="synthetic", official_url=None):
    text = "Art. 1º Norma municipal de exemplo."
    (tmp_path / "norma-v2.txt").write_text(text, encoding="utf-8")
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    record = {
        "schema_version": 2,
        "norma_key": "municipal_lo|100|2026",
        "document_key": "archive:sha256:" + HASH,
        "sapl_id": sapl_id,
        "norma": {
            "tipo": "Lei Ordinária",
            "numero": "100",
            "ano": 2026,
            "jurisdicao": "municipal_natal",
            "ementa": "Exemplo",
        },
        "document": {
            "source_kind": "archive",
            "source_ref": "sistema2/pdfs/LeiOrdinaria_20260101_100.pdf",
            "sha256": HASH,
            "archive_sha256": "b" * 64,
            "entry_index": 5,
            "pdf_path": None,
            "official_url": official_url,
            "role": "original",
        },
        "text": {
            "path": "norma-v2.txt",
            "sha256": text_hash,
            "text_version": "technical_text_v1",
            "extractor_version": "pymupdf-test",
            "ocr_status": "native",
        },
        "provenance": {
            "retrieved_at": "2026-10-01T12:00:00Z",
            "selection_rationale": "Fixture sintética para teste de contrato",
        },
        "condition_of_use": "unknown",
        "pilot": "technical_pilot",
        "human_review": {
            "status": "not_reviewed",
            "reviewer_id": None,
            "reviewed_at": None,
            "review_kind": review_kind,
        },
    }
    quote = "Art. 1º Norma municipal de exemplo."
    annotation = {
        "schema_version": 2,
        "annotation_id": "annotation-v2-1",
        "norma_key": record["norma_key"],
        "document_key": record["document_key"],
        "revision": {
            "source_text_sha256": text_hash,
            "text_version": "technical_text_v1",
            "extractor_version": "pymupdf-test",
        },
        "scope": {"kind": "device", "jurisdiction": "municipal_natal", "as_of": None},
        "annotator_id": "synthetic-annotator",
        "review": {
            "status": "adjudicated",
            "reviewer_id": "synthetic-reviewer",
            "reviewed_at": "2026-10-01T12:00:00Z",
            "review_kind": "synthetic",
        },
        "spans": [
            {
                "span_id": "span-art-1",
                "device_key": "artigo:1",
                "parent_device_key": None,
                "label": "artigo",
                "start": 0,
                "end": len(quote),
                "quote": quote,
            }
        ],
        "events": [],
    }
    manifest_path = tmp_path / "manifest-v2.jsonl"
    annotations_path = tmp_path / "annotations-v2.jsonl"
    manifest_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    annotations_path.write_text(json.dumps(annotation) + "\n", encoding="utf-8")
    return manifest_path, annotations_path, record, annotation


def test_v2_accepts_archive_document_without_sapl_id_but_blocks_synthetic_gold(tmp_path):
    manifest, annotations, _record, _annotation = _v2_case(tmp_path)

    report = validate_corpus(manifest, annotations, min_reviewed_pilot=1)

    assert report["valid"] is True
    assert report["schema_version"] == 2
    assert report["normas_distintas"] == 1
    assert report["release_ready"] is False
    assert report["reviewed_pilot_norms"] == 0
    assert any("gate científico bloqueado" in warning for warning in report["warnings"])


def test_v2_rejects_unverified_external_official_url(tmp_path):
    manifest, annotations, record, _annotation = _v2_case(
        tmp_path, official_url="https://example.invalid/fake-law.pdf"
    )
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is False
    assert any("URL oficial" in error for error in report["errors"])


def test_v2_rejects_source_revision_hash_mismatch_and_conflicting_quote(tmp_path):
    manifest, annotations, _record, annotation = _v2_case(tmp_path)
    annotation["revision"]["source_text_sha256"] = "c" * 64
    annotation["spans"][0]["quote"] = "trecho fabricado"
    annotations.write_text(json.dumps(annotation) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is False
    assert any("mistura hash ou revisão" in error for error in report["errors"])
    assert any("quote do span" in error for error in report["errors"])


def test_v2_rejects_invalid_normative_year_document_hash_and_archive_path(tmp_path):
    manifest, annotations, record, _annotation = _v2_case(tmp_path)
    record["norma"]["ano"] = 26
    record["document"]["sha256"] = "not-a-hash"
    record["document"]["source_ref"] = "../../outside/lei.pdf"
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is False
    assert any("identidade normativa" in error for error in report["errors"])
    assert any("hash do documento inválido" in error for error in report["errors"])
    assert any("source_ref do acervo" in error for error in report["errors"])


def test_v2_rejects_manifest_text_hash_that_does_not_match_file(tmp_path):
    manifest, annotations, record, _annotation = _v2_case(tmp_path)
    record["text"]["sha256"] = "e" * 64
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is False
    assert any("hash do texto extraído não confere" in error for error in report["errors"])


def test_v2_supports_substitui_with_pending_typed_target_and_literal_evidence(tmp_path):
    manifest, annotations, record, annotation = _v2_case(tmp_path)
    text = (tmp_path / "norma-v2.txt").read_text(encoding="utf-8")
    annotation["events"] = [
        {
            "event_id": "event-substitui-1",
            "action": "SUBSTITUI",
            "source_span_id": "span-art-1",
            "target_norma_key": None,
            "target_device_key": None,
            "scope": "dispositivo",
            "revision": "technical_text_v1",
            "effective_date": {"value": None, "status": "unknown", "basis": None},
            "resolution": "pending_review",
            "evidence": {
                "quote": text,
                "start": 0,
                "end": len(text),
                "source_text_sha256": record["text"]["sha256"],
            },
        }
    ]
    annotations.write_text(json.dumps(annotation) + "\n", encoding="utf-8")

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is True
    assert report["release_ready"] is False
    assert report["reviewed_pilot_norms"] == 0


def test_v2_allows_multiple_documents_for_one_norma_without_inflating_norm_count(tmp_path):
    manifest, annotations, record, _annotation = _v2_case(tmp_path)
    second_text = "Art. 1º Texto da republicação."
    (tmp_path / "republicacao.txt").write_text(second_text, encoding="utf-8")
    second = json.loads(json.dumps(record))
    second["document_key"] = "archive:sha256:" + "d" * 64
    second["document"]["sha256"] = "d" * 64
    second["document"]["role"] = "republicacao"
    second["text"]["path"] = "republicacao.txt"
    second["text"]["sha256"] = hashlib.sha256(second_text.encode()).hexdigest()
    manifest.write_text(
        json.dumps(record) + "\n" + json.dumps(second) + "\n", encoding="utf-8"
    )

    report = validate_corpus(manifest, annotations)

    assert report["valid"] is True
    assert report["manifest_records"] == 2
    assert report["normas_distintas"] == 1


def test_v2_human_document_review_without_adjudicated_annotation_does_not_pass_gate(tmp_path):
    manifest, annotations, record, _annotation = _v2_case(tmp_path, review_kind="human")
    record["condition_of_use"] = "public_record_reviewed"
    record["pilot"] = "approved"
    record["human_review"] = {
        "status": "approved",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-10-02T12:00:00Z",
        "review_kind": "human",
    }
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")
    annotations.write_text("", encoding="utf-8")

    report = validate_corpus(manifest, annotations, min_reviewed_pilot=1)

    assert report["valid"] is True
    assert report["reviewed_pilot_norms"] == 0
    assert report["release_ready"] is False


def test_v2_cli_exit_3_for_valid_synthetic_and_exit_0_only_for_human_review(tmp_path, monkeypatch, capsys):
    manifest, annotations, record, annotation = _v2_case(tmp_path)
    args = [
        "validate_municipal_corpus.py",
        "--manifest",
        str(manifest),
        "--annotations",
        str(annotations),
        "--min-reviewed-pilot",
        "1",
    ]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 3
    assert json.loads(capsys.readouterr().out)["valid"] is True

    record["condition_of_use"] = "public_record_reviewed"
    record["pilot"] = "approved"
    record["human_review"] = {
        "status": "approved",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-10-02T12:00:00Z",
        "review_kind": "human",
    }
    annotation["review"] = {
        "status": "adjudicated",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-10-02T12:00:00Z",
        "review_kind": "human",
    }
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")
    annotations.write_text(json.dumps(annotation) + "\n", encoding="utf-8")
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["release_ready"] is True


def test_v2_cli_exit_2_for_mixed_schema_versions(tmp_path, monkeypatch):
    manifest, annotations, record, _annotation = _v2_case(tmp_path)
    record["schema_version"] = 1
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_municipal_corpus.py", "--manifest", str(manifest), "--annotations", str(annotations)],
    )

    assert main() == 2


def test_v2_schemas_are_valid_json_and_add_substitui_without_changing_v1():
    schema_root = Path("benchmarks/corpus/municipal_natal")
    manifest_schema = json.loads((schema_root / "manifest.v2.schema.json").read_text("utf-8"))
    annotation_schema = json.loads((schema_root / "annotation.v2.schema.json").read_text("utf-8"))
    v1_annotation_schema = json.loads((schema_root / "annotation.schema.json").read_text("utf-8"))

    assert manifest_schema["properties"]["schema_version"]["const"] == 2
    assert annotation_schema["properties"]["schema_version"]["const"] == 2
    assert "SUBSTITUI" in annotation_schema["properties"]["events"]["items"]["properties"]["action"]["enum"]
    assert "SUBSTITUI" not in v1_annotation_schema["properties"]["events"]["items"]["properties"]["action"]["enum"]
