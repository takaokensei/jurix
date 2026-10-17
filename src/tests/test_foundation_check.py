from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.models import Norma
from src.processing.foundation_check import (
    FoundationCheckCancelled,
    _device_matches,
    check_foundation,
)

pytestmark = pytest.mark.django_db


def _projection(norma, as_of, *, text, status="in_force", complete=True):
    source = SimpleNamespace(
        tipo="artigo",
        numero="1",
        structural_key="article-1",
        parent_key=None,
        page_index=0,
        extracao=SimpleNamespace(documento=SimpleNamespace(public_id=uuid4())),
    )
    projected = SimpleNamespace(source=source, text=text, legal_status=status)
    return SimpleNamespace(
        norma_id=norma.pk,
        as_of=as_of,
        status=NormativeSnapshot.Status.COMPLETE if complete else NormativeSnapshot.Status.PARTIAL,
        input_sha256="a" * 64,
        content_sha256=("b" if text.endswith("novo") else "c") * 64,
        devices=(projected,),
        coverage={"reason": "test_projection", "pending_event_ids": []},
    )


def _norma(number="10", kind="Lei"):
    return Norma.objects.create(
        tipo=kind,
        numero=number,
        ano=2020,
        status="consolidated",
        data_publicacao=date(2020, 1, 1),
        data_vigencia=date(2020, 1, 1),
    )


def _reviewed_coverage(*series):
    return {
        "coverage_status": "reviewed",
        "checked_until": "2021-01-01",
        "scope_limited": True,
        "sources_checked": [
            {
                "source": "sapl",
                "jurisdiction": "BR-RN-NATAL",
                "series": item,
                "period_start": "2020-01-01",
                "period_end": "2021-12-31",
                "checked_until": "2021-01-01",
                "coverage_status": "reviewed",
                "missing_intervals": [],
                "pending_review": 0,
            }
            for item in series
        ],
    }


def test_check_compares_each_norm_article_separately_without_persisting_input():
    ordinary = _norma("10", "Lei")
    complementary = _norma("20", "Lei Complementar")
    projections = {
        (ordinary.pk, date(2020, 1, 1)): _projection(ordinary, date(2020, 1, 1), text="Texto antigo"),
        (ordinary.pk, date(2021, 1, 1)): _projection(ordinary, date(2021, 1, 1), text="Texto novo"),
        (complementary.pk, date(2020, 1, 1)): _projection(complementary, date(2020, 1, 1), text="Texto estável"),
        (complementary.pk, date(2021, 1, 1)): _projection(complementary, date(2021, 1, 1), text="Texto estável"),
    }
    foundation = "Art. 1º da Lei nº 10/2020 e Art. 1º da Lei Complementar nº 20/2020."
    with (
        patch(
            "src.processing.foundation_check.project_norma_as_of",
            side_effect=lambda norma, as_of: projections[(norma.pk, as_of)],
        ),
        patch(
            "src.processing.foundation_check.current_corpus_coverage",
            return_value=_reviewed_coverage("municipal_lo", "municipal_lc"),
        ),
    ):
        result = check_foundation(
            foundation, from_date=date(2020, 1, 1), to_date=date(2021, 1, 1)
        )

    assert [item["status"] for item in result["references"]] == [
        "changed",
        "unchanged_in_checked_scope",
    ]
    assert result["summary"]["changed"] == 1
    assert result["summary"]["unchanged_in_checked_scope"] == 1
    assert result["references"][1]["coverage"]["selected_scope"]["source"] == "sapl"
    assert result["persisted"] is False and result["llm_used"] is False
    assert result["corpus_coverage"]["coverage_status"] == "reviewed"
    assert result["references"][0]["evidence"]["before"][0]["text"] == "Texto antigo"
    assert result["references"][0]["evidence"]["after"][0]["text"] == "Texto novo"


def test_equal_projected_text_is_inconclusive_without_a_matching_reviewed_scope():
    norma = _norma("20", "Lei Complementar")
    projections = {
        (norma.pk, date(2020, 1, 1)): _projection(
            norma, date(2020, 1, 1), text="Texto idêntico"
        ),
        (norma.pk, date(2021, 1, 1)): _projection(
            norma, date(2021, 1, 1), text="Texto idêntico"
        ),
    }
    with (
        patch(
            "src.processing.foundation_check.project_norma_as_of",
            side_effect=lambda row, as_of: projections[(row.pk, as_of)],
        ),
        patch(
            "src.processing.foundation_check.current_corpus_coverage",
            return_value={
                "coverage_status": "unknown",
                "checked_until": None,
                "sources_checked": [],
            },
        ),
    ):
        result = check_foundation(
            "Lei Complementar nº 20/2020, Art. 1º",
            from_date=date(2020, 1, 1),
            to_date=date(2021, 1, 1),
        )

    reference = result["references"][0]
    assert reference["status"] == "inconclusive"
    assert reference["observation"] == "same_projected_text"
    assert "não há escopo de cobertura revisado" in reference["reason"]
    assert result["summary"]["inconclusive"] == 1


