import hashlib
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("jsonschema", reason="Research schema checks need uv run --with jsonschema")

from scripts.validate_pgm_ai_adjudicated import validate_reference  # noqa: E402

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/corpus/municipal_natal/ai-adjudicated-20261018-v1/reference"
)


def _change_jsonl(root, name, modify):
    path = root / name
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    modify(rows)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    _update_inventory(root, name)


def _update_inventory(root, name):
    inventory_path = root / "SHA256SUMS.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")


@pytest.fixture
def reference_copy(tmp_path):
    target = tmp_path / "reference"
    shutil.copytree(REFERENCE, target)
    return target


def test_actual_twenty_norm_reference_passes_and_keeps_human_gold_pending():
    report = validate_reference(REFERENCE)
    assert report["valid"] is True
    assert report["distinct_norms"] == 20
    assert report["relation_families"] == ["ctm", "ppa", "urbanismo"]
    assert report["scientific_human_gold_ready"] is False
    assert report["human_adjudications"] == 0


def test_lc55_art34_gold_matches_environmental_license_not_building_permit():
    queries = [
        json.loads(line)
        for line in (REFERENCE / "queries.ai.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    case = next(row for row in queries if row["case_id"] == "AI-PGM-n04-v1")
    evidence = (REFERENCE / "texts/n04.txt").read_text(encoding="utf-8")
    assert "Licença Ambiental" in evidence
    assert "Licença Ambiental" in case["expected_answer_points"]
    assert "Alvará" not in case["expected_answer_points"]


def test_forged_human_review_is_rejected_even_with_recomputed_file_digest(reference_copy):
    def forge(rows):
        rows[0]["adjudication"]["review_kind"] = "human"
        rows[0]["adjudication"]["human_approved"] = True

    _change_jsonl(reference_copy, "annotations.ai-adjudicated.jsonl", forge)
    report = validate_reference(reference_copy)
    assert not report["valid"]
    assert any("AI origin" in error for error in report["errors"])


def test_forged_quote_is_rejected_even_with_recomputed_file_digest(reference_copy):
    _change_jsonl(
        reference_copy,
        "annotations.pending-human.jsonl",
        lambda rows: rows[0]["spans"][0].update(quote="Texto jurídico inventado"),
    )
    report = validate_reference(reference_copy)
    assert not report["valid"]
    assert any("quote" in error for error in report["errors"])


def test_related_norm_cannot_be_moved_to_another_split(reference_copy):
    path = reference_copy / "splits.json"
    splits = json.loads(path.read_text(encoding="utf-8"))
    splits["n10"]["split"] = "development"
    path.write_text(json.dumps(splits), encoding="utf-8")
    _update_inventory(reference_copy, "splits.json")
    report = validate_reference(reference_copy)
    assert not report["valid"]
    assert any("split:" in error for error in report["errors"])


def test_distinct_keys_do_not_hide_duplicate_normative_identity(reference_copy):
    def duplicate(rows):
        rows[1]["norma"] = dict(rows[0]["norma"])

    _change_jsonl(reference_copy, "manifest.jsonl", duplicate)
    report = validate_reference(reference_copy)
    assert not report["valid"]
    assert any("distinct normative identities" in error for error in report["errors"])
