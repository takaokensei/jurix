#!/usr/bin/env python3
"""Aggregate gate artifacts into one deterministic release report."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def load_optional(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("release-report-v2.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("."))
    args = parser.parse_args()

    names = (
        "security-audit.json",
        "architecture-budget.json",
        "vector-health.json",
        "corpus-integrity.json",
        "http-smoke.json",
        "rag-release.json",
        "production-preflight.json",
    )

    report = {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": {},
    }

    for name in names:
        report["artifacts"][name] = load_optional(args.artifacts / name)

    failures = []
    for name, value in report["artifacts"].items():
        if isinstance(value, dict) and value.get("passed") is False:
            failures.append(name)
        if isinstance(value, dict) and value.get("rejected"):
            failures.append(name)

    report["release_candidate"] = not failures
    report["failures"] = sorted(set(failures))
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["release_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
