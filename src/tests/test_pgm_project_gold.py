import hashlib
import json
import shutil

import pytest

pytest.importorskip("jsonschema", reason="Gold validation needs uv run --with jsonschema")

from scripts.pgm_project_gold import DEFAULT_GOLD, main, validate_gold  # noqa: E402


def _adopt_copy(tmp_path, change):
    gold = json.loads(DEFAULT_GOLD.read_text(encoding="utf-8"))
    change(gold)
    path = tmp_path / DEFAULT_GOLD.name
    path.write_text(json.dumps(gold), encoding="utf-8")
    return path


def test_registered_gold_is_ready_for_project_evaluation_with_ai_provenance():
    report = validate_gold()
    assert report["valid"] and report["project_gold_ready"]
    assert report["gold_id"] == "jurix-pgm-gold-v1"
    assert report["counts"]["distinct_norms"] == 20
    assert report["counts"]["queries"] == 28
    assert report["package_files_verified"] == 37
    assert report["scientific_human_gold_ready"] is False
    assert report["review_kind"] == "ai"


def test_project_adoption_cannot_be_used_to_fabricate_human_gold(tmp_path):
    path = _adopt_copy(
        tmp_path,
        lambda gold: gold["evaluation_policy"].update(scientific_human_gold_ready=True),
    )
    report = validate_gold(path)
    assert not report["project_gold_ready"]
    assert any("evaluation policy" in error for error in report["errors"])


def test_rehashing_changed_reference_does_not_replace_the_adopted_gold(tmp_path):
    source = DEFAULT_GOLD.parent / "ai-adjudicated-20261018-v1"
    package = tmp_path / source.name
    shutil.copytree(source, package)
    gold = _adopt_copy(tmp_path, lambda _: None)
    changed = package / "reference/texts/n01.txt"
    changed.write_text("Uma redação diferente", encoding="utf-8")
    index_path = package / "reference/SHA256SUMS.json"
    inventory = json.loads(index_path.read_text(encoding="utf-8"))
    inventory["texts/n01.txt"] = hashlib.sha256(changed.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(inventory), encoding="utf-8")
    report = validate_gold(gold)
    assert not report["project_gold_ready"]
    assert any("frozen evidence index" in error for error in report["errors"])


def test_missing_reference_is_an_invalid_gold_not_a_successful_adoption(tmp_path):
    report = validate_gold(_adopt_copy(tmp_path, lambda _: None))
    assert not report["valid"]
    assert report["errors"]


def test_report_creation_never_overwrites_previous_validation(tmp_path):
    output = tmp_path / "validation.json"
    output.write_text("original report", encoding="utf-8")
    with pytest.raises(FileExistsError):
        main(["--output", str(output)])
    assert output.read_text(encoding="utf-8") == "original report"