def test_check_keeps_pending_or_conflicting_projection_inconclusive():
    norma = _norma()
    projections = {
        (norma.pk, date(2020, 1, 1)): _projection(norma, date(2020, 1, 1), text="Texto", complete=False),
        (norma.pk, date(2021, 1, 1)): _projection(norma, date(2021, 1, 1), text="Texto"),
    }
    with patch(
        "src.processing.foundation_check.project_norma_as_of",
        side_effect=lambda row, as_of: projections[(row.pk, as_of)],
    ):
        result = check_foundation(
            "Lei nº 10/2020, Art. 1º",
            from_date=date(2020, 1, 1),
            to_date=date(2021, 1, 1),
        )

    assert result["references"][0]["status"] == "inconclusive"
    assert "incompletas" in result["references"][0]["reason"]


def test_check_requires_confirmation_and_does_not_query_unqualified_articles():
    result = check_foundation(
        "O Art. 1º está citado sem identificar sua lei.",
        from_date=date(2020, 1, 1),
        to_date=date(2021, 1, 1),
    )

    assert result["references"][0]["status"] == "confirmation_required"
    assert result["references"][0].get("norma_id") is None


def test_device_matching_distinguishes_lettered_article_from_base_article():
    base = SimpleNamespace(
        source=SimpleNamespace(tipo="artigo", numero="2º", structural_key="article-2")
    )
    lettered = SimpleNamespace(
        source=SimpleNamespace(tipo="artigo", numero="2º-A", structural_key="article-2-a")
    )
    projection = SimpleNamespace(devices=(base, lettered))

    assert _device_matches(
        projection,
        SimpleNamespace(article="2", paragraph=None, item=None, alinea=None),
    ) == [base]
    assert _device_matches(
        projection,
        SimpleNamespace(article="2-A", paragraph=None, item=None, alinea=None),
    ) == [lettered]


def test_check_resolves_each_article_in_a_coordinated_citation():
    norma = _norma()

    def snapshot(as_of):
        result = _projection(norma, as_of, text="Texto estável")
        devices = []
        for number in ("1º", "2º"):
            source = SimpleNamespace(
                tipo="artigo",
                numero=number,
                structural_key=f"article-{number}",
                parent_key=None,
                page_index=0,
                extracao=SimpleNamespace(documento=SimpleNamespace(public_id=uuid4())),
            )
            devices.append(SimpleNamespace(source=source, text=f"Art. {number} Texto", legal_status="in_force"))
        result.devices = tuple(devices)
        return result

    with (
        patch(
            "src.processing.foundation_check.project_norma_as_of",
            side_effect=lambda _norma, as_of: snapshot(as_of),
        ),
        patch(
            "src.processing.foundation_check.current_corpus_coverage",
            return_value=_reviewed_coverage("municipal_lo"),
        ),
    ):
        result = check_foundation(
            "Arts. 1º e 2º da Lei nº 10/2020",
            from_date=date(2020, 1, 1),
            to_date=date(2021, 1, 1),
        )

    assert [reference["identity"]["article"] for reference in result["references"]] == ["1", "2"]
    assert [reference["status"] for reference in result["references"]] == [
        "unchanged_in_checked_scope",
        "unchanged_in_checked_scope",
    ]


def test_check_rejects_non_increasing_date_range():
    with pytest.raises(ValueError, match="anterior"):
        check_foundation("", from_date=date(2021, 1, 1), to_date=date(2021, 1, 1))


def test_check_rejects_datetime_values_instead_of_calendar_dates():
    with pytest.raises(TypeError, match="datetime.date"):
        check_foundation(
            "",
            from_date=datetime(2020, 1, 1),
            to_date=date(2021, 1, 1),
        )


def test_check_observes_cancellation_before_starting_next_projection():
    _norma()
    with patch("src.processing.foundation_check.project_norma_as_of") as project:
        with pytest.raises(FoundationCheckCancelled):
            check_foundation(
                "Lei nº 10/2020, Art. 1º",
                from_date=date(2020, 1, 1),
                to_date=date(2021, 1, 1),
                should_cancel=lambda: True,
            )
    project.assert_not_called()


def test_check_observes_cancellation_between_temporal_projections():
    _norma()
    cancelled = False

    def mark_cancelled(completed, _total):
        nonlocal cancelled
        cancelled = True

    with patch(
        "src.processing.foundation_check.project_norma_as_of",
        side_effect=lambda row, as_of: _projection(row, as_of, text="Texto estável"),
    ) as project:
        with pytest.raises(FoundationCheckCancelled):
            check_foundation(
                "Lei nº 10/2020, Art. 1º",
                from_date=date(2020, 1, 1),
                to_date=date(2021, 1, 1),
                should_cancel=lambda: cancelled,
                on_progress=mark_cancelled,
            )
    assert project.call_count == 1
