"""Run the deterministic RAG evidence-contract benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import django


def main() -> int:
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--base-url", default=os.getenv("JURIX_BENCHMARK_URL", ""))
    parser.add_argument(
        "--endpoint", default=os.getenv("JURIX_BENCHMARK_ENDPOINT", "/api/v1/chat/ask/")
    )
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from src.processing.rag_assurance import assess_answer

    cases = [
        json.loads(line)
        for line in args.cases.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if cases and "expected_citations" in cases[0]:
        # Legal v1 cases are live endpoint evaluations, not deterministic
        # answer/source contract fixtures. Delegate to the canonical evaluator
        # instead of assuming an ``answer`` field and raising KeyError.
        if not args.base_url:
            print(
                "FAIL: legal cases require --base-url or JURIX_BENCHMARK_URL; "
                "use scripts/run_legal_benchmark_v1.py for the full run."
            )
            return 2
        sys.path.insert(0, str(ROOT / "scripts"))
        from run_legal_benchmark_v1 import evaluate, extract_answer

        passed = 0
        failures = []
        url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
        for case in cases:
            try:
                request = Request(
                    url,
                    data=json.dumps({"question": case["question"]}).encode(),
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=args.timeout) as response:
                    raw = response.read().decode("utf-8", "replace")
                    answer = extract_answer(raw, response.headers.get("Content-Type", ""))
                result = evaluate(case, answer)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                result = {"case_id": case.get("id"), "accepted": False, "error": str(exc)}
            if result.get("accepted"):
                passed += 1
            else:
                failures.append(result)
        result = {
            "total": len(cases),
            "passed": passed,
            "failed": len(failures),
            "failures": failures,
        }
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Legal RAG benchmark: {passed}/{len(cases)} passed"
        )
        return 0 if cases and not failures else 1

    total = passed = 0
    failures = []
    for line_no, case in enumerate(cases, 1):
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
