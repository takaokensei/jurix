"""Explicit, bounded SAPL lookup for legislative-matter references in QA chat."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

from src.processing.normative_reference import parse_normative_references

_EXPLICIT_MATTER_REFERENCE_RE = re.compile(
    r"\b(?P<type>projeto\s+de\s+lei\s+complementar|plc|"
    r"emenda\s+(?:supressiva|modificativa|aditiva))\s*"
    r"(?:n[º°o.]?\s*)?(?P<number>\d{1,5})\s*(?:/|de\s+)\s*(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
_MATTER_TYPE_LABELS = {
    "plc": "Projeto de Lei Complementar",
    "projeto de lei complementar": "Projeto de Lei Complementar",
    "emenda supressiva": "Emenda Supressiva",
    "emenda modificativa": "Emenda Modificativa",
    "emenda aditiva": "Emenda Aditiva",
}
_PROPOSED_WORDING_REQUEST_RE = re.compile(
    r"\b(?:red[aã]ç[aã]o|texto|conte[uú]do)\b.{0,60}\b(?:propost[oa]|projeto)\b|"
    r"\bproposta\s+de\s+(?:nova\s+)?(?:red[aã]ç[aã]o|texto)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RelatedMatterLookupResult:
    status: str
    sources: tuple[dict[str, Any], ...] = ()


def _normalized_label(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def _sapl_timestamp_label(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = timezone.localtime(parsed)
        return parsed.strftime("%d/%m/%Y às %H:%M")
    except (TypeError, ValueError, OverflowError):
        return raw


def parse_explicit_matter_references(question: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Return only explicitly typed references; never infer a matter from a law citation."""
    references = []
    seen = set()
    for match in _EXPLICIT_MATTER_REFERENCE_RE.finditer(str(question or "")):
        requested_type = _MATTER_TYPE_LABELS.get(_normalized_label(match.group("type")))
        if not requested_type:
            continue
        row = {
            "tipo": requested_type,
            "numero": int(match.group("number")),
            "ano": int(match.group("year")),
        }
        identity = (row["tipo"], row["numero"], row["ano"])
        if identity not in seen:
            seen.add(identity)
            references.append(row)
        if len(references) >= limit:
            break
    return references


def _extract_proposed_wording(document_text: str) -> str | None:
    """Extract only an explicitly introduced new article wording from a bill PDF."""
    heading = re.search(
        r"\bpassa\s+a\s+vigorar\s+com\s+a\s+seguinte\s+reda[cç][aã]o\s*:",
        str(document_text or ""),
        re.IGNORECASE,
    )
    if not heading:
        return None
    tail = str(document_text)[heading.end() :]
    article = re.search(
        r"(?:^|\n)\s*[“‘\"']?\s*(Art\.?\s*\d{1,4}\b[\s\S]{1,1600})",
        tail,
        re.IGNORECASE,
    )
    if not article:
        return None
    candidate = article.group(1)
    candidate = re.split(r"[”’\"»]", candidate, maxsplit=1)[0]
    # PDF text extraction often flattens columns and line breaks. Stop at the
    # next top-level article marker even when it is on the same extracted line,
    # while leaving lower-case references such as "art. 51" inside the clause.
    next_article = re.search(
        r"\bArt\.?\s*\d{1,4}\s*[º°]?\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])",
        candidate[1:],
    )
    if next_article:
        candidate = candidate[:1] + candidate[1 : next_article.start()]
    candidate = re.sub(r"\s+", " ", candidate).strip(" \t\r\n“‘”’\"'")
    return candidate if 12 <= len(candidate) <= 1200 else None


