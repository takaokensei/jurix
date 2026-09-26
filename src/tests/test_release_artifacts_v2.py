import json
from pathlib import Path

from src.processing.rag_eval_engine import evaluate_cases


def test_manifest_example_is_machine_readable():
    path = Path("benchmarks/rag/production/manifest.example.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert "recall@3" in payload["metrics"]


def test_synthetic_unanswerable_dataset_is_structurally_valid():
    path = Path("benchmarks/rag/production/synthetic-unanswerable.jsonl")
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) == 60
    assert all(row["answerability"] == "unanswerable" for row in rows)


def test_zero_case_eval_is_safe():
    report = evaluate_cases([])
    assert report["cases"] == 0
    assert report["groundedness"] == 0.0
