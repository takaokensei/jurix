from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError

from src.apps.operations.models import CorpusCoverageScope, CorpusRevision
from src.processing.corpus_coverage import (
    build_corpus_coverage,
    current_corpus_coverage,
    record_corpus_coverage_scope,
)


def test_coverage_without_a_reviewed_scope_is_explicitly_unknown():
    dto = build_corpus_coverage()

    assert dto == {
        "coverage_status": "unknown",
        "corpus_revision": {"revision": None, "digest": None},
        "checked_until": None,
        "sources_checked": [],
        "missing_intervals": None,
        "pending_review": None,
        "reason": "no_reviewed_coverage_scope",
    }


def test_global_revision_counts_never_certify_temporal_coverage():
    dto = build_corpus_coverage(
        {
            "revision": 12,
            "digest": "a" * 64,
            "completeness": "complete",
            "norm_count": 4000,
            "device_count": 25000,
        }
    )

    assert dto["coverage_status"] == "unknown"
    assert dto["corpus_revision"] == {"revision": 12, "digest": "a" * 64}
    assert dto["checked_until"] is None
    assert dto["missing_intervals"] is None
    assert dto["pending_review"] is None


@pytest.mark.django_db
def test_partial_scope_is_versioned_and_does_not_leak_arbitrary_interval_fields():
    revision = CorpusRevision.objects.create(
        key="municipal", revision=4, digest="a" * 64, completeness="complete"
    )
    row, created = record_corpus_coverage_scope(
        source="archive",
        jurisdiction="BR-RN-NATAL",
        series="municipal_lc",
        coverage_status="partial",
        period_start=date(2000, 1, 1),
        period_end=date(2020, 12, 31),
        checked_until=date(2020, 12, 31),
        source_checksum="b" * 64,
        missing_intervals=[
            {"start": "2005-01-01", "end": "2005-12-31", "internal_path": "C:/private/archive"}
        ],
        pending_review_count=3,
    )

    assert created is True
    assert row.corpus_revision_number == revision.revision
    dto = build_corpus_coverage(
        {"revision": revision.revision, "digest": revision.digest}, scopes=[row]
    )
    assert dto["coverage_status"] == "partial"
    assert dto["scope_limited"] is True
    assert dto["checked_until"] == "2020-12-31"
    assert dto["pending_review"] == 3
    assert dto["missing_intervals"] == [
        {
            "source": "archive",
            "jurisdiction": "BR-RN-NATAL",
            "series": "municipal_lc",
            "start": "2005-01-01",
            "end": "2005-12-31",
        }
    ]
    with pytest.raises(ValidationError, match="imutáveis"):
        row.save()
    with pytest.raises(ValidationError, match="imutáveis"):
        CorpusCoverageScope.objects.filter(pk=row.pk).update(coverage_status="reviewed")


@pytest.mark.django_db
def test_reviewed_scope_requires_permission_and_identical_submission_is_idempotent():
    CorpusRevision.objects.create(
        key="municipal", revision=7, digest="c" * 64, completeness="partial"
    )
    reviewer = get_user_model().objects.create_user(
        username="coverage-reviewer-qa", password="test-only", is_staff=True
    )
    options = {
        "source": "sapl",
        "jurisdiction": "BR-RN-NATAL",
        "series": "municipal_lc",
        "coverage_status": "reviewed",
        "period_start": date(2010, 1, 1),
        "period_end": date(2024, 12, 31),
        "checked_until": date(2024, 12, 31),
        "source_checksum": "d" * 64,
        "missing_intervals": [],
        "pending_review_count": 0,
        "reviewer": reviewer,
        "reason": "Conferência QA de escopo em teste; não é revisão jurídica do corpus real.",
    }
    with pytest.raises(PermissionDenied, match="permissão de curadoria"):
        record_corpus_coverage_scope(**options)

    permission = Permission.objects.get(
        codename="add_corpuscoveragescope", content_type__app_label="operations"
    )
    reviewer.user_permissions.add(permission)
    reviewer = get_user_model().objects.get(pk=reviewer.pk)
    options["reviewer"] = reviewer
    assert reviewer.has_perm("operations.add_corpuscoveragescope"), list(
        reviewer.get_all_permissions()
    )
    row, created = record_corpus_coverage_scope(**options)
    duplicate, duplicate_created = record_corpus_coverage_scope(**options)

    assert created is True
    assert duplicate_created is False
    assert duplicate.pk == row.pk
    dto = build_corpus_coverage({"revision": 7, "digest": "c" * 64}, scopes=[row])
    assert dto["coverage_status"] == "reviewed"
    assert dto["scope_limited"] is True
    assert dto["missing_intervals"] == []
    assert dto["pending_review"] == 0


@pytest.mark.django_db
def test_current_coverage_reads_only_snapshots_for_the_requested_corpus_digest():
    CorpusRevision.objects.update_or_create(
        key="municipal",
        defaults={"revision": 9, "digest": "e" * 64, "completeness": "complete"},
    )
    row, _created = record_corpus_coverage_scope(
        source="archive",
        jurisdiction="BR-RN-NATAL",
        series="municipal_lc",
        coverage_status="partial",
        checked_until=date(2022, 12, 31),
        source_checksum="f" * 64,
        missing_intervals=[],
        pending_review_count=2,
    )

    current = current_corpus_coverage({"revision": 9, "digest": "e" * 64})
    stale = current_corpus_coverage({"revision": 10, "digest": "0" * 64})

    assert current["coverage_status"] == "partial"
    assert current["corpus_revision"] == {"revision": 9, "digest": "e" * 64}
    assert current["sources_checked"][0]["source_checksum"] == "f" * 64
    assert stale["coverage_status"] == "unknown"
    assert stale["sources_checked"] == []
    assert row.corpus_revision_digest == "e" * 64
