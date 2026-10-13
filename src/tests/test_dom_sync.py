from datetime import date

import pytest
from django.test import override_settings

from src.apps.ingestion.dom_sync import (
    DomNatalCandidateError,
    _require_dom_qa,
    inspect_dom_natal_editions,
    repair_dom_edition_blob_qa,
    stage_dom_edition_candidate,
    sync_dom_natal_editions,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.operations.models import SaplSyncState
from src.clients.dom_natal.client import DomNatalEdition, DomNatalPdf

pytestmark = pytest.mark.django_db


def _edition(*, number=5000, special=False, publication_date=date(2026, 10, 7)):
    kind = "special" if special else "regular"
    date_token = publication_date.strftime("%Y%m%d")
    date_label = publication_date.strftime("%d/%m/%Y")
    filename = f"dom_{date_token}{'_especial' if special else ''}_{'a' * 24}.pdf"
    return DomNatalEdition(
        identity=f"natal-dom:{publication_date.year}:{number}:{publication_date.isoformat()}:{kind}",
        year=publication_date.year,
        number=number,
        publication_date=publication_date,
        special=special,
        label=f"DOM nº {number} de {date_label}" + (" Especial" if special else ""),
        official_url=f"https://www2.natal.rn.gov.br/_anexos/publicacao/dom/{filename}",
    )


def _download(edition, content=b"%PDF-1.7\nQA fixture\n%%EOF"):
    from hashlib import sha256

    return DomNatalPdf(
        edition=edition,
        content=content,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def test_dom_edition_staging_is_idempotent_and_never_promotes(tmp_path, monkeypatch):
    qa_root = tmp_path / "jurix-qa"
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    edition = _edition()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first, created_first = stage_dom_edition_candidate(
            edition=edition, downloaded=_download(edition)
        )
        second, created_second = stage_dom_edition_candidate(
            edition=edition, downloaded=_download(edition)
        )

    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert first.norma_id is None
    assert first.source_kind == DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE
    assert first.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert first.extraction_status == DocumentoNormativo.ExtractionStatus.PENDING
    assert first.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
    assert first.metadata_json["edition_identity"] == edition.identity
    assert (qa_root / "normative-archive" / first.storage_key).read_bytes() == _download(edition).content
    assert DocumentoNormativo.objects.count() == 1


def test_dom_edition_staging_requires_explicit_qa_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("JURIX_QA_ONLY", raising=False)
    edition = _edition()
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(DomNatalCandidateError, match="JURIX_QA_ONLY=1"):
            stage_dom_edition_candidate(edition=edition, downloaded=_download(edition))
    assert DocumentoNormativo.objects.count() == 0


def test_dom_edition_staging_rejects_identity_mismatch_before_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    edition = _edition()
    other_edition = _edition(number=5001)
    qa_root = tmp_path / "jurix-qa"

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(DomNatalCandidateError, match="different edition"):
            stage_dom_edition_candidate(edition=edition, downloaded=_download(other_edition))

    assert not qa_root.exists()
    assert DocumentoNormativo.objects.count() == 0


def test_dom_qa_repairs_only_missing_blob_when_official_bytes_match_record(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    edition = _edition(number=5922, publication_date=date(2025, 12, 15))
    downloaded = _download(edition, b"%PDF-1.7\nVerified official QA bytes\n%%EOF")
    qa_root = tmp_path / "jurix-qa"

    class FakeClient:
        def list_editions(self, *, month, year):
            assert (month, year) == (12, 2025)
            return [edition]

        def download_edition(self, selected):
            assert selected == edition
            return downloaded

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        document, created = stage_dom_edition_candidate(edition=edition, downloaded=downloaded)
        assert created is True
        blob = qa_root / "normative-archive" / document.storage_key
        blob.unlink()

        preview = repair_dom_edition_blob_qa(
            year=2025, month=12, edition_number=5922, client=FakeClient()
        )
        assert preview == {"status": "missing_blob", "read_only": True, "restored": False}
        assert not blob.exists()

        repaired = repair_dom_edition_blob_qa(
            year=2025, month=12, edition_number=5922, apply=True, client=FakeClient()
        )

    document.refresh_from_db()
    assert repaired == {"status": "restored", "read_only": False, "restored": True}
    assert blob.read_bytes() == downloaded.content
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.extraction_status == DocumentoNormativo.ExtractionStatus.PENDING
    assert document.norma_id is None
    assert DocumentoNormativo.objects.count() == 1


def test_dom_qa_refuses_blob_repair_when_official_hash_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    edition = _edition(number=5922, publication_date=date(2025, 12, 15))
    original = _download(edition, b"%PDF-1.7\nOriginal bytes\n%%EOF")
    altered = _download(edition, b"%PDF-1.7\nAltered bytes\n%%EOF")
    qa_root = tmp_path / "jurix-qa"

    class FakeClient:
        def list_editions(self, *, month, year):
            return [edition]

        def download_edition(self, selected):
            return altered

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        document, _ = stage_dom_edition_candidate(edition=edition, downloaded=original)
        blob = qa_root / "normative-archive" / document.storage_key
        blob.unlink()
        with pytest.raises(DomNatalCandidateError, match="does not match"):
            repair_dom_edition_blob_qa(
                year=2025, month=12, edition_number=5922, apply=True, client=FakeClient()
            )

    assert not blob.exists()
    assert DocumentoNormativo.objects.count() == 1


def test_dom_edition_staging_rejects_invalid_checksum_without_record(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    edition = _edition()
    download = _download(edition)
    object.__setattr__(download, "sha256", "0" * 64)
    qa_root = tmp_path / "jurix-qa"

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(DomNatalCandidateError, match="checksum"):
            stage_dom_edition_candidate(edition=edition, downloaded=download)

    assert DocumentoNormativo.objects.count() == 0
    assert not (qa_root / "normative-archive" / ".staging").exists()


def test_regular_and_special_editions_on_same_date_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    regular = _edition(number=5000)
    special = _edition(number=5000, special=True)

    with override_settings(QA_ROOT=tmp_path / "jurix-qa", NORMATIVE_ARCHIVE_ENABLED=True):
        regular_doc, _ = stage_dom_edition_candidate(
            edition=regular, downloaded=_download(regular, b"%PDF-1.7\nregular\n%%EOF")
        )
        special_doc, _ = stage_dom_edition_candidate(
            edition=special, downloaded=_download(special, b"%PDF-1.7\nspecial\n%%EOF")
        )

    assert regular_doc.pk != special_doc.pk
    assert regular_doc.metadata_json["special_edition"] is False
    assert special_doc.metadata_json["special_edition"] is True
    assert DocumentoNormativo.objects.count() == 2


def test_dom_sync_skips_known_urls_and_discovers_delayed_editions(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    older = _edition(number=4999)
    newer = _edition(number=5000)

    class Client:
        editions = [newer]
        downloads = []

        def list_editions(self, *, month, year):
            assert (month, year) == (10, 2026)
            return list(self.editions)

        def download_edition(self, edition):
            self.downloads.append(edition.identity)
            return _download(edition, f"%PDF-1.7\n{edition.number}\n%%EOF".encode())

    client = Client()
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        first = sync_dom_natal_editions(
            client=client, as_of=date(2026, 10, 8), lookback_months=1
        )
        client.editions = [older, newer]
        second = sync_dom_natal_editions(
            client=client, as_of=date(2026, 10, 8), lookback_months=1
        )

    assert first["status"] == "current"
    assert first["scopes"][0]["new_candidates"] == 1
    assert second["status"] == "current"
    assert second["scopes"][0]["new_candidates"] == 1
    assert client.downloads == [newer.identity, older.identity]
    assert DocumentoNormativo.objects.count() == 2
    assert DocumentoNormativo.objects.filter(
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        norma__isnull=True,
    ).count() == 2
    state = SaplSyncState.objects.get(source="dom_natal")
    assert state.last_success_at is not None
    assert state.last_error == ""
    assert state.last_full_sync_at is not None


def test_dom_sync_batches_new_editions_and_resumes_without_redownloading(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    first_edition = _edition(number=5000)
    second_edition = _edition(number=5001)

    class Client:
        downloads = []

        def list_editions(self, *, month, year):
            assert (month, year) == (10, 2026)
            return [first_edition, second_edition]

        def download_edition(self, edition):
            self.downloads.append(edition.identity)
            return _download(edition, f"%PDF-1.7\n{edition.number}\n%%EOF".encode())

    client = Client()
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        partial = sync_dom_natal_editions(
            client=client,
            as_of=date(2026, 10, 8),
            lookback_months=1,
            max_new_total=1,
        )
        state = SaplSyncState.objects.get(source="dom_natal")
        assert state.last_success_at is None
        assert state.last_error == "edition_batch_incomplete:1"

        resumed = sync_dom_natal_editions(
            client=client,
            as_of=date(2026, 10, 8),
            lookback_months=1,
            max_new_total=1,
        )

    assert partial["status"] == "degraded"
    assert partial["scopes"][0]["remaining_candidates"] == 1
    assert resumed["status"] == "current"
    assert resumed["scopes"][0]["remaining_candidates"] == 0
    assert client.downloads == [first_edition.identity, second_edition.identity]
    assert DocumentoNormativo.objects.count() == 2
    state.refresh_from_db()
    assert state.last_success_at is not None
    assert state.last_error == ""


def test_dom_sync_global_batch_limit_resumes_across_month_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    current = _edition(number=5000)
    delayed = _edition(number=4999, publication_date=date(2026, 9, 30))

    class Client:
        downloads = []

        def list_editions(self, *, month, year):
            assert year == 2026
            return {10: [current], 9: [delayed]}.get(month, [])

        def download_edition(self, edition):
            self.downloads.append(edition.identity)
            return _download(edition, f"%PDF-1.7\n{edition.number}\n%%EOF".encode())

    client = Client()
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        first = sync_dom_natal_editions(
            client=client,
            as_of=date(2026, 10, 8),
            lookback_months=2,
            max_new_total=1,
        )
        second = sync_dom_natal_editions(
            client=client,
            as_of=date(2026, 10, 8),
            lookback_months=2,
            max_new_total=1,
        )

    assert first["status"] == "degraded"
    assert first["scopes"][0]["new_candidates"] == 1
    assert first["scopes"][1]["remaining_candidates"] == 1
    assert second["status"] == "current"
    assert second["scopes"][1]["new_candidates"] == 1
    assert client.downloads == [current.identity, delayed.identity]
    assert DocumentoNormativo.objects.count() == 2


def test_dom_sync_is_refused_outside_the_explicit_qa_profile(monkeypatch):
    monkeypatch.delenv("JURIX_QA_ONLY", raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")

    with pytest.raises(DomNatalCandidateError, match="isolated normative QA profile"):
        sync_dom_natal_editions(as_of=date(2026, 10, 8), lookback_months=1)


def test_dom_sync_refuses_base_settings_even_when_qa_flag_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(DomNatalCandidateError, match="isolated normative QA profile"):
            sync_dom_natal_editions(as_of=date(2026, 10, 8), lookback_months=1)


def test_dom_sync_accepts_the_strict_container_qa_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa"
    )
    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        _require_dom_qa()


def test_dom_sync_records_sanitized_source_failure_and_health_is_degraded(tmp_path, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from src.apps.ingestion.source_sync_health import get_source_sync_health

    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")

    class UnavailableClient:
        def list_editions(self, *, month, year):
            raise RuntimeError("private host and credential must not leak")

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        result = sync_dom_natal_editions(
            client=UnavailableClient(),
            as_of=date(2026, 10, 8),
            lookback_months=1,
        )
        health = get_source_sync_health(
            "dom_natal", now=timezone.now(), max_age=timedelta(hours=36)
        )

    checkpoint = SaplSyncState.objects.get(source="dom_natal")
    assert result["status"] == "degraded"
    assert result["scopes"][0]["error_class"] == "RuntimeError"
    assert health["status"] == "unavailable"
    assert health["has_error"] is True
    assert checkpoint.last_error == "source_error:RuntimeError"
    assert "private host" not in checkpoint.last_error
    assert checkpoint.last_success_at is None


def test_dom_catalog_inspection_is_read_only_and_reports_only_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    edition = _edition()

    class CatalogClient:
        def list_editions(self, *, month, year):
            assert (month, year) == (10, 2026)
            return [edition]

        def download_edition(self, _edition):
            raise AssertionError("read-only catalog inspection must not download PDFs")

    qa_root = tmp_path / "qa"
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        report = inspect_dom_natal_editions(
            client=CatalogClient(), as_of=date(2026, 10, 8), lookback_months=1
        )

    assert report == {
        "source": "dom_natal",
        "catalog_status": "available",
        "read_only": True,
        "scopes": [
            {
                "year": 2026,
                "month": 10,
                "catalog_status": "available",
                "edition_count": 1,
                "known_url_count": 0,
                "new_candidate_count": 1,
            }
        ],
    }
    assert DocumentoNormativo.objects.count() == 0
    assert SaplSyncState.objects.count() == 0
    assert not qa_root.exists()
