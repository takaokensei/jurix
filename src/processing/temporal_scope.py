"""Deterministic temporal reasoning for municipal-law retrieval and audit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q
from django.utils import timezone

from src.processing.event_temporal_policy import event_temporal_decision


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
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo", "review_revision")
    )
    revoked: set[int] = set()
    for event in events:
        temporal = event_temporal_decision(event)
        if not event.validado or not temporal.operative:
            continue
        effective_date = temporal.effective_on
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
    ).select_related("dispositivo_fonte__norma", "review_revision")
    revoked: set[int] = set()
    for event in events:
        temporal = event_temporal_decision(event)
        effective_date = temporal.effective_on
        if (
            event.validado
            and temporal.operative
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

    events = EventoAlteracao.objects.filter(
        acao="REVOGA",
        validado=True,
        is_active=True,
        dispositivo_alvo__norma_id=norma_id,
    ).select_related("dispositivo_fonte__norma", "review_revision")
    for event in events:
        temporal = event_temporal_decision(event)
        if (
            event.validado
            and temporal.operative
            and temporal.effective_on
            and temporal.effective_on <= as_of
        ):
            return True
    return False


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


def deduplicate_event_revisions(events):
    """Collapse duplicate rows for the same evidence/target, preserving the strongest current review."""
    from src.apps.legislation.event_review import event_review_status

    def identity(event):
        fingerprint = str(event.revision_fingerprint or "").strip()
        if not fingerprint:
            return ("unfingerprinted", event.pk)
        return (
            event.dispositivo_fonte_id,
            event.acao,
            fingerprint,
            event.norma_alvo_id,
            event.dispositivo_alvo_id,
            event.effective_on,
            event.effective_date_status,
        )

    def priority(event):
        status_rank = {"pending": 0, "rejected": 1, "confirmed": 2}
        return (
            status_rank.get(event_review_status(event), 0),
            bool(event.review_revision_id),
            event.pk,
        )

    selected = {}
    for event in events:
        key = identity(event)
        current = selected.get(key)
        if current is None or priority(event) > priority(current):
            selected[key] = event
    return list(selected.values())


def build_norma_timeline(norma, *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Build an auditable timeline, optionally cut at a historical date."""
    from src.apps.legislation.event_review import event_review_status
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
            Q(norma_alvo=norma)
            | Q(dispositivo_alvo__norma=norma)
            | Q(dispositivo_fonte__norma=norma),
            is_active=True,
        )
        .select_related(
            "dispositivo_fonte__norma", "dispositivo_alvo", "norma_alvo", "review_revision"
        )
        .distinct()
        .order_by("dispositivo_fonte__norma__data_publicacao", "created_at", "id")
    )
    # Multiple rows can represent one extracted event after an earlier import
    # or QA seeding pass. Keep the strongest current review for identical
    # evidence/target, but never collapse distinct targets or temporal states.
    events = deduplicate_event_revisions(events)
    for event in events:
        source = event.dispositivo_fonte.norma
        is_outgoing_event = source.id == norma.id
        # A self-reference is not a normative change.  SAPL extraction often
        # creates these from citations inside the body of the same norm; if we
        # render them as timeline events the UI falsely suggests an alteration
        # and overwhelms the genuinely relevant history.
        if is_outgoing_event and (
            event.norma_alvo_id == norma.id
            or (
                event.dispositivo_alvo_id
                and event.dispositivo_alvo
                and event.dispositivo_alvo.norma_id == norma.id
            )
        ):
            continue
        source_date = source.data_publicacao
        temporal = event_temporal_decision(event)
        relation_status = event_review_status(event)
        effective_date = temporal.effective_on if temporal.status == "confirmed" else None
        candidate_effective_date = (
            temporal.effective_on if temporal.status == "candidate" else None
        )
        if as_of is not None:
            if temporal.status == "not_applicable":
                if temporal.publication_on is None or temporal.publication_on > as_of:
                    continue
            elif not temporal.operative or effective_date is None or effective_date > as_of:
                continue
        pending = relation_status != "confirmed" or temporal.status not in {
            "confirmed",
            "not_applicable",
        }
        if temporal.status == "not_applicable":
            title = "Referência documental"
        elif relation_status != "confirmed":
            title = "Evento extraído — vínculo pendente de revisão"
        elif temporal.status != "confirmed":
            title = "Evento confirmado — efeito temporal indeterminado"
        else:
            title = event.get_acao_display()
        if is_outgoing_event and title == event.get_acao_display():
            prefix = (
                "Relação desta norma — "
                if temporal.status == "not_applicable"
                else "Efeito em outra norma — "
            )
            title = f"{prefix}{title}"
        action = (event.acao or "").upper()
        target_label = (
            event.dispositivo_alvo.get_caminho_completo()
            if event.dispositivo_alvo_id and event.dispositivo_alvo
            else event.target_text
        )
        effect_scope = (
            "total"
            if action == "REVOGA" and not event.dispositivo_alvo_id
            else "parcial"
            if action == "REVOGA" and event.dispositivo_alvo_id
            else "indeterminado"
        )
        source_label = f"{source}, {event.dispositivo_fonte.get_caminho_completo()}"
        if event.dispositivo_alvo_id and event.dispositivo_alvo:
            target_description = (
                f"{event.dispositivo_alvo.get_caminho_completo()} da {event.dispositivo_alvo.norma}"
            )
        elif event.target_text:
            target_description = event.target_text
        elif event.norma_alvo_id and event.norma_alvo:
            target_description = f"dispositivos da {event.norma_alvo}"
        else:
            target_description = target_label
        verbs = {
            "REFERENCIA": "menciona",
            "REGULAMENTA": "regulamenta",
            "REVOGA": "revoga",
            "ALTERA": "altera",
            "ADICIONA": "adiciona conteúdo a",
            "SUBSTITUI": "substitui",
        }
        description = (
            f"{source_label} {verbs[action]} {target_description}."
            if action in verbs
            else event.get_descricao_completa()
        )
        items.append(
            {
                "kind": "event",
                "date": effective_date.isoformat() if effective_date else None,
                "date_display": date_display(effective_date),
                "candidate_effective_date": candidate_effective_date.isoformat()
                if candidate_effective_date
                else None,
                "candidate_effective_date_display": date_display(candidate_effective_date),
                "publication_date": source_date.isoformat() if source_date else None,
                "publication_date_display": date_display(source_date),
                "availability_date": temporal.publication_on.isoformat()
                if temporal.status == "not_applicable" and temporal.publication_on
                else None,
                "title": title,
                "timeline_role": "source" if is_outgoing_event else "target",
                "action": event.get_acao_display(),
                "description": description,
                "source_norma": str(source),
                "source_norma_id": source.id,
                "target_text": event.target_text,
                "target_label": target_label,
                "target_dispositivo_id": event.dispositivo_alvo_id,
                "validated": relation_status == "confirmed" and temporal.status == "confirmed",
                "pending": pending,
                "relation_status": relation_status,
                "effective_date_status": temporal.status,
                "effect_scope": effect_scope,
                "temporal_basis": temporal.basis,
                "temporal_reason": temporal.reason,
                # Extraction confidence is a model signal, never legal certainty.
                # A stored zero is also the legacy default for missing calibration.
                "extraction_signal": (
                    float(event.extraction_confidence)
                    if event.extraction_confidence and event.extraction_confidence > 0
                    else None
                ),
            }
        )
    items.sort(
        key=lambda item: (
            item["date"]
            or item.get("candidate_effective_date")
            or item.get("availability_date")
            or "9999-99-99",
            {"publication": 0, "effective": 1, "event": 2}.get(item["kind"], 3),
            item["title"],
        )
    )
    target_record_counts: dict[int, int] = {}
    for item in items:
        target_id = item.get("target_dispositivo_id")
        if item.get("kind") == "event" and target_id is not None:
            target_record_counts[target_id] = target_record_counts.get(target_id, 0) + 1
    target_record_seen: dict[int, int] = {}
    for item in items:
        target_id = item.get("target_dispositivo_id")
        count = target_record_counts.get(target_id, 0)
        if item.get("kind") != "event" or target_id is None or count < 2:
            continue
        ordinal = target_record_seen.get(target_id, 0) + 1
        target_record_seen[target_id] = ordinal
        item["target_relation_count"] = count
        item["target_relation_ordinal"] = ordinal
    return items
