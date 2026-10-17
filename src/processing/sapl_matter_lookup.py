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


def _explicit_parent_projects(ementa: str) -> list[dict[str, Any]]:
    """Return only a single, explicitly named PLC parent from an amendment ementa."""
    references = parse_explicit_matter_references(ementa)
    projects = [
        reference
        for reference in references
        if reference["tipo"] == "Projeto de Lei Complementar"
    ]
    return projects if len(projects) == 1 else []


def _extract_proposed_effect_clause(
    document_text: str,
    *,
    type_key: str,
    number: str,
    year: int,
    article: str | None,
) -> str | None:
    """Extract an article that proposes an effect on the exact cited norm/device."""
    value = str(document_text or "")
    headings = list(
        re.finditer(
            r"(?m)^\s*Art\.?\s*(\d{1,4})\s*[º°ª]?\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])",
            value,
        )
    )
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(value)
        section = value[heading.start() : end]
        normalized = _normalized_label(section)
        if not re.search(r"\brevog\w*", normalized):
            continue
        if not _matter_ementa_mentions_target(
            section,
            type_key=type_key,
            number=number,
            year=year,
            article=article,
        ):
            continue
        clause = re.sub(r"\s+", " ", section).strip()
        if len(clause) > 1400:
            clause = clause[:1400].rsplit(" ", 1)[0].rstrip(" ,;:")
        return clause if len(clause) >= 24 else None
    return None


