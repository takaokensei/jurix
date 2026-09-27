"""Deterministic answers for structured legal metadata and clauses."""

from __future__ import annotations

import re
from typing import Any


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


def deterministic_answer(question: str, results: list[dict[str, Any]]) -> str | None:
    return norma_summary(question, results) or temporal_clause(question, results)
