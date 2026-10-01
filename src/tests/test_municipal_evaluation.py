from scripts.evaluate_municipal_v1 import evaluate_events, evaluate_parser, evaluate_rag


def test_parser_metrics_are_exact_by_label_and_span():
    gold = [
        {
            "case_id": "p1",
            "spans": [
                {"label": "artigo", "start": 0, "end": 5},
                {"label": "inciso", "start": 6, "end": 10},
            ],
        }
    ]
    predictions = [
        {
            "case_id": "p1",
            "spans": [
                {"label": "artigo", "start": 0, "end": 5},
            ],
        }
    ]

    report = evaluate_parser(gold, predictions)

    assert report["by_label"]["artigo"]["f1"] == 1.0
    assert report["by_label"]["inciso"]["recall"] == 0.0


def test_event_matrix_keeps_unresolved_as_a_real_class():
    gold = [
        {
            "case_id": "e1",
            "events": [
                {"action": "REVOGA", "target_key": "lei:1:2020:art1"},
                {"action": "unresolved"},
            ],
        }
    ]
    predictions = [
        {
            "case_id": "e1",
            "events": [
                {"action": "REVOGA", "target_key": "lei:2:2020:art1"},
                {"action": "ALTERA"},
            ],
        }
    ]

    report = evaluate_events(gold, predictions)

    assert report["confusion_matrix"]["unresolved"]["ALTERA"] == 1
    assert report["target_accuracy"] == 0.0


def test_rag_denominators_exclude_cases_without_expected_sources():
    gold = [
        {
            "case_id": "r1",
            "expected_source_ids": ["a", "b"],
            "answerable": True,
            "support_reviewed": False,
            "temporal_reviewed": True,
            "temporal_expected": "valid",
        },
        {"case_id": "r2", "expected_source_ids": [], "answerable": False},
    ]
    predictions = [
        {
            "case_id": "r1",
            "retrieved_source_ids": ["a", "x"],
            "cited_source_ids": ["a"],
            "abstained": False,
            "temporal_result": "invalid",
            "ttft_ms": 120,
        },
        {"case_id": "r2", "retrieved_source_ids": [], "cited_source_ids": [], "abstained": True},
    ]

    report = evaluate_rag(gold, predictions)

    assert report["retrieval"]["recall@1"] == 0.5
    assert report["retrieval"]["recall@3"] == 0.5
    assert report["mrr"] == 1.0
    assert report["citation_precision"] == 1.0
    assert report["citation_recall"] == 0.5
    assert report["abstention_accuracy"] == 1.0
    assert report["temporal_error_rate"] == 1.0
    assert report["human_claim_support"].startswith("not_evaluated")
    assert report["cases_without_expected_sources_excluded"] == 1
