from unittest.mock import patch

import pytest

from src.apps.legislation.models import Norma, NormaTopic, Topic
from src.processing.normative_topics import persist_topic_candidates, suggest_topics

pytestmark = pytest.mark.django_db


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
