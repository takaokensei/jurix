"""Fast, evidence-aware conversation titles that never block the answer stream."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping

from src.processing.normative_reference import parse_normative_references

_ARTICLE = re.compile(r"\b(?:art(?:igo)?\.?)\s*(\d{1,4})\s*[º°o]?(?:\s*[a-z])?", re.IGNORECASE)
_LEGISLATIVE_MATTER = re.compile(
    r"\b(?P<kind>projeto\s+de\s+lei\s+complementar|projeto\s+de\s+lei|plc|pl)"
    r"\s*(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)\s*(?:/|de)\s*(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
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
    "esses",
    "esta",
    "este",
    "estas",
    "estes",
    "foi",
    "na",
    "nas",
    "não",
    "nao",
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
    "artigos",
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
    "complementar",
    # Prompt/instruction vocabulary is not a conversation topic, even when it
    # also appears in the cited text (for example, "cada unidade" in a law).
    "cada",
    "afirmação",
    "afirmacao",
    "afirmações",
    "afirmacoes",
    "correspondente",
    "correspondentes",
    "vincule",
    "vincular",
    "resuma",
    "resumo",
    "principais",
    "temas",
    "eixos",
    "dispositivo",
    "dispositivos",
    "ordinária",
    "ordinaria",
    "orgânica",
    "organica",
    "legislativo",
    "constitucional",
    "emenda",
    "antes",
    "aplicar",
    "aplique",
    "cautela",
    "cautelas",
    "deve",
    "devem",
    "gerais",
    "linhas",
    "observar",
    "organiza",
    "organizam",
    "procurador",
    "processo",
    "excertos",
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
    matter_matches = list(_LEGISLATIVE_MATTER.finditer(text))
    # A bill is not a promulgated norm. Avoid allowing the embedded words
    # "Lei Complementar" in its full name to become a false norm citation.
    references = () if len(matter_matches) == 1 else parse_normative_references(text)
    reference = references[0] if len(references) == 1 else None
    norm_label = None
    if reference and reference.year:
        type_labels = {
            "lei": "Lei",
            "lei_complementar": "Lei Complementar",
            "lei_organica": "Lei Orgânica",
            "decreto": "Decreto",
            "decreto_lei": "Decreto-Lei",
            "decreto_legislativo": "Decreto Legislativo",
            "resolucao": "Resolução",
            "portaria": "Portaria",
            "emenda_constitucional": "Emenda Constitucional",
            "emenda": "Emenda",
        }
        kind = type_labels.get(reference.type_key, reference.type_key.replace("_", " ").title())
        number = reference.number
        if len(number) > 3:
            first_group_size = len(number) % 3 or 3
            number = ".".join(
                [number[:first_group_size], *[number[index : index + 3] for index in range(first_group_size, len(number), 3)]]
            )
        norm_label = f"{kind} nº {number}/{reference.year}"

    matter_label = None
    if not norm_label and len(matter_matches) == 1:
        matter = matter_matches[0]
        raw_kind = _fold(matter.group("kind"))
        kind = "PLC" if raw_kind in {"plc", "projeto de lei complementar"} else "PL"
        number = matter.group("number")
        if len(number) > 3:
            first_group_size = len(number) % 3 or 3
            number = ".".join(
                [number[:first_group_size], *[number[index : index + 3] for index in range(first_group_size, len(number), 3)]]
            )
        matter_label = f"{kind} nº {number}/{matter.group('year')}"

    article_number = None
    if reference:
        if not reference.ambiguous:
            article_number = reference.article
    else:
        article_match = _ARTICLE.search(text)
        article_number = article_match.group(1) if article_match else None

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
    if article_number:
        parts.append(f"Art. {article_number}º")
    if norm_label:
        parts.append(norm_label)
    elif matter_label:
        parts.append(matter_label)
    if not parts:
        return "Pesquisa jurídica"
    return " — ".join(parts)[:70].rstrip(" —")
