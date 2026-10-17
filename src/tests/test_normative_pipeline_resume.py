"""Regression coverage for resumable QA-only normative pipeline stages."""

import hashlib
import json
from io import StringIO
from types import SimpleNamespace

import fitz
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from src.apps.ingestion import normative_tasks
from src.apps.ingestion.normative_impact import (
    claim_normative_work_item,
    enqueue_normative_work,
    fail_normative_stage,
    finish_normative_stage,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Dispositivo, Norma
from src.apps.operations.models import NormativeWorkItem

pytestmark = pytest.mark.django_db(transaction=True)


def _approved_norma(number="9911"):
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    norma = Norma.objects.create(tipo="Lei", numero=number, ano=2091, texto_original="Art. 1º QA")
    document = DocumentoNormativo.objects.create(
        norma=norma,
        document_key=digest(f"document-{number}"),
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref=f"synthetic-qa:{number}",
        content_sha256=digest(f"pdf-{number}"),
        role=DocumentoNormativo.Role.ORIGINAL,
        condition_of_use=DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
        review_status=DocumentoNormativo.ReviewStatus.APPROVED,
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="synthetic-test-v1",
        policy_fingerprint=digest(f"policy-{number}"),
        text_version="test-v1",
        raw_text="Art. 1º QA",
        legal_text="Art. 1º QA",
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256=digest(f"extraction-{number}"),
    )
    document.accepted_extraction = extraction
    document.save(update_fields=["accepted_extraction", "updated_at"])
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    return norma, document, extraction


def _work_item(norma, stage):
    from src.apps.ingestion.normative_impact import safe_norma_revision

    item, _ = enqueue_normative_work(
        source_kind="norma",
        source_id=norma.pk,
        source_revision=safe_norma_revision(norma),
        stage=stage,
    )
    item.stage = stage
    item.save(update_fields=["stage"])
    return item


def test_reusable_ocr_page_helper_verifies_quote_hash_and_preserves_root_origin():
    text = "Art. 1º Texto OCR reconhecido."
    parent_hash = hashlib.sha256(b"parent-extraction").hexdigest()
    start = len("--- Página 1 ---\n")
    extraction = ExtracaoDocumento(
        legal_text=f"--- Página 1 ---\n{text}",
        extraction_sha256=hashlib.sha256(b"child-extraction").hexdigest(),
        page_map_json=[
            {
                "page": 1,
                "start": start,
                "end": start + len(text),
                "method": "ocr",
                "quote_hash": hashlib.sha256(text.encode()).hexdigest(),
                "reused_from_extraction_sha256": parent_hash,
            },
            {
                "page": 2,
                "start": start,
                "end": start + len(text),
                "method": "ocr",
                "quote_hash": "0" * 64,
            },
        ],
    )

    assert normative_tasks._reusable_ocr_pages(extraction) == {1: (text, parent_hash)}


def test_embedding_stage_indexes_all_39_devices_in_batches_of_ten(monkeypatch):
    norma, _document, _extraction = _approved_norma()
    for order in range(39):
        Dispositivo.objects.create(
            norma=norma,
            tipo="artigo",
            numero=str(order + 1),
            texto=f"Texto legal de teste {order + 1}",
            ordem=order,
            revision_fingerprint=f"{order + 1:064x}",
        )
    item = _work_item(norma, NormativeWorkItem.Stage.EMBEDDING)

    class HealthyOllama:
        def __init__(self, model):
            assert model == "nomic-embed-text"

        def check_health(self):
            return True

    monkeypatch.setattr("src.llm_engine.ollama_service.OllamaService", HealthyOllama)
    generated_ids = []

    def embed(_task, device_id):
        device = Dispositivo.objects.get(pk=device_id)
        Dispositivo.objects.filter(pk=device_id).update(
            embedding=[0.0] * 768,
            embedding_model="nomic-embed-text",
            embedding_revision_fingerprint=device.revision_fingerprint,
        )
        generated_ids.append(device_id)
        return {"success": True, "stale_input": False}

    monkeypatch.setattr(normative_tasks, "_run_inline_task", embed)
    outputs = []
    crashed_once = False
    while True:
        item, token = claim_normative_work_item(item.pk)
        result = normative_tasks._execute_normative_stage(item, norma)
        if not crashed_once:
            # Simulate loss after successful external/model work but before saving
            # the batch cursor. The next attempt must reuse current vectors.
            item = fail_normative_stage(item.pk, token, "simulated worker loss")
            crashed_once = True
            continue
        outputs.append(result)
        item = finish_normative_stage(item.pk, token, result=result)
        if not result.get("continue_stage"):
            break

    assert [len(result["results"]) for result in outputs] == [10, 10, 10, 9]
    assert all(row["reused_current"] for row in outputs[0]["results"])
    assert len(generated_ids) == len(set(generated_ids)) == 39
    assert item.stage == NormativeWorkItem.Stage.EMBEDDING
    assert item.status == NormativeWorkItem.Status.COMPLETED
    final = item.result["stage_results"][NormativeWorkItem.Stage.EMBEDDING]
    assert final["embedding_status"] == "complete"
    assert final["count"] == final["expected_count"] == 39
    assert (
        Dispositivo.objects.filter(
            norma=norma,
            embedding_model="nomic-embed-text",
            embedding_revision_fingerprint=__import__("django.db.models", fromlist=["F"]).F(
                "revision_fingerprint"
            ),
        ).count()
        == 39
    )


def test_embedding_outage_never_completes_and_retry_remains_bounded(monkeypatch):
    norma, _document, _extraction = _approved_norma("9912")
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1",
        texto="Texto legal QA",
        ordem=0,
        revision_fingerprint="a" * 64,
    )
    item = _work_item(norma, NormativeWorkItem.Stage.EMBEDDING)

    class OfflineOllama:
        def __init__(self, model):
            pass

        def check_health(self):
            return False

    monkeypatch.setattr("src.llm_engine.ollama_service.OllamaService", OfflineOllama)
    for attempt in range(3):
        item, token = claim_normative_work_item(item.pk)
        with pytest.raises(RuntimeError, match="Ollama indisponível"):
            normative_tasks._execute_normative_stage(item, norma)
        item = fail_normative_stage(item.pk, token, "Ollama indisponível")
        assert item.status == (
            NormativeWorkItem.Status.PENDING if attempt < 2 else NormativeWorkItem.Status.FAILED
        )
    assert item.stage == NormativeWorkItem.Stage.EMBEDDING
    assert item.status != NormativeWorkItem.Status.COMPLETED
    assert not item.result.get("stage_results", {}).get(NormativeWorkItem.Stage.EMBEDDING)


