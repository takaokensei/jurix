from scripts.lexical_scale_benchmark import database_is_allowed, percentile, ranking_metrics


def test_scale_runner_accepts_only_the_local_audit_database():
    assert database_is_allowed("postgresql://fixture:fixture@127.0.0.1:55432/jurix_audit")
    assert not database_is_allowed("postgresql://fixture:fixture@127.0.0.1:5432/jurix")
    assert not database_is_allowed("postgresql://fixture:fixture@example.com:55432/jurix_audit")


def test_ranking_metrics_use_expected_ids_and_safe_denominators():
    assert ranking_metrics({1, 2}, [1, 9]) == {
        "recall_at_10": 0.5,
        "mrr": 1.0,
        "expected_relevant": 2,
        "retrieved": 2,
    }
    assert ranking_metrics(set(), [1])["recall_at_10"] is None


def test_p95_sample_is_not_reported_without_observations():
    assert percentile([], 0.95) is None
    assert percentile([10, 20, 30], 0.95) == 30
