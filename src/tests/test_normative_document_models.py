from __future__ import annotations

import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from src.apps.legislation.models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
    Norma,
    RevisaoJuridica,
)
from src.apps.operations.models import ArchiveImportRun

DOC_HASH = "a" * 64
POLICY_HASH = "b" * 64


@pytest.mark.django_db
def test_legacy_norma_remains_unchanged_and_new_identity_fields_start_null():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        texto_original="texto legado original",
        texto_consolidado="texto legado consolidado",
    )

    norma.refresh_from_db()
    assert norma.identity_key is None
    assert norma.identity_json == {}
    assert norma.data_norma is None
    assert norma.documento_base is None
    assert norma.texto_original == "texto legado original"
    assert norma.texto_consolidado == "texto legado consolidado"


@pytest.mark.django_db
def test_document_key_is_unique_but_identical_content_hash_is_allowed():
    first = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="sistema2/pdfs/lei.pdf",
        content_sha256=DOC_HASH,
        original_filename="lei.pdf",
    )
    second = DocumentoNormativo.objects.create(
        document_key="c" * 64,
        source_kind="archive",
        source_ref="sistema2/pdfs/republicacao.pdf",
        content_sha256=DOC_HASH,
        original_filename="republicacao.pdf",
    )
    assert first.pk != second.pk
    assert second.content_sha256 == first.content_sha256
    with pytest.raises(ValidationError):
        DocumentoNormativo.objects.create(
            document_key=DOC_HASH,
            source_kind="archive",
            source_ref="duplicate.pdf",
            content_sha256="d" * 64,
        )


@pytest.mark.django_db
def test_storage_key_rejects_absolute_windows_and_parent_paths():
    document = DocumentoNormativo(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="relative.pdf",
        content_sha256=DOC_HASH,
        storage_key=r"C:\private\law.pdf",
    )

    with pytest.raises(ValidationError, match="chave deve ser relativa"):
        document.full_clean()


@pytest.mark.django_db
def test_extraction_hashes_are_computed_and_existing_revision_is_immutable():
    document = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="sistema2/pdfs/lei.pdf",
        content_sha256=DOC_HASH,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-test",
        policy_fingerprint=POLICY_HASH,
        text_version="technical_text_v1",
        raw_text="texto bruto",
        legal_text="Art. 1º Texto legal.",
        status="complete",
        page_count=1,
        page_map_json=[
            {
                "text_version": "technical_text_v1",
                "page": 1,
                "start": 0,
                "end": len("Art. 1º Texto legal."),
                "method": "native",
            }
        ],
    )

    assert extraction.raw_text_sha256 == hashlib.sha256(b"texto bruto").hexdigest()
    assert extraction.legal_text_sha256 == hashlib.sha256(extraction.legal_text.encode()).hexdigest()
    assert len(extraction.extraction_sha256) == 64
    extraction.legal_text = "texto alterado"
    with pytest.raises(ValidationError, match="imutáveis"):
        extraction.save()
    with pytest.raises(ValidationError, match="Registros versionados"):
        ExtracaoDocumento.objects.filter(pk=extraction.pk).update(legal_text="bulk overwrite")


@pytest.mark.django_db
def test_duplicate_document_extractor_policy_revision_is_rejected():
    document = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="sistema2/pdfs/lei.pdf",
        content_sha256=DOC_HASH,
    )
    args = {
        "documento": document,
        "extractor_version": "pymupdf-test",
        "policy_fingerprint": POLICY_HASH,
        "text_version": "technical_text_v1",
        "legal_text": "Texto estável.",
    }
    ExtracaoDocumento.objects.create(**args)

    with pytest.raises(ValidationError):
        ExtracaoDocumento.objects.create(**args)


@pytest.mark.django_db
def test_document_device_offsets_and_content_are_frozen():
    document = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="lei.pdf",
        content_sha256=DOC_HASH,
    )
    legal_text = "Art. 1º Texto legal."
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-test",
        policy_fingerprint=POLICY_HASH,
        text_version="technical_text_v1",
        legal_text=legal_text,
    )
    device = DocumentoDispositivo.objects.create(
        extracao=extraction,
        structural_key="artigo:1",
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto=legal_text,
        start_offset=0,
        end_offset=len(legal_text),
    )
    device.texto = "outra redação"
    with pytest.raises(ValidationError, match="imutáveis"):
        device.save()
    with pytest.raises(ValidationError, match="Registros versionados"):
        DocumentoDispositivo.objects.filter(pk=device.pk).update(texto="bulk overwrite")


@pytest.mark.django_db
def test_extraction_and_document_deletions_are_protected():
    document = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="lei.pdf",
        content_sha256=DOC_HASH,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-test",
        policy_fingerprint=POLICY_HASH,
        text_version="technical_text_v1",
        legal_text="Art. 1º Texto legal.",
    )
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction"])

    with pytest.raises(ValidationError, match="não podem ser removidas"):
        extraction.delete()
    with pytest.raises(ProtectedError):
        document.delete()


@pytest.mark.django_db
def test_legal_review_requires_one_target_and_is_append_only(django_user_model):
    reviewer = django_user_model.objects.create_user(username="reviewer-fixture")
    invalid = RevisaoJuridica(
        target_fingerprint=DOC_HASH,
        decision="approve",
        reason="Decisão sintética de teste.",
        actor=reviewer,
    )
    with pytest.raises(ValidationError, match="exatamente"):
        invalid.save()

    document = DocumentoNormativo.objects.create(
        document_key=DOC_HASH,
        source_kind="archive",
        source_ref="lei.pdf",
        content_sha256=DOC_HASH,
    )
    review = RevisaoJuridica.objects.create(
        documento=document,
        target_fingerprint=DOC_HASH,
        decision="approve",
        reason="Decisão sintética de teste.",
        actor=reviewer,
    )
    review.reason = "Tentativa de reescrever decisão existente."
    with pytest.raises(ValidationError, match="append-only"):
        review.save()
    with pytest.raises(ValidationError, match="append-only"):
        RevisaoJuridica.objects.filter(pk=review.pk).update(reason="bulk overwrite")


@pytest.mark.django_db
def test_archive_run_is_operational_and_does_not_auto_approve_documents():
    run = ArchiveImportRun.objects.create(
        archive_sha256=DOC_HASH,
        manifest_sha256=POLICY_HASH,
        manifest_path="qa/archive-manifest.jsonl",
        total_entries=100,
    )

    assert run.status == "planned"
    assert run.cursor == 0
    assert run.import_limit == 40
    assert run.batch_size == 10
    assert run.stats_json == {}
