"""Ownership and persistence contracts for the workspace collections surface."""

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
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
    response = client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "add"}, follow=True
    )
    assert response.status_code == 200
    assert collection.normas.filter(pk=norma.pk).exists()
    first_add_messages = list(response.context["messages"])
    assert any(message.level_tag == "success" for message in first_add_messages)

    duplicate_client = Client()
    duplicate_client.force_login(owner)
    duplicate_add = duplicate_client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "add"}, follow=True
    )
    add_messages = list(duplicate_add.context["messages"])
    assert not any(message.level_tag == "success" for message in add_messages), add_messages
    assert any(message.level_tag == "info" for message in add_messages)

    detail = client.get(f"/colecoes/{collection.pk}/")
    assert detail.status_code == 200
    rendered = detail.content.decode()
    assert "data-collection-remove-form" in rendered
    assert f'aria-label="Remover {norma} da coleção"' in rendered
    assert "jurix-collections.js?v=20260930-remove-confirm1" in rendered

    response = client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "remove"}, follow=True
    )
    assert response.status_code == 200
    assert not collection.normas.filter(pk=norma.pk).exists()
    first_remove_messages = list(response.context["messages"])
    assert any(message.level_tag == "success" for message in first_remove_messages)

    duplicate_client = Client()
    duplicate_client.force_login(owner)
    duplicate_remove = duplicate_client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma.pk, "action": "remove"}, follow=True
    )
    remove_messages = list(duplicate_remove.context["messages"])
    assert not any(message.level_tag == "success" for message in remove_messages)
    assert any(message.level_tag == "info" for message in remove_messages)


@pytest.mark.parametrize(
    ("payload", "field_id", "error_id", "submitted_value"),
    [
        ({"name": "N" * 121, "description": "Pesquisa"}, "collection-name", "collection-name-error", "N" * 121),
        (
            {"name": "ISS", "description": "D" * 501},
            "collection-description",
            "collection-description-error",
            "D" * 501,
        ),
        ({"name": "   ", "description": "Pesquisa"}, "collection-name", "collection-name-error", "   "),
    ],
)
def test_collection_creation_rejects_invalid_fields_and_preserves_form_values(
    payload, field_id, error_id, submitted_value
):
    user = User.objects.create_user("invalid-collection-user", password="secret")
    client = Client()
    client.force_login(user)

    response = client.post("/colecoes/", payload)
    body = response.content.decode()

    assert response.status_code == 400
    assert Collection.objects.filter(user=user).count() == 0
    assert 'data-collection-dialog' in body and '<dialog' in body and ' open>' in body
    assert f'<label for="{field_id}">' in body
    assert f'id="{field_id}"' in body
    assert f'aria-invalid="true" aria-describedby="{error_id}"' in body
    assert f'id="{error_id}" class="workspace-confirm-error" role="alert"' in body
    assert submitted_value in body


@pytest.mark.parametrize("norma_id", ["not-an-id", "-12", "9223372036854775808", "999999999"])
def test_collection_rejects_invalid_norma_ids_before_querying_or_mutating(norma_id):
    user = User.objects.create_user("invalid-norma-id-user", password="secret")
    collection = Collection.objects.create(user=user, name="Dossiê")
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/colecoes/{collection.pk}/", {"norma_id": norma_id, "action": "add"}
    )

    assert response.status_code == 400
    assert collection.normas.count() == 0
    body = response.content.decode()
    assert 'id="collection-norma-id-error"' in body
    assert 'role="alert"' in body
    assert "identificador de norma válido" in body


def test_existing_collection_without_changes_does_not_emit_a_success_message():
    user = User.objects.create_user("existing-collection-user", password="secret")
    Collection.objects.create(user=user, name="ISS", description="Pesquisa")
    client = Client()
    client.force_login(user)

    response = client.post("/colecoes/", {"name": "ISS", "description": "Pesquisa"})
    emitted_messages = list(get_messages(response.wsgi_request))

    assert response.status_code == 302
    assert not any(message.level_tag == "success" for message in emitted_messages)
    assert any(message.level_tag == "info" for message in emitted_messages)
