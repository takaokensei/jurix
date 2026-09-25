#!/usr/bin/env python3
"""Release contract validator independent of application runtime.

It checks that the repository contains the operational artifacts required for a
production candidate. It intentionally validates presence and structure rather
than inventing benchmark scores or infrastructure state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = (
    ".env.production.example",
    "docker-compose.prod.yml",
    "docs/production-readiness-v3.md",
    "docs/security-production-matrix.md",
    "docs/rag-quality-contract-v2.md",
    "benchmarks/rag/production/README.md",
    "src/processing/strict_grounding.py",
    "src/processing/rag_policy.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    missing = [item for item in REQUIRED if not (root / item).exists()]
    payload = {"ok": not missing, "missing": missing}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("PASS" if payload["ok"] else "FAIL")
        for item in missing:
            print(f"missing: {item}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
