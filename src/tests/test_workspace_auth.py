"""Workspace sign-in and sign-out behavior for provisioned user accounts."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_login_authenticates_provisioned_user_and_returns_to_requested_workspace():
    user = get_user_model().objects.create_user("workspace-login", password="fixture-pass")
    client = Client()

    response = client.get(reverse("workspace:login"), {"next": "/colecoes/"})
    assert response.status_code == 200
    assert b'autocomplete="username"' in response.content
    assert b'autocomplete="current-password"' in response.content

    response = client.post(
        reverse("workspace:login"),
        {"username": user.username, "password": "fixture-pass", "next": "/colecoes/"},
    )
    assert response.status_code == 302
    assert response["Location"] == "/colecoes/"
    assert client.get("/colecoes/").status_code == 200


def test_login_rejects_bad_credentials_without_disclosing_account_existence():
    get_user_model().objects.create_user("known-user", password="fixture-pass")
    client = Client()

    response = client.post(
        reverse("workspace:login"),
        {"username": "missing-user", "password": "wrong", "next": "/colecoes/"},
    )

    assert response.status_code == 200
    assert "Usu\u00e1rio ou senha incorretos.".encode() in response.content
    assert client.session.get("_auth_user_id") is None


def test_login_blocks_external_redirect_and_defaults_to_assistant():
    user = get_user_model().objects.create_user("safe-redirect-user", password="fixture-pass")
    client = Client()

    response = client.post(
        reverse("workspace:login"),
        {"username": user.username, "password": "fixture-pass", "next": "https://example.com"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("workspace:assistant")


def test_logout_is_post_only_and_clears_the_workspace_session():
    user = get_user_model().objects.create_user("workspace-logout", password="fixture-pass")
    client = Client()
    client.force_login(user)

    assert client.get(reverse("workspace:logout")).status_code == 405
    response = client.post(reverse("workspace:logout"))

    assert response.status_code == 302
    assert response["Location"] == reverse("workspace:assistant")
    assert client.session.get("_auth_user_id") is None


def test_login_form_requires_csrf_in_browser_style_client():
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("workspace:login"))

    response = client.post(
        reverse("workspace:login"),
        {"username": "any-user", "password": "any-password"},
    )

    assert response.status_code == 403


def test_anonymous_collection_empty_state_links_to_sign_in_without_public_signup():
    response = Client().get("/colecoes/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Entre para salvar suas coleções" in body
    assert 'href="/conta/entrar/?next=/colecoes/"' in body
    assert "não há cadastro público" in body