def test_reconciliation_cursor_is_persisted_between_batches(monkeypatch):
    norma, _document, _extraction = _approved_norma("9913")
    item = _work_item(norma, NormativeWorkItem.Stage.RECONCILE)
    calls = []

    def reconcile(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "inspected": 10,
                "resolved": 4,
                "remaining_unresolved": 6,
                "next_cursor": 25,
                "has_more": True,
            }
        return {
            "inspected": 3,
            "resolved": 2,
            "remaining_unresolved": 1,
            "next_cursor": 41,
            "has_more": False,
        }

    monkeypatch.setattr(normative_tasks, "reconcile_unresolved_event_targets", reconcile)
    item, token = claim_normative_work_item(item.pk)
    first = normative_tasks._execute_normative_stage(item, norma)
    item = finish_normative_stage(item.pk, token, result=first)
    assert item.stage == NormativeWorkItem.Stage.RECONCILE
    assert item.status == NormativeWorkItem.Status.PENDING
    assert item.result["stage_progress"][NormativeWorkItem.Stage.RECONCILE]["cursor"] == 25

    item, token = claim_normative_work_item(item.pk)
    second = normative_tasks._execute_normative_stage(item, norma)
    item = finish_normative_stage(item.pk, token, result=second)
    assert calls[1]["after_event_id"] == 25
    assert calls[1]["max_event_id"] == calls[0]["max_event_id"]
    assert item.stage == NormativeWorkItem.Stage.SNAPSHOT
    assert item.result["stage_results"][NormativeWorkItem.Stage.RECONCILE]["inspected"] == 13


