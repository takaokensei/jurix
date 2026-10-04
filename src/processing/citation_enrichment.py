"""Attach renderer-resolvable citations to claims already accepted by grounding."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_MARKER_RE = re.compile(r"\[\[\d{1,3}\]\]")


def _source_indexes(sources: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    rows = list(sources)
    has_explicit_indexes = any(row.get("citation_index") is not None for row in rows)
    indexes: dict[str, int] = {}
    for position, row in enumerate(rows, start=1):
        citation_id = row.get("citation_id")
        if not citation_id:
            continue
        value = row.get("citation_index")
        if value is None and not has_explicit_indexes:
            value = position
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= 999:
            indexes.setdefault(str(citation_id), index)
    return indexes


def _claim_pattern(claim: str) -> re.Pattern[str] | None:
    parts = claim.split()
    if not parts:
        return None
    return re.compile(r"\s+".join(re.escape(part) for part in parts), re.IGNORECASE)


def attach_grounded_citations(
    answer: str,
    grounding: Mapping[str, Any],
    sources: Iterable[Mapping[str, Any]],
) -> str:
    """Append stable source markers to supported claims missing a citation.

    Grounding chooses the evidence; this function only maps its stable citation
    IDs back to the already-serialized source indexes consumed by the Markdown
    renderer. It never creates a source, URL, or legal assertion.
    """
    if not grounding.get("grounded") or not answer:
        return answer

    indexes = _source_indexes(sources)
    if not indexes:
        return answer

    insertions: list[tuple[int, str]] = []
    search_from = 0
    for claim in grounding.get("claims", []):
        if not isinstance(claim, Mapping) or not claim.get("supported"):
            continue
        claim_text = str(claim.get("claim") or "").strip()
        if not claim_text or _MARKER_RE.search(claim_text):
            continue
        pattern = _claim_pattern(claim_text)
        if pattern is None:
            continue
        match_text = pattern.search(answer, pos=search_from)
        if not match_text:
            continue

        evidence_matches = [
            item for item in claim.get("matches", []) if isinstance(item, Mapping)
        ]
        evidence_matches.sort(
            key=lambda item: (
                -float(item.get("lexical_overlap", 0.0) or 0.0),
                int(item.get("evidence_index", 0) or 0),
            )
        )
        source_index = next(
            (
                indexes[citation_id]
                for item in evidence_matches
                for citation_id in item.get("citation_ids", [])
                if str(citation_id) in indexes
            ),
            None,
        )
        if source_index is None:
            search_from = match_text.end()
            continue
        insertions.append((match_text.end(), f" [[{source_index}]]"))
        search_from = match_text.end()

    for offset, marker in reversed(insertions):
        answer = answer[:offset] + marker + answer[offset:]
    return answer
