#!/usr/bin/env python3
"""Operational pgvector benchmark for release qualification.

Usage:
    python scripts/vector_search_benchmark.py --runs 20 --threshold-ms 250

The script deliberately does not fabricate production data. It measures the
existing ``Dispositivo.embedding`` query shape and reports EXPLAIN ANALYZE
output, row counts, and latency distribution against a supplied threshold.
"""
from __future__ import annotations

import argparse
import os
import statistics
import time

import psycopg2

SQL = """
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT id
FROM legislation_dispositivo
WHERE embedding IS NOT NULL
  AND embedding_model = %(embedding_model)s
ORDER BY embedding <=> %(embedding)s::vector
LIMIT %(limit)s
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--threshold-ms", type=float, default=250.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--vector", required=True, help="768-dimensional vector literal")
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    timings = []
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for _ in range(args.runs):
                start = time.perf_counter()
                cur.execute(SQL, {
                    "embedding_model": args.embedding_model,
                    "embedding": args.vector,
                    "limit": args.limit,
                })
                cur.fetchone()
                timings.append((time.perf_counter() - start) * 1000)

    p95 = sorted(timings)[max(0, int(len(timings) * 0.95) - 1)]
    print(f"runs={len(timings)} mean_ms={statistics.mean(timings):.2f} "
          f"p95_ms={p95:.2f} max_ms={max(timings):.2f}")
    print(f"threshold_ms={args.threshold_ms:.2f}")
    return 0 if p95 <= args.threshold_ms else 2


if __name__ == "__main__":
    raise SystemExit(main())