def test_incomplete_snapshot_stays_awaiting_review(monkeypatch):
    norma, _document, _extraction = _approved_norma("9914")
    item = _work_item(norma, NormativeWorkItem.Stage.SNAPSHOT)
    monkeypatch.setattr(
        normative_tasks,
        "project_norma_as_of",
        lambda *_args: SimpleNamespace(
            status="not_reconstructable", coverage={"reason": "review_pending"}
        ),
    )
    item, token = claim_normative_work_item(item.pk)
    result = normative_tasks._execute_normative_stage(item, norma)
    assert result["awaiting_review"] is True
    assert result["snapshot_persisted"] is False

    from src.apps.ingestion.normative_impact import defer_normative_stage_for_review

    item = defer_normative_stage_for_review(
        item.pk, token, reason=result["review_reason"], result={"required_action": "human_review"}
    )
    assert item.stage == NormativeWorkItem.Stage.SNAPSHOT
    assert item.status == NormativeWorkItem.Status.AWAITING_REVIEW


def test_extraction_creates_only_candidate_for_hash_verified_qa_pdf(
    monkeypatch, tmp_path, settings
):
    norma = Norma.objects.create(tipo="Lei", numero="9915", ano=2091, texto_original="Art. 1º QA")
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    pdf_path = archive_root / "sha256" / "sample.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"synthetic QA PDF bytes")
    document = DocumentoNormativo.objects.create(
        norma=norma,
        document_key=hashlib.sha256(b"archive-document-9915").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:synthetic-qa:entry:1",
        storage_key="sha256/sample.pdf",
        content_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        role=DocumentoNormativo.Role.ORIGINAL,
        condition_of_use=DocumentoNormativo.ConditionOfUse.UNKNOWN,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    norma.documento_base = document
    norma.save(update_fields=["documento_base", "updated_at"])
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)

    digest = hashlib.sha256(b"candidate text").hexdigest()
    tesseract_configured = {"value": False}

    def configure_tesseract():
        tesseract_configured["value"] = True

    def extract_pdf(*_args, **_kwargs):
        assert tesseract_configured["value"] is True
        return {
            "policy_fingerprint": "b" * 64,
            "extractor_version": "test-extractor-v1",
            "text_version": "technical_text_v1",
            "raw_text": "candidate text",
            "legal_text": "candidate text",
            "page_count": 1,
            "source_map": [],
            "metadata_candidates": {},
            "quality": {"page_methods": {"native": 1}},
            "complete": True,
            "needs_review": False,
            "extraction_sha256": digest,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(normative_tasks, "_configure_tesseract", configure_tesseract)
    monkeypatch.setattr(
        normative_tasks,
        "extract_pdf_document",
        extract_pdf,
    )
    item = _work_item(norma, NormativeWorkItem.Stage.EXTRACTION)
    result = normative_tasks._execute_normative_stage(item, norma)
    document.refresh_from_db()
    assert result["extraction_candidate_created"] is True
    assert result["legal_text_accepted"] is False
    assert result["text_mutated"] is False
    assert document.accepted_extraction_id is None
    assert document.extracoes.filter(legal_text="candidate text").exists()


@pytest.mark.parametrize(
    "settings_module",
    ["config.settings_normative_qa", "config.settings_normative_container_qa"],
)
def test_single_archive_extraction_command_stops_at_human_review(
    monkeypatch, tmp_path, settings, settings_module
):
    qa_root = tmp_path / "qa-root"
    pdf_path = qa_root / "normative-archive" / "sha256" / "lc258.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"synthetic single-document QA PDF")
    document = DocumentoNormativo.objects.create(
        norma=None,
        document_key=hashlib.sha256(b"lc258-document").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:synthetic-qa:lc258",
        storage_key="sha256/lc258.pdf",
        content_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        role=DocumentoNormativo.Role.ORIGINAL,
        condition_of_use=DocumentoNormativo.ConditionOfUse.UNKNOWN,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", settings_module)
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)
    extraction_hash = hashlib.sha256(b"candidate legal text").hexdigest()
    reused_text = "previous OCR page"
    previous_extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="previous-ocr-v1",
        policy_fingerprint=hashlib.sha256(b"previous-ocr-policy").hexdigest(),
        text_version="technical_text_v1",
        raw_text=reused_text,
        legal_text=reused_text,
        page_count=1,
        page_map_json=[{
            "text_version": "technical_text_v1",
            "start": 0,
            "end": len(reused_text),
            "page": 1,
            "method": "ocr",
            "status": "complete",
            "quote_hash": hashlib.sha256(reused_text.encode()).hexdigest(),
        }],
        quality_json={"ocr_pages_attempted": [1]},
        status=ExtracaoDocumento.Status.PARTIAL,
        extraction_sha256=hashlib.sha256(b"previous-ocr-extraction").hexdigest(),
    )
    received = {}

    def extract_pdf(*_args, **kwargs):
        received.update(kwargs)
        return {
            "policy_fingerprint": "c" * 64,
            "extractor_version": "test-extractor-v1",
            "text_version": "technical_text_v1",
            "raw_text": "candidate legal text",
            "legal_text": "candidate legal text",
            "page_count": 1,
            "source_map": [],
            "metadata_candidates": {},
            "quality": {
                "page_methods": {"native": 1},
                "ocr_pages_attempted": [],
                "ocr_pages_reused": [1],
                "ocr_budget_skipped_pages": [],
            },
            "complete": True,
            "needs_review": True,
            "extraction_sha256": extraction_hash,
            "duration_seconds": 0.01,
        }

    monkeypatch.setattr(
        normative_tasks,
        "extract_pdf_document",
        extract_pdf,
    )

    output = StringIO()
    call_command("extract_archive_candidate_qa", document_id=str(document.public_id), stdout=output)

    report = json.loads(output.getvalue())
    document.refresh_from_db()
    assert report["candidate_created"] is True
    assert report["ocr_pages_reused"] == 1
    assert received["reusable_ocr_pages"] == {
        1: (reused_text, previous_extraction.extraction_sha256)
    }
    assert report["text_accepted"] is False
    assert report["document_review_status"] == DocumentoNormativo.ReviewStatus.PENDING
    assert report["norma_linked"] is False
    assert report["queued"] is False
    assert document.accepted_extraction_id is None
    assert document.extracoes.filter(legal_text="candidate legal text").exists()


