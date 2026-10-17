"""Conservative second-pass reconciliation for normative alteration targets.

References are linked only when type, number, year and the available scope
resolve to exactly one existing Norma. The event JSON records an outcome; it
does not constitute legal validation and never changes ``validado``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from src.apps.legislation.models import EventoAlteracao, Norma
from src.processing.document_metadata import (
    TYPE_SERIES,
    build_normative_identity,
    is_natal_municipal_jurisdiction,
    normalize_document_number,
)
from src.processing.event_revision import event_revision_for_target
from src.processing.normative_reference import canonical_type, parse_normative_references

_REFERENCE_SCOPE_RE = re.compile(
    r"\b(?P<type>lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica|promulgada))?|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?|resolu[çc][ãa]o|portaria|"
    r"emenda(?:\s+constitucional)?)\s+"
    r"(?:(?P<scope>municipal|federal|estadual|distrital)(?:\s+de\s+[\wÀ-ÿ -]+?)?\s+)?"
    r"(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)\s*(?:/|de)\s*(?P<year>(?:19|20)\d{2})",
    flags=re.IGNORECASE,
)
_EXPLICIT_EXTERNAL_SCOPES = {"federal", "estadual", "distrital"}
_ALLOWED_TYPES = {
    "lei",
    "lei_complementar",
    "lei_organica",
    "lei_promulgada",
    "decreto",
    "decreto_legislativo",
    "decreto_lei",
    "resolucao",
    "portaria",
    "emenda",
    "emenda_constitucional",
}


def _normalize_number(value) -> str:
    return normalize_document_number(value)


@dataclass(frozen=True)
class TargetReference:
    tipo: str
    numero: str
    ano: int
    jurisdiction: str = "unknown"

    @property
    def type_key(self) -> str:
        return canonical_type(self.tipo)

    @property
    def number_key(self) -> str:
        return _normalize_number(self.numero)

    @property
    def series(self) -> str | None:
        if self.jurisdiction in _EXPLICIT_EXTERNAL_SCOPES:
            return None
        return TYPE_SERIES.get(self.type_key)


def parse_target_reference(event: EventoAlteracao) -> TargetReference | None:
    """Parse one explicit type/number/year; never inherit the source norm's year.

    Entity extraction intentionally stores a structural target (for example,
    ``Art. 14``) separately from the cited statute. In that case the exact
    evidence span and the structured NER metadata are the citation source; do
    not require the short display label in ``target_text`` to repeat it.
    """
    text = str(getattr(event, "target_text", "") or "")
    references = parse_normative_references(text)
    if len(references) > 1:
        return None
    parsed = references[0] if references else None
    if parsed is None:
        evidence = getattr(event, "evidence_json", {})
        evidence = evidence if isinstance(evidence, dict) else {}
        evidence_text = str(evidence.get("target_quote") or evidence.get("quote") or "")
        evidence_references = parse_normative_references(evidence_text)
        if len(evidence_references) > 1:
            return None
        if evidence_references:
            text = evidence_text
            references = evidence_references
            parsed = references[0]

    # Explicit jurisdiction prefixes are intentionally parsed by this richer
    # matcher (the generic citation parser accepts only the municipal label).
    scoped_matches = list(_REFERENCE_SCOPE_RE.finditer(text))
    if len(scoped_matches) > 1:
        return None
    if scoped_matches and parsed is None:
        match = scoped_matches[0]
        display_type = match.group("type")
        display_number = match.group("number").rstrip(".,;:")
        year = int(match.group("year"))
        jurisdiction = (match.group("scope") or "unknown").lower()
        if canonical_type(display_type) in _ALLOWED_TYPES:
            return TargetReference(display_type, display_number, year, jurisdiction)

    structured = getattr(event, "target_reference_json", {})
    structured = structured if isinstance(structured, dict) else {}
    if parsed is None:
        # Only use metadata emitted as a single, explicit NER candidate. Do not
        # turn a generic unresolved/ambiguous result into a resolvable citation.
        if structured.get("resolution_status") not in {"candidate", "resolved_unreviewed"}:
            return None
        raw_type = str(structured.get("type_candidate") or "").strip()
        canonical_types = {
            "lei": "Lei",
            "lei_complementar": "Lei Complementar",
            "lei_organica": "Lei Orgânica",
            "lei_promulgada": "Lei Promulgada",
            "decreto": "Decreto",
            "decreto_legislativo": "Decreto Legislativo",
            "decreto_lei": "Decreto-Lei",
            "resolucao": "Resolução",
            "portaria": "Portaria",
            "emenda": "Emenda",
            "emenda_constitucional": "Emenda Constitucional",
        }
        display_type = canonical_types.get(raw_type.casefold(), raw_type)
        display_number = str(structured.get("number_candidate") or "").strip().rstrip(".,;:")
        try:
            year = int(structured.get("year_candidate"))
        except (TypeError, ValueError):
            return None
        if (
            canonical_type(display_type) not in _ALLOWED_TYPES
            or not _normalize_number(display_number)
            or not 1900 <= year <= 2099
        ):
            return None
        jurisdiction = str(
            structured.get("jurisdiction_status")
            or structured.get("jurisdiction_candidate")
            or "unknown"
        ).strip().lower()
        return TargetReference(display_type, display_number, year, jurisdiction)

    display_type = parsed.type_key if parsed else ""
    display_number = parsed.number if parsed else ""
    year = parsed.year if parsed else None
    jurisdiction = str(
        structured.get("jurisdiction_status") or "unknown"
    ).strip().lower()
    for match in _REFERENCE_SCOPE_RE.finditer(text):
        if (
            (not parsed or canonical_type(match.group("type")) == parsed.type_key)
            and (
                not parsed
                or normalize_document_number(match.group("number"))
                == _normalize_number(parsed.number)
            )
            and (not year or int(match.group("year")) == year)
        ):
            display_type = match.group("type")
            display_number = match.group("number")
            year = int(match.group("year"))
            jurisdiction = (match.group("scope") or "").lower() or "unknown"
            break
    if not year or canonical_type(display_type) not in _ALLOWED_TYPES:
        return None
    return TargetReference(display_type, display_number, int(year), jurisdiction)


def _outcome(
    reference: TargetReference | None,
    status: str,
    *,
    existing: dict | None = None,
    **extra,
) -> dict:
    payload = dict(existing or {})
    payload.update(
        {
            "schema_version": 2,
            "kind": "normative_reference" if reference else "unresolved_reference",
            "resolution_status": status,
            "jurisdiction_status": reference.jurisdiction if reference else "unknown",
            "checked_at": timezone.now().isoformat(),
        }
    )
    if reference:
        payload.update(
            {
                "type_candidate": reference.type_key,
                "series_candidate": reference.series,
                "number_candidate": reference.number_key,
                "year_candidate": reference.ano,
            }
        )
        if reference.jurisdiction in _EXPLICIT_EXTERNAL_SCOPES:
            payload["external_identity_key"] = "|".join(
                (
                    reference.jurisdiction.upper(),
                    reference.type_key,
                    reference.number_key,
                    str(reference.ano),
                )
            )
    payload.update(extra)
    return payload


def _record_unresolved(
    event: EventoAlteracao, reference: TargetReference | None, status: str
) -> None:
    existing = getattr(event, "target_reference_json", {})
    EventoAlteracao.objects.filter(pk=event.pk, norma_alvo__isnull=True).update(
        target_reference_json=_outcome(
            reference,
            status,
            existing=existing if isinstance(existing, dict) else {},
        )
    )


def _candidate_normas(reference: TargetReference, target_norma_ids: set[int] | None):
    candidates = Norma.objects.filter(ano=reference.ano)
    if target_norma_ids is not None:
        if not target_norma_ids:
            return []
        candidates = candidates.filter(pk__in=target_norma_ids)
    if reference.jurisdiction == "municipal" and reference.series:
        expected = build_normative_identity(
            jurisdiction="Município de Natal",
            raw_type=reference.tipo,
            series=reference.series,
            number=reference.numero,
            year=reference.ano,
        )
        if expected.identity_key:
            exact = candidates.filter(identity_key=expected.identity_key)
            if exact.exists():
                return list(exact[:2])

    matched = []
    for norma in candidates.only("id", "tipo", "numero", "ano", "identity_key", "identity_json"):
        if canonical_type(norma.tipo) != reference.type_key:
            continue
        if _normalize_number(norma.numero) != reference.number_key:
            continue
        identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        jurisdiction = str(identity.get("jurisdiction") or "").casefold()
        series = identity.get("series")
        if reference.jurisdiction in _EXPLICIT_EXTERNAL_SCOPES:
            continue
        if (
            reference.jurisdiction == "municipal"
            and jurisdiction
            and not is_natal_municipal_jurisdiction(jurisdiction)
        ):
            continue
        if series and reference.series and series != reference.series:
            continue
        matched.append(norma)
        if len(matched) > 1:
            break
    return matched


def inspect_event_target_resolution(
    event: EventoAlteracao,
    *,
    target_norma_ids: Iterable[int] | None = None,
) -> dict:
    """Return the exact second-pass decision without mutating an event or relation."""
    if getattr(event, "norma_alvo_id", None):
        return {"status": "already_linked", "target_norma_id": event.norma_alvo_id}
    reference = parse_target_reference(event)
    if reference is None:
        return {"status": "unresolved_or_ambiguous_reference", "target_norma_id": None}
    if reference.jurisdiction in _EXPLICIT_EXTERNAL_SCOPES:
        return {"status": "external_jurisdiction", "target_norma_id": None}

    scope = set(int(value) for value in target_norma_ids) if target_norma_ids is not None else None
    matched = _candidate_normas(reference, scope)
    if len(matched) != 1:
        status = "ambiguous_multiple_candidates" if len(matched) > 1 else "not_found_in_corpus"
        return {"status": status, "target_norma_id": None}

    target = matched[0]
    return {
        "status": "resolved_unreviewed",
        "target_norma_id": target.pk,
        "identity_key": target.identity_key or None,
        "match_method": "identity_key" if target.identity_key else "unique_legacy_type_number_year",
    }


def resolve_event_target(
    event: EventoAlteracao,
    *,
    target_norma_ids: Iterable[int] | None = None,
) -> bool:
    """CAS-update a unique target; return whether a relation exists after the call."""
    inspected = inspect_event_target_resolution(event, target_norma_ids=target_norma_ids)
    if inspected["status"] == "already_linked":
        return True
    if inspected["status"] != "resolved_unreviewed":
        _record_unresolved(event, parse_target_reference(event), inspected["status"])
        return False

    target_id = inspected["target_norma_id"]
    result_json = _outcome(
        parse_target_reference(event),
        "resolved_unreviewed",
        existing=(
            event.target_reference_json
            if isinstance(getattr(event, "target_reference_json", None), dict)
            else {}
        ),
        matched_norma_id=target_id,
        identity_key=inspected["identity_key"],
        match_method=inspected["match_method"],
    )
    revision_fingerprint, provenance = event_revision_for_target(event, target_id)
    with transaction.atomic():
        changed = EventoAlteracao.objects.filter(pk=event.pk, norma_alvo__isnull=True).update(
            norma_alvo_id=target_id,
            target_reference_json=result_json,
            revision_fingerprint=revision_fingerprint,
            provenance_json=provenance,
        )
        if changed:
            return True
        return EventoAlteracao.objects.filter(pk=event.pk, norma_alvo_id=target_id).exists()


def reconcile_unresolved_event_targets(
    limit: int = 5000,
    *,
    target_norma_ids: Iterable[int] | None = None,
    after_event_id: int = 0,
    max_event_id: int | None = None,
    return_cursor: bool = False,
    dry_run: bool = False,
    include_diagnostics: bool = False,
) -> dict[str, int | bool | None]:
    """Resolve a bounded set of unresolved events, optionally scoped to new targets."""
    limit = max(1, min(int(limit), 50_000))
    ids = set(int(value) for value in target_norma_ids) if target_norma_ids is not None else None
    events = EventoAlteracao.objects.filter(
        norma_alvo__isnull=True, is_active=True, pk__gt=max(0, int(after_event_id))
    )
    if max_event_id is not None:
        events = events.filter(pk__lte=max(0, int(max_event_id)))
    next_cursor = None
    if ids is not None:
        if not ids:
            return {"inspected": 0, "resolved": 0, "remaining_unresolved": 0}
        refs = [
            (norma.tipo, norma.numero, norma.ano)
            for norma in Norma.objects.filter(pk__in=ids).only("tipo", "numero", "ano")
        ]
        # Scope second pass to events whose explicit reference could identify one of
        # the newly arrived targets. The final resolver still checks all identity fields.
        reference_keys = {
            (canonical_type(tipo), _normalize_number(numero), int(ano))
            for tipo, numero, ano in refs
        }
        if not reference_keys:
            return {"inspected": 0, "resolved": 0, "remaining_unresolved": 0}
        events = events.select_related("dispositivo_fonte__norma")
        selected = []
        scan_limit = min(50_000, max(limit, limit * 20))
        scanned = 0
        for event in events.order_by("id").iterator(chunk_size=500):
            if scanned >= scan_limit:
                break
            scanned += 1
            next_cursor = event.pk
            ref = parse_target_reference(event)
            if ref and (ref.type_key, ref.number_key, ref.ano) in reference_keys:
                selected.append(event)
                if len(selected) >= limit:
                    break
        event_list = selected
    else:
        event_list = list(events.select_related("dispositivo_fonte__norma").order_by("id")[:limit])
        next_cursor = event_list[-1].pk if event_list else None

    inspected = resolved = unresolved = 0
    status_counts: dict[str, int] = {}
    diagnostics = []
    for event in event_list:
        inspected += 1
        if dry_run:
            resolution = inspect_event_target_resolution(event, target_norma_ids=ids)
            status = resolution["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            is_resolved = status in {"resolved_unreviewed", "already_linked"}
            if include_diagnostics:
                references = parse_normative_references(
                    str(getattr(event, "target_text", "") or "")
                )
                parsed = parse_target_reference(event)
                source_device = event.dispositivo_fonte
                source_norma = source_device.norma
                identity = (
                    source_norma.identity_json
                    if isinstance(source_norma.identity_json, dict)
                    else {}
                )
                diagnostics.append(
                    {
                        "synthetic_fixture": identity.get("synthetic_fixture") is True,
                        "source_norma": {
                            "type": source_norma.tipo,
                            "number": source_norma.numero,
                            "year": source_norma.ano,
                        },
                        "source_device": {
                            "type": source_device.tipo,
                            "number": source_device.numero,
                        },
                        "action": event.acao,
                        "reference_count": len(references),
                        "parsed_reference": (
                            {
                                "type": parsed.type_key,
                                "number": parsed.number_key,
                                "year": parsed.ano,
                                "jurisdiction": parsed.jurisdiction,
                            }
                            if parsed
                            else None
                        ),
                        "status": status,
                    }
                )
        else:
            is_resolved = resolve_event_target(event, target_norma_ids=ids)
            status = "resolved_unreviewed" if is_resolved else "unresolved"
            status_counts[status] = status_counts.get(status, 0) + 1
        if is_resolved:
            resolved += 1
        else:
            unresolved += 1
    remaining = EventoAlteracao.objects.filter(
        norma_alvo__isnull=True, is_active=True, pk__gt=next_cursor or max(0, int(after_event_id))
    )
    if max_event_id is not None:
        remaining = remaining.filter(pk__lte=max(0, int(max_event_id)))
    has_more = remaining.exists()
    result = {
        "inspected": inspected,
        "resolved": resolved,
        "remaining_unresolved": unresolved,
    }
    if dry_run:
        result.update({"dry_run": True, "resolution_status_counts": status_counts})
        if include_diagnostics:
            result["diagnostics"] = diagnostics
    if return_cursor:
        result.update({"next_cursor": next_cursor, "has_more": has_more})
    return result
