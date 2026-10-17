#!/usr/bin/env python3
"""Profile one fixed public thematic archive search in the isolated QA DB.

The report contains timings, query-shape metadata and PostgreSQL plan nodes only;
it never prints SQL, parameters, excerpts, filenames or candidate identities.
All measurements run inside a read-only transaction with a statement timeout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import time
from urllib.parse import urlparse

QUERY = "ambiental lixo"
SAMPLE_COUNT = 7
STATEMENT_TIMEOUT_MS = 20_000
TABLE_NAMES = (
    "legislation_documentonormativo",
    "legislation_extracaodocumento",
)


def _query_shape(sql: str, duration_ms: float) -> dict[str, object]:
    normalized = re.sub(r"\s+", " ", sql).strip()
    upper = normalized.upper()
    return {
        "fingerprint": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16],
        "duration_ms": round(duration_ms, 3),
        "statement": upper.split(" ", 1)[0] if upper else "unknown",
        "tables": [name for name in TABLE_NAMES if name.upper() in upper],
        "count_distinct": "COUNT(DISTINCT" in upper,
        "window_row_number": "ROW_NUMBER" in upper,
        "subselects": max(0, upper.count("SELECT") - 1),
        "full_text_search": any(
            marker in upper for marker in ("TO_TSVECTOR", "SEARCHVECTOR", "TSQUERY")
        ),
        "statement_length": len(normalized),
    }


def _plan_nodes(plan: dict) -> list[dict[str, object]]:
    rows = []
    pending = [plan.get("Plan", plan)]
    while pending:
        node = pending.pop()
        rows.append(
            {
                "node_type": node.get("Node Type"),
                "index_name": node.get("Index Name"),
                "actual_total_time_ms": node.get("Actual Total Time"),
                "actual_rows": node.get("Actual Rows"),
                "actual_loops": node.get("Actual Loops"),
                "rows_removed_by_filter": node.get("Rows Removed by Filter"),
                "shared_hit_blocks": node.get("Shared Hit Blocks"),
                "shared_read_blocks": node.get("Shared Read Blocks"),
            }
        )
        pending.extend(node.get("Plans", []))
    return rows


def _require_qa() -> None:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
    ):
        raise RuntimeError("profile requires the dedicated normative QA settings")
    database = urlparse(os.environ.get("DATABASE_URL", ""))
    if (
        database.scheme not in {"postgres", "postgresql"}
        or database.hostname != "127.0.0.1"
        or database.port != 55432
        or database.username != "jurix_audit"
        or database.path != "/jurix_audit"
    ):
        raise RuntimeError("profile refuses any database outside the dedicated QA service")


def run() -> dict[str, object]:
    _require_qa()
    project_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    for import_root in (project_root / "src", project_root):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

    import django

    django.setup()

    from django.conf import settings
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext

    from src.processing.document_search import search_archive_documents

    configured = settings.DATABASES["default"]
    if (
        connection.vendor != "postgresql"
        or str(configured.get("HOST")) != "127.0.0.1"
        or str(configured.get("PORT")) != "55432"
        or str(configured.get("NAME")) != "jurix_audit"
        or str(configured.get("USER")) != "jurix_audit"
    ):
        raise RuntimeError("Django resolved a database outside the dedicated QA service")

    samples: list[dict[str, object]] = []
    statement_samples: dict[str, list[dict[str, object]]] = {}
    explain_sql = ""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")

        for sample_number in range(SAMPLE_COUNT):
            started = time.perf_counter()
            with CaptureQueriesContext(connection) as captured:
                result = search_archive_documents(QUERY)
            total_ms = (time.perf_counter() - started) * 1000
            query_profiles = []
            for item in captured.captured_queries:
                duration_ms = float(item.get("time") or 0) * 1000
                profile = _query_shape(item.get("sql", ""), duration_ms)
                query_profiles.append(profile)
                statement_samples.setdefault(str(profile["fingerprint"]), []).append(profile)
            samples.append(
                {
                    "sample": sample_number + 1,
                    "total_ms": round(total_ms, 3),
                    "sql_query_count": len(query_profiles),
                    "result_record_count": int(result.get("record_count") or 0),
                    "result_group_count": int(result.get("count") or 0),
                }
            )
            if sample_number == SAMPLE_COUNT - 1 and query_profiles:
                slowest = max(
                    captured.captured_queries,
                    key=lambda item: float(item.get("time") or 0),
                )
                candidate_sql = str(slowest.get("sql") or "").strip().rstrip(";")
                if candidate_sql.upper().startswith("SELECT "):
                    explain_sql = candidate_sql

        explain = None
        if explain_sql:
            with connection.cursor() as cursor:
                cursor.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + explain_sql
                )
                explain = cursor.fetchone()[0][0]

    aggregated_statements = []
    for _fingerprint, rows in statement_samples.items():
        durations = [float(row["duration_ms"]) for row in rows]
        shape = {key: value for key, value in rows[-1].items() if key != "duration_ms"}
        aggregated_statements.append(
            {
                **shape,
                "samples": len(rows),
                "median_ms": round(statistics.median(durations), 3),
                "max_ms": round(max(durations), 3),
            }
        )
    aggregated_statements.sort(key=lambda row: float(row["median_ms"]), reverse=True)

    totals = [float(sample["total_ms"]) for sample in samples]
    return {
        "status": "measured_read_only_qa",
        "query_label": QUERY,
        "samples": samples,
        "total_ms": {
            "median": round(statistics.median(totals), 3),
            "min": round(min(totals), 3),
            "max": round(max(totals), 3),
        },
        "statements_by_median_ms": aggregated_statements,
        "slowest_statement_plan": {
            "planning_ms": explain.get("Planning Time"),
            "execution_ms": explain.get("Execution Time"),
            "nodes": _plan_nodes(explain["Plan"]),
        } if explain else None,
        "privacy": "SQL text, bound values, filenames, excerpts and legal content are omitted",
        "write_scope": "read-only transaction; no corpus or cache writes",
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
