"""Validate an AI-adjudicated technical reference without claiming human gold."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import jsonschema

try:
    from scripts.validate_municipal_corpus import validate_corpus
except ModuleNotFoundError:
    from validate_municipal_corpus import validate_corpus


def load_lines(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_reference(root: Path, *, inputs: Path | None = None) -> dict:
    root = root.resolve()
    errors = []
    legacy = validate_corpus(root / "manifest.jsonl", root / "annotations.pending-human.jsonl")
    errors.extend(legacy["errors"])
    manifest = load_lines(root / "manifest.jsonl")
    wrappers = load_lines(root / "annotations.ai-adjudicated.jsonl")
    decisions = load_lines(root / "adjudications.ai.jsonl")
    pending = load_lines(root / "annotations.pending-human.jsonl")
    queries = load_lines(root / "queries.ai.jsonl")
    origins = load_lines(root / "source-origins.jsonl")
    supplements = load_lines(root / "supporting-evidence.jsonl")
    splits = json.loads((root / "splits.json").read_text(encoding="utf-8"))
    inventory = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
    for relative, expected in inventory.items():
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or sha(path.read_bytes()) != expected
        ):
            errors.append(f"integrity: {relative}")
    schema_root = Path(__file__).resolve().parents[1] / "benchmarks/corpus/municipal_natal"
    manifest_schema = json.loads(
        (schema_root / "manifest.v2.schema.json").read_text(encoding="utf-8")
    )
    annotation_schema = json.loads(
        (schema_root / "annotation.v2.schema.json").read_text(encoding="utf-8")
    )
    ai_schema = json.loads(
        (schema_root / "ai-adjudicated-20261018-v1/annotation.ai.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    for row in manifest:
        for error in jsonschema.Draft202012Validator(manifest_schema).iter_errors(row):
            errors.append(f"manifest schema: {error.message}")
    identities = {
        (
            r["norma"]["jurisdicao"],
            r["norma"]["tipo"],
            str(int(r["norma"]["numero"].replace(".", ""))),
            r["norma"]["ano"],
        )
        for r in manifest
    }
    norm_keys = {r["norma_key"] for r in manifest}
    if len(identities) != len(manifest) or len(norm_keys) != len(manifest) or len(norm_keys) < 20:
        errors.append("identity: expected at least 20 distinct normative identities, one per unit")
    if not (len(wrappers) == len(decisions) == len(pending) == len(manifest)):
        errors.append("coverage: missing annotation or adjudication")
    documents = {r["document_key"]: r for r in manifest}
    texts = {
        r["document_key"]: (root / r["text"]["path"]).read_text(encoding="utf-8") for r in manifest
    }
    pending_by_id = {r["annotation_id"]: r for r in pending}
    decisions_by_id = {r["norma_key"]: r for r in decisions}
    norm_to_split = {value["norma_key"]: value for value in splits.values()}
    chain_splits = defaultdict(set)
    for assignment in splits.values():
        chain_splits[assignment["chain_key"]].add(assignment["split"])
    if any(len(values) != 1 for values in chain_splits.values()):
        errors.append("split: chain crosses partitions")
    if set(norm_to_split) != norm_keys:
        errors.append("split: missing or unknown norm")
    citations, event_ids, relation_families = set(), set(), set()
    events_count, spans_count = 0, 0
    for wrapper in wrappers:
        for error in jsonschema.Draft202012Validator(
            ai_schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(wrapper):
            errors.append(f"AI adjudication schema: {error.message}")
        annotation, decision = wrapper["annotation"], wrapper["adjudication"]
        for error in jsonschema.Draft202012Validator(annotation_schema).iter_errors(annotation):
            errors.append(f"annotation schema: {error.message}")
        if wrapper.get("schema_version") != "jurix-ai-adjudicated-v1":
            errors.append("review: unknown AI schema")
        if (
            decision.get("review_kind") != "ai"
            or decision.get("status") != "adjudicated_by_ai"
            or decision.get("human_approved") is not False
            or decision.get("independent_review") is not False
        ):
            errors.append("review: AI origin or independence misrepresented")
        if decision != decisions_by_id.get(annotation["norma_key"]):
            errors.append("review: inconsistent adjudication trail")
        if decision.get("source_text_sha256") != annotation["revision"][
            "source_text_sha256"
        ] or not decision.get("decision"):
            errors.append("review: unbound or empty adjudication")
        doc = documents[annotation["document_key"]]
        text = texts[annotation["document_key"]]
        if annotation["norma_key"] != doc["norma_key"]:
            errors.append("identity: annotation/document mismatch")
        normalized = deepcopy(annotation)
        for event in normalized["events"]:
            event["resolution"] = "pending_review"
        if normalized != pending_by_id.get(annotation["annotation_id"]):
            errors.append("review: pending human export differs from AI evidence")
        if annotation["review"] != {
            "status": "pending",
            "reviewer_id": None,
            "reviewed_at": None,
            "review_kind": "human",
        }:
            errors.append("review: human approval was fabricated")
        for span in annotation["spans"]:
            spans_count += 1
            citations.add(span["span_id"])
            if text[span["start"] : span["end"]] != span["quote"]:
                errors.append("quote: span differs from frozen text")
        span_by_id = {span["span_id"]: span for span in annotation["spans"]}
        for event in annotation["events"]:
            events_count += 1
            if event["event_id"] in event_ids:
                errors.append("events: duplicate ID")
            event_ids.add(event["event_id"])
            proof = event["evidence"]
            if (
                proof["source_text_sha256"] != doc["text"]["sha256"]
                or text[proof["start"] : proof["end"]] != proof["quote"]
            ):
                errors.append("quote: event differs from frozen text")
            parent = span_by_id.get(event["source_span_id"])
            if (
                parent is None
                or not parent["start"] <= proof["start"] < proof["end"] <= parent["end"]
            ):
                errors.append("events: evidence outside source span")
            target = event["target_norma_key"]
            if event["resolution"] == "resolved" and (
                target not in norm_keys or not event["target_device_key"]
            ):
                errors.append("events: resolved target absent")
            if target in norm_to_split:
                source_assignment = norm_to_split[annotation["norma_key"]]
                target_assignment = norm_to_split[target]
                if source_assignment["split"] != target_assignment["split"]:
                    errors.append("split: related norms leak between partitions")
                if event["resolution"] == "resolved":
                    relation_families.add(source_assignment["chain_key"])
    if len(relation_families) < 3:
        errors.append("chains: fewer than three actual relation families")
    if any(
        r["human_review"]["status"] != "not_reviewed" or r["pilot"] != "technical_pilot"
        for r in manifest
    ):
        errors.append("review: manifest falsely claims human approval")
    versions = {r["document_key"]: r["text"]["sha256"] for r in manifest}
    for source in supplements:
        if source.get("citation_id"):
            citations.add(source["citation_id"])
            versions[source["document_key"]] = source["source_text_sha256"]
    case_ids = set()
    for case in queries:
        if case["case_id"] in case_ids:
            errors.append("query: duplicate ID")
        case_ids.add(case["case_id"])
        if case.get("review_kind") != "ai" or case.get("human_evidence_review") is not False:
            errors.append("query: review origin misrepresented")
        if (
            not set(case["expected_citation_ids"]) <= citations
            or not set(case["expected_source_ids"]) <= versions.keys()
        ):
            errors.append("query: unknown expected citation or source")
        if any(versions.get(key) != value for key, value in case["expected_versions"].items()):
            errors.append("query: version mismatch")
        if any(splits[uid]["split"] != case["split"] for uid in case["expected_unit_ids"]):
            errors.append("split: query crosses partitions")
    pdfs_verified, source_texts_verified = 0, 0
    if inputs is not None:
        frozen = {
            r["unit_id"]: r
            for r in json.loads((inputs / "inputs.json").read_text(encoding="utf-8"))
        }
        for origin in origins:
            source = frozen[origin["unit_id"]]
            original = (inputs / source["text_path"]).read_text(encoding="utf-8")
            if sha(original.encode()) != origin["origin_text_sha256"]:
                errors.append("origin: text hash mismatch")
            else:
                source_texts_verified += 1
            if (
                sha(Path(source["pdf_path"]).read_bytes())
                != documents[origin["document_key"]]["document"]["sha256"]
            ):
                errors.append("origin: PDF hash mismatch")
            else:
                pdfs_verified += 1
            selected = texts[origin["document_key"]]
            for name in ("identity_evidence", "ementa_conflict_evidence"):
                proof = origin.get(name)
                if proof and (
                    proof["origin_text_sha256"] != origin["origin_text_sha256"]
                    or original[proof["start"] : proof["end"]] != proof["quote"]
                ):
                    errors.append("origin: identity/ementa evidence mismatch")
            for segment in origin["excerpt_mapping"]:
                if (
                    original[segment["source_start"] : segment["source_end"]]
                    != selected[segment["excerpt_start"] : segment["excerpt_end"]]
                ):
                    errors.append("origin: excerpt is not an exact source slice")
    return {
        "valid": not errors,
        "ai_reference_ready": not errors,
        "scientific_human_gold_ready": False,
        "human_adjudications": 0,
        "distinct_norms": len(identities),
        "adjudications_ai": len(decisions),
        "spans": spans_count,
        "events": events_count,
        "queries": len(queries),
        "relation_families": sorted(relation_families),
        "pdfs_verified": pdfs_verified,
        "original_texts_verified": source_texts_verified,
        "errors": errors,
        "pending_human_validator": legacy,
        "limits": [
            "AI session, no independent reviewers",
            "Retrospective sample exposed to development",
            "Selected devices and non-exhaustive events",
            "No legal validity guarantee or whole-corpus accuracy estimate",
        ],
    }


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_reference(args.reference, inputs=args.inputs)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        if args.output.exists():
            raise SystemExit("Refusing to replace an existing validation report")
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
