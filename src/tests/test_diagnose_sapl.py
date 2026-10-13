from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


class FakeSaplClient:
    def __init__(self, pages):
        self.base_url = "https://sapl.natal.rn.leg.br/api"
        self.pages = pages
        self.requested_urls = []

    def fetch_normas_page(self, *, limit, offset, tipo=None, ano=None):
        assert limit == 10
        assert offset == 0
        return self.pages[0]

    def _make_request_url(self, url):
        self.requested_urls.append(url)
        return self.pages[len(self.requested_urls)]

    def validate_pagination_url(self, url):
        if not url.startswith("https://sapl.natal.rn.leg.br/api/"):
            raise ValueError("outside source origin")
        return url

    def build_normas_page_url(self, page, *, tipo=None, ano=None):
        return f"https://sapl.natal.rn.leg.br/api/norma/normajuridica/?page={page}"


def _page(ids, page_number, next_url=None):
    start = ((page_number - 1) * 10) + 1
    end = start + len(ids) - 1
    return {
        "results": [{"id": item} for item in ids],
        "next": next_url,
        "_jurix_pagination": {
            "page": page_number,
            "total_pages": 2,
            "total_entries": 20,
            "start_index": start,
            "end_index": end,
        },
    }


def test_diagnose_sapl_follows_validated_next_url_not_repeated_offset(monkeypatch, capsys):
    next_url = "https://sapl.natal.rn.leg.br/api/norma/normajuridica/?page=2"
    client = FakeSaplClient([
        _page(range(1, 11), 1, next_url),
        _page(range(11, 21), 2),
    ])
    monkeypatch.setattr(
        "src.apps.ingestion.management.commands.diagnose_sapl.SaplAPIClient",
        lambda: client,
    )

    call_command("diagnose_sapl", limit=10, max_pages=4)

    output = capsys.readouterr().out
    assert client.requested_urls == [next_url]
    assert "Página 1: 10 registros, 10 IDs únicos" in output
    assert "Página 2: 10 registros, 10 IDs únicos" in output
    assert "20 registros distintos observados" in output
    assert "offset não é confiável" not in output


def test_diagnose_sapl_fails_when_next_repeats_a_page(monkeypatch):
    next_url = "https://sapl.natal.rn.leg.br/api/norma/normajuridica/?page=2"
    page = _page(range(1, 11), 1, next_url)
    client = FakeSaplClient([page, _page(range(1, 11), 2)])
    monkeypatch.setattr(
        "src.apps.ingestion.management.commands.diagnose_sapl.SaplAPIClient",
        lambda: client,
    )

    with pytest.raises(CommandError, match="repetiu o conteúdo de uma página"):
        call_command("diagnose_sapl", limit=10, max_pages=4)


def test_diagnose_sapl_rejects_missing_or_duplicate_ids(monkeypatch):
    page = _page([1, 1], 1)
    client = FakeSaplClient([page])
    monkeypatch.setattr(
        "src.apps.ingestion.management.commands.diagnose_sapl.SaplAPIClient",
        lambda: client,
    )

    with pytest.raises(CommandError, match="IDs ausentes ou repetidos"):
        call_command("diagnose_sapl", limit=10, max_pages=4)


def test_diagnose_sapl_fails_when_ids_overlap_between_pages(monkeypatch):
    next_url = "https://sapl.natal.rn.leg.br/api/norma/normajuridica/?page=2"
    client = FakeSaplClient([
        _page(range(1, 11), 1, next_url),
        _page(range(10, 20), 2),
    ])
    monkeypatch.setattr(
        "src.apps.ingestion.management.commands.diagnose_sapl.SaplAPIClient",
        lambda: client,
    )

    with pytest.raises(CommandError, match="repetiu 1 ID repetido entre páginas"):
        call_command("diagnose_sapl", limit=10, max_pages=4)


def test_diagnose_sapl_rejects_pagination_outside_client_origin(monkeypatch):
    page = _page(range(1, 11), 1, "https://attacker.invalid/api/page=2")
    client = FakeSaplClient([page])
    monkeypatch.setattr(
        "src.apps.ingestion.management.commands.diagnose_sapl.SaplAPIClient",
        lambda: client,
    )

    with pytest.raises(CommandError, match="URL de paginação SAPL inválida"):
        call_command("diagnose_sapl", limit=10, max_pages=4)
