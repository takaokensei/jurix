#!/usr/bin/env python3
"""Bounded offline algorithm/memory benchmark; never opens a database or network."""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from collections import deque

SIZES = (1, 10, 40, 300, 1000)
MAX_QUERY_NODES = 40
MAX_QUERY_EDGES = 80


def make_graph(size: int) -> dict[int, tuple[int, ...]]:
    if size not in SIZES:
        raise ValueError(f"size must be one of {SIZES}")
    graph = {}
    for node in range(size):
        # Deterministic bounded-degree edges; do not materialize an NxN matrix.
        graph[node] = tuple(target for target in (node + 1, node + 7) if target < size)
    return graph


def bounded_bfs(graph: dict[int, tuple[int, ...]], seed: int = 0) -> dict:
    visited = {seed} if seed in graph else set()
    queue = deque(visited)
    examined = 0
    while queue and len(visited) < MAX_QUERY_NODES and examined < MAX_QUERY_EDGES:
        node = queue.popleft()
        for target in graph.get(node, ()):
            examined += 1
            if target not in visited:
                visited.add(target)
                if len(visited) >= MAX_QUERY_NODES or examined >= MAX_QUERY_EDGES:
                    break
                queue.append(target)
    return {"visited_nodes": len(visited), "examined_edges": examined}


def benchmark(sizes: tuple[int, ...] = SIZES, *, repeats: int = 20) -> dict:
    if tuple(sizes) != SIZES:
        raise ValueError("benchmark sizes must remain the published fixed sequence")
    report = {"mode": "offline_synthetic_algorithm_only", "database_queries": None, "results": []}
    for size in sizes:
        tracemalloc.start()
        graph = make_graph(size)
        samples = []
        visited = edges = 0
        for _ in range(max(1, min(int(repeats), 20))):
            start = time.perf_counter()
            outcome = bounded_bfs(graph)
            samples.append((time.perf_counter() - start) * 1000)
            visited, edges = outcome["visited_nodes"], outcome["examined_edges"]
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report["results"].append({
            "entities": size,
            "edges": sum(len(targets) for targets in graph.values()),
            "query_nodes": visited,
            "query_edges": edges,
            "query_p50_ms": statistics.median(samples),
            "query_samples": len(samples),
            "peak_allocated_bytes": peak_bytes,
            "db_query_count": None,
        })
    return report


if __name__ == "__main__":
    print(json.dumps(benchmark(), ensure_ascii=False, indent=2))