@pytest.mark.django_db
def test_archive_batch_extraction_dry_run_and_resume_never_accept_or_link_documents(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)
    documents = []
    for index in range(2):
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), f"QA archive candidate {index}")
        content = pdf.tobytes()
        pdf.close()
        path = qa_root / "normative-archive" / f"{index}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        documents.append(
            DocumentoNormativo.objects.create(
                norma=None,
                document_key=hashlib.sha256(f"archive-batch-{index}".encode()).hexdigest(),
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                source_ref=f"archive:qa:{index}",
                storage_key=f"{index}.pdf",
                content_sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
            )
        )

    from src.apps.ingestion.management.commands import extract_archive_candidates_batch_qa

    def extract(document, **_kwargs):
        return ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version="qa-test-v1",
            policy_fingerprint=hashlib.sha256(b"policy").hexdigest(),
            text_version="technical_text_v1",
            raw_text="candidate only",
            legal_text="candidate only",
            page_count=1,
            page_map_json=[],
            metadata_candidates_json={},
            quality_json={"needs_review": True},
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"candidate only").hexdigest(),
        )

    monkeypatch.setattr(extract_archive_candidates_batch_qa, "_extract_archive_candidate", extract)
    output = StringIO()
    call_command("extract_archive_candidates_batch_qa", dry_run=True, batch_size=1, stdout=output)
    assert json.loads(output.getvalue())["checkpoint_written"] is False
    assert not (qa_root / extract_archive_candidates_batch_qa.CHECKPOINT_NAME).exists()
    assert all(not document.extracoes.exists() for document in documents)

    output = StringIO()
    call_command("extract_archive_candidates_batch_qa", apply=True, batch_size=1, stdout=output)
    first = json.loads(output.getvalue())
    assert first["cursor"] == 1
    assert first["review_accepted"] is False
    assert first["norma_linkage_created"] is False

    output = StringIO()
    call_command("extract_archive_candidates_batch_qa", apply=True, resume=True, batch_size=1, stdout=output)
    second = json.loads(output.getvalue())
    assert second["status"] == "completed"
    assert second["cursor"] == 2
    for document in documents:
        document.refresh_from_db()
        assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
        assert document.norma_id is None
        assert document.accepted_extraction_id is None
        assert document.extracoes.count() == 1

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "QA candidate added after checkpoint")
    additional_content = pdf.tobytes()
    pdf.close()
    additional_path = qa_root / "normative-archive" / "new.pdf"
    additional_path.write_bytes(additional_content)
    DocumentoNormativo.objects.create(
        norma=None,
        document_key=hashlib.sha256(b"archive-batch-added-later").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa:new-candidate",
        storage_key="new.pdf",
        content_sha256=hashlib.sha256(additional_content).hexdigest(),
        size_bytes=len(additional_content),
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    with pytest.raises(CommandError, match="Universo de candidatos mudou"):
        call_command("extract_archive_candidates_batch_qa", apply=True, resume=True, batch_size=1)


@pytest.mark.django_db
def test_archive_ocr_resume_is_one_document_bounded_and_never_accepts_candidate(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "QA page one")
    pdf.new_page().insert_text((72, 72), "QA page two")
    content = pdf.tobytes()
    pdf.close()
    (archive_root / "resume.pdf").write_bytes(content)
    document = DocumentoNormativo.objects.create(
        norma=None,
        document_key=hashlib.sha256(b"resume-ocr-document").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa:resume-ocr",
        storage_key="resume.pdf",
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    previous = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-test-v1",
        policy_fingerprint=hashlib.sha256(b"previous-policy").hexdigest(),
        text_version="technical_text_v1",
        raw_text="Page one OCR\fPage two native",
        legal_text="Prior candidate text",
        page_count=2,
        quality_json={"ocr_budget_skipped_pages": [2]},
        status=ExtracaoDocumento.Status.PARTIAL,
        extraction_sha256=hashlib.sha256(b"previous-extraction").hexdigest(),
    )
    calls = []

    def extract(candidate_document, **kwargs):
        calls.append((candidate_document.pk, kwargs))
        return ExtracaoDocumento.objects.create(
            documento=candidate_document,
            extractor_version="qa-test-v2",
            policy_fingerprint=hashlib.sha256(b"resumed-policy").hexdigest(),
            text_version="technical_text_v1",
            raw_text="Rebuilt pages",
            legal_text="Rebuilt pages",
            page_count=2,
            quality_json={
                "ocr_pages_attempted": [2],
                "ocr_pages_reused": [1],
                "ocr_budget_skipped_pages": [],
            },
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"resumed-extraction").hexdigest(),
        )

    from src.apps.ingestion.management.commands import resume_archive_ocr_qa

    monkeypatch.setattr(resume_archive_ocr_qa, "_extract_archive_candidate", extract)
    with pytest.raises(CommandError, match="só pode selecionar páginas do backlog"):
        call_command(
            "resume_archive_ocr_qa",
            document_id=str(document.public_id),
            pages=[1],
            batch_pages=1,
            dry_run=True,
            stdout=StringIO(),
        )
    assert calls == []
    assert document.extracoes.count() == 1

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        dry_run=True,
        stdout=output,
    )
    report = json.loads(output.getvalue())
    assert report["selected_pages"] == [2]
    assert report["will_accept_or_promote"] is False
    assert calls == []
    assert document.extracoes.count() == 1

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        apply=True,
        stdout=output,
    )
    report = json.loads(output.getvalue())
    assert report["ocr_pages_attempted"] == 1
    assert report["ocr_pages_reused"] == 1
    assert report["accepted_extraction"] is False
    assert report["norma_linkage_created"] is False
    assert calls[0][1]["ocr_pages_to_process"] == {2}
    assert calls[0][1]["reuse_from"].pk == previous.pk
    document.refresh_from_db()
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    assert document.norma_id is None
    assert document.extracoes.count() == 2

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        batch_pages=1,
        dry_run=True,
        stdout=output,
    )
    noop = json.loads(output.getvalue())
    assert noop["mode"] == "noop"
    assert noop["reason"] == "latest_extraction_complete"
    assert noop["accepted_extraction"] is False
    assert document.extracoes.count() == 2


