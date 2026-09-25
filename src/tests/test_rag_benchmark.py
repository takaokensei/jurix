from src.processing.rag_benchmark import BenchmarkCase, BenchmarkResult, evaluate


def test_benchmark_metrics_are_deterministic():
    cases = [BenchmarkCase('Q1', frozenset({'10','20'}), frozenset({'10'}))]
    results = [BenchmarkResult('Q1', ('30','20','10'), frozenset({'10'}), True)]
    metrics = evaluate(cases, results)
    assert metrics['recall@1'] == 0.0
    assert metrics['recall@3'] == 1.0
    assert metrics['precision@3'] == 0.666667
    assert metrics['mrr'] == 0.5
    assert metrics['citation_precision'] == 1.0
    assert metrics['citation_recall'] == 1.0
    assert metrics['groundedness'] == 1.0
