"""Parse narrowly scoped lists of article references sharing one named norm."""

from __future__ import annotations

import re

from src.processing.normative_reference import normalize_number, parse_normative_references

_NORM_SPAN_RE = re.compile(
    r"\b(?:lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica|promulgada))?|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?|"
    r"resolu[çc][ãa]o|portaria|emenda(?:\s+constitucional)?|lc)\s*"
    r"(?:\s+(?:municipal(?:\s+de\s+Natal)?|do\s+munic[ií]pio(?:\s+de\s+Natal)?))?\s*"
    r"(?:n[º°o.]?\s*)?\d[\d.]*"
    r"(?:\s*(?:/|de)\s*(?:19|20)\d{2})?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart(?:igo)?\.?\s*(\d{1,4})\s*[º°ªo]?", re.IGNORECASE)
_COORDINATION_GAP_RE = re.compile(
    r"\s*(?:(?:,|;|e|ou)\s*)?(?:(?:o|a|os|as)\s*)?"
    r"(?:(?:inciso\s+[ivxlcdm]+)\s*,?\s*)?"
    r"(?:(?:,|;|e|ou)\s*)?(?:(?:o|a|os|as)\s*)?",
    re.IGNORECASE,
)


def _identity(reference) -> tuple[str, str, int | None]:
    number = normalize_number(reference.number).lstrip("0") or "0"
    return reference.type_key, number, reference.year


def _article_key(value: str) -> str:
    return str(int(value)) if str(value).isdigit() else ""


def parse_coordinated_article_norm_pairs(
    question: str,
) -> tuple[tuple[int, tuple[str, str, int | None], str], ...]:
    """Resolve article lists whose shared norm is stated immediately before or after.

    Example: ``Art. 260, inciso IV, o Art. 262 e o Art. 266 da LC 258/2024``.
    Any sentence break, comparison cue, intervening prose, or conflicting norm
    identities keeps the references unresolved for the caller's safe fallback.
    """
    raw = question or ""
    article_spans = sorted(
        (match.start(), match.end(), _article_key(match.group(1)))
        for match in _ARTICLE_RE.finditer(raw)
    )
    if len(article_spans) < 2:
        return ()

    norm_matches = list(_NORM_SPAN_RE.finditer(raw))
    runs: list[list[tuple[int, int, str]]] = []
    for span in article_spans:
        gap = raw[runs[-1][-1][1] : span[0]] if runs else ""
        if (
            runs
            and re.search(r"[,;]|\b(?:e|ou)\b", gap, re.IGNORECASE)
            and _COORDINATION_GAP_RE.fullmatch(gap)
        ):
            runs[-1].append(span)
        else:
            runs.append([span])

    pairs: list[tuple[int, tuple[str, str, int | None], str]] = []
    for run in runs:
        if len(run) < 2:
            continue
        first_start = run[0][0]
        last_end = run[-1][1]
        preceding = next(
            (match for match in reversed(norm_matches) if match.end() <= first_start), None
        )
        following = next(
            (match for match in norm_matches if match.start() >= last_end), None
        )
        preceding_ref = None
        if preceding is not None:
            gap = raw[preceding.end() : first_start]
            if (
                len(gap) <= 100
                and not re.search(r"[;!?]|\.(?!\s*\d)", gap)
                and not re.search(r"\b(?:entre|versus|comparar|compare)\b", gap, re.I)
            ):
                preceding_ref = next(
                    (
                        ref
                        for ref in parse_normative_references(preceding.group(0))
                        if ref.year is not None and ref.number
                    ),
                    None,
                )
        following_ref = None
        if following is not None:
            gap = raw[last_end : following.start()]
            if len(gap) <= 24 and re.fullmatch(r"\s*(?:da|do|de)?\s*", gap, re.I):
                following_ref = next(
                    (
                        ref
                        for ref in parse_normative_references(following.group(0))
                        if ref.year is not None and ref.number
                    ),
                    None,
                )
        if (
            preceding_ref is not None
            and following_ref is not None
            and _identity(preceding_ref) != _identity(following_ref)
        ):
            continue
        reference = following_ref or preceding_ref
        if reference is None:
            continue
        identity = _identity(reference)
        pairs.extend((start, identity, article) for start, _end, article in run)

    return tuple(pairs)