def _original_pdf_url(client: Any, value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("url") or value.get("href")
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        from urllib.parse import urlparse

        base = urlparse(client.base_url)
        raw = base._replace(path=raw, params="", query="", fragment="").geturl()
    try:
        return client._validated_sapl_pdf_url(raw)
    except (AttributeError, TypeError, ValueError):
        return None


def lookup_explicit_matter_sources(question: str) -> list[dict[str, Any]]:
    """Lookup exact references without sending the free-form question to SAPL."""
    if not getattr(settings, "SAPL_MATTER_LOOKUP_ENABLED", False):
        return []
    references = parse_explicit_matter_references(question)
    if not references:
        return []

    from src.clients.sapl.sapl_client import SaplAPIClient

    client = SaplAPIClient(timeout=5, max_retries=0)
    try:
        matches = client.fetch_materias_by_references(references)
        sources = []
        for reference in references:
            key = (_normalized_label(reference["tipo"]), reference["numero"], reference["ano"])
            for record in matches.get(key, []):
                matter_id = record.get("_jurix_materia_id")
                try:
                    official_url = client.get_public_materia_url(matter_id)
                except (TypeError, ValueError):
                    continue
                title = f'{reference["tipo"]} nº {reference["numero"]}/{reference["ano"]}'
                original_document = None
                if _PROPOSED_WORDING_REQUEST_RE.search(question):
                    try:
                        detail = client.fetch_materia_by_id(matter_id)
                        original_pdf_url = _original_pdf_url(
                            client, detail.get("texto_original")
                        )
                        if original_pdf_url:
                            original_text, original_pages = client.read_pdf_text(
                                original_pdf_url, include_pages=True
                            )
                            proposed_text = _extract_proposed_wording(original_text)
                            if proposed_text:
                                normalized_clause = re.sub(r"\s+", " ", proposed_text).strip()
                                page_number = next(
                                    (
                                        page_index
                                        for page_index, page_text in enumerate(
                                            original_pages, start=1
                                        )
                                        if normalized_clause
                                        in re.sub(r"\s+", " ", page_text).strip()
                                    ),
                                    None,
                                )
                                original_document = {
                                    "citation_id": f"sapl:materia:{matter_id}:texto-original",
                                    "citation_label": f"{title}, Texto Original",
                                    "norma_ref": title,
                                    "dispositivo_ref": "Texto Original — redação proposta",
                                    "source_kind": "sapl_matter_original_pdf",
                                    "source_type": "Texto original da proposição — PDF oficial SAPL",
                                    "evidence_scope": "official_legislative_matter_document",
                                    "contribution": (
                                        "Trecho do documento original anexado à proposição; "
                                        "não é norma promulgada nem comprova vigência."
                                    ),
                                    "full_text": proposed_text,
                                    "text": proposed_text[:200],
                                    "page": page_number,
                                    "pdf_url": original_pdf_url,
                                    "sapl_url": official_url,
                                    "matter_id": matter_id,
                                }
                    except Exception as exc:
                        # Failure to retrieve an attachment must not erase the
                        # official matter record or imply the file is absent.
                        import logging

                        logging.getLogger(__name__).warning(
                            "Could not inspect official SAPL matter attachment (%s)",
                            type(exc).__name__,
                        )
                in_progress = record.get("em_tramitacao")
                status_label = (
                    "Em tramitação no SAPL"
                    if in_progress is True
                    else "Fora de tramitação no SAPL"
                    if in_progress is False
                    else "Situação não informada pelo SAPL"
                )
                consulted_at = timezone.localtime(timezone.now())
                ementa = str(record.get("ementa") or "").strip()
                if not ementa:
                    ementa = "O registro oficial não forneceu ementa legível."
                sources.append(
                    {
                        "id": f"sapl-materia-{matter_id}",
                        "citation_id": f"sapl:materia:{matter_id}",
                        "citation_label": title,
                        "norma_ref": title,
                        "dispositivo_ref": "Matéria legislativa",
                        "source_kind": "sapl_legislative_matter",
                        "source_type": "Matéria legislativa — registro oficial SAPL",
                        "evidence_scope": "official_legislative_matter",
                        "match_kind": "explicit_reference",
                        "contribution": (
                            "Ementa e metadados de tramitação; não é norma promulgada "
                            "nem comprova vigência ou resultado legislativo."
                        ),
                        "status_label": status_label,
                        "consulted_at": consulted_at.isoformat(timespec="seconds"),
                        "consulted_at_label": consulted_at.strftime("%d/%m/%Y %H:%M %Z").strip(),
                        "matter_status": in_progress,
                        "matter_result": record.get("resultado") or None,
                        "data_publicacao": record.get("data_publicacao") or None,
                        "full_text": ementa,
                        "text": ementa[:200],
                        "sapl_url": official_url,
                        "source_url": official_url,
                        "similarity_score": None,
                        "_matter_id": matter_id,
                        "_original_document": original_document,
                    }
                )
        return sources
    except Exception:
        # SAPL is supplemental context. A transient external failure must not
        # fail local legal retrieval or imply that no matter exists.
        return []
    finally:
        client.session.close()


def _matter_ementa_mentions_target(
    ementa: str,
    *,
    type_key: str,
    number: str,
    year: int,
    article: str | None,
) -> bool:
    """Require an exact act reference and, when given, the article in its ementa."""
    text = _normalized_label(ementa)
    type_patterns = {
        "lei_complementar": r"(?:lei\s+complementar|lc)",
        "lei_organica": r"(?:lei\s+organica|lo)",
        "lei": r"lei(?!\s+(?:complementar|organica|promulgada))",
        "decreto": r"decreto(?!\s+(?:legislativo|lei))",
        "decreto_legislativo": r"decreto\s+legislativo",
        "decreto_lei": r"decreto-lei",
        "resolucao": r"resolucao",
        "portaria": r"portaria",
    }
    type_pattern = type_patterns.get(type_key)
    if not type_pattern:
        return False
    number_digits = re.sub(r"\D", "", str(number))
    number_pattern = re.escape(number_digits[:1]) + "".join(
        rf"[.\s]?{re.escape(digit)}" for digit in number_digits[1:]
    )
    norm_match = re.search(
        rf"\b{type_pattern}\b[^0-9]{{0,16}}{number_pattern}\b.{{0,100}}\b{year}\b",
        text,
    )
    if not norm_match:
        return False
    if article is None:
        return True
    article_match = re.search(rf"\bart(?:igo)?\.?\s*{re.escape(article)}\b", text)
    if not article_match:
        return False
    return abs(norm_match.start() - article_match.start()) <= 180


def lookup_related_matter_result(
    question: str, *, include_exact_article: bool = False
) -> RelatedMatterLookupResult:
    """Find related SAPL proposals and preserve whether the public search completed.

    Exact article lookups may opt into a bounded proposal check so the archive
    can surface a pending matter that explicitly cites the same provision.
    """
    if not getattr(settings, "SAPL_MATTER_LOOKUP_ENABLED", False):
        return RelatedMatterLookupResult("disabled")
    from src.processing.normative_query import classify_normative_query

    query_plan = classify_normative_query(question)
    explicit_article_lookup = (
        include_exact_article
        and query_plan.kind == "provision"
        and len(query_plan.article_targets) == 1
        and query_plan.reference is not None
        and query_plan.reference.year is not None
        and not query_plan.reference.ambiguous
    )
    if query_plan.relation_intent not in {"modification", "mixed"} and not explicit_article_lookup:
        return RelatedMatterLookupResult("not_applicable")
    references = tuple(
        reference
        for reference in parse_normative_references(question)
        if reference.year is not None and not reference.ambiguous
    )
    if len(references) != 1:
        return RelatedMatterLookupResult("not_applicable")
    reference = references[0]
    article = reference.article
    if article is None and not (
        query_plan.relation_intent in {"modification", "mixed"}
        and not explicit_article_lookup
    ):
        return RelatedMatterLookupResult("not_applicable")
    type_labels = {
        "lei_complementar": "Lei Complementar",
        "lei_organica": "Lei Orgânica",
        "lei": "Lei",
        "decreto": "Decreto",
        "decreto_legislativo": "Decreto Legislativo",
        "decreto_lei": "Decreto-Lei",
        "resolucao": "Resolução",
        "portaria": "Portaria",
    }
    norm_label = type_labels.get(reference.type_key)
    if not norm_label:
        return RelatedMatterLookupResult("not_applicable")

    from src.clients.sapl.sapl_client import SaplAPIClient

    client = None
    sources = []
    search_completed = False
    try:
        client = SaplAPIClient(timeout=5, max_retries=0)
        expression = (
            f"Art. {article} {norm_label} {reference.number} {reference.year}"
            if article
            else f"{norm_label} {reference.number} {reference.year}"
        )
        candidates = client.search_public_materias_by_ementa(expression)
        search_completed = True
        seen_ids = set()
        for candidate in candidates:
            matter_type = _normalized_label(candidate.get("tipo__descricao") or "")
            if not (
                matter_type.startswith("projeto de lei")
                or matter_type.startswith("projeto de decreto")
                or matter_type.startswith("emenda")
            ):
                continue
            try:
                matter_id = int(candidate.get("id"))
            except (TypeError, ValueError):
                continue
            if matter_id <= 0 or matter_id in seen_ids:
                continue
            candidate_ementa = str(candidate.get("ementa") or "").strip()
            if not _matter_ementa_mentions_target(
                candidate_ementa,
                type_key=reference.type_key,
                number=reference.number,
                year=reference.year,
                article=article,
            ):
                continue
            record = client.fetch_materia_by_id(matter_id)
            record_ementa = str(record.get("ementa") or "").strip()
            if (
                str(record.get("id") or "") != str(matter_id)
                or not _matter_ementa_mentions_target(
                    record_ementa,
                    type_key=reference.type_key,
                    number=reference.number,
                    year=reference.year,
                    article=article,
                )
            ):
                continue
            try:
                official_url = client.get_public_materia_url(matter_id)
            except (TypeError, ValueError):
                continue
            title = (
                f"{str(record.get('tipo__descricao') or candidate.get('tipo__descricao') or 'Matéria legislativa')} "
                f"nº {record.get('numero') or candidate.get('numero')}/"
                f"{record.get('ano') or candidate.get('ano')}"
            )
            status = record.get("em_tramitacao")
            status_label = (
                "Em tramitação no SAPL"
                if status is True
                else "Fora de tramitação no SAPL"
                if status is False
                else "Situação não informada pelo SAPL"
            )
            consulted_at = timezone.localtime(timezone.now())
            updated_at = record.get("data_ultima_atualizacao")
            sources.append(
                {
                    "id": f"sapl-materia-{matter_id}",
                    "citation_id": f"sapl:materia:{matter_id}",
                    "citation_label": title,
                    "norma_ref": title,
                    "dispositivo_ref": "Matéria legislativa",
                    "source_kind": "sapl_legislative_matter",
                    "source_type": "Matéria legislativa — registro oficial SAPL",
                    "evidence_scope": "official_legislative_matter",
                    "match_kind": (
                        "official_ementa_explicit_article_and_norm_reference"
                        if article
                        else "official_ementa_explicit_norm_reference"
                    ),
                    "contribution": (
                        (
                            "Ementa cita expressamente a norma e o dispositivo; a matéria "
                            if article
                            else "Ementa cita expressamente a norma; a matéria "
                        )
                        + "não é lei promulgada e a correspondência não confirma efeito modificador."
                    ),
                    "relation_label": (
                        f"{norm_label} nº {reference.number}/{reference.year}"
                        + (f", Art. {article}" if article else "")
                    ),
                    "status_label": status_label,
                    "consulted_at": consulted_at.isoformat(timespec="seconds"),
                    "consulted_at_label": consulted_at.strftime("%d/%m/%Y %H:%M %Z").strip(),
                    "matter_status": status,
                    "matter_result": record.get("resultado") or None,
                    "data_publicacao": record.get("data_publicacao") or None,
                    "matter_updated_at": updated_at or None,
                    "matter_updated_at_label": _sapl_timestamp_label(updated_at),
                    "full_text": record_ementa or candidate_ementa,
                    "text": (record_ementa or candidate_ementa)[:200],
                    "sapl_url": official_url,
                    "source_url": official_url,
                    "similarity_score": None,
                    "_matter_id": matter_id,
                }
            )
            seen_ids.add(matter_id)
            if len(sources) >= 5:
                break
        return RelatedMatterLookupResult("searched", tuple(sources))
    except Exception:
        # Neither an outage nor a partially validated result list proves absence.
        return RelatedMatterLookupResult(
            "partial" if search_completed else "unavailable",
            tuple(sources),
        )
    finally:
        if client is not None:
            client.session.close()


def lookup_related_matter_sources(question: str) -> list[dict[str, Any]]:
    """Compatibility helper for callers that need only matching source rows."""
    return list(lookup_related_matter_result(question).sources)
