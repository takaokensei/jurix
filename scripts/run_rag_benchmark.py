from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

from src.processing.rag_benchmark import BenchmarkCase, BenchmarkResult, evaluate


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open('r', encoding='utf-8') as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    cases = [BenchmarkCase(str(item['id']), frozenset(map(str, item.get('expected_devices', []))), frozenset(map(str, item.get('expected_citations', [])))) for item in read_jsonl(args.cases)]
    results = [BenchmarkResult(str(item['id']), tuple(map(str, item.get('retrieved_device_ids', []))), frozenset(map(str, item.get('citations', []))), bool(item.get('grounded', False))) for item in read_jsonl(args.results)]
    print(json.dumps(evaluate(cases, results), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
