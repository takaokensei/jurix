"""Read-only relation candidates derived from one document segmentation preview."""

from __future__ import annotations

import re

from src.processing.ner_extractor import LegalNERExtractor

_PORTUGUESE_MONTHS = (
    "janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|"
    "setembro|outubro|novembro|dezembro"
)


def _explicit_norma_reference(event: dict, evidence: dict) -> dict | None:
    reference = event.get("norma_referenciada")
    if isinstance(reference, dict) and all(
        str(reference.get(key) or "").strip() for key in ("tipo", "numero", "ano")
    ):
        return reference

    # Some official PDFs omit the ordinal marker after "Lei". Recover only a
    # citation that supplies both its species/number and a full date or year.
    quote = str(evidence.get("quote") or "")
    species = re.search(
        r"\b(lei\s+complementar|lei\s+promulgada|lei)\b\s*"
        r"(?:n[º°.]?\s*)?([\d.]+)\b",
        quote,
        re.IGNORECASE,
    )
    if not species:
        return None
    year = re.search(r"/((?:19|20)\d{2})\b", quote)
    if year is None:
        year = re.search(
            rf"\bde\s+\d{{1,2}}\s+de\s+(?:{_PORTUGUESE_MONTHS})\s+de\s+((?:19|20)\d{{2}})\b",
            quote,
            re.IGNORECASE,
        )
    if year is None:
        return None
    return {
        "tipo": " ".join(species.group(1).split()).title(),
        "numero": species.group(2),
        "ano": year.group(1),
    }


def _single_article_action_candidates(rows: list[dict]) -> list[dict]:
    """Preview explicit amendment events embedded in an article's own text."""
    extractor = LegalNERExtractor()
    candidates = []
    for row in rows:
        if row.get("tipo") != "artigo" or not isinstance(row.get("start_offset"), int):
            continue
        source_text = str(row.get("texto") or "")
        for event in extractor.extract_events(texto=source_text):
            if event.get("acao") not in {"ALTERA", "SUBSTITUI", "ADICIONA"}:
                continue
            evidence = event.get("evidence")
            if not isinstance(evidence, dict):
                continue
            target_quote = str(evidence.get("target_quote") or "").strip()
            action_quote = str(evidence.get("action_quote") or "").strip()
            target_start = evidence.get("target_start_offset")
            target_end = evidence.get("target_end_offset")
            action_start = evidence.get("action_start_offset")
            action_end = evidence.get("action_end_offset")
            if (
                not target_quote
                or not action_quote
                or not all(isinstance(value, int) for value in (
                    target_start, target_end, action_start, action_end
                ))
                or source_text[target_start:target_end] != target_quote
                or source_text[action_start:action_end] != action_quote
            ):
                continue
            reference = _explicit_norma_reference(event, evidence)
            structural_type = str(event.get("referencia_tipo") or "").strip().casefold()
            structural_number = str(event.get("referencia_numero") or "").strip()
            if not reference or not structural_type or not structural_number:
                continue
            if (
                structural_type == "artigo"
                and re.sub(r"\D", "", structural_number)
                == re.sub(r"\D", "", str(row.get("numero") or ""))
                and not source_text[:target_start].strip()
                and target_end <= action_start
            ):
                # Do not interpret the source article heading as its own target.
                continue
            normalized_number = structural_number
            if "\ufffd" in normalized_number:
                quoted_number = re.search(
                    rf"\barts?\.?\s*{re.escape(re.sub(r'\D', '', normalized_number))}\s*([º°ª])",
                    str(evidence.get("quote") or ""),
                    re.IGNORECASE,
                )
                if quoted_number:
                    normalized_number = re.sub(r"\ufffd+$", "", normalized_number)
                    normalized_number += "º"
            candidates.append(
                {
                    "action": event["acao"],
                    "action_quote": action_quote,
                    "action_device": f"Artigo {row.get('numero', '')}".strip(),
                    "action_structural_key": row.get("structural_key"),
                    "action_page": row.get("page_index"),
                    "item_device": f"Artigo {row.get('numero', '')}".strip(),
                    "source_structural_key": row.get("structural_key"),
                    "item_quote": source_text,
                    "item_start_offset": row.get("start_offset"),
                    "item_end_offset": row.get("end_offset"),
                    "target_quote": target_quote,
                    "action_start_offset": row["start_offset"] + action_start,
                    "action_end_offset": row["start_offset"] + action_end,
                    "target_start_offset": row["start_offset"] + target_start,
                    "target_end_offset": row["start_offset"] + target_end,
                    "target_page": row.get("page_index"),
                    "norma_candidate": reference,
                    "device_type": structural_type,
                    "device_number": normalized_number,
                    "structural_article_number": (
                        normalized_number if structural_type == "artigo" else None
                    ),
                    "status": "candidate_unreviewed",
                }
            )
    selected = {}
    specificity = {"artigo": 1, "paragrafo": 2, "inciso": 3, "alinea": 4, "item": 5}
    for candidate in candidates:
        target_quote = str(candidate.get("target_quote") or "")
        article_match = re.search(
            r"\barts?\.?\s*(\d+[A-Za-z]?(?:-[A-Za-z])?)",
            target_quote,
            re.IGNORECASE,
        )
        article_number = (
            candidate.get("device_number")
            if candidate.get("device_type") == "artigo"
            else article_match.group(1) if article_match else ""
        )
        reference = candidate.get("norma_candidate") or {}
        key = (
            candidate.get("action_start_offset"),
            candidate.get("action_end_offset"),
            str(reference.get("tipo") or "").casefold(),
            reference.get("numero"),
            reference.get("ano"),
            str(article_number).casefold(),
        )
        rank = specificity.get(str(candidate.get("device_type") or ""), 0)
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, candidate)
    return [candidate for _, candidate in selected.values()]


