from unittest.mock import patch

import pytest

from src.apps.legislation.models import Norma, NormaTopic, Topic
from src.processing.normative_topics import persist_topic_candidates, suggest_topics

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def ensure_topics_for_each_isolated_test():
    """Keep these tests independent of migration rows removed by transactional flushes."""
    for code, label in (
        ("educacao", "Educação"),
        ("meio-ambiente", "Meio ambiente"),
        ("urbanismo", "Urbanismo"),
    ):
        Topic.objects.get_or_create(code=code, defaults={"label": label})


def test_topic_suggestions_are_candidates_not_legal_effects():
    norma = Norma(
        tipo="Lei",
        numero="9001",
        ano=2026,
        ementa="Institui política municipal de educação ambiental e gestão de resíduos.",
    )

    suggestions = suggest_topics(norma)

    assert {item["code"] for item in suggestions} >= {"educacao", "meio-ambiente"}
    assert all(item["status"] == "candidate" for item in suggestions)
    assert all("action" not in item and "effective_on" not in item for item in suggestions)


def test_persisted_topic_candidates_are_idempotent_and_do_not_downgrade_manual_tag():
    norma = Norma.objects.create(
        tipo="Lei", numero="9002", ano=2026, ementa="Programa municipal de educação escolar."
    )
    topic = Topic.objects.get(code="educacao")
    NormaTopic.objects.create(
        norma=norma,
        topic=topic,
        origin=NormaTopic.Origin.MANUAL,
        status=NormaTopic.Status.CONFIRMED,
        version=1,
    )

    assert persist_topic_candidates(norma) == 0
    link = NormaTopic.objects.get(norma=norma, topic=topic)
    assert link.status == NormaTopic.Status.CONFIRMED
    assert link.origin == NormaTopic.Origin.MANUAL


def test_confirmed_topic_filter_does_not_include_candidates(client):
    candidate = Norma.objects.create(
        tipo="Lei", numero="9003", ano=2026, status="consolidated", ementa="Escolas municipais"
    )
    topic = Topic.objects.get(code="educacao")
    NormaTopic.objects.create(
        norma=candidate,
        topic=topic,
        origin=NormaTopic.Origin.RULE,
        status=NormaTopic.Status.CANDIDATE,
    )

    with patch(
        "src.apps.legislation.workspace_views.RAGService.semantic_search",
        return_value={"results": [{"norma": candidate, "dispositivo": None, "texto": "Escolas municipais", "similarity_score": 0.9}], "mode": "semantic"},
    ):
        response = client.get("/pesquisa/?q=escolas&tema=educacao")

    assert response.status_code == 200
    assert "Lei nº 9003/2026" not in response.content.decode()


def test_topic_only_browse_returns_confirmed_norms_and_combines_type_and_year(client):
    confirmed_law = Norma.objects.create(
        tipo="Lei",
        numero="9004",
        ano=2026,
        status="consolidated",
        ementa="Dispõe sobre o zoneamento urbano municipal.",
    )
    confirmed_decree = Norma.objects.create(
        tipo="Decreto",
        numero="9005",
        ano=2026,
        status="consolidated",
        ementa="Regulamenta o uso do solo urbano.",
    )
    confirmed_other_year = Norma.objects.create(
        tipo="Lei",
        numero="9006",
        ano=2025,
        status="consolidated",
        ementa="Dispõe sobre o perímetro urbano.",
    )
    automatic_candidate = Norma.objects.create(
        tipo="Lei",
        numero="9007",
        ano=2026,
        status="consolidated",
        ementa="Dispõe sobre a ocupação urbana.",
    )
    urbanismo = Topic.objects.get(code="urbanismo")
    for norma in (confirmed_law, confirmed_decree, confirmed_other_year):
        NormaTopic.objects.create(
            norma=norma,
            topic=urbanismo,
            origin=NormaTopic.Origin.MANUAL,
            status=NormaTopic.Status.CONFIRMED,
        )
    NormaTopic.objects.create(
        norma=automatic_candidate,
        topic=urbanismo,
        origin=NormaTopic.Origin.RULE,
        status=NormaTopic.Status.CANDIDATE,
    )

    response = client.get("/pesquisa/?tema=urbanismo&tipo=Lei&ano=2026")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Tema confirmado" in body
    assert "Afinidade temática não indica alteração, revogação ou vigência" in body
    assert "Lei nº 9004/2026" in body
    assert "Lei nº 9006/2025" not in body
    assert "Decreto nº 9005/2026" not in body
    assert "Lei nº 9007/2026" not in body
