from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import User

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    ExtracaoDocumento,
    NormativeSnapshot,
)
from src.apps.legislation.models import Norma


@pytest.mark.django_db(transaction=True)
def test_seed_normative_qa_is_idempotent_synthetic_and_has_no_credentials(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    output_one = root / "fixture-map.json"
    output_two = root / "fixture-map-repeat.json"
    first = seed_fixture(output_one)
    second = seed_fixture(output_two)
    assert first["dataset"] == "synthetic_not_gold"
    assert first["scenarios"] == second["scenarios"]
    assert first["temporal_scenarios"] == second["temporal_scenarios"]
    edge_cases = first["normative_edge_cases"]
    assert len(edge_cases) >= 12
    assert all(case["synthetic_only"] and case["human_review_required"] for case in edge_cases)
    assert {case["case_id"] for case in edge_cases} >= {
        "lc_reference", "partial_revocation", "add_article_5_a", "future_norm", "conflicting_candidate"
    }
    assert first["credentials_included"] is False
    assert "password" not in json.loads(output_one.read_text(encoding="utf-8"))
    assert Norma.objects.filter(ano=2090, numero="9901").count() == 2
    assert DocumentoNormativo.objects.filter(source_ref__startswith="jurix-synthetic-qa:").count() == 5
    assert ExtracaoDocumento.objects.filter(documento__source_ref__startswith="jurix-synthetic-qa:").count() == 5
    temporal = first["temporal_scenarios"]
    assert temporal["synthetic_only"] is True
    assert temporal["snapshots"]["d_minus_1"]["content_sha256"] != temporal["snapshots"]["d"]["content_sha256"]
    assert temporal["snapshots"]["d_minus_1"]["article_5_text"] == "Art. 5º O prazo é de dez dias."
    assert temporal["snapshots"]["d"]["article_5_text"] == "O prazo é de vinte dias."
    assert temporal["snapshots"]["d_plus_1"]["content_sha256"] == temporal["snapshots"]["d"]["content_sha256"]
    assert NormativeSnapshot.objects.filter(norma_id=temporal["norma_a"]["norma_id"]).count() == 3
    assert DocumentoNormativo.objects.filter(norma__isnull=True).count() >= 3
    conflict = DocumentoNormativo.objects.get(source_ref__endswith=":conflito:v1")
    assert conflict.conflicts_json
    reviewer = User.objects.get(username="jurix-qa-reviewer")
    assert reviewer.is_staff and reviewer.is_superuser and not reviewer.has_usable_password()


@pytest.mark.django_db(transaction=True)
def test_seed_refuses_output_outside_qa_and_overwrite(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    with pytest.raises(Exception, match="dentro da raiz QA"):
        seed_fixture(tmp_path / "outside.json")


@pytest.mark.django_db(transaction=True)
def test_seed_rejects_missing_qa_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    with pytest.raises(Exception, match="JURIX_QA_ONLY=1"):
        seed_fixture(tmp_path / "fixture.json")
