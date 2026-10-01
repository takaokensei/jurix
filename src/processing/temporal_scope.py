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
            # An explicit historical/publication filter cannot confirm a
            # document whose publication date is unknown.
            return not (self.as_of or self.published_from or self.published_to)
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
        EventoAlteracao.objects.filter(acao="REVOGA", is_active=True)
        .filter(Q(norma_alvo_id__in=ids) | Q(dispositivo_alvo__norma_id__in=ids))
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo")
    )
    revoked: set[int] = set()
    for event in events:
        source_norma = getattr(event.dispositivo_fonte, "norma", None)
        if not event.validado:
            continue
        effective_date = getattr(source_norma, "data_vigencia", None)
        if effective_date is None or effective_date > as_of:
            continue
        # A targeted dispositivo is a partial event; it does not revoke the
        # containing norma as a whole.
        if event.norma_alvo_id and not event.dispositivo_alvo_id:
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
        is_active=True,
        dispositivo_alvo__norma_id__in=ids,
    ).select_related("dispositivo_fonte__norma")
    revoked: set[int] = set()
    for event in events:
        source_norma = getattr(event.dispositivo_fonte, "norma", None)
        effective_date = getattr(source_norma, "data_vigencia", None)
        if (
            event.validado
            and effective_date is not None
            and effective_date <= as_of
            and event.dispositivo_alvo_id
        ):
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
    if not effective:
        return "data_indeterminada"
    if not publication:
        return "data_indeterminada"
    if _partially_revoked(getattr(norma, "id", 0), when):
        return "parcialmente_revogada"
    return "vigente"


def _partially_revoked(norma_id: int, as_of: date) -> bool:
    if not norma_id:
        return False
    from src.apps.legislation.models import EventoAlteracao

    return EventoAlteracao.objects.filter(
        acao="REVOGA",
        validado=True,
        is_active=True,
        dispositivo_alvo__norma_id=norma_id,
        dispositivo_fonte__norma__data_vigencia__isnull=False,
        dispositivo_fonte__norma__data_vigencia__lte=as_of,
    ).exists()


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
    # Historical scope requires both publication and effective dates. Unknown
    # dates are not evidence that the norma was available/in force.
    if effective is None or effective > scope.as_of:
        return False
    if revoked_ids and int(getattr(norma, "id", 0) or 0) in revoked_ids:
        return False
    return True


def build_norma_timeline(norma, *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Build an auditable timeline, optionally cut at a historical date."""
    from src.apps.legislation.models import EventoAlteracao

    def date_display(value: date | str | None) -> str | None:
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
        if value:
            try:
                return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
            except ValueError:
                return None
        return None

    items: list[dict[str, Any]] = []
    if norma.data_publicacao and (as_of is None or norma.data_publicacao <= as_of):
        items.append(
            {
                "kind": "publication",
                "date": norma.data_publicacao.isoformat(),
                "date_display": date_display(norma.data_publicacao),
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
                "date_display": date_display(norma.data_vigencia),
                "title": "Início da vigência",
                "description": f"Vigência indicada para {norma}.",
                "source_norma": str(norma),
                "confidence": 1.0,
            }
        )

    events = (
        EventoAlteracao.objects.filter(
            Q(norma_alvo=norma) | Q(dispositivo_alvo__norma=norma), is_active=True
        )
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo", "norma_alvo")
        .distinct()
        .order_by("dispositivo_fonte__norma__data_publicacao", "created_at", "id")
    )
    for event in events:
        source = event.dispositivo_fonte.norma
        # A self-reference is not a normative change.  SAPL extraction often
        # creates these from citations inside the body of the same norm; if we
        # render them as timeline events the UI falsely suggests an alteration
        # and overwhelms the genuinely relevant history.
        if source.id == norma.id:
            continue
        source_date = source.data_publicacao
        effective_date = source.data_vigencia if event.validado else None
        if as_of is not None and (
            not event.validado or effective_date is None or effective_date > as_of
        ):
            continue
        pending = not event.validado
        items.append(
            {
                "kind": "event",
                "date": effective_date.isoformat() if effective_date else None,
                "date_display": date_display(effective_date),
                "publication_date": source_date.isoformat() if source_date else None,
                "publication_date_display": date_display(source_date),
                "title": "Evento extraído — pendente de revisão"
                if pending
                else event.get_acao_display(),
                "action": event.get_acao_display(),
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
