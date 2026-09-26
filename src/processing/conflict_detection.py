"""Advisory signals for the municipal legal alteration graph.

These checks surface data-quality/review signals. They do not decide legal
meaning or declare a legal conflict without human review.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from django.db.models import Q

from src.apps.legislation.models import EventoAlteracao


@dataclass(frozen=True)
class ConflictSignal:
    code: str
    severity: str
    title: str
    description: str
    event_ids: tuple[int, ...] = ()


CONTRADICTORY_PAIRS = {
    frozenset({"REVOGA", "ALTERA"}),
    frozenset({"REVOGA", "SUBSTITUI"}),
}


def detect_for_norma(norma) -> list[dict]:
    events = list(
        EventoAlteracao.objects.filter(Q(norma_alvo=norma) | Q(dispositivo_alvo__norma=norma))
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo", "norma_alvo")
        .order_by("dispositivo_fonte__norma__data_publicacao", "created_at", "id")
    )
    signals: list[ConflictSignal] = []

    by_action_target: defaultdict[tuple[str, int | None], list[EventoAlteracao]] = defaultdict(list)
    by_target: defaultdict[int | None, list[EventoAlteracao]] = defaultdict(list)
    for event in events:
        target_id = event.dispositivo_alvo_id or event.norma_alvo_id
        by_action_target[(event.acao, target_id)].append(event)
        if target_id is not None:
            by_target[target_id].append(event)
        if not event.norma_alvo_id and not event.dispositivo_alvo_id:
            signals.append(
                ConflictSignal(
                    code="unresolved_target",
                    severity="warning",
                    title="Alvo não resolvido",
                    description="O evento possui referência textual, mas nenhum alvo estruturado foi localizado.",
                    event_ids=(event.id,),
                )
            )

    for (action, target_id), rows in by_action_target.items():
        if target_id is not None and len(rows) > 1:
            signals.append(
                ConflictSignal(
                    code="duplicate_action_target",
                    severity="warning",
                    title="Ação duplicada para o mesmo alvo",
                    description=(
                        f"{len(rows)} eventos '{action}' apontam para o mesmo alvo; "
                        "o caso merece revisão do extrator."
                    ),
                    event_ids=tuple(row.id for row in rows),
                )
            )

    for _target_id, rows in by_target.items():
        actions = {row.acao for row in rows}
        for pair in CONTRADICTORY_PAIRS:
            if pair.issubset(actions):
                pair_rows = [row for row in rows if row.acao in pair]
                signals.append(
                    ConflictSignal(
                        code="contradictory_action_sequence",
                        severity="review",
                        title="Sequência potencialmente contraditória",
                        description=(
                            "O mesmo alvo possui revogação e modificação/substituição. "
                            "Isso é um sinal de revisão, não uma conclusão jurídica."
                        ),
                        event_ids=tuple(row.id for row in pair_rows),
                    )
                )
    return [asdict(signal) for signal in signals]
