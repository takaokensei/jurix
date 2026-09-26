from __future__ import annotations

import hashlib
import re
from typing import Any

from django.core.cache import cache
from django.db.models import Exists, OuterRef, Q

from .models import EventoAlteracao, Norma

SUGGESTION_CACHE_SECONDS = 300
MAX_SUGGESTIONS = 8
CANDIDATE_MULTIPLIER = 4


def _short(text: str, limit: int = 96) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _topic_from_ementa(ementa: str) -> str:
    """Extract a compact topic from corpus metadata without inventing legal subjects."""
    value = " ".join((ementa or "").split()).strip(" .;:")
    value = re.sub(
        r"^(disp[oõ]e|institui|cria|estabelece|regulamenta|altera|define)\s+",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"^(sobre|acerca de|quanto a)\s+", "", value, flags=re.I)
    return _short(value, 86)


def _cache_key(normas: list[Norma]) -> str:
    signature = "|".join(
        f"{n.id}:{n.updated_at.isoformat()}:{n.data_vigencia!s}:{bool(getattr(n, 'has_events', False))}"
        for n in normas
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
    return f"jurix:ui:dynamic-suggestions:v3:{digest}"


def _candidate_queryset(limit: int) -> list[Norma]:
    event_exists = EventoAlteracao.objects.filter(
        Q(norma_alvo=OuterRef("pk")) | Q(dispositivo_fonte__norma=OuterRef("pk"))
    )
    return list(
        Norma.objects.filter(
            sapl_id__isnull=False,
            status__in=["consolidated", "ready", "segmented"],
        )
        .exclude(ementa__isnull=True)
        .exclude(ementa="")
        .annotate(has_events=Exists(event_exists))
        .only(
            "id",
            "tipo",
            "numero",
            "ano",
            "ementa",
            "sapl_id",
            "updated_at",
            "data_publicacao",
            "data_vigencia",
        )
        .order_by("-updated_at", "-data_publicacao", "-ano", "-id")[: max(12, limit * CANDIDATE_MULTIPLIER)]
    )


def _question_variants(identifier: str, topic: str, has_events: bool, has_validity: bool) -> list[tuple[str, str]]:
    variants = [
        (
            f"O que estabelece a {identifier} sobre {topic}?",
            f"Tema extraído da ementa da própria norma: {_short(topic, 88)}",
        ),
        (
            f"Quais dispositivos da {identifier} tratam de {topic}?",
            "Localize os dispositivos correspondentes no texto consolidado.",
        ),
    ]
    if has_validity:
        variants.append(
            (
                f"Qual é a vigência e como se aplica a {identifier}?",
                "A resposta deve usar as datas e os dispositivos disponíveis no corpus.",
            )
        )
    if has_events:
        variants.append(
            (
                f"Quais alterações atingem a {identifier}?",
                "Consulte os eventos normativos relacionados à norma.",
            )
        )
    return variants


def build_dynamic_suggestions(limit: int = 4) -> list[dict[str, Any]]:
    """Build suggestion cards exclusively from currently ingested norm metadata."""
    limit = max(1, min(int(limit or 4), MAX_SUGGESTIONS))
    normas = _candidate_queryset(limit)
    if not normas:
        return []

    key = _cache_key(normas)
    cached = cache.get(key)
    if isinstance(cached, list) and len(cached) >= limit:
        return cached[:limit]

    suggestions: list[dict[str, Any]] = []
    seen_questions: set[str] = set()

    # First pass intentionally spreads suggestions over different norms instead of
    # producing four cards about the same document.
    for variant_index in range(4):
        for norma in normas:
            topic = _topic_from_ementa(norma.ementa)
            if not topic:
                continue
            identifier = f"{norma.tipo} {norma.numero}/{norma.ano}"
            variants = _question_variants(
                identifier,
                topic,
                bool(norma.has_events),
                bool(norma.data_vigencia),
            )
            if variant_index >= len(variants):
                continue
            question, description = variants[variant_index]
            if question in seen_questions:
                continue
            seen_questions.add(question)
            suggestions.append(
                {
                    "question": question,
                    "title": _short(f"{identifier} · {topic}", 72),
                    "description": description,
                    "norma_id": norma.id,
                    "sapl_id": norma.sapl_id,
                    "identifier": identifier,
                    "source": "municipal_natal_corpus",
                    "topic": topic,
                }
            )
            if len(suggestions) >= limit:
                cache.set(key, suggestions, SUGGESTION_CACHE_SECONDS)
                return suggestions

    cache.set(key, suggestions, SUGGESTION_CACHE_SECONDS)
    return suggestions
