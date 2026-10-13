"""Security boundary regressions for the PGM pilot workflow.

These tests use only Django's isolated test database and synthetic account/session
records. They do not provision a real reviewer or access production data.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.models import ChatSession

pytestmark = pytest.mark.django_db


def test_chat_session_mutations_cannot_cross_account_boundary():
    owner = get_user_model().objects.create_user("pgm-boundary-owner", password="test-only")
    other = get_user_model().objects.create_user("pgm-boundary-other", password="test-only")
    session = ChatSession.objects.create(user=owner, title="Pesquisa pública")
    client = Client()
    client.force_login(other)
    url = reverse("legislation_api:chat_session_detail", args=(session.pk,))

    assert client.get(url).status_code == 404
    assert client.patch(
        url,
        data=json.dumps({"title": "Acesso indevido"}),
        content_type="application/json",
    ).status_code == 404
    assert client.delete(url).status_code == 404

    session.refresh_from_db()
    assert session.title == "Pesquisa pública"
    assert ChatSession.objects.filter(pk=session.pk, user=owner).exists()


def test_browser_session_mutation_requires_csrf_token():
    user = get_user_model().objects.create_user("pgm-csrf-user", password="test-only")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    url = reverse("legislation_api:chat_sessions")

    denied = client.post(
        url,
        data=json.dumps({"title": "Consulta"}),
        content_type="application/json",
    )
    assert denied.status_code == 403
    assert not ChatSession.objects.filter(user=user).exists()


def test_non_staff_user_cannot_submit_document_review_action(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(tmp_path))
    mapping = seed_fixture(tmp_path / "fixture-map.json")
    user = get_user_model().objects.create_user("pgm-no-review-permission", password="test-only")
    client = Client()
    client.force_login(user)
    document_id = mapping["temporal_scenarios"]["norma_a"]["document_id"]

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        response = client.post(
            reverse("legislation:document_evidence", args=(document_id,)),
            {"action": "review_identity"},
        )

    assert response.status_code == 403
