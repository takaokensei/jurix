import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from scripts.normative_qa import _allowed_command
from src.processing.pilot_corpus import (
    build_source_record,
    canonical_bytes,
    has_active_source,
    load_active_corpus,
    load_source_selection,
    publish_revision,
    resolve_pilot_query,
    verified_blob,
)


def source(digest="a" * 64):
    return {
        "pdf_sha256": digest, "norma_key": "BR-RN-NATAL|lei|20|2026",
        "source_role": "primary", "text": "Art. 1º Exemplo.",
    }


def test_content_revision_is_idempotent_and_not_affected_by_operational_clock(tmp_path):
    first = publish_revision(tmp_path, [source()], report={"captured_at": "first", "pk": 1})
    second = publish_revision(tmp_path, [source()], report={"captured_at": "later", "pk": 999})
    assert second == first
    assert len(list((tmp_path / "revisions").iterdir())) == 1
    assert load_active_corpus(tmp_path)["sources"] == [source()]
    assert has_active_source(tmp_path, "a" * 64)
    assert not has_active_source(tmp_path, "b" * 64)
    assert not has_active_source(tmp_path, "../../private")


def test_sidecar_tampering_is_detected(tmp_path):
    result = publish_revision(tmp_path, [source()], report={})
    sidecar = tmp_path / "revisions" / result["corpus_revision"] / "sources" / ("a" * 64 + ".json")
    sidecar.write_text("{}")
    with pytest.raises(ValueError, match="Source integrity"):
        load_active_corpus(tmp_path)
    with pytest.raises(ValueError, match="was modified"):
        publish_revision(tmp_path, [source()], report={})


def test_concurrent_builders_publish_one_complete_revision(tmp_path):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: publish_revision(tmp_path, [source()], report={}), range(2)))
    assert results[0] == results[1]
    assert len(list((tmp_path / "revisions").iterdir())) == 1
    assert load_active_corpus(tmp_path)["sources"] == [source()]


def test_failure_before_activation_preserves_previous_revision(tmp_path, monkeypatch):
    from src.processing import pilot_corpus

    first = publish_revision(tmp_path, [source()], report={})
    replace = pilot_corpus.os.replace

    def fail_pointer(src, dst):
        if dst.name == "current.json":
            raise OSError("simulated interruption")
        replace(src, dst)

    monkeypatch.setattr(pilot_corpus.os, "replace", fail_pointer)
    with pytest.raises(OSError, match="interruption"):
        publish_revision(tmp_path, [{**source(), "text": "new text"}], report={})
    assert load_active_corpus(tmp_path)["corpus_revision"] == first["corpus_revision"]


def test_blob_integrity_and_path_escape_are_rejected(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\nexample")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert verified_blob(tmp_path, pdf.name, digest) == pdf
    with pytest.raises(ValueError, match="hash mismatch"):
        verified_blob(tmp_path, pdf.name, "b" * 64)
    with pytest.raises(ValueError, match="escapes"):
        verified_blob(tmp_path, "../outside.pdf", digest)


def test_source_selection_retains_typed_identity_and_refuses_gold_answers(tmp_path):
    identity = {"jurisdicao": "BR-RN-NATAL", "tipo": "lei_complementar", "numero": "20", "ano": 2026}
    data = {
        "schema_version": "jurix-pilot-source-selection-v1",
        "documents": [{**source(), "identity": identity, "norma_key": "BR-RN-NATAL|lei_complementar|20|2026"}],
    }
    path = tmp_path / "selection.json"
    path.write_bytes(canonical_bytes(data))
    assert load_source_selection(path)["documents"][0]["identity"] == identity
    data["documents"][0]["expected_answer"] = "not operational input"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Evaluation labels"):
        load_source_selection(path)


def test_pilot_command_guard_rejects_foreign_selection_or_root():
    assert _allowed_command(["python", "manage.py", "build_pgm_pilot_qa", "--fetch-missing"])
    with pytest.raises(ValueError, match="fixed source selection"):
        _allowed_command(["python", "manage.py", "build_pgm_pilot_qa", "--output", "C:/product"])


def test_multi_act_pdf_does_not_attribute_other_law_to_selected_identity():
    text = (
        "LEI Nº 19, DE 10 DE JANEIRO DE 2026\nArt. 1º Anterior.\nANEXO I\nTabela alheia.\n"
        "LEI Nº 20, DE 10 DE JANEIRO DE 2026\nArt. 1º Regra vinte.\n"
        "LEI Nº 21, DE 10 DE JANEIRO DE 2026\nArt. 1º Outra regra.\n"
    )
    spec = {**source(), "identity": {"jurisdicao": "BR-RN-NATAL", "tipo": "lei", "numero": "20", "ano": 2026}}
    extraction = SimpleNamespace(
        legal_text=text, legal_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        page_map_json=[{"page": 1, "start": 0, "end": len(text)}], page_count=1,
        extractor_version="test", policy_fingerprint="b" * 64, status="complete",
    )
    record = build_source_record(spec, extraction)
    assert record["coverage"]["act_boundary_status"] == "candidate"
    assert len(record["devices"]) == 1
    device = record["devices"][0]
    assert "Regra vinte" in text[device["start"]:device["end"]]
    assert "Outra regra" not in text[device["start"]:device["end"]]


def test_old_number_and_leading_zeroes_do_not_change_act_identity():
    from src.processing.gazette_act_candidates import find_gazette_act_candidates

    candidates = find_gazette_act_candidates([
        "LEI Nº 1.894/69 DE 31 DE DEZEMBRO DE 1969\nArt. 1º Texto.\n"
    ]).candidates
    assert candidates[0].number_candidate == "1894"
    assert candidates[0].year_candidate == 1969


def test_alias_and_edition_resolution_does_not_substitute_other_year_or_type():
    def record(kind, number, year, edition=None, aliases=()):
        return {
            "norma_key": f"BR-RN-NATAL|{kind}|{number}|{year}", "pdf_sha256": str(edition or number),
            "identity": {"tipo": kind, "numero": number, "ano": year},
            "aliases": list(aliases), "edition_year": edition,
        }
    ctm = record("lei", "3882", 1989, 2024, ["CTM"])
    lc = record("lei_complementar", "271", 2025)
    sources = [ctm, lc, record("lei_complementar", "3882", 1989)]
    result = resolve_pilot_query("Compare o Art. 20 do CTM na compilação de 2024 com a LC 271/2025, art. 1º", sources)
    assert result["status"] == "resolved"
    by_key = {tuple(item["norma_keys"]): item for item in result["references"]}
    assert by_key[(ctm["norma_key"],)]["requested_edition_year"] == 2024
    assert by_key[(lc["norma_key"],)]["requested_edition_year"] is None
    assert resolve_pilot_query("CTM na compilação de 2022", sources)["references"][0]["source_hashes"] == []
    assert resolve_pilot_query("3882/1989", sources)["status"] == "ambiguous"
    followup = resolve_pilot_query("E o artigo 7?", sources, context_keys=(lc["norma_key"],))
    assert followup["references"][0]["norma_keys"] == [lc["norma_key"]]
