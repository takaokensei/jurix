#!/usr/bin/env python3
"""Check that production documentation has one current status source."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_PATTERNS = (
    re.compile(r"OCR.*planned", re.I),
    re.compile(r"SAPL.*Em Desenvolvimento", re.I),
    re.compile(r"Deploy produção.*próxima", re.I),
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    status_doc = root / "docs" / "current-status.md"
    if not status_doc.exists():
        print("FAIL: docs/current-status.md missing")
        return 1
    stale = [pattern.pattern for pattern in FORBIDDEN_PATTERNS if pattern.search(readme)]
    if stale:
        print("FAIL: stale roadmap/status claims remain in README")
        for item in stale:
            print(f" - {item}")
        return 2
    print("PASS: documentation contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
