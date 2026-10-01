"""Second-pass reconciliation for legal alteration targets.

Target extraction happens before the whole corpus is necessarily present. A
reference such as ``Lei 8206/2026`` can therefore be unresolved when the
altering norm arrives first. This module stores no guessed relationship: it
only fills ``EventoAlteracao.norma_alvo`` when a deterministic type/number/year
match exists. Unresolved events remain explicitly unresolved and can be
retried after subsequent ingestion batches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from src.apps.legislation.models import EventoAlteracao, Norma
from src.processing.normative_reference import canonical_type, parse_normative_references

REFERENCE_RE = re.compile(
    r"\b(?P<tipo>lei\s+complementar|lei|decreto|resolu(?:c|ç)ão|portaria|emenda)"
    r"(?:\s+(?:municipal|ordinária|do município))?\s*"
    r"(?:n(?:º|o|\.)?\s*)?(?P<numero>[0-9][0-9.]*)"
    r"(?:\s*(?:de|/|-)\s*)?(?P<ano>19[0-9]{2}|20[0-9]{2})?",
    flags=re.IGNORECASE,
)


def _normalize_number(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_type(value: str) -> str:
    return canonical_type(value)


@dataclass(frozen=True)
class TargetReference:
    tipo: str
    numero: str
    ano: int | None


def parse_target_reference(event: EventoAlteracao) -> TargetReference | None:
    tipo = getattr(event, "referencia_tipo", None)
    numero = getattr(event, "referencia_numero", None)
    ano = None
    if (
        tipo
        and numero
        and _normalize_type(tipo)
        in {"lei", "lei complementar", "decreto", "resolucao", "portaria", "emenda"}
    ):
        match_year = re.search(
            r"\b(19\d{2}|20\d{2})\b", str(getattr(event, "target_text", "") or "")
        )
        if match_year:
            ano = int(match_year.group(1))
        parts = str(numero).split("/")
        if len(parts) == 2 and re.fullmatch(r"(19|20)\d{2}", parts[1]):
            numero, ano = parts[0], int(parts[1])
        if ano is None:
            return None
        return TargetReference(str(tipo), str(numero), ano)

    text = str(getattr(event, "target_text", "") or "")
    references = parse_normative_references(text)
    if len(references) == 1 and not references[0].ambiguous:
        reference = references[0]
        match = REFERENCE_RE.search(text)
        display_number = match.group("numero") if match else reference.number
        return TargetReference(reference.type_key, display_number, reference.year)
    match = REFERENCE_RE.search(text)
    if not match or not match.group("ano"):
        return None
    parsed_year = match.group("ano")
    return TargetReference(
        tipo=match.group("tipo"),
        numero=match.group("numero"),
        ano=int(parsed_year) if parsed_year else None,
    )


def resolve_event_target(event: EventoAlteracao) -> bool:
    reference = parse_target_reference(event)
    if reference is None:
        return False

    # An amendment may refer to a much older law. Never guess its year
    # from the amending norm; without a year require an unambiguous match.
    expected_year = reference.ano
    type_key = _normalize_type(reference.tipo)
    number_key = _normalize_number(reference.numero)
    if not type_key or not number_key:
        return False

    candidates = Norma.objects.all()
    if expected_year:
        candidates = candidates.filter(ano=expected_year)
    candidates = candidates.filter(tipo__icontains=reference.tipo.split()[0])

    matched = []
    for norma in candidates.only("id", "tipo", "numero", "ano"):
        if _normalize_type(norma.tipo) != type_key:
            continue
        if _normalize_number(norma.numero) != number_key:
            continue
        matched.append(norma)
        if len(matched) > 1:
            return False

    if len(matched) != 1:
        return False

    target = matched[0]
    if getattr(event, "norma_alvo_id", None) == target.id:
        return True
    with transaction.atomic():
        changed = EventoAlteracao.objects.filter(pk=event.pk, norma_alvo__isnull=True).update(
            norma_alvo_id=target.id
        )
    return bool(changed)


def reconcile_unresolved_event_targets(limit: int = 5000) -> dict[str, int]:
    """Resolve a bounded number of previously unresolved alteration events."""
    events = (
        EventoAlteracao.objects.filter(norma_alvo__isnull=True, is_active=True)
        .select_related("dispositivo_fonte__norma")
        .order_by("id")[: max(1, min(int(limit), 50_000))]
    )
    inspected = resolved = ambiguous = 0
    for event in events:
        inspected += 1
        try:
            if resolve_event_target(event):
                resolved += 1
            else:
                ambiguous += 1
        except Exception:
            ambiguous += 1
    return {"inspected": inspected, "resolved": resolved, "remaining_unresolved": ambiguous}