@pytest.mark.django_db
def test_archive_ocr_resume_can_retry_unreadable_pages_without_acceptance(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root, raising=False)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True, raising=False)

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "QA página um")
    pdf.new_page().insert_text((72, 72), "QA página dois")
    content = pdf.tobytes()
    pdf.close()
    (archive_root / "unreadable.pdf").write_bytes(content)
    document = DocumentoNormativo.objects.create(
        norma=None,
        document_key=hashlib.sha256(b"unreadable-ocr-document").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa:unreadable-ocr",
        storage_key="unreadable.pdf",
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    previous = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-test-v1",
        policy_fingerprint=hashlib.sha256(b"unreadable-policy").hexdigest(),
        text_version="technical_text_v1",
        raw_text="QA página um\f",
        legal_text="QA página um",
        page_count=2,
        quality_json={"unreadable_pages": [2], "ocr_pages_attempted": [2]},
        status=ExtracaoDocumento.Status.PARTIAL,
        extraction_sha256=hashlib.sha256(b"unreadable-extraction").hexdigest(),
    )
    calls = []

    def extract(candidate_document, **kwargs):
        calls.append((candidate_document.pk, kwargs))
        return ExtracaoDocumento.objects.create(
            documento=candidate_document,
            extractor_version="qa-test-v2",
            policy_fingerprint=hashlib.sha256(b"unreadable-retry-policy").hexdigest(),
            text_version="technical_text_v1",
            raw_text="QA página um\fOCR recuperado",
            legal_text="QA página um\nOCR recuperado",
            page_count=2,
            quality_json={
                "ocr_pages_attempted": [2],
                "ocr_pages_reused": [1],
                "unreadable_pages": [],
                "ocr_budget_skipped_pages": [],
            },
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"recovered-extraction").hexdigest(),
        )

    from src.apps.ingestion.management.commands import resume_archive_ocr_qa

    monkeypatch.setattr(resume_archive_ocr_qa, "_extract_archive_candidate", extract)
    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        pick_unreadable=True,
        batch_pages=1,
        dry_run=True,
        stdout=output,
    )
    picked = json.loads(output.getvalue())
    assert picked["selection"] == "smallest_unreadable_backlog"
    assert picked["retry_kind"] == "unreadable"
    assert picked["document_id"] == str(document.public_id)
    assert picked["selected_pages"] == [2]
    assert picked["will_accept_or_promote"] is False
    assert calls == []

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        retry_unreadable=True,
        dry_run=True,
        stdout=output,
    )
    dry_run = json.loads(output.getvalue())
    assert dry_run["retry_kind"] == "unreadable"
    assert dry_run["selected_pages"] == [2]
    assert dry_run["will_accept_or_promote"] is False
    assert calls == []
    assert document.extracoes.count() == 1

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        retry_unreadable=True,
        apply=True,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["retry_kind"] == "unreadable"
    assert result["extraction_status"] == ExtracaoDocumento.Status.COMPLETE
    assert result["remaining_unreadable_pages"] == 0
    assert result["accepted_extraction"] is False
    assert result["norma_linkage_created"] is False
    assert calls[0][1]["ocr_pages_to_process"] == {2}
    assert calls[0][1]["reuse_from"].pk == previous.pk
    document.refresh_from_db()
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    assert document.norma_id is None
    assert document.extracoes.count() == 2


