import hashlib
import json
from pathlib import Path

import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands.extract_archive_relation_candidates_qa import (
    CHECKPOINT_NAME,
    _candidate_rows,
    _checkpoint_path,
    _record_batch,
    _universe_fingerprint,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento

pytestmark = pytest.mark.django_db


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _archive_document(key, *, metadata=None):
    return DocumentoNormativo.objects.create(
        document_key=_digest(key),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref=f"archive:{key}",
        archive_sha256=_digest(f"archive:{key}"),
        entry_index=1,
        entry_name=f"{key}.pdf",
        original_filename=f"{key}.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key=f"{key}.pdf",
        content_sha256=_digest(f"pdf:{key}"),
        size_bytes=128,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json=metadata or {},
    )


def _extraction(document, *, version, status=ExtracaoDocumento.Status.COMPLETE):
    return ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version=version,
        policy_fingerprint=_digest(f"policy:{version}"),
        text_version="legal-text-v1",
        legal_text="Art. 1º Texto de teste de arquivo público.",
        status=status,
        extraction_sha256="",
    )


def test_batch_universe_uses_latest_complete_non_synthetic_archive_extraction():
    authentic = _archive_document("authentic")
    _extraction(authentic, version="authentic-v1")

    latest_partial = _archive_document("latest-partial")
    _extraction(latest_partial, version="old-complete")
    _extraction(latest_partial, version="new-partial", status=ExtracaoDocumento.Status.PARTIAL)

    synthetic = _archive_document(
        "synthetic",
        metadata={"identity_candidate": {"synthetic_fixture": True}},
    )
    _extraction(synthetic, version="synthetic-v1")

    rows = _candidate_rows()

    assert [row[0] for row in rows] == [str(authentic.public_id)]
    assert rows[0][1] == authentic.extracoes.get().pk
    assert rows[0][2] == authentic.extracoes.get().extraction_sha256
    assert _universe_fingerprint(rows) == _universe_fingerprint(list(rows))


def test_universe_fingerprint_changes_with_extraction_revision():
    original = [("public-id", 10, "a" * 64)]
    revised = [("public-id", 11, "b" * 64)]

    assert _universe_fingerprint(original) != _universe_fingerprint(revised)


def test_changed_universe_gets_new_checkpoint_without_overwriting_completed_legacy(tmp_path):
    legacy_path = tmp_path / CHECKPOINT_NAME
    legacy_payload = {
        "schema": 1,
        "universe_sha256": "a" * 64,
        "universe_count": 10,
        "cursor": 10,
        "processed": 10,
        "status": "completed",
    }
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    with override_settings(QA_ROOT=Path(tmp_path)):
        new_path = _checkpoint_path("b" * 64)
        same_universe_path = _checkpoint_path("a" * 64)

    assert new_path == tmp_path / f"archive-relation-candidates-{'b' * 64}-checkpoint.json"
    assert same_universe_path == legacy_path
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == legacy_payload


def test_checkpoint_advances_exactly_once_and_marks_the_final_short_slice_complete():
    checkpoint = {
        "processed": 20,
        "cursor": 20,
        "candidates_found": 4,
        "candidates_created": 3,
        "status": "pending",
    }

    next_cursor = _record_batch(
        checkpoint,
        cursor=20,
        batch_size=2,
        found=1,
        created=1,
        universe_count=22,
    )

    assert next_cursor == 22
    assert checkpoint == {
        "processed": 22,
        "cursor": 22,
        "candidates_found": 5,
        "candidates_created": 4,
        "status": "completed",
    }
