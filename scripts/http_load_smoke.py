#!/usr/bin/env python3
"""Dependency-free concurrent HTTP smoke/load probe."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((p / 100.0) * (len(ordered) - 1)))),
    )
    return ordered[index]


def request_once(
    url: str,
    method: str,
    body: bytes | None,
    timeout: float,
) -> tuple[float, int]:
    started = time.perf_counter()
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()
        return time.perf_counter() - started, response.status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--method", choices=("GET", "POST"), default="GET")
    parser.add_argument("--body", default="")
    parser.add_argument("--max-p95-ms", type=float, default=1000.0)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        raise SystemExit("--requests e --concurrency devem ser >= 1.")

    body = args.body.encode("utf-8") if args.body else None
    samples: list[float] = []
    statuses: list[int] = []
    failures = 0

    def one(_index: int):
        nonlocal failures
        try:
            return request_once(args.url, args.method, body, args.timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            failures += 1
            return None

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.concurrency, args.requests)
    ) as executor:
        for result in executor.map(one, range(args.requests)):
            if result is None:
                continue
            latency, status = result
            samples.append(latency)
            statuses.append(status)

    elapsed = time.perf_counter() - started
    p95_ms = percentile([sample * 1000 for sample in samples], 95)
    summary = {
        "requests": args.requests,
        "completed": len(samples),
        "failures": failures,
        "success_statuses": sum(200 <= status < 300 for status in statuses),
        "elapsed_seconds": round(elapsed, 6),
        "rps": round(len(samples) / elapsed, 3) if elapsed else 0.0,
        "p50_ms": round(percentile([sample * 1000 for sample in samples], 50), 3),
        "p95_ms": round(p95_ms, 3),
        "max_ms": round(max(samples) * 1000, 3) if samples else 0.0,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    return int(
        failures
        or len(samples) != args.requests
        or any(not 200 <= status < 300 for status in statuses)
        or p95_ms > args.max_p95_ms
    )


if __name__ == "__main__":
    raise SystemExit(main())