@pytest.mark.django_db
def test_sapl_normative_candidate_can_resume_selected_ocr_pages_without_acceptance(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "LC 258 artigo recuperável")
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    (archive_root / "lc-258-2024.pdf").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="258",
        ano=2024,
        sapl_id=4052,
        status=Norma.Status.PENDING,
    )
    document = DocumentoNormativo.objects.create(
        norma=norma,
        document_key=hashlib.sha256(b"sapl-lc258-resume").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="https://sapl.natal.rn.leg.br/norma/4052",
        storage_key="lc-258-2024.pdf",
        content_sha256=digest,
        size_bytes=len(content),
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    previous = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-sapl-v1",
        policy_fingerprint=hashlib.sha256(b"sapl-lc258-policy-old").hexdigest(),
        text_version="technical_text_v1",
        raw_text="LC 258 artigo recuperável\f",
        legal_text="LC 258 artigo recuperável",
        page_count=2,
        quality_json={"ocr_budget_skipped_pages": [2]},
        status=ExtracaoDocumento.Status.PARTIAL,
        extraction_sha256=hashlib.sha256(b"sapl-lc258-extraction-old").hexdigest(),
    )
    calls = []

    def extract(candidate_document, **kwargs):
        calls.append((candidate_document.pk, kwargs))
        return ExtracaoDocumento.objects.create(
            documento=candidate_document,
            extractor_version="qa-sapl-v2",
            policy_fingerprint=hashlib.sha256(b"sapl-lc258-policy-new").hexdigest(),
            text_version="technical_text_v1",
            raw_text="LC 258 artigo recuperável\fOCR candidato",
            legal_text="LC 258 artigo recuperável\nOCR candidato",
            page_count=2,
            quality_json={
                "ocr_pages_attempted": [2],
                "ocr_pages_reused": [1],
                "ocr_budget_skipped_pages": [],
                "unreadable_pages": [],
            },
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"sapl-lc258-extraction-new").hexdigest(),
        )

    from src.apps.ingestion.management.commands import resume_archive_ocr_qa

    monkeypatch.setattr(resume_archive_ocr_qa, "_extract_archive_candidate", extract)
    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        dry_run=True,
        stdout=output,
    )
    dry_run = json.loads(output.getvalue())
    assert dry_run["selected_pages"] == [2]
    assert dry_run["will_accept_or_promote"] is False
    assert calls == []
    assert document.extracoes.count() == 1

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        pages=[2],
        batch_pages=1,
        apply=True,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["ocr_pages_attempted"] == 1
    assert result["ocr_pages_reused"] == 1
    assert result["accepted_extraction"] is False
    assert result["norma_linkage_created"] is False
    assert calls[0][1]["ocr_pages_to_process"] == {2}
    assert calls[0][1]["reuse_from"].pk == previous.pk
    document.refresh_from_db()
    norma.refresh_from_db()
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    assert norma.status == Norma.Status.PENDING
    assert norma.documento_base_id is None
    assert not norma.texto_original
    assert not norma.texto_consolidado

    norma.status = Norma.Status.CONSOLIDATED
    norma.save(update_fields=["status", "updated_at"])
    with pytest.raises(CommandError, match="Norma vinculada, pendente e vazia"):
        call_command(
            "resume_archive_ocr_qa",
            document_id=str(document.public_id),
            pages=[2],
            batch_pages=1,
            dry_run=True,
            stdout=StringIO(),
        )