def build_document_relation_preview(
    devices: tuple[dict, ...] | list[dict], *, limit: int = 200,
    include_single_article_actions: bool = True,
) -> list[dict]:
    """Derive unreviewed parent-action → child-target candidates without persistence.

    The source device's introductory clause and the target child's text remain separate.
    This helper is intentionally limited to list items whose parent chain contains a
    standalone action clause; it does not infer implied repeal or currentness.
    """
    rows = [row for row in devices if isinstance(row, dict)]
    by_key = {str(row.get("structural_key")): row for row in rows if row.get("structural_key")}
    extractor = LegalNERExtractor()
    candidates = _single_article_action_candidates(rows) if include_single_article_actions else []

    for row in rows:
        if row.get("tipo") not in {"inciso", "alinea", "item"}:
            continue
        item_text = str(row.get("texto") or "")
        if not item_text.strip():
            continue
        explicit_events = extractor.extract_events(texto=item_text)
        if any(
            event.get("acao") in {"REVOGA", "ALTERA", "SUBSTITUI", "ADICIONA"}
            for event in explicit_events
        ):
            continue

        parent_key = row.get("parent_key")
        visited = set()
        while parent_key and parent_key not in visited:
            visited.add(parent_key)
            parent = by_key.get(str(parent_key))
            if parent is None:
                break
            introduction = extractor.list_action_introduction(str(parent.get("texto") or ""))
            if introduction:
                events = extractor.extract_inherited_list_item_events(introduction, item_text)
                specifically_targeted_articles = set()
                for event in events:
                    if event.get("referencia_tipo") == "artigo":
                        continue
                    evidence = event.get("evidence") or {}
                    quote = str(evidence.get("target_quote") or event.get("target_text") or "")
                    specifically_targeted_articles.update(
                        number.casefold()
                        for number in re.findall(
                            r"\barts?\.?\s*(\d+[A-Za-z]?(?:-[A-Za-z])?)",
                            quote,
                            flags=re.IGNORECASE,
                        )
                    )
                if specifically_targeted_articles:
                    events = [
                        event
                        for event in events
                        if not (
                            event.get("referencia_tipo") == "artigo"
                            and str(event.get("referencia_numero") or "").casefold()
                            in specifically_targeted_articles
                        )
                    ]
                for event in events:
                    reference = event.get("norma_referenciada") or {}
                    structural_type = event.get("referencia_tipo")
                    if not reference and structural_type not in {
                        "artigo",
                        "paragrafo",
                        "inciso",
                        "alinea",
                        "item",
                    }:
                        continue
                    candidates.append(
                        {
                            "action": event.get("acao"),
                            "action_quote": introduction["quote"],
                            "action_device": f"{parent.get('tipo', '').capitalize()} {parent.get('numero', '')}".strip(),
                            "action_structural_key": parent.get("structural_key"),
                            "action_page": parent.get("page_index"),
                            "item_device": f"{row.get('tipo', '').capitalize()} {row.get('numero', '')}".strip(),
                            "source_structural_key": row.get("structural_key"),
                            "item_quote": item_text,
                            "item_start_offset": row.get("start_offset"),
                            "item_end_offset": row.get("end_offset"),
                            "target_quote": (event.get("evidence") or {}).get("target_quote")
                            or event.get("target_text")
                            or "",
                            "action_start_offset": (
                                parent.get("start_offset", 0) + introduction["start_offset"]
                                if isinstance(parent.get("start_offset"), int)
                                else None
                            ),
                            "action_end_offset": (
                                parent.get("start_offset", 0) + introduction["end_offset"]
                                if isinstance(parent.get("start_offset"), int)
                                else None
                            ),
                            "target_start_offset": (
                                row.get("start_offset", 0)
                                + (event.get("evidence") or {}).get("target_start_offset", 0)
                                if isinstance(row.get("start_offset"), int)
                                and isinstance(
                                    (event.get("evidence") or {}).get("target_start_offset"), int
                                )
                                else None
                            ),
                            "target_end_offset": (
                                row.get("start_offset", 0)
                                + (event.get("evidence") or {}).get("target_end_offset", 0)
                                if isinstance(row.get("start_offset"), int)
                                and isinstance(
                                    (event.get("evidence") or {}).get("target_end_offset"), int
                                )
                                else None
                            ),
                            "target_page": row.get("page_index"),
                            "norma_candidate": reference,
                            "device_type": structural_type,
                            "device_number": event.get("referencia_numero"),
                            "structural_article_number": (
                                (event.get("evidence") or {}).get("structural_article_number")
                            ),
                            "status": "candidate_unreviewed",
                        }
                    )
                break
            parent_key = parent.get("parent_key")
        if len(candidates) >= limit:
            break

    unique_candidates = {}
    for candidate in candidates:
        key = (
            candidate.get("action_start_offset"),
            candidate.get("action_end_offset"),
            candidate.get("target_start_offset"),
            candidate.get("target_end_offset"),
            candidate.get("device_type"),
            candidate.get("device_number"),
        )
        unique_candidates[key] = candidate
    return list(unique_candidates.values())[:limit]
