from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from src.apps.ingestion.management.commands import isolate_synthetic_norma_identity_qa as isolation
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Dispositivo, Norma
from src.processing.document_metadata import build_normative_identity


@pytest.fixture
def synthetic_norma(db):
    document = DocumentoNormativo.objects.create(
        document_key="a" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="fixture:synthetic-lc55",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256="b" * 64,
        size_bytes=1,
        metadata_json={"synthetic": True},
        review_status=DocumentoNormativo.ReviewStatus.APPROVED,
    )
    identity = {
        "jurisdiction": "BR-RN-NATAL",
        "type": "lei_complementar",
        "series": "municipal_lc",
        "number": "55",
        "year": 2004,
        "synthetic_fixture": True,
    }
    norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="55",
        ano=2004,
        identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|55|2004",
        identity_json=identity,
        documento_base=document,
    )
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1",
        texto="Texto sintético de teste.",
        ordem=1,
        nivel=1,
    )
    return norma, document, device


def _qa_env(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
    monkeypatch.setattr(isolation, "_is_isolated_qa_database", lambda: True)


@pytest.mark.django_db(transaction=True)
def test_fixture_identity_isolation_dry_run_preserves_all_rows(synthetic_norma, monkeypatch):
    norma, document, device = synthetic_norma
    _qa_env(monkeypatch)

    result = isolation.isolate_synthetic_norma_identity(
        norma_id=norma.pk,
        expected_identity_key=norma.identity_key,
        expected_tipo=norma.tipo,
        expected_numero=norma.numero,
        expected_ano=norma.ano,
    )

    assert result["mode"] == "dry-run"
    assert result["persisted"] is False
    norma.refresh_from_db()
    document.refresh_from_db()
    device.refresh_from_db()
    assert norma.tipo == "Lei Complementar"
    assert norma.identity_key == "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004"
    assert norma.documento_base_id == document.pk
    assert device.norma_id == norma.pk


@pytest.mark.django_db(transaction=True)
def test_fixture_identity_isolation_changes_only_identity_fields(synthetic_norma, monkeypatch):
    norma, document, device = synthetic_norma
    _qa_env(monkeypatch)
    original_identity_json = norma.identity_json.copy()
    original_device_ids = list(Dispositivo.objects.filter(norma=norma).values_list("pk", flat=True))

    result = isolation.isolate_synthetic_norma_identity(
        norma_id=norma.pk,
        expected_identity_key=norma.identity_key,
        expected_tipo=norma.tipo,
        expected_numero=norma.numero,
        expected_ano=norma.ano,
        apply=True,
    )

    norma.refresh_from_db()
    document.refresh_from_db()
    device.refresh_from_db()
    assert result["persisted"] is True
    assert norma.tipo == "QA fixture — Lei Complementar"
    assert norma.identity_key.startswith(f"synthetic-fixture|{norma.pk}|")
    assert norma.identity_json == original_identity_json
    assert norma.numero == "55" and norma.ano == 2004
    assert norma.documento_base_id == document.pk
    assert list(Dispositivo.objects.filter(norma=norma).values_list("pk", flat=True)) == original_device_ids
    assert device.norma_id == norma.pk

    real_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei complementar",
        series="municipal_lc",
        number="55",
        year=2004,
    )
    from src.apps.ingestion.norma_registry import _find_or_create_pending_norma

    with transaction.atomic():
        real_norma, created, reconciliation = _find_or_create_pending_norma(real_identity)
    assert created is True
    assert reconciliation is None
    assert real_norma.pk != norma.pk
    assert real_norma.tipo == "Lei Complementar"
    assert real_norma.identity_key == real_identity.identity_key
    assert real_norma.documento_base_id is None


@pytest.mark.django_db(transaction=True)
def test_fixture_identity_isolation_rejects_mismatched_record_without_writes(synthetic_norma, monkeypatch):
    norma, _, _ = synthetic_norma
    _qa_env(monkeypatch)

    with pytest.raises(ValueError, match="não corresponde à fixture"):
        isolation.isolate_synthetic_norma_identity(
            norma_id=norma.pk,
            expected_identity_key="wrong-key",
            expected_tipo=norma.tipo,
            expected_numero=norma.numero,
            expected_ano=norma.ano,
            apply=True,
        )

    norma.refresh_from_db()
    assert norma.tipo == "Lei Complementar"
    assert norma.identity_key == "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004"


def test_fixture_identity_isolation_command_refuses_non_qa(monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")
    with pytest.raises(CommandError, match="QA isolado"):
        call_command(
            "isolate_synthetic_norma_identity_qa",
            norma_id=5,
            expected_identity_key="key",
            expected_tipo="Lei Complementar",
            expected_numero="55",
            expected_ano=2004,
            apply=True,
        )