def test_archive_ocr_dry_run_skips_missing_blob_and_picks_next_verified_candidate(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "PDF íntegro de QA")
    pdf.new_page().insert_text((72, 72), "Segunda página do PDF QA")
    content = pdf.tobytes()
    pdf.close()
    (archive_root / "available.pdf").write_bytes(content)

    def create_candidate(key, digest, unreadable_pages):
        document = DocumentoNormativo.objects.create(
            norma=None,
            document_key=hashlib.sha256(f"document-{key}".encode()).hexdigest(),
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"archive:qa:{key}",
            storage_key=key,
            content_sha256=digest,
            size_bytes=1,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )
        ExtracaoDocumento.objects.create(
            documento=document,
            extractor_version="qa-test-v1",
            policy_fingerprint=hashlib.sha256(f"policy-{key}".encode()).hexdigest(),
            text_version="technical_text_v1",
            raw_text="QA extraído parcialmente",
            legal_text="QA extraído parcialmente",
            page_count=max(unreadable_pages),
            quality_json={"unreadable_pages": unreadable_pages},
            status=ExtracaoDocumento.Status.PARTIAL,
            extraction_sha256=hashlib.sha256(f"extraction-{key}".encode()).hexdigest(),
        )
        return document

    missing = create_candidate("missing.pdf", hashlib.sha256(b"missing").hexdigest(), [1])
    available = create_candidate("available.pdf", hashlib.sha256(content).hexdigest(), [1, 2])

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        pick_unreadable=True,
        batch_pages=1,
        dry_run=True,
        stdout=output,
    )

    report = json.loads(output.getvalue())
    assert report["document_id"] == str(available.public_id)
    assert report["selection"] == "smallest_unreadable_backlog"
    assert report["skipped_unavailable_storage_count"] == 1
    assert report["selected_pages"] == [1]
    assert report["will_accept_or_promote"] is False
    assert missing.extracoes.count() == 1
    assert available.extracoes.count() == 1


