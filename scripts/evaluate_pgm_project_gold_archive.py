#!/usr/bin/env python3
"""Measure exact source/article retrieval for the adopted PGM gold in isolated QA.

This read-only diagnostic exercises the local-archive retriever. It does not
generate answers, change document review state, or claim legal/scientific accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_normative_rag_experiment import _gold_citation_id  # noqa: E402
from scripts.pgm_project_gold import DEFAULT_GOLD, validate_gold  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _source_unit_map(reference: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for filename, source_key in (
        ("source-origins.jsonl", "unit_id"),
        ("supporting-evidence.jsonl", "source_id"),
    ):
        for row in _read_jsonl(reference / filename):
            document_key = row.get("document_key")
            source_id = row.get(source_key)
            if document_key and source_id:
                result[str(document_key).removeprefix("sha256:").lower()] = str(source_id)
    return result


def score_retrieval(query_rows: list[dict], retrieval_rows: list[list[dict]], limit: int) -> dict:
    if len(query_rows) != len(retrieval_rows):
        raise ValueError("one retrieval result is required for each gold query")
    expected_sources = expected_articles = 0
    source_hits_5 = source_hits_limit = 0
    article_hits_5 = article_hits_limit = 0
    queries_source_hit_5 = queries_source_hit_limit = 0
    queries_article_hit_5 = queries_article_hit_limit = 0
    missing_article_cases = []
    total_records = records_with_hash = records_matching_gold = 0
    per_query = []

    for query, sources in zip(query_rows, retrieval_rows, strict=True):
        expected_hashes = {
            str(value).removeprefix("sha256:").lower()
            for value in query.get("expected_source_ids", [])
        }
        expected_citations = set(query.get("expected_citation_ids", []))
        expected_sources += len(expected_hashes)
        expected_articles += len(expected_citations)
        total_records += len(sources)

        hashes = [str(source.get("document_sha256") or "").lower() for source in sources]
        records_with_hash += sum(bool(value) for value in hashes)
        records_matching_gold += sum(value in expected_hashes for value in hashes if value)
        hash_hits_5 = expected_hashes & set(hashes[:5])
        hash_hits_limit = expected_hashes & set(hashes[:limit])
        source_hits_5 += len(hash_hits_5)
        source_hits_limit += len(hash_hits_limit)
        queries_source_hit_5 += bool(hash_hits_5)
        queries_source_hit_limit += bool(hash_hits_limit)

        citations = [
            _gold_citation_id(source, query["gold_source_unit_map"])
            for source in sources
        ]
        citations = [value for value in citations if value]
        article_query_hits_5 = expected_citations & set(citations[:5])
        article_query_hits_limit = expected_citations & set(citations[:limit])
        article_hits_5 += len(article_query_hits_5)
        article_hits_limit += len(article_query_hits_limit)
        queries_article_hit_5 += bool(article_query_hits_5)
        queries_article_hit_limit += bool(article_query_hits_limit)
        if not article_query_hits_limit:
            missing_article_cases.append(query["case_id"])
        per_query.append(
            {
                "case_id": query["case_id"],
                "expected_source_count": len(expected_hashes),
                "expected_citation_count": len(expected_citations),
                "retrieved_record_count": len(sources),
                "source_hits_at_5": len(hash_hits_5),
                "source_hits_at_limit": len(hash_hits_limit),
                "article_hits_at_5": len(article_query_hits_5),
                "article_hits_at_limit": len(article_query_hits_limit),
                "missed_sources_at_5": sorted(expected_hashes - set(hashes[:5])),
                "missed_sources_at_limit": sorted(expected_hashes - set(hashes[:limit])),
                "missed_citations_at_5": sorted(expected_citations - set(citations[:5])),
                "missed_citations_at_limit": sorted(expected_citations - set(citations[:limit])),
            }
        )

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "query_count": len(query_rows),
        "retrieval_limit": limit,
        "source_recall_at_5": ratio(source_hits_5, expected_sources),
        "source_recall_at_limit": ratio(source_hits_limit, expected_sources),
        "source_expected_count": expected_sources,
        "queries_with_expected_source_at_5": queries_source_hit_5,
        "queries_with_expected_source_at_limit": queries_source_hit_limit,
        "article_recall_at_5": ratio(article_hits_5, expected_articles),
        "article_recall_at_limit": ratio(article_hits_limit, expected_articles),
        "article_expected_count": expected_articles,
        "queries_with_expected_article_at_5": queries_article_hit_5,
        "queries_with_expected_article_at_limit": queries_article_hit_limit,
        "queries_without_expected_article_at_limit": missing_article_cases,
        "retrieved_records": total_records,
        "retrieved_records_with_document_hash": records_with_hash,
        "retrieved_records_matching_expected_pdf": records_matching_gold,
        "per_query": per_query,
        "scientific_claim_allowed": False,
        "limitations": [
            "AI-adjudicated focal gold; not independently reviewed by human jurists.",
            "This measures retrieval only, not answer correctness, current legal force, or graph quality.",
            "Unannotated sources are not automatically legally irrelevant.",
        ],
    }


def source_inventory(expected_hashes: set[str], document_rows: list[dict]) -> dict:
    """Reconcile expected Gold PDF hashes with QA metadata, without legal text."""
    by_hash: dict[str, list[dict]] = {}
    for row in document_rows:
        digest = str(row.get("content_sha256") or "").lower()
        if digest:
            by_hash.setdefault(digest, []).append(row)

    def counts(matches: list[dict], field: str, missing: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in matches:
            value = str(row.get(field) or missing)
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))

    items = []
    for digest in sorted(expected_hashes):
        matches = by_hash.get(digest, [])
        items.append(
            {
                "document_sha256": digest,
                "qa_document_count": len(matches),
                "source_kinds": counts(matches, "source_kind", "unknown"),
                "review_statuses": counts(matches, "review_status", "unknown"),
                "latest_extraction_statuses": counts(
                    matches, "latest_extraction_status", "none"
                ),
                "accepted_extraction_count": sum(
                    bool(row.get("accepted_extraction_id")) for row in matches
                ),
            }
        )

    present = sum(item["qa_document_count"] > 0 for item in items)
    accepted = sum(item["accepted_extraction_count"] > 0 for item in items)
    return {
        "expected_source_hash_count": len(expected_hashes),
        "exact_hash_present_count": present,
        "exact_hash_absent_count": len(expected_hashes) - present,
        "sources_with_accepted_extraction_count": accepted,
        "sources_without_accepted_extraction_count": len(expected_hashes) - accepted,
        "items": items,
    }


def extracted_article_marker_coverage(
    source_to_unit: dict[str, str], expected_citations: set[str], document_rows: list[dict]
) -> dict:
    """Count expected article markers present in current technical extractions only."""
    expected_by_unit: dict[str, set[str]] = {}
    for citation in expected_citations:
        unit, separator, article = str(citation).partition(":art:")
        match = re.match(r"\s*(\d+)", article) if separator else None
        if match:
            expected_by_unit.setdefault(unit, set()).add(str(int(match.group(1))))

    rows_by_hash: dict[str, list[dict]] = {}
    for row in document_rows:
        digest = str(row.get("content_sha256") or "").lower()
        if digest:
            rows_by_hash.setdefault(digest, []).append(row)

    from src.processing.legal_parser import LegalTextParser

    unit_documents: dict[str, list[dict]] = {}
    for digest, unit in source_to_unit.items():
        for row in rows_by_hash.get(digest, []):
            text = str(row.get("latest_legal_text") or "")
            markers = set()
            if text:
                for article in LegalTextParser.extract_articles(text):
                    match = re.match(r"\s*(\d+)", str(article.get("numero") or ""))
                    if match:
                        markers.add(str(int(match.group(1))))
            unit_documents.setdefault(unit, []).append(
                {
                    "document_sha256": digest,
                    "latest_extraction_status": row.get("latest_extraction_status") or "none",
                    "parsed_article_marker_count": len(markers),
                    "article_markers": markers,
                }
            )

    items = []
    matched_total = 0
    expected_total = 0
    for unit, expected_articles in sorted(expected_by_unit.items()):
        documents = unit_documents.get(unit, [])
        parsed_articles = set().union(*(row["article_markers"] for row in documents)) if documents else set()
        matched = expected_articles & parsed_articles
        matched_total += len(matched)
        expected_total += len(expected_articles)
        items.append(
            {
                "unit_id": unit,
                "expected_article_count": len(expected_articles),
                "expected_article_markers_present": len(matched),
                "missing_article_markers": sorted(expected_articles - parsed_articles, key=int),
                "matching_document_hash_count": len(documents),
                "latest_extraction_statuses": dict(
                    sorted(
                        (status, sum(row["latest_extraction_status"] == status for row in documents))
                        for status in {row["latest_extraction_status"] for row in documents}
                    )
                ),
            }
        )
    return {
        "method": "LegalTextParser article-marker presence in the latest technical extraction; not content validation",
        "expected_unit_article_count": expected_total,
        "unit_article_markers_present": matched_total,
        "unit_article_marker_recall": matched_total / expected_total if expected_total else None,
        "items": items,
    }


def _qa_root() -> Path:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise ValueError("JURIX_QA_ONLY=1 is required")
    if os.environ.get("DJANGO_SETTINGS_MODULE") not in {
        "config.settings_normative_qa",
        "config.settings_normative_container_qa",
    }:
        raise ValueError("an isolated normative QA settings module is required")
    raw_root = os.environ.get("JURIX_QA_ROOT")
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if not raw_root or not temp:
        raise ValueError("QA output root and system temporary directory are required")
    root, temp_root = Path(raw_root).resolve(), Path(temp).resolve()
    if not root.is_relative_to(temp_root) or root == temp_root:
        raise ValueError("QA output root must be a child of the system temporary directory")
    return root


def evaluate(gold_path: Path, limit: int) -> dict:
    validation = validate_gold(gold_path)
    if not validation["valid"] or not validation["project_gold_ready"]:
        raise ValueError("adopted project gold failed integrity validation")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    reference = (gold_path.parent / gold["reference"]["path"]).resolve()
    query_rows = _read_jsonl(reference / "queries.ai.jsonl")
    if len(query_rows) != gold["expected_counts"]["queries"]:
        raise ValueError("gold query count differs from its frozen manifest")
    unit_map = _source_unit_map(reference)
    query_rows = [{**row, "gold_source_unit_map": unit_map} for row in query_rows]

    import django
    from django.conf import settings
    from django.db import connection, transaction
    from django.db.models import OuterRef, Subquery

    django.setup()
    database = settings.DATABASES["default"]
    if (
        database.get("HOST") not in {"127.0.0.1", "localhost"}
        or str(database.get("PORT")) != "55432"
        or database.get("NAME") != "jurix_audit"
    ):
        raise ValueError("refusing to query a database outside the isolated QA service")
    from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
    from src.processing.qa_archive_rag import retrieve_archive_evidence

    expected_hashes = {
        str(source_hash).removeprefix("sha256:").lower()
        for row in query_rows
        for source_hash in row.get("expected_source_ids", [])
    }
    expected_citations = {
        str(citation)
        for row in query_rows
        for citation in row.get("expected_citation_ids", [])
    }
    latest_extraction = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        retrieved = []
        latency_rows = []
        for row in query_rows:
            started = time.perf_counter()
            evidence = retrieve_archive_evidence(row["query"], limit=limit)
            latency_rows.append(
                {
                    "case_id": row["case_id"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
            retrieved.append(evidence)
        document_rows = list(
            DocumentoNormativo.objects.filter(content_sha256__in=expected_hashes)
            .annotate(
                latest_extraction_status=Subquery(latest_extraction.values("status")[:1]),
                latest_legal_text=Subquery(latest_extraction.values("legal_text")[:1]),
            )
            .values(
                "content_sha256",
                "source_kind",
                "review_status",
                "accepted_extraction_id",
                "latest_extraction_status",
                "latest_legal_text",
            )
        )
    report = score_retrieval(query_rows, retrieved, limit)
    report["source_inventory"] = source_inventory(expected_hashes, document_rows)
    report["extracted_article_marker_coverage"] = extracted_article_marker_coverage(
        unit_map, expected_citations, document_rows
    )
    latencies = sorted(row["latency_ms"] for row in latency_rows)
    report["latency"] = {
        "method": "time.perf_counter around each retrieve_archive_evidence call; warm in-process sequence",
        "unit": "ms",
        "query_count": len(latencies),
        "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "p50": latencies[(len(latencies) - 1) // 2] if latencies else None,
        "p95": latencies[min(len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None,
        "per_query": latency_rows,
    }
    report.update({
        "schema_version": "jurix-pgm-project-gold-archive-retrieval-v1",
        "status": "read_only_qa_retrieval_diagnostic",
        "gold_id": gold["gold_id"],
        "gold_adoption_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "gold_validation": {
            "valid": validation["valid"],
            "review_kind": validation["review_kind"],
            "independent_review": validation["independent_review"],
            "scientific_human_gold_ready": validation["scientific_human_gold_ready"],
        },
        "database_mutations": 0,
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--limit", type=int, default=48)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.limit <= 48:
            raise ValueError("limit must be between 1 and 48")
        qa_root = _qa_root()
        output = args.output.resolve()
        if not output.is_relative_to(qa_root) or output == qa_root:
            raise ValueError("report output must stay inside JURIX_QA_ROOT")
        report = evaluate(args.gold.resolve(), args.limit)
        with output.open("x", encoding="utf-8", newline="\n") as target:
            json.dump(report, target, ensure_ascii=False, indent=2, sort_keys=True)
            target.write("\n")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"archive retrieval evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
