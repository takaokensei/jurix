"""Fast, evidence-aware conversation titles that never block the answer stream."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

_NORM = re.compile(
    r"\b(Lei(?:\s+Complementar)?|Decreto(?:\s+Legislativo)?|Resolução|Portaria)"
    r"\s*(?:n[º°o.]?\s*)?(\d{1,7})\s*/\s*((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_ARTICLE = re.compile(r"\b(?:art(?:igo)?\.?)\s*(\d{1,4})\s*[º°o]?(?:\s*[a-z])?", re.IGNORECASE)
_WORD = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
_STOP = {
    "a",
    "as",
    "ao",
    "aos",
    "com",
    "como",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "essa",
    "esse",
    "esta",
    "este",
    "foi",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "pela",
    "pelas",
    "pelo",
    "pelos",
    "por",
    "qual",
    "que",
    "se",
    "sobre",
    "um",
    "uma",
    "uns",
    "umas",
    "prevê",
    "preve",
    "estabelece",
    "trata",
    "dispõe",
    "dispoe",
    "institui",
    "diz",
    "determina",
    "art",
    "artigo",
    "lei",
    "decreto",
    "resolução",
    "resolucao",
    "portaria",
    "n",
    "nº",
    "n°",
    "dia",
    "data",
    "quais",
    "são",
    "sao",
    "ser",
    "previsto",
    "prevista",
}


def _fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def build_conversation_title(question: str, sources: Iterable[Mapping[str, object]]) -> str:
    """Return a short deterministic title; topic words must occur in final evidence."""
    text = " ".join(str(question or "").split())
    norm = _NORM.search(text)
    article = _ARTICLE.search(text)
    norm_label = None
    if norm:
        kind = (
            "Lei Complementar"
            if norm.group(1).casefold().startswith("lei complementar")
            else norm.group(1)
        )
        norm_label = f"{kind} nº {norm.group(2)}/{norm.group(3)}"
        text = f"{text[:norm.start()]} {text[norm.end():]}"

    evidence_words: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        evidence = " ".join(
            str(source.get(key) or "") for key in ("norma_ref", "text", "full_text")
        )
        evidence_words.update(_fold(word) for word in _WORD.findall(evidence))

    candidates = []
    for word in _WORD.findall(text):
        folded = _fold(word)
        if len(folded) < 3 or folded in _STOP or folded.isdigit() or folded not in evidence_words:
            continue
        if folded not in {_fold(item) for item in candidates}:
            candidates.append(word)
        if len(candidates) == 4:
            break

    parts = []
    if candidates:
        topic = " ".join(candidates)
        parts.append(topic[:1].upper() + topic[1:])
    if article:
        parts.append(f"Art. {article.group(1)}º")
    if norm_label:
        parts.append(norm_label)
    if not parts:
        return "Pesquisa jurídica"
    return " — ".join(parts)[:70].rstrip(" —")
