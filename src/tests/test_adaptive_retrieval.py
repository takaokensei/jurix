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
    result = AdaptiveRetriever(service).retrieve(
        "consulta", RetrievalOptions(mode="semantic", max_sources=12)
    )
    assert len(result) == 1


def test_selector_can_return_many_strong_sources():
    rows = [_row(index, 0.90 - index * 0.01, norma_id=index) for index in range(1, 10)]
    service = SimpleNamespace(semantic_search=lambda **_: rows)
    result = AdaptiveRetriever(service).retrieve(
        "consulta", RetrievalOptions(mode="semantic", max_sources=12)
    )
    assert 5 < len(result) <= 9


def test_selector_limits_same_norma_without_deleting_other_normas():
    rows = [_row(index, 0.99 - index * 0.01, norma_id=10) for index in range(1, 8)]
    rows += [_row(20, 0.88, norma_id=20)]
    service = SimpleNamespace(semantic_search=lambda **_: rows)
    result = AdaptiveRetriever(service).retrieve(
        "consulta", RetrievalOptions(mode="semantic", max_sources=12)
    )
    assert any(item["dispositivo"].norma_id == 20 for item in result)
    assert sum(item["dispositivo"].norma_id == 10 for item in result) <= 4


def test_hybrid_reranking_preserves_strong_exact_lexical_match():
    exact = _row(1, 0.45)
    exact["semantic_score"] = 0.45
    exact["lexical_score"] = 1.0
    generic = _row(2, 0.92)
    generic["semantic_score"] = 0.92
    generic["lexical_score"] = 0.0

    ranked = AdaptiveRetriever._merge([generic], [exact], "hybrid")
    assert ranked[0]["dispositivo"].id == 1


def test_citation_resolver_accepts_number_year_without_norma_type(db):
    from src.apps.legislation.models import Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="8001", ano=2025, tipo="1", status="consolidated")
    assert [item.id for item in AdaptiveRAGService._find_cited_normas("8001/2025")] == [norma.id]


def test_citation_resolver_refuses_yearless_citation_and_typed_collision(db):
    from src.apps.legislation.models import Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    ordinary = Norma.objects.create(numero="8205", ano=2026, tipo="Lei")
    Norma.objects.create(numero="8205", ano=2026, tipo="Lei Complementar")
    assert AdaptiveRAGService._find_cited_normas("Lei nº 8205") == []
    assert AdaptiveRAGService._find_cited_normas("Lei nº 8205/2026") == [ordinary]


def test_explicit_article_query_returns_only_that_article_subtree_without_fake_scores(db):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="8206", ano=2026, tipo="Lei", status="consolidated")
    article_7 = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="7º", texto="Artigo sete específico", ordem=7
    )
    child = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="II",
        texto="Regra do inciso dois",
        ordem=72,
        dispositivo_pai=article_7,
    )
    Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="8º", texto="Artigo oito diverso", ordem=8
    )

    rows = AdaptiveRAGService().semantic_search("O que prevê o art. 7º da Lei nº 8206/2026?", k=5)

    assert [row["dispositivo"].id for row in rows] == [article_7.id, child.id]
    assert all(row["match_kind"] == "explicit_reference" for row in rows)
    assert all(row["similarity_score"] == 0.0 for row in rows)


def test_explicit_citation_stays_ahead_of_saturated_general_scores():
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    cited = [_row(1, 0.98, norma_id=8001), _row(2, 0.97, norma_id=8001)]
    general = [_row(3, 1.0, norma_id=7998), _row(4, 1.0, norma_id=7994)]
    selected = AdaptiveRAGService._select_with_citation_priority(
        cited,
        general,
        max_sources=4,
        min_similarity=0.0,
        cited_norma_ids={8001},
    )
    assert [item["dispositivo"].norma_id for item in selected[:2]] == [8001, 8001]
    assert all(item["dispositivo"].norma_id == 8001 for item in selected)
