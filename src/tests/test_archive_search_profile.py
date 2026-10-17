from __future__ import annotations

import json

from scripts.profile_archive_search_qa import _plan_nodes, _query_shape


def test_archive_search_profile_summarizes_shape_without_echoing_sql_or_values():
    private_value = "public-query-value-that-must-not-be-reported"
    profile = _query_shape(
        "SELECT COUNT(DISTINCT hash) FROM legislation_documentonormativo "
        f"WHERE body @@ plainto_tsquery('{private_value}')",
        12.5,
    )

    rendered = json.dumps(profile)
    assert profile["duration_ms"] == 12.5
    assert profile["tables"] == ["legislation_documentonormativo"]
    assert profile["count_distinct"] is True
    assert profile["full_text_search"] is True
    assert private_value not in rendered
    assert "sql" not in profile


def test_archive_search_profile_keeps_only_plan_node_metrics():
    nodes = _plan_nodes(
        {
            "Plan": {
                "Node Type": "Bitmap Heap Scan",
                "Relation Name": "legislation_extracaodocumento",
                "Actual Total Time": 1.25,
                "Actual Rows": 3,
                "Actual Loops": 2,
                "Rows Removed by Filter": 1,
                "Shared Hit Blocks": 8,
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "extr_legal_pt_gin",
                        "Actual Total Time": 0.75,
                        "Actual Rows": 3,
                        "Actual Loops": 1,
                        "Shared Read Blocks": 0,
                    }
                ],
            }
        }
    )

    assert nodes == [
        {
            "node_type": "Bitmap Heap Scan",
            "index_name": None,
            "actual_total_time_ms": 1.25,
            "actual_rows": 3,
            "actual_loops": 2,
            "rows_removed_by_filter": 1,
            "shared_hit_blocks": 8,
            "shared_read_blocks": None,
        },
        {
            "node_type": "Bitmap Index Scan",
            "index_name": "extr_legal_pt_gin",
            "actual_total_time_ms": 0.75,
            "actual_rows": 3,
            "actual_loops": 1,
            "rows_removed_by_filter": None,
            "shared_hit_blocks": None,
            "shared_read_blocks": 0,
        },
    ]
