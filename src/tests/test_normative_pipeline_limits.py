from pathlib import Path

import pytest

from scripts.benchmark_normative_api_qa import EVENT_COUNTS, MAX_RESPONSE_EDGES, MAX_RESPONSE_NODES
from scripts.benchmark_normative_pipeline import MAX_QUERY_EDGES, MAX_QUERY_NODES, SIZES, benchmark


def test_offline_benchmark_uses_fixed_sizes_and_bounded_graph_queries():
    report = benchmark(repeats=2)

    assert report["database_queries"] is None
    assert [row["entities"] for row in report["results"]] == [1, 10, 40, 300, 1000]
    assert all(row["query_nodes"] <= MAX_QUERY_NODES for row in report["results"])
    assert all(row["query_edges"] <= MAX_QUERY_EDGES for row in report["results"])
    assert all(row["peak_allocated_bytes"] > 0 for row in report["results"])


def test_postgres_qa_benchmark_covers_same_fixed_sizes_and_api_caps():
    assert EVENT_COUNTS == SIZES == (1, 10, 40, 300, 1000)
    assert MAX_RESPONSE_NODES == 40
    assert MAX_RESPONSE_EDGES == 80


def test_graph_frontend_assets_remain_within_raw_bundle_budget():
    root = Path(__file__).resolve().parents[2]
    asset_paths = [
        root / "src/apps/core/static/css/jurix-normative-graph.css",
        root / "src/apps/core/static/js/jurix-normative-graph.js",
    ]

    assert sum(path.stat().st_size for path in asset_paths) <= 45 * 1024


def test_benchmark_refuses_unbounded_arbitrary_sizes():
    with pytest.raises(ValueError, match="published fixed sequence"):
        benchmark((100_000,), repeats=1)