@pytest.mark.django_db
def test_archive_ocr_resume_can_reclassify_only_visually_empty_pages_without_ocr(
    monkeypatch, tmp_path, settings
):
    qa_root = tmp_path / "qa-root"
    archive_root = qa_root / "normative-archive"
    archive_root.mkdir(parents=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    monkeypatch.setattr(settings, "QA_ROOT", qa_root)
    monkeypatch.setattr(settings, "NORMATIVE_ARCHIVE_ENABLED", True)

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Decreto QA com conteúdo normativo")
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    (archive_root / "blank-trailer.pdf").write_bytes(content)
    document = DocumentoNormativo.objects.create(
        norma=None,
        document_key=hashlib.sha256(b"blank-trailer-document").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa:blank-trailer",
        storage_key="blank-trailer.pdf",
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    previous = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-test-v1",
        policy_fingerprint=hashlib.sha256(b"blank-policy-old").hexdigest(),
        text_version="technical_text_v1",
        raw_text="Decreto QA com conteúdo normativo\f",
        legal_text="Decreto QA com conteúdo normativo",
        page_count=2,
        quality_json={"unreadable_pages": [2]},
        status=ExtracaoDocumento.Status.PARTIAL,
        extraction_sha256=hashlib.sha256(b"blank-extraction-old").hexdigest(),
    )
    calls = []

    def extract(candidate_document, **kwargs):
        calls.append((candidate_document.pk, kwargs))
        return ExtracaoDocumento.objects.create(
            documento=candidate_document,
            extractor_version="qa-test-v2",
            policy_fingerprint=hashlib.sha256(b"blank-policy-new").hexdigest(),
            text_version="technical_text_v1",
            raw_text="Decreto QA com conteúdo normativo\f",
            legal_text="Decreto QA com conteúdo normativo",
            page_count=2,
            quality_json={"blank_pages": [2], "unreadable_pages": []},
            status=ExtracaoDocumento.Status.COMPLETE,
            extraction_sha256=hashlib.sha256(b"blank-extraction-new").hexdigest(),
        )

    from src.apps.ingestion.management.commands import resume_archive_ocr_qa

    monkeypatch.setattr(resume_archive_ocr_qa, "_extract_archive_candidate", extract)
    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        pick_blank=True,
        dry_run=True,
        stdout=output,
    )
    picked_blank = json.loads(output.getvalue())
    assert picked_blank["retry_kind"] == "blank_reclassification"
    assert picked_blank["selection"] == "smallest_blank_page_candidate"
    assert picked_blank["document_id"] == str(document.public_id)
    assert picked_blank["selected_pages"] == []
    assert picked_blank["max_ocr_calls"] == 0
    assert calls == []

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        reclassify_blank=True,
        dry_run=True,
        stdout=output,
    )
    dry_run = json.loads(output.getvalue())
    assert dry_run["retry_kind"] == "blank_reclassification"
    assert dry_run["selected_pages"] == []
    assert dry_run["max_ocr_calls"] == 0
    assert calls == []

    output = StringIO()
    call_command(
        "resume_archive_ocr_qa",
        document_id=str(document.public_id),
        reclassify_blank=True,
        apply=True,
        stdout=output,
    )
    applied = json.loads(output.getvalue())
    assert applied["extraction_status"] == ExtracaoDocumento.Status.COMPLETE
    assert applied["blank_pages"] == [2]
    assert applied["accepted_extraction"] is False
    assert applied["norma_linkage_created"] is False
    assert calls[0][1]["max_ocr_pages"] == 0
    assert "ocr_pages_to_process" not in calls[0][1]
    assert calls[0][1]["reuse_from"].pk == previous.pk
