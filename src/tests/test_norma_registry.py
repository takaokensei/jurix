from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections

from src.apps.ingestion.document_promotion import PromotionBlocked, promotion_fingerprint
from src.apps.ingestion.norma_registry import register_reviewed_identity
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.document_metadata import build_normative_identity


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _candidate(*, key: str = "registry-candidate", raw_type: str = "Lei Complementar"):
    type_series = {
        "Lei Complementar": "municipal_lc",
        "Lei": "municipal_lo",
        "Decreto": "municipal_decreto",
    }
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type=raw_type,
        series=type_series[raw_type],
        number="120",
        year=2010,
    )
    document = DocumentoNormativo.objects.create(
        document_key=_sha(key),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref=f"archive:{key}",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256=_sha(f"pdf:{key}"),
        size_bytes=100,
        metadata_json={
            "identity_key": identity.identity_key,
            "identity_candidate": identity.identity_json,
            "synthetic": False,
        },
        condition_of_use=DocumentoNormativo.ConditionOfUse.UNKNOWN,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    return document, identity


@pytest.fixture
def registry_reviewer(db):
    return get_user_model().objects.create_user(
        username="registry-reviewer", is_active=True, is_staff=True
    )


def _register(document, identity, reviewer, **overrides):
    values = {
        "document_id": str(document.public_id),
        "reviewer": reviewer,
        "reason": "Espécie, número, ano e jurisdição cotejados com o PDF público.",
        "fingerprint": promotion_fingerprint(document),
        "confirmed_identity_key": identity.identity_key,
        "confirmed_condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
    }
    values.update(overrides)
    return register_reviewed_identity(**values)


@pytest.mark.django_db(transaction=True)
def test_register_identity_creates_pending_norma_without_sapl_or_text(registry_reviewer):
    document, identity = _candidate()

    result = _register(document, identity, registry_reviewer)

    document.refresh_from_db()
    norma = Norma.objects.get(pk=result["norma_id"])
    assert result["norma_created"] is True
    assert result["text_promoted"] is False
    assert norma.identity_key == identity.identity_key
    assert norma.tipo == "Lei Complementar"
    assert norma.numero == "120" and norma.ano == 2010
    assert norma.status == Norma.Status.PENDING and norma.needs_review is True
    assert norma.texto_original == norma.texto_consolidado == ""
    assert norma.sapl_id is None and norma.sapl_url == ""
    assert norma.documento_base_id is None
    assert document.norma_id == norma.pk
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    assert document.condition_of_use == DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED
    review = RevisaoJuridica.objects.get(public_id=result["review_id"])
    assert review.target_fingerprint != promotion_fingerprint(document)
    assert review.reason.startswith("[identidade normativa revisada]")


@pytest.mark.django_db(transaction=True)
def test_identity_registration_is_idempotent_for_same_document(registry_reviewer):
    document, identity = _candidate()
    fingerprint = promotion_fingerprint(document)
    first = _register(document, identity, registry_reviewer, fingerprint=fingerprint)
    second = _register(document, identity, registry_reviewer, fingerprint=fingerprint)

    assert first["norma_id"] == second["norma_id"]
    assert first["review_id"] == second["review_id"]
    assert second["idempotent"] is True
    assert Norma.objects.count() == 1
    assert RevisaoJuridica.objects.filter(documento=document).count() == 1


@pytest.mark.django_db(transaction=True)
def test_legacy_norma_with_same_canonical_identity_is_reused(registry_reviewer):
    document, identity = _candidate()
    legacy = Norma.objects.create(
        tipo="Lei Complementar",
        numero="120",
        ano=2010,
        identity_json=identity.identity_json,
    )

    result = _register(document, identity, registry_reviewer)

    legacy.refresh_from_db()
    assert result["norma_id"] == legacy.pk
    assert result["norma_created"] is False
    assert legacy.identity_key == identity.identity_key
    assert legacy.status == Norma.Status.PENDING
    assert legacy.sapl_id is None


@pytest.mark.django_db(transaction=True)
def test_same_number_and_year_with_different_species_is_not_merged(registry_reviewer):
    document, identity = _candidate(raw_type="Lei Complementar")
    ordinary_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei",
        series="municipal_lo",
        number="120",
        year=2010,
    )
    ordinary = Norma.objects.create(
        tipo="Lei Ordinária",
        numero="120",
        ano=2010,
        identity_key=ordinary_identity.identity_key,
        identity_json=ordinary_identity.identity_json,
    )

    result = _register(document, identity, registry_reviewer)

    assert result["norma_id"] != ordinary.pk
    assert Norma.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_typed_legacy_identity_conflict_blocks_registration(registry_reviewer):
    document, identity = _candidate()
    conflicting_json = {**identity.identity_json, "jurisdiction": "BR-RN-OTHER"}
    Norma.objects.create(
        tipo="Lei Complementar",
        numero="120",
        ano=2010,
        identity_key="legacy-conflicting-key",
        identity_json=conflicting_json,
    )

    with pytest.raises(PromotionBlocked, match="Conflito tipado"):
        _register(document, identity, registry_reviewer)

    assert document.norma_id is None
    assert RevisaoJuridica.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_unknown_conflicting_and_synthetic_candidates_are_refused(registry_reviewer):
    document, identity = _candidate()
    with pytest.raises(PromotionBlocked, match="diverge"):
        _register(document, identity, registry_reviewer, confirmed_identity_key="wrong")
    with pytest.raises(PromotionBlocked, match="base de registro público"):
        _register(
            document,
            identity,
            registry_reviewer,
            confirmed_condition_of_use=DocumentoNormativo.ConditionOfUse.UNKNOWN,
        )
    with pytest.raises(PromotionBlocked, match="Fingerprint desatualizado"):
        _register(document, identity, registry_reviewer, fingerprint="0" * 64)

    document.metadata_json["synthetic"] = True
    document.save(update_fields=["metadata_json", "updated_at"])
    with pytest.raises(PromotionBlocked, match="sintética"):
        _register(document, identity, registry_reviewer)
    assert Norma.objects.count() == 0
    assert RevisaoJuridica.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_non_staff_cannot_register_identity():
    reviewer = get_user_model().objects.create_user(username="visitor", is_active=True, is_staff=False)
    document, identity = _candidate()

    with pytest.raises(PermissionDenied):
        _register(document, identity, reviewer)

    assert Norma.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_documents_with_same_identity_resolve_to_one_norma():
    user_model = get_user_model()
    reviewer = user_model.objects.create_user(
        username="concurrent-reviewer", is_active=True, is_staff=True
    )
    first_document, identity = _candidate(key="concurrent-one")
    second_document, _ = _candidate(key="concurrent-two")
    barrier = Barrier(2)

    def submit(document_id: str):
        close_old_connections()
        try:
            local_reviewer = user_model.objects.get(pk=reviewer.pk)
            barrier.wait(timeout=10)
            document = DocumentoNormativo.objects.get(public_id=document_id)
            return _register(document, identity, local_reviewer)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, [str(first_document.public_id), str(second_document.public_id)]))

    assert results[0]["norma_id"] == results[1]["norma_id"]
    assert Norma.objects.filter(identity_key=identity.identity_key).count() == 1
    assert RevisaoJuridica.objects.filter(documento__in=[first_document, second_document]).count() == 2
