from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db.models import Q

from .models import EventoAlteracao, Norma

SUGGESTION_CACHE_KEY = "jurix:ui:dynamic-suggestions:v1"
SUGGESTION_CACHE_SECONDS = 300


def _short(text: str, limit: int = 86) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def build_dynamic_suggestions(limit: int = 4) -> list[dict[str, Any]]:
    """Generate UI suggestions exclusively from the currently ingested municipal corpus."""
    cached = cache.get(SUGGESTION_CACHE_KEY)
    if isinstance(cached, list) and len(cached) >= limit:
        return cached[:limit]

    normas = list(
        Norma.objects.filter(
            sapl_id__isnull=False,
            status__in=["consolidated", "ready", "segmented"],
        )
        .exclude(ementa="")
        .order_by("-data_publicacao", "-ano", "-id")[: max(12, limit * 3)]
    )

    suggestions: list[dict[str, Any]] = []
    patterns = (
        lambda n, e: (
            f"O que estabelece a {n}?",
            f"Síntese da ementa: {_short(e)}",
        ),
        lambda n, e: (
            f"Quais regras de vigência da {n} aparecem no corpus?",
            f"Verifique dispositivos e relações temporais de {_short(e, 64)}",
        ),
        lambda n, e: (
            f"Quais alterações envolvem a {n}?",
            "Consulta os eventos normativos registrados para esta norma.",
        ),
        lambda n, e: (
            f"Quais dispositivos da {n} tratam do tema principal?",
            f"Tema extraído da ementa: {_short(e, 70)}",
        ),
    )

    for index, norma in enumerate(normas):
        identifier = f"{norma.tipo} {norma.numero}/{norma.ano}"
        has_events = EventoAlteracao.objects.filter(
            Q(norma_alvo=norma) | Q(dispositivo_fonte__norma=norma)
        ).exists()
        pattern = patterns[index % len(patterns)]
        question, description = pattern(identifier, norma.ementa)
        if "alterações envolvem" in question and not has_events:
            continue
        suggestions.append(
            {
                "question": question,
                "title": question,
                "description": description,
                "norma_id": norma.id,
                "sapl_id": norma.sapl_id,
                "identifier": identifier,
            }
        )
        if len(suggestions) >= limit:
            break

    cache.set(SUGGESTION_CACHE_KEY, suggestions, SUGGESTION_CACHE_SECONDS)
    return suggestions
