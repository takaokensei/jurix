"""Ownership and persistence contracts for the workspace collections surface."""

import pytest
from django.contrib.auth.models import User
from django.test import Client

from src.apps.legislation.models import Collection, Norma

pytestmark = pytest.mark.django_db


def test_authenticated_user_can_create_and_update_collection():
    user = User.objects.create_user("collections-user", password="secret")
    client = Client()
    client.force_login(user)

    response = client.post("/colecoes/", {"name": "ISS", "description": "Pesquisa"})
    assert response.status_code == 302
    collection = Collection.objects.get(user=user, name="ISS")
    assert collection.description == "Pesquisa"


def test_collection_items_are_mutated_only_by_owner():
    owner = User.objects.create_user("owner", password="secret")
    other = User.objects.create_user("other", password="secret")
    collection = Collection.objects.create(user=owner, name="Dossiê")
    norma = Norma.objects.create(tipo="Lei", numero="901", ano=2026, status="consolidated")

    client = Client()
    client.force_login(other)
    response = client.post(f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "add"})
    assert response.status_code == 404
    assert not collection.normas.filter(pk=norma.pk).exists()

    client.force_login(owner)
    response = client.post(f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "add"})
    assert response.status_code == 302
    assert collection.normas.filter(pk=norma.pk).exists()

    detail = client.get(f"/colecoes/{collection.pk}/")
    assert detail.status_code == 200
    rendered = detail.content.decode()
    assert 'data-collection-remove-form' in rendered
    assert f'aria-label="Remover {norma} da coleção"' in rendered
    assert 'jurix-collections.js?v=20260930-remove-confirm1' in rendered

    response = client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "remove"}
    )
    assert response.status_code == 302
    assert not collection.normas.filter(pk=norma.pk).exists()
