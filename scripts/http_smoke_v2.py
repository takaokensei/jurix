#!/usr/bin/env python3
"""Small dependency-free HTTP smoke/load probe for staging."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    path: str
    status: int
    elapsed_ms: float
    error: str = ""


def request(base_url: str, path: str, timeout: float) -> Sample:
    started = time.perf_counter()
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(2048)
            status = int(response.status)
            error = ""
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        error = str(exc)
    except Exception as exc:
        status = 0
        error = str(exc)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return Sample(path, status, elapsed_ms, error)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument(
        "--paths",
        default="/api/v1/health/,/api/v1/normas/?page=1&page_size=1",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", type=str)
    args = parser.parse_args()

    paths = [item.strip() for item in args.paths.split(",") if item.strip()]
    jobs = [path for _ in range(max(1, args.repeat)) for path in paths]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        samples = list(pool.map(lambda p: request(args.base_url, p, args.timeout), jobs))

    latencies = [sample.elapsed_ms for sample in samples]
    statuses_ok = all(200 <= sample.status < 400 for sample in samples)

    report = {
        "base_url": args.base_url,
        "requests": len(samples),
        "status_ok": statuses_ok,
        "latency_ms": {
            "min": min(latencies) if latencies else 0,
            "median": statistics.median(latencies) if latencies else 0,
            "p95_approx": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0,
            "max": max(latencies) if latencies else 0,
        },
        "samples": [sample.__dict__ for sample in samples],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    return 0 if statuses_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
