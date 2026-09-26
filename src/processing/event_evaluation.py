"""Reproducible evaluation of extracted legal alteration actions."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from django.db.models import Q

from src.apps.legislation.models import EventoAlteracao

ACTIONS = ("REVOGA", "ALTERA", "ADICIONA", "SUBSTITUI", "REGULAMENTA", "REFERENCIA")


@dataclass(frozen=True)
class EventCase:
    case_id: str
    norma_id: int
    gold_actions: tuple[str, ...]


@dataclass(frozen=True)
class ClassMetrics:
    action: str
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def load_cases(path: str | Path) -> list[EventCase]:
    cases: list[EventCase] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        item = json.loads(raw)
        actions = tuple(sorted({str(action).upper() for action in item.get("gold_actions", [])}))
        unknown = set(actions) - set(ACTIONS)
        if unknown:
            raise ValueError(f"Ações desconhecidas em {item.get('case_id')}: {sorted(unknown)}")
        cases.append(EventCase(str(item["case_id"]), int(item["norma_id"]), actions))
    return cases


def predicted_actions(norma_id: int) -> tuple[str, ...]:
    rows = EventoAlteracao.objects.filter(
        Q(norma_alvo_id=norma_id) | Q(dispositivo_fonte__norma_id=norma_id)
    ).values_list("acao", flat=True)
    return tuple(sorted(set(rows)))


def evaluate(cases: list[EventCase]) -> dict:
    totals = {action: Counter(tp=0, fp=0, fn=0) for action in ACTIONS}
    case_results: list[dict] = []
    for case in cases:
        gold = set(case.gold_actions)
        predicted = set(predicted_actions(case.norma_id))
        case_results.append(
            {
                "case_id": case.case_id,
                "norma_id": case.norma_id,
                "gold_actions": sorted(gold),
                "predicted_actions": sorted(predicted),
                "missing": sorted(gold - predicted),
                "unexpected": sorted(predicted - gold),
            }
        )
        for action in ACTIONS:
            totals[action]["tp"] += int(action in gold and action in predicted)
            totals[action]["fp"] += int(action not in gold and action in predicted)
            totals[action]["fn"] += int(action in gold and action not in predicted)

    metrics = []
    for action in ACTIONS:
        current = totals[action]
        precision = (
            current["tp"] / (current["tp"] + current["fp"])
            if current["tp"] + current["fp"]
            else 0.0
        )
        recall = (
            current["tp"] / (current["tp"] + current["fn"])
            if current["tp"] + current["fn"]
            else 0.0
        )
        metrics.append(
            asdict(
                ClassMetrics(
                    action=action,
                    tp=current["tp"],
                    fp=current["fp"],
                    fn=current["fn"],
                    precision=round(precision, 6),
                    recall=round(recall, 6),
                    f1=round(_f1(precision, recall), 6),
                )
            )
        )
    macro_f1 = sum(item["f1"] for item in metrics) / len(metrics) if metrics else 0.0
    return {
        "cases": len(cases),
        "macro_f1": round(macro_f1, 6),
        "metrics": metrics,
        "case_results": case_results,
    }
