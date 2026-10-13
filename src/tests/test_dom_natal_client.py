"""Offline contracts for the official Natal DOM edition client."""

from datetime import date
from pathlib import Path

import pytest

from src.clients.dom_natal.client import (
    OFFICIAL_HOST,
    DomNatalClient,
    DomNatalEdition,
    DomNatalError,
)


class _Response:
    def __init__(self, status=200, *, headers=None, body=b"", encoding="utf-8"):
        self.status_code = status
        self.headers = headers or {}
        self.body = body
        self.encoding = encoding
        self.closed = False

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def mount(self, *_args):
        pass

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _edition(url, *, special=False):
    return DomNatalEdition(
        identity="natal-dom:2026:6211:2026-10-07:regular",
        year=2026,
        number=6211,
        publication_date=date(2026, 10, 7),
        special=special,
        label="Ano XXVI - Num. 6211 - 07/10/2026",
        official_url=url,
    )


def test_list_editions_parses_regular_and_special_dates_and_keeps_identity():
    html = f"""
      <a href="/_anexos/publicacao/dom/dom_20261003_{'a' * 32}.pdf">
        Ano XXVI - Num. 6207 - 03/10/2026
      </a>
      <a href="/_anexos/publicacao/dom/dom_20261003_especial_{'b' * 32}.pdf">
        Ano XXVI - Num. 6208 - Especial - 03/10/2026
      </a>
      <a href="https://evil.example/document.pdf">Ano XXVI - Num. 1 - 03/10/2026</a>
      <a href="/_anexos/publicacao/dom/dom_20261002_{'c' * 32}.pdf">
        Ano XXVI - Num. 6206 - 02/10/2026
      </a>
    """.encode()
    session = _Session([_Response(headers={"Content-Type": "text/html; charset=utf-8"}, body=html)])
    editions = DomNatalClient(session=session).list_editions(month=10, year=2026)

    assert [(item.number, item.special, item.publication_date) for item in editions] == [
        (6206, False, date(2026, 10, 2)),
        (6207, False, date(2026, 10, 3)),
        (6208, True, date(2026, 10, 3)),
    ]
    assert editions[1].identity.endswith(":regular")
    assert editions[2].identity.endswith(":special")
    assert session.calls[0][0] == "POST"
    assert session.calls[0][2]["data"] == {"mes": "10", "ano": "2026", "list": "Consultar"}


def test_list_editions_parses_sanitized_snapshot_from_official_dom_portal():
    fixture_path = Path(__file__).parent / "fixtures" / "dom_natal" / "editions_2026_10_sanitized.html"
    html = fixture_path.read_bytes()
    session = _Session([_Response(headers={"Content-Type": "text/html; charset=utf-8"}, body=html)])

    editions = DomNatalClient(session=session).list_editions(month=10, year=2026)

    assert [(item.number, item.publication_date, item.special) for item in editions] == [
        (6206, date(2026, 10, 1), False),
        (6208, date(2026, 10, 3), True),
        (6211, date(2026, 10, 7), False),
    ]
    assert len({item.identity for item in editions}) == 3


@pytest.mark.parametrize(("month", "year"), [(0, 2026), (13, 2026), (1, 2000), (1, 2101)])
def test_month_year_are_bounded_before_network_call(month, year):
    session = _Session([])
    client = DomNatalClient(session=session)

    with pytest.raises(ValueError):
        client.list_editions(month=month, year=year)
    assert not session.calls


def test_rejects_redirect_to_untrusted_host_before_following_it():
    url = f"https://{OFFICIAL_HOST}/dom/index.php?p=d"
    session = _Session([
        _Response(302, headers={"Location": "https://evil.example/steal"})
    ])
    client = DomNatalClient(session=session)

    with pytest.raises(DomNatalError, match="destino não permitido"):
        client._request("GET", url, max_bytes=1024)
    assert len(session.calls) == 1


def test_retries_transient_dom_status_with_a_bounded_attempt_count(monkeypatch):
    body = b"<a href=\"/_anexos/publicacao/dom/dom_20261007_" + b"a" * 32 + b".pdf\">Num. 6211 - 07/10/2026</a>"
    session = _Session(
        [
            _Response(503),
            _Response(headers={"Content-Type": "text/html"}, body=body),
        ]
    )
    monkeypatch.setattr("src.clients.dom_natal.client.time.sleep", lambda _delay: None)

    editions = DomNatalClient(session=session).list_editions(month=10, year=2026)

    assert len(editions) == 1
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    ("url", "headers", "body", "message"),
    [
        (
            f"https://{OFFICIAL_HOST}/_anexos/publicacao/dom/not-a-dom-file.pdf",
            {"Content-Type": "application/pdf"},
            b"%PDF-1.7\n%%EOF",
            "não corresponde",
        ),
        (
            f"https://{OFFICIAL_HOST}/_anexos/publicacao/dom/dom_20261007_{'a' * 32}.pdf",
            {"Content-Type": "text/html"},
            b"%PDF-1.7\n%%EOF",
            "identificado como PDF",
        ),
        (
            f"https://{OFFICIAL_HOST}/_anexos/publicacao/dom/dom_20261007_{'a' * 32}.pdf",
            {"Content-Type": "application/pdf"},
            b"<html>not a pdf</html>",
            "validação estrutural",
        ),
    ],
)
def test_pdf_download_fails_closed_for_invalid_url_or_content(url, headers, body, message):
    session = _Session([_Response(headers=headers, body=body)])
    client = DomNatalClient(session=session)

    with pytest.raises(DomNatalError, match=message):
        client.download_edition(_edition(url))


def test_pdf_download_returns_sha256_only_after_content_and_size_validation():
    body = b"%PDF-1.7\nsmall sanitized fixture\n%%EOF"
    url = f"https://{OFFICIAL_HOST}/_anexos/publicacao/dom/dom_20261007_{'d' * 32}.pdf"
    session = _Session([
        _Response(headers={"Content-Type": "application/pdf", "Content-Length": str(len(body))}, body=body)
    ])
    downloaded = DomNatalClient(session=session).download_edition(_edition(url))

    assert downloaded.content == body
    assert downloaded.size_bytes == len(body)
    assert len(downloaded.sha256) == 64
    assert downloaded.edition.number == 6211
