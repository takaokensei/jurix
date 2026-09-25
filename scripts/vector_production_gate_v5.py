#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def _init_django():
    import django

    django.setup()
    from django.db import connection

    return connection


def q(n: str, conn: Any) -> str:
    return conn.ops.quote_name(n)


def vectors(conn: Any) -> list[tuple[Any, ...]]:
    if conn.vendor != "postgresql":
        return []
    with conn.cursor() as c:
        c.execute(
            """SELECT n.nspname, c.relname, a.attname, a.atttypmod
               FROM pg_attribute a
               JOIN pg_class c ON c.oid = a.attrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               JOIN pg_type t ON t.oid = a.atttypid
               WHERE a.attnum > 0
                 AND NOT a.attisdropped
                 AND t.typname = 'vector'
                 AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                 AND c.relkind IN ('r', 'p')
               ORDER BY (a.attname ILIKE '%embedding%') DESC, n.nspname, c.relname, a.attname"""
        )
        return c.fetchall()


def indexes(s: str, t: str, conn: Any) -> list[str]:
    with conn.cursor() as c:
        c.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND tablename=%s",
            [s, t],
        )
        return [r[0] for r in c.fetchall()]


def explain(s: str, t: str, col: str, typmod: int | None, conn: Any) -> dict[str, Any]:
    dim = typmod - 4 if typmod and typmod > 4 else int(os.getenv("JURIX_VECTOR_DIMENSIONS", "768"))
    v = "[" + ",".join("0" for _ in range(dim)) + "]"
    table = f"{q(s, conn)}.{q(t, conn)}"
    column = q(col, conn)
    with conn.cursor() as c:
        try:
            c.execute("SET enable_seqscan = off")
            c.execute(
                f"EXPLAIN (FORMAT JSON, COSTS TRUE) SELECT {column} FROM {table} ORDER BY {column} <=> %s::vector LIMIT 10",
                [v],
            )
            return c.fetchone()[0][0]
        finally:
            try:
                c.execute("SET enable_seqscan = on")
            except Exception:
                pass


def walk(node: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    yield node
    for child in node.get("Plans", []) or []:
        yield from walk(child)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    conn = _init_django()
    failures: list[str] = []
    inspected: list[dict[str, Any]] = []

    if conn.vendor != "postgresql":
        msg = f"FAIL: database vendor is '{conn.vendor}'; pgvector gate requires PostgreSQL with pgvector"
        failures.append(msg)
        result = {"ok": False, "checked": [], "failures": failures}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(msg)
        return 1

    cand = vectors(conn)
    wanted = os.getenv("JURIX_VECTOR_TABLE", "").strip()
    column = os.getenv("JURIX_VECTOR_COLUMN", "").strip()

    if wanted:
        cand = [x for x in cand if f"{x[0]}.{x[1]}" == wanted or x[1] == wanted]
    if column:
        cand = [x for x in cand if x[2] == column]
    if not cand:
        failures.append("no pgvector column found in database")
        result = {"ok": False, "checked": [], "failures": failures}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("FAIL: no pgvector column found")
        return 1

    for s, t, col, typmod in cand[:3]:
        defs = indexes(s, t, conn)
        vec = [d for d in defs if "hnsw" in d.lower() or "ivfflat" in d.lower()]
        ops = [d for d in vec if "vector_cosine_ops" in d.lower()]
        entry: dict[str, Any] = {"schema": s, "table": t, "column": col, "indexes": vec}
        if not vec:
            failures.append(f"{s}.{t}.{col}: missing HNSW/IVFFlat index")
            inspected.append(entry)
            continue
        if not ops:
            failures.append(f"{s}.{t}.{col}: missing vector_cosine_ops")
            inspected.append(entry)
            continue
        try:
            plan = explain(s, t, col, typmod, conn)
            entry["plan"] = plan
        except Exception as exc:
            failures.append(f"{s}.{t}.{col}: EXPLAIN failed: {exc}")
            inspected.append(entry)
            continue
        nodes = list(walk(plan["Plan"]))
        scan = [n for n in nodes if n.get("Node Type") in {"Index Scan", "Index Only Scan"}]
        entry["index_scan"] = bool(scan)
        if not scan:
            failures.append(f"{s}.{t}.{col}: query plan did not use vector index")
        inspected.append(entry)

    ok = not failures
    result = {"ok": ok, "checked": inspected, "failures": failures}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Vector production gate passed." if ok else "\n".join(["Vector production gate FAILED:"] + failures))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
