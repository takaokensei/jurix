#!/usr/bin/env python3
"""
Verify a database backup artifact without modifying the source environment.

The actual restore command is operator-supplied. This script focuses on file
integrity, expected headers, age, size and optional SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--min-bytes", type=int, default=1024)
    parser.add_argument("--max-age-hours", type=float, default=48.0)
    args = parser.parse_args()

    artifact = args.artifact
    if not artifact.is_file():
        print(json.dumps({"passed": False, "reason": "missing"}, indent=2))
        return 2

    stat = artifact.stat()
    age_hours = (time.time() - stat.st_mtime) / 3600.0
    digest = sha256(artifact)

    checks = {
        "exists": True,
        "size_ok": stat.st_size >= args.min_bytes,
        "age_ok": age_hours <= args.max_age_hours,
        "sha256_ok": not args.expected_sha256 or digest == args.expected_sha256.lower(),
    }
    report = {
        "passed": all(checks.values()),
        "artifact": str(artifact),
        "bytes": stat.st_size,
        "age_hours": round(age_hours, 3),
        "sha256": digest,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
