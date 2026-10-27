import json
from copy import deepcopy

import pytest
from django.test import override_settings
from django.urls import reverse

from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.pilot_casefile import build_pilot_casefile, render_pilot_casefile_markdown
from src.processing.pilot_corpus import publish_revision
from src.tests.test_pilot_projection import KEY, corpus, event


def test_one_dossier_binds_comparison_graph_and_portable_source_export():
    c = corpus(event())
    c["corpus_revision"] = "a" * 64
    c["sources"][0]["identity"] = {"tipo": "lei", "numero": "20", "ano": 2020}
    first = build_pilot_casefile(c, KEY, paths=("art:1",), as_of="2025-01-10")
    assert first == build_pilot_casefile(c, KEY, paths=("art:1",), as_of="2025-01-10")
    assert first["devices"][0]["after"] == c["events"][0]["new_text"]
    assert {edge["event_id"] for edge in first["graph"]["edges"]} == {event["event_id"] for event in first["events"]}
    assert all(edge["casefile_id"] == first["casefile_id"] for edge in first["graph"]["edges"])
    assert all(row["corpus_revision"] == c["corpus_revision"] for row in first["sources"])
    markdown = render_pilot_casefile_markdown(first)
    assert "localhost" not in markdown and "127.0.0.1" not in markdown
    assert "/explorar/fontes/" in markdown and "#page=1" in markdown
    changed = deepcopy(c)
    changed["corpus_revision"] = "r2"
    assert build_pilot_casefile(changed, KEY)["casefile_id"] != first["casefile_id"]


def test_conflict_remains_in_dossier_and_graph_without_a_definitive_version():
    c = corpus(event())
    c["events"][0]["resolution"] = "conflict"
    result = build_pilot_casefile(c, KEY)
    assert result["devices"][0]["status"] == "conflict"
    assert result["devices"][0]["after"] is None
    assert result["graph"]["edges"][0]["resolution"] == "conflict"


@pytest.fixture
def pilot_dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    c = corpus(event())
    for row in c["sources"]:
        _j, kind, number, year = row["norma_key"].split("|")
        row["identity"] = {"tipo": kind, "numero": number, "ano": int(year)}
        DocumentoNormativo.objects.create(document_key=row["pdf_sha256"], content_sha256=row["pdf_sha256"], source_ref="test-pilot-dossier", source_kind="archive")
    revision = publish_revision(tmp_path / "pilot", c["sources"], report={}, event_bundle={"events": c["events"]})
    with override_settings(QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="qa", NORMATIVE_ARCHIVE_ENABLED=True):
        yield c, revision


@pytest.mark.django_db
def test_dossier_view_and_export_resolve_same_identity_and_reject_future(client, pilot_dossier):
    c, revision = pilot_dossier
    path = reverse("workspace:pilot_casefile")
    query = {"norma": KEY, "revision": revision["corpus_revision"], "as_of": "2025-01-10", "dispositivo": "art:1"}
    response = client.get(path, query)
    assert response.status_code == 200
    body = response.content.decode()
    assert "Texto e comparação" in body and "Confirmado após revisão humana" not in body
    assert "Regra nova." in body and "normative-casefile-graph" in body
    exported = client.get(path, {**query, "formato": "json"}).json()
    assert response.context["casefile"]["casefile_id"] == exported["casefile_id"]
    assert client.get(path, {**query, "formato": "markdown"}).status_code == 200
    source_path = reverse("workspace:pilot_source_pdf", args=(c["sources"][0]["pdf_sha256"],))
    assert client.get(source_path, {"revision": revision["corpus_revision"]}).status_code == 302
    assert client.get(path, {**query, "as_of": "2099-01-01"}).status_code == 400
    assert client.get(path, {**query, "revision": "../../outside"}).status_code == 404


@pytest.mark.django_db
def test_revision_remains_pinned_after_activation_and_profile_is_not_bypassed(client, pilot_dossier, tmp_path):
    c, original = pilot_dossier
    fresh = deepcopy(c)
    fresh["events"][0]["resolution"] = "conflict"
    latest = publish_revision(tmp_path / "pilot", fresh["sources"], report={}, event_bundle={"events": fresh["events"]})
    assert latest["corpus_revision"] != original["corpus_revision"]
    response = client.get(reverse("workspace:pilot_casefile"), {"norma": KEY, "revision": original["corpus_revision"], "formato": "json"})
    result = json.loads(response.content)
    assert result["corpus_revision"] == original["corpus_revision"]
    assert result["events"][0]["resolution"] == "resolved"
    with override_settings(JURIX_BUILD_PROFILE="production"):
        assert client.get(reverse("workspace:pilot_casefile"), {"norma": KEY}).status_code == 404
