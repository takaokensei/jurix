from types import SimpleNamespace

from src.processing.adaptive_retrieval import AdaptiveRetriever, RetrievalOptions


def _row(idx, score, norma_id=1):
    disp = SimpleNamespace(id=idx, norma_id=norma_id, norma=SimpleNamespace(status="consolidated"))
    return {
        "dispositivo": disp,
        "similarity_score": score,
        "distance": 1 - score,
        "context": {"hierarchy": "", "parent": None},
        "embedding_model": "nomic-embed-text",
    }


def test_selector_does_not_force_five_sources():
    rows = [_row(1, 0.46), _row(2, 0.30), _row(3, 0.25), _row(4, 0.10)]
    service = SimpleNamespace(semantic_search=lambda **_: rows)
    result = AdaptiveRetriever(service).retrieve("consulta", RetrievalOptions(mode="semantic", max_sources=12))
    assert len(result) == 1


def test_selector_can_return_many_strong_sources():
    rows = [_row(index, 0.90 - index * 0.01) for index in range(1, 10)]
    service = SimpleNamespace(semantic_search=lambda **_: rows)
    result = AdaptiveRetriever(service).retrieve("consulta", RetrievalOptions(mode="semantic", max_sources=12))
    assert 5 < len(result) <= 9


def test_selector_limits_same_norma_without_deleting_other_normas():
    rows = [_row(index, 0.99 - index * 0.01, norma_id=10) for index in range(1, 8)]
    rows += [_row(20, 0.88, norma_id=20)]
    service = SimpleNamespace(semantic_search=lambda **_: rows)
    result = AdaptiveRetriever(service).retrieve("consulta", RetrievalOptions(mode="semantic", max_sources=12))
    assert any(item["dispositivo"].norma_id == 20 for item in result)
    assert sum(item["dispositivo"].norma_id == 10 for item in result) <= 4
