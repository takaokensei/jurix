"""Report unusually large Python modules without blocking normal development."""
from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_LIMIT = 900
EXCLUDES = {".git", ".venv", "venv", "build", "dist", "staticfiles", "data", ".history"}


def collect(root: Path, limit: int) -> list[tuple[int, Path]]:
    rows = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDES for part in path.parts):
            continue
        lines = sum(1 for _ in path.open(encoding="utf-8"))
        if lines >= limit:
            rows.append((lines, path.relative_to(root)))
    return sorted(rows, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    rows = collect(Path.cwd(), args.limit)
    if not rows:
        print(f"No Python module is at or above {args.limit} lines.")
        return 0
    print(f"Python modules at or above {args.limit} lines:")
    for lines, path in rows:
        print(f"{lines:5d}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
