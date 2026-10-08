"""Deterministic answers for structured legal metadata and clauses."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.processing.normative_query import classify_normative_query
from src.processing.normative_reference import canonical_type, normalize_number
from src.processing.target_resolver import article_key


def _norma_label(norma: Any) -> str:
    tipo = getattr(norma, "tipo", "Lei")
    getter = getattr(norma, "get_tipo_display_name", None)
    if callable(getter):
        tipo = getter()
    if str(tipo).isdigit():
        tipo = "Lei Complementar" if str(getattr(norma, "tipo", "")) == "2" else "Lei"
    return f"{tipo} nº {norma.numero}/{norma.ano}"


def norma_summary(question: str, results: list[dict[str, Any]]) -> str | None:
    """Return the authoritative ementa for an explicit summary question."""
    if not re.search(r"\b(?:ementa|assunto|tema)\b", question or "", re.IGNORECASE):
        return None
    seen: set[int] = set()
    for item in results:
        norma = getattr(item.get("dispositivo"), "norma", None)
        norma_id = getattr(norma, "id", None)
        if norma is None or norma_id in seen:
            continue
        seen.add(norma_id)
        ementa = str(getattr(norma, "ementa", "") or "").strip()
        if ementa:
            return f"A ementa da {_norma_label(norma)} é: {ementa}"
    return None


def temporal_clause(question: str, results: list[dict[str, Any]]) -> str | None:
    """Return a retrieved entry-into-force clause without LLM paraphrasing."""
    if not re.search(
        r"\b(?:vig[êe]ncia|vig[êe]nte|entra\s+em\s+vigor|publica(?:çc)[ãa]o)\b",
        question or "",
        re.IGNORECASE,
    ):
        return None
    for item in results:
        dispositivo = item.get("dispositivo")
        text = str(
            getattr(dispositivo, "texto", "") or item.get("text") or item.get("full_text") or ""
        ).strip()
        if re.search(r"entra\s+em\s+vigor", text, re.IGNORECASE):
            norma = getattr(dispositivo, "norma", None)
            if norma is not None:
                return f"A {_norma_label(norma)} {text}"
    return None


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _device_reference(dispositivo: Any) -> str:
    getter = getattr(dispositivo, "get_full_identifier", None)
    identifier = getter() if callable(getter) else "dispositivo"
    norma = getattr(dispositivo, "norma", None)
    return f"{identifier} da {_norma_label(norma)}" if norma is not None else str(identifier)


def _explicit_article_answer(question: str, results: list[dict[str, Any]]) -> str | None:
    """Quote one exact article only when query, norm, device and citation agree.

    This narrow path avoids probabilistic paraphrase for a direct provision lookup.
    It intentionally declines follow-ups without an explicit norm, relation queries,
    ambiguous/multiple article requests, long text, or incomplete citation metadata.
    """
    plan = classify_normative_query(question)
    if (
        plan.kind != "provision"
        or plan.reference is None
        or plan.relation_intent
        or len(plan.article_targets) != 1
    ):
        return None

    target_match = re.fullmatch(r"(\d+)([a-z]*)", plan.article_targets[0])
    if not target_match:
        return None
    requested_article = (int(target_match.group(1)), target_match.group(2).upper())
    matches = []
    for row in results:
        device = row.get("dispositivo")
        norma = getattr(device, "norma", None)
        if not device or not norma or getattr(device, "tipo", "") != "artigo":
            continue
        tipo_getter = getattr(norma, "get_tipo_display_name", None)
        tipo_label = tipo_getter() if callable(tipo_getter) else getattr(norma, "tipo", "")
        if (
            canonical_type(tipo_label) != plan.reference.type_key
            or normalize_number(str(getattr(norma, "numero", ""))) != plan.reference.number
            or getattr(norma, "ano", None) != plan.reference.year
            or article_key(getattr(device, "numero", "")) != requested_article
        ):
            continue
        text = str(getattr(device, "texto", "") or "").strip()
        citation_id = str(row.get("citation_id") or "").strip()
        try:
            citation_index = int(row.get("citation_index"))
        except (TypeError, ValueError):
            continue
        if not text or len(text) > 1800 or not citation_id or not 1 <= citation_index <= 999:
            continue
        matches.append((row, device, norma, text, citation_index))

    if len(matches) != 1:
        return None

    _, device, norma, text, citation_index = matches[0]
    label = f"{device.get_full_identifier()} da {_norma_label(norma)}"
    return f"O {label} estabelece: “{text}” [[{citation_index}]]"


def reviewed_relation_answer(results: list[dict[str, Any]]) -> str | None:
    """Answer one explicit, resolved graph relation from its two cited devices.

    This avoids asking a language model to infer the relation or compare dates
    when the reviewed event already supplies those facts. It deliberately
    declines multi-edge, unreviewed, unresolved, or incompletely cited cases.
    """
    events: dict[str, dict[str, Any]] = {}
    for row in results:
        relation = row.get("graph_relation")
        if not isinstance(relation, dict):
            continue
        if (
            relation.get("action") not in {"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA"}
            or relation.get("intent") not in {"modification", "mixed"}
            or relation.get("review_status") != "confirmed"
            or relation.get("resolution") != "resolved"
        ):
            continue
        event_id = str(relation.get("event_id") or "")
        dispositivo = row.get("dispositivo")
        try:
            citation_index = int(row.get("citation_index"))
        except (TypeError, ValueError):
            continue
        if not event_id or not dispositivo or not 1 <= citation_index <= 999:
            continue
        event = events.setdefault(event_id, {"relation": relation})
        role = relation.get("role")
        if role in {"modifying_device", "target_device"}:
            event[role] = (row, dispositivo, citation_index)

    if len(events) != 1:
        return None
    event = next(iter(events.values()))
    source = event.get("modifying_device")
    target = event.get("target_device")
    if not source or not target:
        return None

    relation = event["relation"]
    source_row, source_device, source_index = source
    target_row, target_device, target_index = target
    quote = str(relation.get("quote") or "").strip()
    source_text = str(source_row.get("evidence_text") or getattr(source_device, "texto", ""))
    target_text = str(getattr(target_device, "texto", "") or target_row.get("full_text") or "").strip()
    if not quote or quote not in source_text or not target_text:
        return None

    action = str(relation["action"])
    answer = (
        f"A relação revisada registra a ação **{action}** no dispositivo de origem "
        f"**{_device_reference(source_device)}**: “{quote}” [[{source_index}]]. "
        f"O alvo é **{_device_reference(target_device)}** "
        f"[[{source_index}]][[{target_index}]]. O texto de **{_device_reference(target_device)}** é: "
        f"“{target_text}” [[{target_index}]]."
    )

    publication_on = _iso_date(relation.get("publication_on"))
    effective_on = _iso_date(relation.get("effective_on"))
    publication_label = publication_on or "não informada"
    effective_label = (
        effective_on
        if relation.get("effective_status") == "confirmed" and effective_on
        else "não confirmada"
    )
    answer += (
        f" Na relação revisada, status temporal: {relation.get('effective_status') or 'não confirmado'}; "
        f"data de publicação: {publication_label}; data de efeito: {effective_label} "
        f"[[{source_index}]]."
    )
    return answer


def deterministic_answer(question: str, results: list[dict[str, Any]]) -> str | None:
    return (
        reviewed_relation_answer(results)
        or _explicit_article_answer(question, results)
        or norma_summary(question, results)
        or temporal_clause(question, results)
    )
