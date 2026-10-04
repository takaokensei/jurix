from __future__ import annotations

import hashlib
import json

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command
from django.test import override_settings

from src.apps.ingestion.document_promotion import (
    PromotionBlocked,
    promote_document,
    promotion_fingerprint,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.document_metadata import build_normative_identity


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def reviewed_candidate(db):
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei", series="municipal_lo", number="9001", year=2020
    )
    norma = Norma.objects.create(
        tipo="Lei", numero="9001", ano=2020, identity_key=identity.identity_key,
        identity_json=identity.identity_json,
    )
    document = DocumentoNormativo.objects.create(
        document_key=_sha("promotion-doc"), source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:fixture", role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256=_sha("pdf"), size_bytes=3,
        metadata_json={"identity_key": identity.identity_key, "identity_candidate": identity.identity_json},
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    text = "Art. 1º. Norma fictícia usada somente para teste QA."
    extraction = ExtracaoDocumento.objects.create(
        documento=document, extractor_version="fixture-v1", policy_fingerprint=_sha("policy"),
        text_version="fixture-text-v1", raw_text=text, legal_text=text,
        raw_text_sha256=_sha(text), legal_text_sha256=_sha(text), page_count=1,
        page_map_json=[], metadata_candidates_json={}, quality_json={"synthetic": False},
        status=ExtracaoDocumento.Status.COMPLETE, extraction_sha256=_sha("extraction"),
    )
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction", "updated_at"])
    reviewer = User.objects.create_user(username="reviewer", is_staff=True)
    return document, norma, reviewer, identity.identity_key


@pytest.mark.django_db(transaction=True)
def test_document_promotion_requires_staff_reason_identity_and_explicit_confirmation(reviewed_candidate):
    document, norma, reviewer, identity_key = reviewed_candidate
    fingerprint = promotion_fingerprint(document)
    with pytest.raises(PermissionDenied):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk,
            actor=User.objects.create_user(username="visitor"), reason="review",
            expected_fingerprint=fingerprint, confirmed_identity_key=identity_key,
            confirmed_role=DocumentoNormativo.Role.ORIGINAL, confirm_public_record=True,
        )
    with pytest.raises(PromotionBlocked, match="Fingerprint desatualizado"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint="0" * 64,
            confirmed_identity_key=identity_key, confirmed_role=DocumentoNormativo.Role.ORIGINAL,
            confirm_public_record=True,
        )
    with pytest.raises(PromotionBlocked, match="registro público"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint=fingerprint,
            confirmed_identity_key=identity_key, confirmed_role=DocumentoNormativo.Role.ORIGINAL,
        )
    with pytest.raises(PromotionBlocked, match="Identidade não foi confirmada"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint=fingerprint, confirmed_identity_key="wrong",
            confirmed_role=DocumentoNormativo.Role.ORIGINAL, confirm_public_record=True,
        )
    with pytest.raises(PromotionBlocked, match="Confirme explicitamente que o documento"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint=fingerprint, confirmed_identity_key=identity_key,
            confirmed_role=DocumentoNormativo.Role.ANNEX, confirm_public_record=True,
        )


@pytest.mark.django_db(transaction=True)
def test_document_promotion_is_audited_and_repeat_is_idempotent(reviewed_candidate):
    document, norma, reviewer, identity_key = reviewed_candidate
    fingerprint = promotion_fingerprint(document)
    kwargs = {
        "document_id": str(document.public_id), "norma_id": norma.pk, "actor": reviewer,
        "reason": "Identidade cotejada com o documento e fonte pública revisada.",
        "expected_fingerprint": fingerprint, "confirmed_identity_key": identity_key,
        "confirmed_role": DocumentoNormativo.Role.ORIGINAL, "confirm_public_record": True,
    }
    first = promote_document(**kwargs)
    second = promote_document(**kwargs)
    document.refresh_from_db()
    norma.refresh_from_db()
    assert first["review_id"] == second["review_id"]
    assert second["idempotent"] is True
    assert document.norma_id == norma.pk
    assert document.review_status == DocumentoNormativo.ReviewStatus.APPROVED
    assert document.condition_of_use == DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED
    assert norma.documento_base_id == document.pk
    assert RevisaoJuridica.objects.filter(documento=document).count() == 1


@pytest.mark.django_db(transaction=True)
def test_promotion_blocks_conflict_existing_base_and_synthetic_records(reviewed_candidate):
    document, norma, reviewer, identity_key = reviewed_candidate
    document.conflicts_json = [{"field": "year"}]
    document.save(update_fields=["conflicts_json", "updated_at"])
    with pytest.raises(PromotionBlocked, match="Candidato não resolvido"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint=promotion_fingerprint(document),
            confirmed_identity_key=identity_key, confirmed_role=DocumentoNormativo.Role.ORIGINAL,
            confirm_public_record=True,
        )
    document.conflicts_json = []
    document.metadata_json["synthetic"] = True
    document.save(update_fields=["conflicts_json", "metadata_json", "updated_at"])
    with pytest.raises(PromotionBlocked, match="sintética"):
        promote_document(
            document_id=str(document.public_id), norma_id=norma.pk, actor=reviewer,
            reason="review", expected_fingerprint=promotion_fingerprint(document),
            confirmed_identity_key=identity_key, confirmed_role=DocumentoNormativo.Role.ORIGINAL,
            confirm_public_record=True,
        )
    assert RevisaoJuridica.objects.filter(documento=document).count() == 0


@pytest.mark.django_db(transaction=True)
def test_legacy_backfill_plan_is_read_only_hash_only_and_refuses_overwrite(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    Norma.objects.create(tipo="Lei", numero="777", ano=2020, texto_original="Texto legado sem origem certificada.")
    output = qa_root / "legacy-plan.json"
    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        call_command("promote_normative_documents", plan_legacy=True, output=output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["mode"] == "read_only_plan"
        assert payload["count"] == 1
        assert "texto_original" not in output.read_text(encoding="utf-8")
        assert payload["candidates"][0]["status"] == "candidate_unverified_origin"
        assert DocumentoNormativo.objects.count() == 0
        with pytest.raises(CommandError, match="sobrescrever"):
            call_command("promote_normative_documents", plan_legacy=True, output=output)
