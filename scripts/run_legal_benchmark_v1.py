#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "benchmarks/rag/legal/v1/cases.jsonl"
DEFAULT_ENDPOINT = "/api/v1/search/answer/"


def norm(v: str) -> str:
    return re.sub(r"\s+", " ", v.lower()).strip()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {line_no}") from exc
        if not isinstance(case, dict):
            raise ValueError(f"Case at line {line_no} must be an object")
        required = {"id", "question", "source", "expected_citations", "must_contain_any"}
        missing = sorted(required - case.keys())
        if missing:
            raise ValueError(f"Case at line {line_no} is missing: {', '.join(missing)}")
        if not isinstance(case["id"], str) or not case["id"].strip():
            raise ValueError(f"Case at line {line_no} has an invalid id")
        if not isinstance(case["question"], str) or not case["question"].strip():
            raise ValueError(f"Case {case['id']} has an invalid question")
        if not isinstance(case["source"], dict):
            raise ValueError(f"Case {case['id']} has an invalid source")
        if not isinstance(case["expected_citations"], list) or not all(
            isinstance(value, str) and value.strip() for value in case["expected_citations"]
        ):
            raise ValueError(f"Case {case['id']} has invalid expected_citations")
        groups = case["must_contain_any"]
        if not isinstance(groups, list) or not all(
            isinstance(group, list)
            and group
            and all(isinstance(value, str) and value.strip() for value in group)
            for group in groups
        ):
            raise ValueError(f"Case {case['id']} has invalid must_contain_any")
        cases.append(case)
    if not cases:
        raise ValueError("The legal benchmark contains no cases")
    return cases


def extract_answer(raw: str, ctype: str) -> str:
    if "text/event-stream" in ctype or raw.lstrip().startswith("data:"):
        final_answer: str | None = None
        for line in raw.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                raise ValueError("SSE stream contains malformed JSON") from None
            if not isinstance(obj, dict):
                raise ValueError("SSE event must be a JSON object")
            event_type = obj.get("type")
            if event_type == "error" or obj.get("status") in {"failed", "cancelled"}:
                raise ValueError("SSE stream ended without a successful answer")
            if event_type == "done":
                answer = obj.get("answer")
                if not isinstance(answer, str):
                    raise ValueError("SSE completion event has no answer")
                final_answer = answer
        if final_answer is None:
            raise ValueError("SSE stream ended before its completion event")
        return final_answer
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("JSON response is malformed") from None
    if not isinstance(obj, dict):
        raise ValueError("JSON response must be an object")
    for key in ("answer", "response", "message", "text", "content"):
        if isinstance(obj.get(key), str):
            return obj[key]
    if isinstance(obj.get("data"), dict):
        for key in ("answer", "response", "text"):
            if isinstance(obj["data"].get(key), str):
                return obj["data"][key]
    raise ValueError("JSON response has no answer field")


def evaluate(case: dict[str, Any], answer: str) -> dict[str, Any]:
    a = norm(answer)
    source_hits = sum(norm(x) in a for x in case["expected_citations"])
    content_hits = sum(
        any(norm(t) in a for t in group) for group in case.get("must_contain_any", [])
    )
    ok = source_hits == len(case["expected_citations"]) and content_hits == len(
        case.get("must_contain_any", [])
    )
    return {
        "case_id": case["id"],
        "accepted": ok,
        "source_match": source_hits == len(case["expected_citations"]),
        "source_hits": source_hits,
        "content_hits": content_hits,
        "answer": answer,
        "expected_source": case["source"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("JURIX_BENCHMARK_URL", ""))
    ap.add_argument("--endpoint", default=os.getenv("JURIX_BENCHMARK_ENDPOINT", DEFAULT_ENDPOINT))
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument(
        "--timeout", type=int, default=int(os.getenv("JURIX_BENCHMARK_TIMEOUT_SECONDS", "90"))
    )
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/legal-benchmark-v1.json")
    args = ap.parse_args()

    if not args.base_url:
        print("FAIL: JURIX_BENCHMARK_URL/base URL is required.")
        return 2
    try:
        headers = json.loads(os.getenv("JURIX_BENCHMARK_HEADERS_JSON", "{}"))
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        ):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        print("FAIL: benchmark headers must be a JSON object of string values.")
        return 2

    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError) as exc:
        print(f"FAIL: invalid benchmark cases: {exc}")
        return 2

    url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            req = Request(
                url,
                data=json.dumps({"question": case["question"]}).encode(),
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    **headers,
                },
                method="POST",
            )
            with urlopen(req, timeout=args.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                ctype = resp.headers.get("Content-Type", "")
            r = evaluate(case, extract_answer(raw, ctype))
            r["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            r = {
                "case_id": case["id"],
                "accepted": False,
                "transport_error": type(exc).__name__,
            }
        except ValueError as exc:
            r = {"case_id": case["id"], "accepted": False, "response_error": str(exc)}
        results.append(r)
        print(("PASS" if r.get("accepted") else "FAIL"), case["id"])

    total = len(results)
    accepted = sum(bool(x.get("accepted")) for x in results)
    source_ok = sum(bool(x.get("source_match")) for x in results)
    report = {
        "benchmark": "jurix-legal-production-v1",
        "snapshot_date": "2026-09-25",
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit": os.getenv("GITHUB_SHA", "unknown"),
        "endpoint": url,
        "cases": results,
        "pass_rate": accepted / total if total else 0,
        "source_match_rate": source_ok / total if total else 0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Legal benchmark: {accepted}/{total} accepted; sources {source_ok}/{total}")
    if args.strict and (accepted / total < 0.90 or source_ok / total < 0.95):
        print("FAIL: legal benchmark thresholds not met.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
