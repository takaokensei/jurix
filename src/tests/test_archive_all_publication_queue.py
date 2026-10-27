import hashlib
import json
from io import StringIO

import fitz
import pytest
from django.core.management import call_command

from src.apps.ingestion.management.commands import extract_archive_candidates_batch_qa as command
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento


@pytest.mark.django_db
def test_all_publication_queue_is_separate_resumable_and_never_links_or_accepts(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root, raising=False)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True, raising=False)

    documents = []
    for index, filename in enumerate(
        ("Lei_10_2026.pdf", "Lei_11_2025.pdf", "scan_legislacao.pdf"),
        start=1,
    ):
        pdf = fitz.open()
        pdf.new_page().insert_text((72, 72), f"Candidate QA PDF {index}")
        content = pdf.tobytes()
        pdf.close()
        storage_key = f"{index}.pdf"
        (archive_root / storage_key).write_bytes(content)
        documents.append(
            DocumentoNormativo.objects.create(
                norma=None,
                document_key=hashlib.sha256(f"all-priority-{index}".encode()).hexdigest(),
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                source_ref=f"archive:all-priority:{index}",
                original_filename=filename,
                storage_key=storage_key,
                content_sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
            )
        )

    crosswalk = {
        "schema_version": 1,
        "complete": True,
        "total_entries": 1,
        "type_labels": {"1": "Lei Ordinária"},
        "records": [
            {"id": 81, "tipo": 1, "numero": "10", "ano": 2026, "data_publicacao": "2026-02-03"}
        ],
    }
    (qa_root / "sapl-archive-crosswalk-cursor.json").write_text(
        json.dumps(crosswalk), encoding="utf-8"
    )

    already_extracted = "already-extracted, still pending review"
    ExtracaoDocumento.objects.create(
        documento=documents[0],
        extractor_version="pymupdf-qa-existing",
        policy_fingerprint=command._current_extraction_policy_fingerprint(),
        text_version="technical_text_v1",
        raw_text=already_extracted,
        legal_text=already_extracted,
        raw_text_sha256=hashlib.sha256(already_extracted.encode()).hexdigest(),
        legal_text_sha256=hashlib.sha256(already_extracted.encode()).hexdigest(),
        page_count=1,
        page_map_json=[],
        metadata_candidates_json={},
        quality_json={"pipeline_candidate_only": True, "needs_review": True},
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256=hashlib.sha256(already_extracted.encode()).hexdigest(),
    )

    legacy_checkpoints = {
        command.CHECKPOINT_NAME: '{"legacy":"public_id"}',
        command.SAPL_DATE_CHECKPOINT_NAME: '{"legacy":"strict-crosswalk"}',
        command.LEGACY_PRIORITY_QUEUE_CHECKPOINT_NAME: '{"legacy":"priority-v1"}',
        command.PRIORITY_QUEUE_CHECKPOINT_NAME: '{"legacy":"stale-universe"}',
    }
    for name, payload in legacy_checkpoints.items():
        (qa_root / name).write_text(payload, encoding="utf-8")

    dry_output = StringIO()
    call_command(
        "extract_archive_candidates_batch_qa",
        dry_run=True,
        all_publication_order=True,
        batch_size=1,
        stdout=dry_output,
    )
    dry = json.loads(dry_output.getvalue())
    assert dry["universe_candidates"] == 3
    assert dry["queue_candidates"] == 3
    assert dry["ordering_summary"] == {
        "catalog_scan_complete": True,
        "universe_candidates": 3,
        "queue_candidates": 3,
        "extraction_candidates": 2,
        "already_currently_extracted_candidates": 1,
        "strict_sapl_date_priority_candidates": 1,
        "strict_sapl_year_number_fallback_candidates": 0,
        "filename_year_number_priority_candidates": 1,
        "unresolved_stable_id_candidates": 1,
        "identity_linkage_created": False,
        "dates_and_filename_keys_are_reviewed_legal_facts": False,
    }
    assert dry["batch_priority_preview"][0]["public_id"] == str(documents[1].public_id)
    assert dry["batch_priority_preview"][0]["ordering_candidate"].startswith(
        "filename_year_number_fallback||2025|11"
    )
    assert dry["checkpoint_written"] is False
    assert (qa_root / command.PRIORITY_QUEUE_CHECKPOINT_NAME).read_text(encoding="utf-8") == '{"legacy":"stale-universe"}'
    assert all((qa_root / name).read_text(encoding="utf-8") == payload for name, payload in legacy_checkpoints.items())
    assert documents[0].extracoes.count() == 1
    assert all(not document.extracoes.exists() for document in documents[1:])

    def create_candidate(document, **_kwargs):
        return ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version="pymupdf-qa-test",
            policy_fingerprint=command._current_extraction_policy_fingerprint(),
            text_version="technical_text_v1",
            raw_text="unreviewed candidate text",
            legal_text="unreviewed candidate text",
            raw_text_sha256=hashlib.sha256(b"unreviewed candidate text").hexdigest(),
            legal_text_sha256=hashlib.sha256(b"unreviewed candidate text").hexdigest(),
            page_count=1,
            page_map_json=[],
            metadata_candidates_json={},
            quality_json={"pipeline_candidate_only": True, "needs_review": True},
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"unreviewed candidate text").hexdigest(),
        )

    monkeypatch.setattr(command, "_extract_archive_candidate", create_candidate)
    apply_output = StringIO()
    call_command(
        "extract_archive_candidates_batch_qa",
        apply=True,
        all_publication_order=True,
        new_snapshot=True,
        batch_size=1,
        stdout=apply_output,
    )
    applied = json.loads(apply_output.getvalue())
    assert applied["cursor"] == 1
    assert applied["checkpoint_file"].startswith(command.PRIORITY_SNAPSHOT_CHECKPOINT_PREFIX)
    assert (qa_root / applied["checkpoint_file"]).is_file()
    assert applied["ordering"].startswith("SAPL-date-candidate;")
    assert applied["review_accepted"] is False
    assert applied["norma_linkage_created"] is False
    assert applied["batch_summary"]["latest_extraction_statuses"] == {"complete": 1}
    assert all((qa_root / name).read_text(encoding="utf-8") == payload for name, payload in legacy_checkpoints.items())

    resume_output = StringIO()
    call_command(
        "extract_archive_candidates_batch_qa",
        dry_run=True,
        resume=True,
        all_publication_order=True,
        new_snapshot=True,
        batch_size=1,
        stdout=resume_output,
    )
    resumed = json.loads(resume_output.getvalue())
    assert resumed["cursor"] == 1
    assert resumed["batch_priority_preview"][0]["public_id"] == str(documents[2].public_id)
    documents[0].refresh_from_db()
    assert documents[0].review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert documents[0].norma_id is None
    assert documents[0].accepted_extraction_id is None
    assert documents[0].extracoes.count() == 1
    assert documents[1].extracoes.count() == 1

    create_candidate(documents[2])

    def unexpected_pdf_read(*_args, **_kwargs):
        raise AssertionError("current-policy skips must not reopen archived PDFs")

    monkeypatch.setattr(command, "_verified_pdf", unexpected_pdf_read)
    completed_output = StringIO()
    call_command(
        "extract_archive_candidates_batch_qa",
        apply=True,
        resume=True,
        all_publication_order=True,
        new_snapshot=True,
        batch_size=1,
        stdout=completed_output,
    )
    completed = json.loads(completed_output.getvalue())
    assert completed["status"] == "completed"
    assert completed["checkpoint_file"] == applied["checkpoint_file"]
    assert completed["fast_forwarded_existing"] == 2
    assert completed["cursor"] == 3
    assert completed["candidate_extractions_created_total"] == 1
    assert completed["skipped_existing_total"] == 2
    assert completed["review_accepted"] is False
    assert completed["norma_linkage_created"] is False
    assert all(document.extracoes.count() == 1 for document in documents)
    assert all(
        (qa_root / name).read_text(encoding="utf-8") == payload
        for name, payload in legacy_checkpoints.items()
    )