def _parent_project_sources(
    client: Any,
    amendment: dict[str, Any],
    *,
    target_type: str,
    target_number: str,
    target_year: int,
    target_article: str | None,
    consulted_at: datetime,
) -> tuple[list[dict[str, Any]], bool]:
    """Add an explicitly named PLC parent and its relevant official PDF excerpt.

    An amendment is not evidence that its parent project was enacted. The
    parent is included only when the amendment ementa names exactly one PLC,
    SAPL resolves that exact identity, and the original PDF contains a
    revocation article naming the queried norm/device.
    """
    parent_references = _explicit_parent_projects(str(amendment.get("ementa") or ""))
    if len(parent_references) != 1:
        return [], False

    reference = parent_references[0]
    key = (
        client._normalize_matter_type_label(reference["tipo"]),
        reference["numero"],
        reference["ano"],
    )
    records_by_reference = client.fetch_materias_by_references([reference])
    records = records_by_reference.get(key, [])
    if len(records) != 1:
        return [], False
    parent = records[0]
    parent_id = parent.get("_jurix_materia_id")
    if not parent_id:
        return [], False
    detail = client.fetch_materia_by_id(parent_id)
    if str(detail.get("id") or "") != str(parent_id):
        return [], False
    if (
        int(detail.get("numero") or 0) != reference["numero"]
        or int(detail.get("ano") or 0) != reference["ano"]
    ):
        return [], False

    parent_title = (
        f"Projeto de Lei Complementar nº {reference['numero']}/{reference['ano']}"
    )
    parent_url = client.get_public_materia_url(parent_id)
    parent_ementa = str(detail.get("ementa") or parent.get("ementa") or "").strip()
    parent_status = detail.get("em_tramitacao")
    sources = [
        {
            "id": f"sapl-materia-{parent_id}",
            "citation_id": f"sapl:materia:{parent_id}",
            "citation_label": parent_title,
            "norma_ref": parent_title,
            "dispositivo_ref": "Matéria legislativa — PLC principal",
            "source_kind": "sapl_legislative_matter",
            "source_type": "Projeto de lei — registro oficial SAPL",
            "evidence_scope": "official_legislative_matter",
            "match_kind": "official_amendment_ementa_explicit_parent_reference",
            "contribution": (
                "PLC principal explicitamente nomeado na ementa da emenda consultada. "
                "O registro de tramitação e o projeto não comprovam promulgação ou vigência."
            ),
            "relation_label": (
                f"Matéria principal da Emenda nº {amendment.get('numero')}/"
                f"{amendment.get('ano')}"
            ),
            "status_label": (
                "Em tramitação no SAPL" if parent_status is True
                else "Fora de tramitação no SAPL" if parent_status is False
                else "Situação não informada pelo SAPL"
            ),
            "consulted_at": consulted_at.isoformat(timespec="seconds"),
            "consulted_at_label": consulted_at.strftime("%d/%m/%Y %H:%M %Z").strip(),
            "matter_status": parent_status,
            "matter_result": detail.get("resultado") or None,
            "data_publicacao": detail.get("data_publicacao") or None,
            "matter_updated_at": detail.get("data_ultima_atualizacao") or None,
            "matter_updated_at_label": _sapl_timestamp_label(
                detail.get("data_ultima_atualizacao")
            ),
            "full_text": parent_ementa or "Ementa não informada pelo SAPL.",
            "text": (parent_ementa or "Ementa não informada pelo SAPL.")[:200],
            "sapl_url": parent_url,
            "source_url": parent_url,
            "similarity_score": None,
            "_matter_id": int(parent_id),
        }
    ]

    original_pdf_url = _original_pdf_url(client, detail.get("texto_original"))
    if not original_pdf_url:
        return sources, False
    try:
        pdf_text, pages = client.read_pdf_text(original_pdf_url, include_pages=True)
    except Exception:
        # Keep the exact SAPL matter record even when its attachment is unavailable.
        return sources, False
    clause = _extract_proposed_effect_clause(
        pdf_text,
        type_key=target_type,
        number=target_number,
        year=target_year,
        article=target_article,
    )
    if not clause:
        return sources, False
    normalized_clause = re.sub(r"\s+", " ", clause).strip()
    page_number = next(
        (
            page_index
            for page_index, page_text in enumerate(pages, start=1)
            if normalized_clause in re.sub(r"\s+", " ", page_text).strip()
        ),
        None,
    )
    article_match = re.match(r"Art\.?\s*(\d+)", clause, re.IGNORECASE)
    proposal_article = article_match.group(1) if article_match else "?"
    sources.append(
        {
            "id": f"sapl-materia-{parent_id}-texto-original-art-{proposal_article}",
            "citation_id": (
                f"sapl:materia:{parent_id}:texto-original:art-{proposal_article}"
            ),
            "citation_label": f"{parent_title}, Art. {proposal_article} (texto proposto)",
            "norma_ref": parent_title,
            "dispositivo_ref": f"Art. {proposal_article} — redação proposta",
            "source_kind": "sapl_matter_original_pdf",
            "source_type": "Texto original da proposição — PDF oficial SAPL",
            "evidence_scope": "official_legislative_matter_document",
            "match_kind": "proposed_revocation_clause_explicitly_names_target_article",
            "contribution": (
                "Trecho do PDF original do PLC que propõe revogação expressa; "
                "não é norma promulgada e não comprova efeito jurídico."
            ),
            "relation_label": (
                f"Proposta sobre {target_type.replace('_', ' ')} nº "
                f"{target_number}/{target_year}"
                + (f", Art. {target_article}" if target_article else "")
            ),
            "full_text": clause,
            "text": clause[:200],
            "page": page_number,
            "pdf_url": original_pdf_url,
            "source_url": original_pdf_url,
            "sapl_url": parent_url,
            "matter_id": int(parent_id),
        }
    )
    return sources, True


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
    parent_lookup_partial = False
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
            if matter_type.startswith("emenda") and article is not None:
                parent_refs = _explicit_parent_projects(record_ementa)
                if parent_refs:
                    try:
                        parent_sources, parent_pdf_verified = _parent_project_sources(
                            client,
                            record,
                            target_type=reference.type_key,
                            target_number=reference.number,
                            target_year=reference.year,
                            target_article=article,
                            consulted_at=consulted_at,
                        )
                    except Exception as exc:
                        parent_sources, parent_pdf_verified = [], False
                        import logging

                        logging.getLogger(__name__).warning(
                            "Could not resolve explicit SAPL amendment parent (%s)",
                            type(exc).__name__,
                        )
                    parent_lookup_partial = parent_lookup_partial or not parent_pdf_verified
                    existing_citations = {
                        str(source.get("citation_id") or "") for source in sources
                    }
                    for parent_source in parent_sources:
                        citation_id = str(parent_source.get("citation_id") or "")
                        if citation_id and citation_id not in existing_citations:
                            sources.append(parent_source)
                            existing_citations.add(citation_id)
            if len(sources) >= 5:
                break
        return RelatedMatterLookupResult(
            "partial" if parent_lookup_partial else "searched",
            tuple(sources),
        )
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
