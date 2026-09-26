"""Deterministic temporal reasoning for municipal-law retrieval and audit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q
from django.utils import timezone


@dataclass(frozen=True)
class TemporalScope:
    """Validated historical/publication constraints for a retrieval request."""

    as_of: date | None = None
    published_from: date | None = None
    published_to: date | None = None

    def fingerprint(self) -> str:
        return (
            f"as_of={self.as_of.isoformat() if self.as_of else 'none'};"
            f"from={self.published_from.isoformat() if self.published_from else 'none'};"
            f"to={self.published_to.isoformat() if self.published_to else 'none'}"
        )

    def contains_publication(self, publication: date | None) -> bool:
        if publication is None:
            return True
        if self.published_from and publication < self.published_from:
            return False
        if self.published_to and publication > self.published_to:
            return False
        if self.as_of and publication > self.as_of:
            return False
        return True


def parse_iso_date(value: Any, field_name: str) -> date | None:
    """Parse an ISO calendar date and produce a stable public validation error."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} deve estar no formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} deve estar no formato AAAA-MM-DD.") from exc


def temporal_state_from_dates(norma) -> str:
    """Cheap state used by serializers; intentionally performs no database query."""
    today = timezone.localdate()
    publication = getattr(norma, "data_publicacao", None)
    effective = getattr(norma, "data_vigencia", None)
    if publication and today < publication:
        return "futura"
    if effective and today < effective:
        return "vacatio_legis"
    if not publication and not effective:
        return "data_indeterminada"
    return "vigente"


def revoked_norma_ids(norma_ids: Iterable[int], as_of: date | None) -> set[int]:
    """Bulk-resolve recorded revocations for one retrieval request."""
    ids = {int(item) for item in norma_ids if item}
    if not ids or as_of is None:
        return set()

    from src.apps.legislation.models import EventoAlteracao

    events = (
        EventoAlteracao.objects.filter(acao="REVOGA")
        .filter(Q(norma_alvo_id__in=ids) | Q(dispositivo_alvo__norma_id__in=ids))
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo")
    )
    revoked: set[int] = set()
    for event in events:
        source_norma = getattr(event.dispositivo_fonte, "norma", None)
        source_date = getattr(source_norma, "data_publicacao", None)
        if source_date is not None and source_date > as_of:
            continue
        if event.norma_alvo_id:
            revoked.add(int(event.norma_alvo_id))
    return revoked


def revoked_dispositivo_ids(norma_ids: Iterable[int], as_of: date | None) -> set[int]:
    """Return device-level revocations without invalidating the containing norma."""
    ids = {int(item) for item in norma_ids if item}
    if not ids or as_of is None:
        return set()
    from src.apps.legislation.models import EventoAlteracao

    events = EventoAlteracao.objects.filter(
        acao="REVOGA",
        dispositivo_alvo__norma_id__in=ids,
    ).select_related("dispositivo_fonte__norma")
    revoked: set[int] = set()
    for event in events:
        source_norma = getattr(event.dispositivo_fonte, "norma", None)
        source_date = getattr(source_norma, "data_publicacao", None)
        if source_date is not None and source_date <= as_of and event.dispositivo_alvo_id:
            revoked.add(int(event.dispositivo_alvo_id))
    return revoked


def temporal_status(norma, *, as_of: date | None = None) -> str:
    """Return a conservative temporal state, including recorded revocation."""
    when = as_of or timezone.localdate()
    publication = getattr(norma, "data_publicacao", None)
    effective = getattr(norma, "data_vigencia", None)

    if publication and when < publication:
        return "futura"
    if effective and when < effective:
        return "vacatio_legis"

    revoked = revoked_norma_ids([getattr(norma, "id", 0)], when)
    if int(getattr(norma, "id", 0) or 0) in revoked:
        return "revogada"
    if not publication and not effective:
        return "data_indeterminada"
    return "vigente"


def matches_temporal_scope(
    norma,
    scope: TemporalScope,
    revoked_ids: set[int] | None = None,
) -> bool:
    """Apply explicit publication/effectivity bounds and optional bulk revocation IDs."""
    publication = getattr(norma, "data_publicacao", None)
    if not scope.contains_publication(publication):
        return False
    if scope.as_of is None:
        return True
    effective = getattr(norma, "data_vigencia", None)
    if effective and effective > scope.as_of:
        return False
    if revoked_ids and int(getattr(norma, "id", 0) or 0) in revoked_ids:
        return False
    return True


def build_norma_timeline(norma, *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Build an auditable timeline, optionally cut at a historical date."""
    from src.apps.legislation.models import EventoAlteracao

    items: list[dict[str, Any]] = []
    if norma.data_publicacao and (as_of is None or norma.data_publicacao <= as_of):
        items.append(
            {
                "kind": "publication",
                "date": norma.data_publicacao.isoformat(),
                "title": "Publicação",
                "description": f"{norma} publicada no corpus municipal.",
                "source_norma": str(norma),
                "confidence": 1.0,
            }
        )
    if norma.data_vigencia and (as_of is None or norma.data_vigencia <= as_of):
        items.append(
            {
                "kind": "effective",
                "date": norma.data_vigencia.isoformat(),
                "title": "Início da vigência",
                "description": f"Vigência indicada para {norma}.",
                "source_norma": str(norma),
                "confidence": 1.0,
            }
        )

    events = (
        EventoAlteracao.objects.filter(Q(norma_alvo=norma) | Q(dispositivo_alvo__norma=norma))
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo", "norma_alvo")
        .order_by("dispositivo_fonte__norma__data_publicacao", "created_at", "id")
    )
    for event in events:
        source = event.dispositivo_fonte.norma
        source_date = source.data_publicacao
        if as_of is not None and source_date and source_date > as_of:
            continue
        items.append(
            {
                "kind": "event",
                "date": source_date.isoformat() if source_date else None,
                "title": event.get_acao_display(),
                "description": event.get_descricao_completa(),
                "source_norma": str(source),
                "source_norma_id": source.id,
                "target_text": event.target_text,
                "target_dispositivo_id": event.dispositivo_alvo_id,
                "validated": bool(event.validado),
                "confidence": float(event.extraction_confidence or 0.0),
            }
        )
    items.sort(key=lambda item: (item["date"] or "9999-99-99", item["kind"], item["title"]))
    return items
