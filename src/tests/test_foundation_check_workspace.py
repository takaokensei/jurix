import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from src.apps.legislation.workspace_views import _foundation_job_key

pytestmark = pytest.mark.django_db


def _user_client(username="foundation-reviewer"):
    user = get_user_model().objects.create_user(username, password="test-only")
    client = Client()
    client.force_login(user)
    return user, client


def test_foundation_workspace_requires_authentication_and_uses_workspace_shell():
    response = Client().get(reverse("workspace:foundation_check"))
    assert response.status_code == 302
    assert response["Location"].startswith("/conta/entrar/?next=/conferir/")

    user, client = _user_client()
    response = client.get(reverse("workspace:foundation_check"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Conferir fundamentação" in body
    assert "A escolha das datas aplicáveis aos fatos é do usuário" in body
    assert "jurix-foundation-check.js" in body
    assert "As datas são necessárias apenas" in body
    assert "name=\"csrfmiddlewaretoken\"" in body
    assert user.is_staff is False


def test_review_step_shows_detected_reference_and_preserves_text_without_persisting():
    user, client = _user_client("foundation-parse")
    text = "Art. 1º da Lei nº 10/2020 deve ser verificado."
    response = client.post(
        reverse("workspace:foundation_check"),
        {"action": "review", "text": text, "from_date": "2020-01-01", "to_date": "2021-01-01"},
    )
    assert response.status_code == 200
    assert "Lei nº 10/2020" in response.content.decode()
    assert "Conferir dispositivos" in response.content.decode()
    assert not user.chat_sessions.exists()


def test_review_step_renders_flat_parser_identity_and_device_metadata():
    _, client = _user_client("foundation-review-metadata")
    response = client.post(
        reverse("workspace:foundation_check"),
        {
            "action": "review",
            "text": "Fundamento: Art. 1º da Lei Complementar nº 198/2021.",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    visible_text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
    assert "Lei Complementar nº 198/2021, Art. 1" in visible_text
    assert "Espécie não identificada" not in body


def test_reference_identification_does_not_require_comparison_dates():
    _, client = _user_client("foundation-review-without-dates")
    response = client.post(
        reverse("workspace:foundation_check"),
        {"action": "review", "text": "Art. 1º da Lei nº 10/2020 deve ser verificado."},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Lei nº 10/2020" in body
    assert "As datas são necessárias apenas" in body
    assert "Informe duas datas válidas" not in body


def test_compare_returns_evidence_links_and_cache_contains_no_pasted_text():
    user, client = _user_client("foundation-compare")
    job_id = uuid4()
    text = "Art. 1º da Lei nº 10/2020 deve ser verificado."
    called = {}
    evidence = {
        "evidence_id": "ev_123456789012345678901234",
        "document_id": str(uuid4()),
        "page": 3,
        "text": "Texto normativo público.",
        "legal_status": "in_force",
        "source_event_id": 7,
        "source_norma_id": 99,
        "effective_on": "2020-06-01",
    }
    result = {
        "comparison": {"from": "2020-01-01", "to": "2021-01-01"},
        "references": [{
            "reference_id": "ref_123456789012345678901234",
            "text": text,
            "identity": {"article": "1"},
            "status": "changed",
            "reason": None,
            "norma": "Lei nº 10/2020",
            "evidence": {"before": [dict(evidence)], "after": [dict(evidence)]},
            "coverage": {"before": {"reason": "verified"}, "after": {"reason": "verified"}},
        }],
        "summary": {"changed": 1, "revoked": 0, "vetoed": 0, "unchanged_in_checked_scope": 0, "inconclusive": 0, "confirmation_required": 0},
        "persisted": False,
        "llm_used": False,
        "corpus_revision": {"revision": 12, "completeness": "partial", "generated_at": "2026-10-08T12:00:00+00:00"},
        "corpus_coverage": {
            "coverage_status": "unknown",
            "checked_until": None,
            "sources_checked": [],
        },
    }

    class SourceNorma:
        pk = 99
        identity_json = {}
        sapl_url = ""
        sapl_id = None

        def __str__(self):
            return "Lei nº 5/2019"

    source_norma = SourceNorma()
    source_device = SimpleNamespace(norma=source_norma, get_caminho_completo=lambda: "Art. 2º")
    event = SimpleNamespace(
        pk=7,
        dispositivo_fonte=source_device,
        effective_on=date(2020, 6, 1),
        target_text="Altera o Art. 1º da Lei nº 10/2020",
        get_acao_display=lambda: "Alteração",
    )
    events_queryset = SimpleNamespace(select_related=lambda *_args: [event])

    def fake_check(submitted_text, *, from_date, to_date, should_cancel, on_progress):
        called.update(text=submitted_text, from_date=from_date, to_date=to_date)
        on_progress(2, 2)
        assert should_cancel() is False
        return result

    with (
        patch("src.apps.legislation.workspace_views.check_foundation", side_effect=fake_check),
        patch("src.apps.legislation.workspace_views.EventoAlteracao.objects.filter", return_value=events_queryset),
        patch("src.apps.legislation.workspace_views.event_review_status", return_value="confirmed"),
    ):
        response = client.post(
            reverse("workspace:foundation_check"),
            {
                "action": "compare", "job_id": str(job_id), "text": text,
                "from_date": "2020-01-01", "to_date": "2021-01-01",
            },
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Redação diferente" in body
    assert "Corte do corpus" in body and "revisão 12" in body
    assert "Cobertura registrada:</strong> desconhecida" in body
    assert "completude declarada: parcial." in body
    assert "Estado técnico da projeção: indicado como vigente neste corte" in body
    assert "A ausência de escopo revisado mantém “sem mudança” inconclusivo." in body
    assert "Evento revisado que explica a redação" in body
    assert "Lei nº 5/2019, Art. 2º" in body
    assert f"/normas/documentos/{evidence['document_id']}/pdf/#page=3" in body
    assert called == {"text": text, "from_date": date(2020, 1, 1), "to_date": date(2021, 1, 1)}
    state = cache.get(_foundation_job_key(job_id))
    assert state == {"owner_id": user.pk, "status": "completed", "completed": 2, "total": 2}
    assert text not in repr(state)
    cache.delete(_foundation_job_key(job_id))

    for status, expected_label, legal_status, expected_legal_label in (
        ("partial", "Cobertura registrada:</strong> parcial", "revoked", "indicado como revogado neste corte"),
        (
            "reviewed", "Cobertura registrada:</strong> revisada somente nos escopos listados",
            "unknown", "indeterminado neste corte",
        ),
    ):
        next_job_id = uuid4()
        result["corpus_coverage"]["coverage_status"] = status
        evidence["legal_status"] = legal_status
        for moment in ("before", "after"):
            result["references"][0]["evidence"][moment][0]["legal_status"] = legal_status
        with (
            patch("src.apps.legislation.workspace_views.check_foundation", side_effect=fake_check),
            patch("src.apps.legislation.workspace_views.EventoAlteracao.objects.filter", return_value=events_queryset),
            patch("src.apps.legislation.workspace_views.event_review_status", return_value="confirmed"),
        ):
            response = client.post(
                reverse("workspace:foundation_check"),
                {
                    "action": "compare", "job_id": str(next_job_id), "text": text,
                    "from_date": "2020-01-01", "to_date": "2021-01-01",
                },
            )
        assert response.status_code == 200
        body = response.content.decode()
        assert expected_label in body
        assert f"Estado técnico da projeção: {expected_legal_label}" in body
        cache.delete(_foundation_job_key(next_job_id))


def test_status_and_cancel_endpoints_are_scoped_to_authenticated_owner():
    owner, client = _user_client("foundation-owner")
    _, other_client = _user_client("foundation-other")
    job_id = uuid4()
    key = _foundation_job_key(job_id)
    cache.set(key, {"owner_id": owner.pk, "status": "running", "completed": 0, "total": 2}, timeout=60)
    try:
        assert client.get(reverse("workspace:foundation_check_status", args=(job_id,))).json()["status"] == "running"
        assert other_client.get(reverse("workspace:foundation_check_status", args=(job_id,))).status_code == 404
        response = client.post(reverse("workspace:foundation_check_cancel", args=(job_id,)))
        assert response.status_code == 200
        assert cache.get(key)["status"] == "cancelling"
    finally:
        cache.delete(key)


def test_duplicate_compare_job_id_is_rejected_without_running_twice():
    user, client = _user_client("foundation-duplicate")
    job_id = uuid4()
    key = _foundation_job_key(job_id)
    cache.set(key, {"owner_id": user.pk, "status": "completed", "completed": 2, "total": 2}, timeout=60)
    try:
        with patch("src.apps.legislation.workspace_views.check_foundation") as compare:
            response = client.post(
                reverse("workspace:foundation_check"),
                {
                    "action": "compare", "job_id": str(job_id),
                    "text": "Lei nº 10/2020, Art. 1º", "from_date": "2020-01-01", "to_date": "2021-01-01",
                },
            )
        assert response.status_code == 409
        compare.assert_not_called()
    finally:
        cache.delete(key)
