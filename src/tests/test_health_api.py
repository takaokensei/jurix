from unittest.mock import patch

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
def test_ready_health_returns_all_dependency_states(
    _db, _vector, _redis, _migrations, _ollama, client
):
    response = client.get(reverse("legislation_api:health_ready"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["dependencies"]) == {"database", "pgvector", "redis", "migrations", "ollama"}


@patch("src.apps.legislation.api_views._check_ollama", return_value=(False, "error"))
@patch("src.apps.legislation.api_views._check_migrations", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_redis", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_pgvector", return_value=(True, "ok"))
@patch("src.apps.legislation.api_views._check_database", return_value=(True, "ok"))
def test_ready_health_returns_503_when_dependency_is_down(
    _db, _vector, _redis, _migrations, _ollama, client
):
    response = client.get(reverse("legislation_api:health_ready"))
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
