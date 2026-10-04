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
    normalize_document_number,
)
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
    """Parse one explicit type/number/year; never inherit the source norm's year."""
    text = str(getattr(event, "target_text", "") or "")
    references = parse_normative_references(text)
    if len(references) > 1:
        return None
    parsed = references[0] if references else None
    display_type = parsed.type_key if parsed else ""
    display_number = parsed.number if parsed else ""
    year = parsed.year if parsed else None
    jurisdiction = "unknown"
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
            and not jurisdiction.startswith("MUNICIPIO")
        ):
            continue
        if series and reference.series and series != reference.series:
            continue
        matched.append(norma)
        if len(matched) > 1:
            break
    return matched


def resolve_event_target(
    event: EventoAlteracao,
    *,
    target_norma_ids: Iterable[int] | None = None,
) -> bool:
    """CAS-update a unique target; return whether a relation exists after the call."""
    if getattr(event, "norma_alvo_id", None):
        return True
    reference = parse_target_reference(event)
    if reference is None:
        _record_unresolved(event, None, "unresolved_or_ambiguous_reference")
        return False
    if reference.jurisdiction in _EXPLICIT_EXTERNAL_SCOPES:
        _record_unresolved(event, reference, "external_jurisdiction")
        return False

    scope = set(int(value) for value in target_norma_ids) if target_norma_ids is not None else None
    matched = _candidate_normas(reference, scope)
    if len(matched) != 1:
        status = "ambiguous_multiple_candidates" if len(matched) > 1 else "not_found_in_corpus"
        _record_unresolved(event, reference, status)
        return False

    target = matched[0]
    result_json = _outcome(
        reference,
        "resolved_unreviewed",
        existing=(
            event.target_reference_json
            if isinstance(getattr(event, "target_reference_json", None), dict)
            else {}
        ),
        matched_norma_id=target.pk,
        identity_key=target.identity_key or None,
        match_method="identity_key" if target.identity_key else "unique_legacy_type_number_year",
    )
    with transaction.atomic():
        changed = EventoAlteracao.objects.filter(pk=event.pk, norma_alvo__isnull=True).update(
            norma_alvo_id=target.pk,
            target_reference_json=result_json,
        )
        if changed:
            return True
        return EventoAlteracao.objects.filter(pk=event.pk, norma_alvo_id=target.pk).exists()


def reconcile_unresolved_event_targets(
    limit: int = 5000,
    *,
    target_norma_ids: Iterable[int] | None = None,
) -> dict[str, int]:
    """Resolve a bounded set of unresolved events, optionally scoped to new targets."""
    limit = max(1, min(int(limit), 50_000))
    ids = set(int(value) for value in target_norma_ids) if target_norma_ids is not None else None
    events = EventoAlteracao.objects.filter(norma_alvo__isnull=True, is_active=True)
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
        for event in events.order_by("id")[:scan_limit].iterator(chunk_size=500):
            ref = parse_target_reference(event)
            if ref and (ref.type_key, ref.number_key, ref.ano) in reference_keys:
                selected.append(event)
                if len(selected) >= limit:
                    break
        event_list = selected
    else:
        event_list = list(events.select_related("dispositivo_fonte__norma").order_by("id")[:limit])

    inspected = resolved = unresolved = 0
    for event in event_list:
        inspected += 1
        try:
            if resolve_event_target(event, target_norma_ids=ids):
                resolved += 1
            else:
                unresolved += 1
        except Exception:
            unresolved += 1
    return {"inspected": inspected, "resolved": resolved, "remaining_unresolved": unresolved}
