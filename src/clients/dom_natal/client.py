"""Bounded, read-only access to editions listed by the official Natal DOM portal."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

OFFICIAL_HOST = "www2.natal.rn.gov.br"
PORTAL_URL = f"https://{OFFICIAL_HOST}/dom/index.php?p=d"
EDITION_PATH_PREFIX = "/_anexos/publicacao/dom/"
MAX_LISTING_BYTES = 2_000_000
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_REQUEST_RETRIES = 2
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_TIMEOUT = (4.0, 15.0)
_EDITION_FILENAME = re.compile(r"^dom_\d{8}(?:_especial)?_[a-f0-9]{24,64}\.pdf$", re.I)
_NUMBER = re.compile(r"\b(?:num\.?|n[º°.]?)\s*(\d{1,8})\b", re.I)
_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


class DomNatalError(RuntimeError):
    """A safe, source-specific error; never includes response bodies or credentials."""


@dataclass(frozen=True)
class DomNatalEdition:
    identity: str
    year: int
    number: int
    publication_date: date
    special: bool
    label: str
    official_url: str


@dataclass(frozen=True)
class DomNatalPdf:
    edition: DomNatalEdition
    content: bytes
    sha256: str
    size_bytes: int


class _EditionLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            label = " ".join(" ".join(self._text).split())
            self.links.append((self._href, label))
            self._href = None
            self._text = []


class DomNatalClient:
    """Discover official monthly editions and fetch a selected PDF safely.

    The portal's edition search is a read-only form POST (`mes`, `ano`, `list`).
    No local records are created by this client; ingestion is a separate explicit
    operation and must keep every edition as an unreviewed candidate.
    """

    def __init__(self, *, session: requests.Session | None = None, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "JurixResearch/1.0 (+read-only legal source client)")

    @staticmethod
    def _validate_url(url: str, *, pdf: bool) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != OFFICIAL_HOST
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or (parsed.query != "p=d" if not pdf else bool(parsed.query))
            or parsed.fragment
        ):
            raise DomNatalError("A fonte redirecionou para um destino não permitido.")
        if pdf:
            filename = parsed.path.rsplit("/", 1)[-1]
            if not parsed.path.startswith(EDITION_PATH_PREFIX) or not _EDITION_FILENAME.fullmatch(filename):
                raise DomNatalError("O link não corresponde a um PDF de edição permitido do DOM.")
        elif parsed.path != "/dom/index.php":
            raise DomNatalError("O endereço não corresponde à página oficial de consulta do DOM.")
        return url

    def _request(self, method: str, url: str, *, data=None, max_bytes: int):
        current_url = url
        current_method = method.upper()
        current_data = data
        for hop in range(MAX_REDIRECTS + 1):
            self._validate_url(current_url, pdf=EDITION_PATH_PREFIX in urlsplit(current_url).path)
            for attempt in range(MAX_REQUEST_RETRIES + 1):
                try:
                    response = self.session.request(
                        current_method,
                        current_url,
                        data=current_data,
                        timeout=self.timeout,
                        allow_redirects=False,
                        stream=True,
                    )
                except requests.RequestException as exc:
                    if attempt < MAX_REQUEST_RETRIES:
                        time.sleep(0.1 * (attempt + 1))
                        continue
                    raise DomNatalError(
                        "Não foi possível consultar o Diário Oficial de Natal."
                    ) from exc
                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < MAX_REQUEST_RETRIES
                ):
                    response.close()
                    time.sleep(0.1 * (attempt + 1))
                    continue
                break
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location or hop >= MAX_REDIRECTS:
                    raise DomNatalError("Redirecionamento do DOM ausente ou excedeu o limite.")
                current_url = urljoin(current_url, location)
                if response.status_code in {301, 302, 303}:
                    current_method, current_data = "GET", None
                continue
            if response.status_code != 200:
                response.close()
                raise DomNatalError(f"Consulta ao DOM retornou HTTP {response.status_code}.")
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdecimal() and int(content_length) > max_bytes:
                response.close()
                raise DomNatalError("A resposta do DOM excede o limite de tamanho permitido.")
            chunks = []
            size = 0
            try:
                try:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            raise DomNatalError("A resposta do DOM excede o limite de tamanho permitido.")
                        chunks.append(chunk)
                except requests.RequestException as exc:
                    raise DomNatalError("A transferência do arquivo do DOM foi interrompida.") from exc
            finally:
                response.close()
            return response, b"".join(chunks)
        raise DomNatalError("Redirecionamento do DOM excedeu o limite.")

    def list_editions(self, *, month: int, year: int) -> list[DomNatalEdition]:
        if not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError("month deve estar entre 1 e 12.")
        if not isinstance(year, int) or not 2001 <= year <= 2100:
            raise ValueError("year deve estar entre 2001 e 2100.")
        response, body = self._request(
            "POST",
            PORTAL_URL,
            data={"mes": str(month), "ano": str(year), "list": "Consultar"},
            max_bytes=MAX_LISTING_BYTES,
        )
        if "text/html" not in str(response.headers.get("Content-Type", "")).lower():
            raise DomNatalError("A consulta do DOM não retornou HTML.")
        parser = _EditionLinkParser()
        parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
        editions = {}
        for href, label in parser.links:
            full_url = urljoin(PORTAL_URL, href)
            try:
                self._validate_url(full_url, pdf=True)
            except DomNatalError:
                continue
            number_match = _NUMBER.search(label)
            date_match = _DATE.search(label)
            if not number_match or not date_match:
                continue
            try:
                published = date(
                    int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1))
                )
            except ValueError:
                continue
            if published.year != year or published.month != month:
                continue
            number = int(number_match.group(1))
            special = bool(re.search(r"\bespecial\b", f"{label} {full_url}", re.I))
            edition_kind = "special" if special else "regular"
            identity = f"natal-dom:{published.year}:{number}:{published.isoformat()}:{edition_kind}"
            editions[identity] = DomNatalEdition(
                identity=identity,
                year=published.year,
                number=number,
                publication_date=published,
                special=special,
                label=label,
                official_url=full_url,
            )
        return sorted(editions.values(), key=lambda item: (item.publication_date, item.number, item.special))

    def download_edition(self, edition: DomNatalEdition) -> DomNatalPdf:
        self._validate_url(edition.official_url, pdf=True)
        response, content = self._request(
            "GET", edition.official_url, max_bytes=MAX_PDF_BYTES
        )
        content_type = str(response.headers.get("Content-Type", "")).lower().split(";", 1)[0].strip()
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise DomNatalError("O arquivo oficial não foi identificado como PDF.")
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise DomNatalError("O arquivo oficial não passou pela validação estrutural mínima de PDF.")
        return DomNatalPdf(
            edition=edition,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
