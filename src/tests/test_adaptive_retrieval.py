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


def test_plural_explicit_articles_return_only_the_named_article_subtrees(db):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="120", ano=2010, tipo="Lei Complementar", status="consolidated")
    article_17 = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="17", texto="Atribuições gerais.", ordem=17
    )
    child_17 = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Regra do primeiro artigo.",
        ordem=171,
        dispositivo_pai=article_17,
    )
    article_18 = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="18º", texto="Vencimento básico.", ordem=18
    )
    Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="19º", texto="Outro assunto.", ordem=19
    )

    rows = AdaptiveRAGService().semantic_search(
        "Explique a diferença entre as regras dos arts. 17 e 18 da Lei Complementar nº 120/2010.",
        k=5,
    )

    assert {row["dispositivo"].id for row in rows} == {
        article_17.id,
        child_17.id,
        article_18.id,
    }
    assert all(row["match_kind"] == "explicit_reference" for row in rows)
    assert all(row["similarity_score"] == 0.0 for row in rows)


def test_whole_norma_overview_ignores_small_ui_top_k_and_returns_all_devices(db):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="8206", ano=2026, tipo="Lei", status="consolidated")
    article_1 = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Institui o programa.", ordem=1
    )
    article_2 = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="2º", texto="Define os critérios.", ordem=2
    )
    inciso = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Reconhecimento mensal.",
        ordem=21,
        dispositivo_pai=article_2,
    )

    service = AdaptiveRAGService()
    service._jurix_retrieval_options = RetrievalOptions(max_sources=1)
    rows = service.semantic_search("O que prevê a Lei nº 8206/2026?", k=1)

    assert [row["dispositivo"].id for row in rows] == [article_1.id, article_2.id, inciso.id]
    assert all(row["match_kind"] == "norma_overview_complete" for row in rows)
    assert all(row["coverage"]["complete"] is True for row in rows)


def test_large_norma_overview_samples_distributed_articles_without_claiming_completeness(db):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="8206", ano=2026, tipo="Lei", status="consolidated")
    Dispositivo.objects.bulk_create(
        [
            Dispositivo(
                norma=norma,
                tipo="artigo",
                numero=f"{number}º",
                texto=f"Dispositivo {number}.",
                ordem=number,
            )
            for number in range(1, 61)
        ]
    )

    service = AdaptiveRAGService()
    service._jurix_retrieval_options = RetrievalOptions(max_sources=2)
    rows = service.semantic_search("O que prevê a Lei nº 8206/2026?", k=2)

    assert len(rows) == 32
    assert rows[0]["match_kind"] == "norma_overview_sampled"
    coverage = rows[0]["coverage"]
    assert coverage["complete"] is False
    assert coverage["total_articles"] == 60
    assert coverage["selected_articles"] == 32
    assert rows[-1]["dispositivo"].numero in {"59º", "60º"}


def test_large_norma_overview_distributes_detail_devices_across_the_norm(db):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    norma = Norma.objects.create(numero="8206", ano=2026, tipo="Lei", status="consolidated")
    Dispositivo.objects.bulk_create([
        Dispositivo(norma=norma, tipo="artigo", numero=f"{number}º", texto=f"Artigo {number}.", ordem=number)
        for number in range(1, 61)
    ])
    articles = Dispositivo.objects.filter(norma=norma, tipo="artigo").order_by("ordem")
    Dispositivo.objects.bulk_create([
        Dispositivo(
            norma=norma,
            tipo="inciso",
            numero="I",
            texto=f"Detalhe do artigo {article.numero}.",
            ordem=1_000 + article.ordem,
            dispositivo_pai=article,
        )
        for article in articles
    ])

    service = AdaptiveRAGService()
    service._jurix_retrieval_options = RetrievalOptions(max_sources=2)
    rows = service.semantic_search("O que prevê a Lei nº 8206/2026?", k=2)
    child_rows = [row for row in rows if row["dispositivo"].tipo == "inciso"]
    referenced_articles = [int(row["dispositivo"].dispositivo_pai.numero.rstrip("º")) for row in child_rows]

    assert len(child_rows) == 16
    assert min(referenced_articles) <= 3
    assert max(referenced_articles) >= 57


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


def test_missing_exact_norma_does_not_fall_back_to_a_similar_norma(db, monkeypatch):
    from src.apps.legislation.models import Dispositivo, Norma
    from src.processing.adaptive_rag_service import AdaptiveRAGService
    from src.processing.rag_service import RAGService

    similar_norma = Norma.objects.create(numero="99998", ano=2026, tipo="Lei")
    similar_device = Dispositivo.objects.create(
        norma=similar_norma,
        tipo="artigo",
        numero="1º",
        texto="Regra municipal sobre o mesmo assunto da pergunta.",
        ordem=1,
    )
    distractor = _row(similar_device.id, 0.99, norma_id=similar_norma.id)
    distractor["dispositivo"] = similar_device
    monkeypatch.setattr(RAGService, "semantic_search", lambda *args, **kwargs: [distractor])

    service = AdaptiveRAGService()
    rows = service.semantic_search("O que prevê a Lei nº 99999/2026?", k=5)

    assert rows == []
    assert rows.reason_code == "norm_not_in_corpus"
    assert rows.coverage["selected_devices"] == 0
