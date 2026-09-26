import json
from pathlib import Path


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_legal_benchmark_has_real_official_sources() -> None:
    cases = [
        json.loads(x)
        for x in (root() / "benchmarks/rag/legal/v1/cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if x
    ]
    assert len(cases) >= 10
    assert all("planalto.gov.br" in c["source"]["url"] for c in cases)


def test_release_workflow_contains_blocking_vector_gate() -> None:
    text = (root() / ".github/workflows/final-production-assurance-v5.yml").read_text(
        encoding="utf-8"
    )
    assert "vector_production_gate_v5.py --strict --json" in text


def test_ingestion_refactor_contract_is_current() -> None:
    assert (root() / "scripts/check_ingestion_contract.py").exists()
    assert not (root() / "src/apps/ingestion/tasks_legacy.py").exists()
