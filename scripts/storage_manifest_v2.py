#!/usr/bin/env python3
"""Build a deterministic manifest for a local Jurix storage tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("storage-manifest.json"))
    args = parser.parse_args()

    root = args.root.resolve()
    entries = []
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        digest = file_hash(path)
        entries.append({"path": relative, "bytes": stat.st_size, "sha256": digest})
        total_bytes += stat.st_size

    payload = {
        "schema_version": 1,
        "root": str(root),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest written: {args.output} ({len(entries)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
