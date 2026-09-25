import json

import pytest
from django.urls import reverse

from src.apps.legislation.models import Norma


@pytest.mark.django_db
def test_dynamic_suggestions_use_ingested_municipal_normas(client):
    norma = Norma.objects.create(
        tipo="LEI ORDINÁRIA",
        numero="7999",
        ano=2026,
        ementa="Institui regras municipais para um serviço público.",
        sapl_id=999999,
        sapl_url="https://sapl.natal.rn.leg.br/norma/999999/",
        status="consolidated",
    )

    response = client.get(reverse("legislation_api:dynamic_suggestions"))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["success"] is True
    assert payload["source"] == "municipal_natal_corpus"
    assert any(item["norma_id"] == norma.id for item in payload["suggestions"])
    assert all("question" in item and "sapl_id" in item for item in payload["suggestions"])
