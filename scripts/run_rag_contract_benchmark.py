"""Run the deterministic RAG evidence-contract benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import django


def main() -> int:
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from src.processing.rag_assurance import assess_answer

    total = passed = 0
    failures = []
    for line_no, line in enumerate(args.cases.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        case = json.loads(line)
        total += 1
        report = assess_answer(case["answer"], case.get("sources", []))
        expected = bool(case.get("expected_grounded", False))
        actual = bool(report.get("grounded"))
        if actual == expected:
            passed += 1
        else:
            failures.append(
                {
                    "line": line_no,
                    "id": case.get("id"),
                    "expected": expected,
                    "actual": actual,
                    "reason": report.get("policy", {}).get("reason"),
                }
            )
    result = {"total": total, "passed": passed, "failed": total - passed, "failures": failures}
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else f"RAG contract benchmark: {passed}/{total} passed"
    )
    return 0 if total and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
