from types import SimpleNamespace

import pytest

from scripts.run_qa_sapl_incremental import (
    _validate_checkpoint_page,
    _validate_existing_replay_anchors,
)


class FakeClient:
    def validate_pagination_url(self, url):
        assert url.startswith("https://sapl.natal.rn.leg.br/api/")
        return url


def _checkpoint(*, cursor=30, page=4):
    return SimpleNamespace(
        last_cursor=cursor,
        last_cursor_url=(
            "https://sapl.natal.rn.leg.br/api/norma/normajuridica/"
            f"?page={page}&tipo=1&ano=2026"
        ),
    )


def _page(*, start=31, end=40, records=None):
    values = records or [
        {"id": index, "numero": str(index), "ano": 2026, "tipo": "1"}
        for index in range(10)
    ]
    return {
        "_jurix_pagination": {"start_index": start, "end_index": end},
        "results": values,
    }


def test_replay_uses_exact_checkpoint_page_and_respects_ten_record_limit():
    records = _validate_checkpoint_page(
        checkpoint=_checkpoint(), page=_page(), client=FakeClient(), limit=10
    )

    assert len(records) == 10


@pytest.mark.parametrize(
    ("checkpoint", "page"),
    [
        (_checkpoint(), _page(start=1, end=10)),
        (_checkpoint(cursor=20, page=4), _page(start=31, end=40)),
        (_checkpoint(page=3), _page()),
        (_checkpoint(), _page(end=41, records=[{"id": n, "ano": 2026, "tipo": "1"} for n in range(11)])),
    ],
)
def test_replay_refuses_page_or_cursor_mismatch(checkpoint, page):
    with pytest.raises(SystemExit, match="does not match the exact checkpoint scope"):
        _validate_checkpoint_page(
            checkpoint=checkpoint, page=page, client=FakeClient(), limit=10
        )


class FakeQuerySet:
    def __init__(self, rows):
        self.rows = rows

    def only(self, *_fields):
        return self.rows


class FakeNormaManager:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *, sapl_id__in):
        return FakeQuerySet([row for row in self.rows if row.sapl_id in sapl_id__in])


class FakeNorma:
    objects = None


def test_replay_allows_missing_local_rows_after_exact_page_validation():
    FakeNorma.objects = FakeNormaManager([])

    assert _validate_existing_replay_anchors(
        FakeNorma,
        [{"id": 7, "numero": "7", "ano": 2026}],
    ) == 0


def test_replay_accepts_only_matching_pending_rows_without_local_source():
    FakeNorma.objects = FakeNormaManager(
        [
            SimpleNamespace(
                sapl_id=7,
                numero="7",
                ano=2026,
                status="pending",
                pdf_path="",
                texto_consolidado="",
            )
        ]
    )

    assert _validate_existing_replay_anchors(
        FakeNorma,
        [{"id": 7, "numero": "7", "ano": 2026}],
    ) == 1


def test_replay_refuses_row_that_no_longer_matches_the_source():
    FakeNorma.objects = FakeNormaManager(
        [
            SimpleNamespace(
                sapl_id=7,
                numero="70",
                ano=2026,
                status="pending",
                pdf_path="",
                texto_consolidado="",
            )
        ]
    )

    with pytest.raises(SystemExit, match="not a matching pending metadata row"):
        _validate_existing_replay_anchors(
            FakeNorma,
            [{"id": 7, "numero": "7", "ano": 2026}],
        )
