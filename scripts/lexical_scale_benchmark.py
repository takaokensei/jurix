#!/usr/bin/env python3
"""Compare synthetic lexical and pgvector retrieval only in the audit database."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import statistics
import time
from urllib.parse import urlparse

from psycopg2 import Error as PsycopgError
from psycopg2 import connect
from psycopg2.extras import execute_values

DIMENSIONS = 768
TOP_K = 10
FILTER = "norma_type = 'Lei' AND publication_year = 2026 AND is_active"
TOPICS = {index: f"categoria {index} politica educacional municipal" for index in range(5)}


def database_is_allowed(database_url: str) -> bool:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    return (
        parsed.scheme in {"postgres", "postgresql"}
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and parsed.port == 55432
        and database_name == "jurix_audit"
    )


def ranking_metrics(expected_ids: set[int], retrieved_ids: list[int]) -> dict:
    denominator = min(TOP_K, len(expected_ids))
    hits = len(expected_ids & set(retrieved_ids[:TOP_K]))
    reciprocal_rank = next(
        (
            1 / rank
            for rank, identifier in enumerate(retrieved_ids, 1)
            if identifier in expected_ids
        ),
        0.0,
    )
    return {
        "recall_at_10": hits / denominator if denominator else None,
        "mrr": reciprocal_rank,
        "expected_relevant": len(expected_ids),
        "retrieved": len(retrieved_ids),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _vector(topic: int, rng: random.Random) -> str:
    values = [rng.gauss(0, 0.001) for _ in range(DIMENSIONS)]
    values[topic] += 1.0
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _seed(cursor, rows: int, seed: int) -> float:
    rng = random.Random(seed)
    statement = """INSERT INTO jurix_scale_fixture
        (id, norma_type, publication_year, is_active, body, body_tsv, embedding)
        VALUES %s"""
    started = time.perf_counter()
    for start in range(1, rows + 1, 500):
        batch = []
        for identifier in range(start, min(start + 500, rows + 1)):
            topic = identifier % len(TOPICS)
            body = f"Lei municipal {TOPICS[topic]} interesse publico dispositivos {identifier}"
            batch.append(
                (
                    identifier,
                    "Lei" if identifier % 4 else "Decreto",
                    2026 if identifier % 3 else 2025,
                    identifier % 7 != 0,
                    body,
                    body,
                    _vector(topic, rng),
                )
            )
        execute_values(
            cursor,
            statement,
            batch,
            template="(%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector)",
            page_size=500,
        )
    return round((time.perf_counter() - started) * 1000, 3)


def _explain(cursor, query: str, params: tuple) -> dict:
    cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params)
    return cursor.fetchone()[0][0]


def _plan_summary(plan: dict) -> list[dict]:
    nodes = []
    pending = [plan.get("Plan", {})]
    while pending:
        node = pending.pop()
        nodes.append(
            {
                "node_type": node.get("Node Type"),
                "index_name": node.get("Index Name"),
                "local_hit_blocks": node.get("Local Hit Blocks"),
                "local_read_blocks": node.get("Local Read Blocks"),
                "shared_hit_blocks": node.get("Shared Hit Blocks"),
                "shared_read_blocks": node.get("Shared Read Blocks"),
            }
        )
        pending.extend(node.get("Plans", []))
    return nodes


def _run_mode(cursor, mode: str, query: str, params: tuple, expected: set[int], runs: int) -> dict:
    cursor.execute(query, params)
    warm_ids = [row[0] for row in cursor.fetchall()]
    plan = _explain(cursor, query, params)
    timings = []
    result_ids = warm_ids
    for _ in range(runs):
        started = time.perf_counter()
        cursor.execute(query, params)
        result_ids = [row[0] for row in cursor.fetchall()]
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "mode": mode,
        "runs": len(timings),
        "cache_state": "warm after initial query",
        "latency_ms": {
            "median": round(statistics.median(timings), 3),
            "p95_sample": percentile(timings, 0.95),
            "min": round(min(timings), 3),
            "max": round(max(timings), 3),
        },
        "ranking": ranking_metrics(expected, result_ids),
        "explain_analyze_buffers": {
            "planning_ms": plan.get("Planning Time"),
            "execution_ms": plan.get("Execution Time"),
            "nodes": _plan_summary(plan),
        },
    }


def run(database_url: str, rows: int, runs: int, seed: int) -> dict:
    if not database_is_allowed(database_url):
        raise ValueError("DATABASE_URL deve apontar exatamente para o banco isolado jurix_audit")
    report = {
        "schema_version": 1,
        "status": "measured synthetic workload",
        "database": "jurix_audit",
        "rows": rows,
        "dimensions": DIMENSIONS,
        "top_k": TOP_K,
        "runs_per_query": runs,
        "seed": seed,
        "host": {"platform": platform.platform(), "cpu_count": os.cpu_count()},
        "cache_state": "warm only; cold-cache benchmark not attempted",
        "results": [],
    }
    connection = connect(database_url)
    try:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cursor.execute("""CREATE TEMP TABLE jurix_scale_fixture (
                id integer PRIMARY KEY,
                norma_type text NOT NULL,
                publication_year integer NOT NULL,
                is_active boolean NOT NULL,
                body text NOT NULL,
                body_tsv tsvector NOT NULL,
                embedding vector(768) NOT NULL
            ) ON COMMIT PRESERVE ROWS""")
            report["seed_time_ms"] = _seed(cursor, rows, seed)
            index_started = time.perf_counter()
            cursor.execute(
                "CREATE INDEX ON jurix_scale_fixture USING hnsw (embedding vector_cosine_ops)"
            )
            cursor.execute("CREATE INDEX ON jurix_scale_fixture USING gin (body_tsv)")
            cursor.execute("CREATE INDEX ON jurix_scale_fixture USING gin (body gin_trgm_ops)")
            cursor.execute(
                "CREATE INDEX ON jurix_scale_fixture (norma_type, publication_year, is_active)"
            )
            report["index_build_ms"] = round((time.perf_counter() - index_started) * 1000, 3)
            cursor.execute("SET LOCAL hnsw.ef_search = 100")

            for topic, query_text in TOPICS.items():
                cursor.execute(
                    f"SELECT id FROM jurix_scale_fixture WHERE {FILTER} AND id %% 5 = %s",
                    (topic,),
                )
                expected_ids = {row[0] for row in cursor.fetchall()}
                vector = "[" + ",".join("1" if i == topic else "0" for i in range(DIMENSIONS)) + "]"
                report["results"].append(
                    {
                        "query_class": f"synthetic_topic_{topic}",
                        "modes": [
                            _run_mode(
                                cursor,
                                "pgvector_hnsw",
                                f"""SELECT id FROM jurix_scale_fixture
                            WHERE {FILTER} ORDER BY embedding <=> %s::vector LIMIT {TOP_K}""",
                                (vector,),
                                expected_ids,
                                runs,
                            ),
                            _run_mode(
                                cursor,
                                "postgres_fts",
                                f"""SELECT id FROM jurix_scale_fixture
                            WHERE {FILTER} AND body_tsv @@ plainto_tsquery('simple', %s)
                            ORDER BY ts_rank(body_tsv, plainto_tsquery('simple', %s)) DESC LIMIT {TOP_K}""",
                                (query_text, query_text),
                                expected_ids,
                                runs,
                            ),
                            _run_mode(
                                cursor,
                                "postgres_trigram",
                                f"""SELECT id FROM jurix_scale_fixture
                            WHERE {FILTER} AND body %% %s ORDER BY similarity(body, %s) DESC LIMIT {TOP_K}""",
                                (query_text, query_text),
                                expected_ids,
                                runs,
                            ),
                        ],
                    }
                )
        connection.rollback()
    finally:
        connection.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, choices=(10000, 100000), default=10000)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.runs < 30:
        parser.error("--runs deve ser >= 30 para este protocolo")
    database_url = os.getenv("DATABASE_URL", "")
    try:
        report = run(database_url, args.rows, args.runs, args.seed)
    except (ValueError, OSError, PsycopgError) as exc:
        parser.error(
            str(exc)
            if isinstance(exc, ValueError)
            else f"Falha no banco de auditoria ({type(exc).__name__})"
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
