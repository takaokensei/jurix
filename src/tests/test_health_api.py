from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse


def test_live_health_is_cheap(client):
    response = client.get(reverse("legislation_api:health_live"))
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@patch("src.apps.legislation.api_views._check_ollama", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_migrations", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_redis", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_pgvector", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_database", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_corpus", return_value=(True, "ok"))
def test_ready_health_returns_all_dependency_states(
    _corpus, _db, _vector, _redis, _migrations, _ollama, client
):
    response = client.get(reverse("legislation_api:health_ready"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["dependencies"]) == {
        "database",
        "pgvector",
        "redis",
        "migrations",
        "ollama",
        "corpus",
    }


@patch("src.apps.legislation.api_views._check_ollama", return_value=(False, "error"))
@patch("src.apps.legislation.api_views._check_migrations", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_redis", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_pgvector", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_database", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_corpus", return_value=(True, "ok"))
def test_ready_health_returns_503_when_dependency_is_down(
    _corpus, _db, _vector, _redis, _migrations, _ollama, client
):
    response = client.get(reverse("legislation_api:health_ready"))
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.django_db
@override_settings(READINESS_REQUIRE_CORPUS=True)
@patch("src.apps.legislation.api_views._check_ollama", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_migrations", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_redis", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_pgvector", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_database", return_value=(True, "ok"))
def test_ready_health_rejects_empty_production_corpus(
    _db, _vector, _redis, _migrations, _ollama, client
):
    response = client.get(reverse("legislation_api:health_ready"))

    assert response.status_code == 503
    assert response.json()["dependencies"]["corpus"] == "no consolidated normas available"


def test_dependency_failure_sanitizes_internal_error():
    from src.apps.legislation.api_health import _dependency_failure

    ok, detail = _dependency_failure("database", RuntimeError("password=super-secret"))

    assert ok is False
    assert detail == "database check failed"
