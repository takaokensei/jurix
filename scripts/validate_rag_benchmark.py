"""Validate the integrity of a reviewed RAG benchmark dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REQUIRED_MANIFEST_KEYS = {
    "schema_version",
    "dataset_path",
    "dataset_sha256",
    "embedding_model",
    "generation_model",
    "min_cases",
    "metrics",
}
REQUIRED_METRICS = {
    "recall@1",
    "recall@3",
    "mrr",
    "citation_precision",
    "citation_recall",
    "groundedness",
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Linha {number}: JSON inválido: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Linha {number}: caso deve ser objeto JSON.")
            rows.append(payload)
    return rows


def validate_case(case: dict, index: int) -> list[str]:
    required = {"id", "question", "expected_sources"}
    errors = []
    missing = sorted(required - case.keys())
    if missing:
        errors.append(f"case[{index}] missing: {', '.join(missing)}")
    if not str(case.get("question", "")).strip():
        errors.append(f"case[{index}] question is empty")
    if not isinstance(case.get("expected_sources"), list):
        errors.append(f"case[{index}] expected_sources must be a list")
    if case.get("answerability") not in {None, "answerable", "unanswerable"}:
        errors.append(f"case[{index}] answerability is invalid")
    return errors


def validate(manifest_path: Path) -> list[str]:
    errors = []
    manifest = load_json(manifest_path)
    missing = sorted(REQUIRED_MANIFEST_KEYS - manifest.keys())
    if missing:
        return [f"manifest missing: {', '.join(missing)}"]

    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not str(manifest.get("embedding_model", "")).strip():
        errors.append("embedding_model must be pinned")
    if not str(manifest.get("generation_model", "")).strip():
        errors.append("generation_model must be pinned")

    metrics = set(manifest.get("metrics", []))
    missing_metrics = sorted(REQUIRED_METRICS - metrics)
    if missing_metrics:
        errors.append("manifest missing metrics: " + ", ".join(missing_metrics))

    dataset = (manifest_path.parent / manifest["dataset_path"]).resolve()
    if not dataset.is_file():
        return errors + [f"dataset does not exist: {dataset}"]

    expected_hash = str(manifest["dataset_sha256"]).lower()
    actual_hash = sha256(dataset)
    if expected_hash != actual_hash:
        errors.append(
            f"dataset sha256 mismatch: expected={expected_hash} actual={actual_hash}"
        )

    cases = load_jsonl(dataset)
    min_cases = int(manifest["min_cases"])
    if len(cases) < min_cases:
        errors.append(f"dataset has {len(cases)} case(s), minimum is {min_cases}")

    seen_ids = set()
    for index, case in enumerate(cases):
        errors.extend(validate_case(case, index))
        case_id = case.get("id")
        if case_id in seen_ids:
            errors.append(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)

    try:
        errors = validate(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RAG benchmark invalid: {exc}", file=sys.stderr)
        return 2

    if errors:
        print("RAG benchmark contract failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"RAG benchmark contract valid: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
