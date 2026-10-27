"""Validate the adopted Jurix project gold and its frozen AI evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.validate_pgm_ai_adjudicated import validate_reference
except ModuleNotFoundError:
    from validate_pgm_ai_adjudicated import validate_reference


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "benchmarks/corpus/municipal_natal/project-gold.v1.json"
COUNTS = ("distinct_norms", "adjudications_ai", "spans", "events", "queries")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_package(root: Path, expected_hash: str) -> int:
    inventory = root / "ARTIFACT_SHA256SUMS.json"
    if _sha(inventory) != expected_hash:
        raise ValueError("package: frozen artifact index differs from the adopted gold")
    entries = json.loads(inventory.read_text(encoding="utf-8"))
    if not isinstance(entries, dict) or not entries:
        raise ValueError("package: empty or malformed artifact index")
    for relative, digest in entries.items():
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file() or _sha(target) != digest:
            raise ValueError(f"package: changed or missing artifact: {relative}")
    return len(entries)


def validate_gold(path: Path = DEFAULT_GOLD, *, inputs: Path | None = None) -> dict:
    """Check adoption plus evidence; project readiness never implies human review."""
    report = {
        "schema_version": "jurix-project-gold-validation-v1",
        "validated_at": datetime.now(UTC).isoformat(),
        "valid": False,
        "project_gold_ready": False,
        "scientific_human_gold_ready": False,
        "human_adjudications": 0,
        "errors": [],
    }
    path = path.resolve()
    try:
        gold = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(gold, dict):
            raise ValueError("adoption: expected an object")
        for key in (
            "adjudication",
            "authorization",
            "coverage",
            "evaluation_policy",
            "expected_counts",
            "reference",
        ):
            if not isinstance(gold.get(key), dict):
                raise ValueError(f"adoption: {key} must be an object")
        if (
            gold.get("schema_version") != "jurix-project-gold-v1"
            or gold.get("gold_id") != "jurix-pgm-gold-v1"
            or gold.get("status") != "adopted"
        ):
            raise ValueError("adoption: unknown gold version or inactive adoption")
        if gold.get("adjudication") != {
            "review_kind": "ai",
            "independent_review": False,
            "human_approved": False,
        }:
            raise ValueError("adoption: AI adjudication provenance was changed")
        policy = gold["evaluation_policy"]
        required_policy = {
            "project_evaluation_authorized": True,
            "scientific_human_gold_ready": False,
            "keep_unresolved_and_abstention_cases": True,
            "keep_chain_splits": True,
            "predictions_must_be_separate": True,
            "unannotated_events_are_not_automatically_false_positives": True,
        }
        if any(policy.get(key) is not value for key, value in required_policy.items()):
            raise ValueError("adoption: evaluation policy was changed")
        if gold.get("coverage") != {
            "devices": "selected_excerpts",
            "events_exhaustive": False,
            "complete_current_validity": False,
            "prior_development_exposure": True,
        }:
            raise ValueError("adoption: evidence coverage was changed")
        authorization = gold["authorization"]
        if (
            authorization.get("source") != "project_owner_instruction_in_this_conversation"
            or not authorization.get("instruction")
            or not authorization.get("scope")
        ):
            raise ValueError("adoption: owner decision is missing")
        datetime.strptime(gold["adoption_date"], "%Y-%m-%d")
        source = gold["reference"]
        reference = (path.parent / source["path"]).resolve()
        if not reference.is_relative_to(path.parent) or reference == path.parent:
            raise ValueError("reference: path must stay inside the corpus directory")
        if _sha(reference / "SHA256SUMS.json") != source["hash_index_sha256"]:
            raise ValueError("reference: frozen evidence index differs from the adopted gold")
        verified = _verify_package(reference.parent, source["package_index_sha256"])
        evidence = validate_reference(reference, inputs=inputs)
        report["errors"].extend(evidence["errors"])
        expected = gold["expected_counts"]
        for key in (*COUNTS, "relation_families"):
            if expected[key] != evidence[key]:
                report["errors"].append(f"counts: {key} differs from the adopted gold")
        report.update(
            gold_id=gold["gold_id"],
            title=gold["title"],
            evidence_status=policy["label"],
            review_kind="ai",
            independent_review=False,
            adoption_sha256=_sha(path),
            reference_hash_index_sha256=source["hash_index_sha256"],
            package_hash_index_sha256=source["package_index_sha256"],
            package_files_verified=verified,
            counts={key: evidence[key] for key in (*COUNTS, "relation_families")},
            pdfs_verified_this_run=evidence["pdfs_verified"],
            original_texts_verified_this_run=evidence["original_texts_verified"],
            reference_limits=evidence["limits"],
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["errors"].append(str(exc))
    report["valid"] = not report["errors"]
    report["project_gold_ready"] = report["valid"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--inputs", type=Path, help="Optional frozen originals for PDF rechecks")
    parser.add_argument("--output", type=Path, help="Create a new report; refuses replacement")
    args = parser.parse_args(argv)
    report = validate_gold(args.gold, inputs=args.inputs)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered)
    print(rendered, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
