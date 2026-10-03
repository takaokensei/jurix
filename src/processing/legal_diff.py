"""Structural, conservative textual comparison for OCR and consolidated law text."""

from __future__ import annotations

import re
from collections import Counter

_ARTICLE = re.compile(r"^\s*art(?:igo)?\.?\s*(\d{1,4})(?:\s*[º°o])?(?=\s|$|[.:;,)])", re.IGNORECASE)
_UNIQUE_PARAGRAPH = re.compile(r"^\s*par[aá]grafo\s+[uú]nico\b", re.IGNORECASE)
_PARAGRAPH = re.compile(r"^\s*§+\s*(\d{1,4})(?:\s*[º°o])?(?=\s|$|[.:;,)])", re.IGNORECASE)
_INCISO = re.compile(
    r"^\s*(?:inciso\s+([IVXLCDM]{1,8})\b(?=\s|$|[.:;,)])"
    r"|([IVXLCDM]{1,8})\s*(?:[.)–—-]|$))",
    re.IGNORECASE,
)
_ALINEA = re.compile(r"^\s*(?:al[ií]nea\s+)?([a-z])\s*[).]\s+", re.IGNORECASE)
_ROMAN = set("IVXLCDM")


def _compact(text: str) -> str:
    """Normalize layout whitespace only; retain punctuation, tokens and negation."""
    return re.sub(r"\s+", " ", text).strip()


def _comparable_text(text: str, key: str) -> str:
    """Remove only a structural inciso label when that label is the paired key."""
    if ":inc:" not in key:
        return _compact(text)
    first_line, separator, remainder = text.partition("\n")
    marker = _INCISO.match(first_line)
    if marker:
        first_line = first_line[marker.end() :]
    return _compact("\n".join((first_line, remainder)) if separator else first_line)


def _units(text: str) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    occurrence: Counter[str] = Counter()
    article = None
    paragraph = None
    inciso = None
    active_key = None
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            if units and units[-1]["raw"]:
                units[-1]["raw"] = f"{units[-1]['raw']}\n"
            continue

        key = None
        match = _ARTICLE.match(line)
        if match:
            article = match.group(1).lstrip("0") or "0"
            paragraph = inciso = None
            key = f"art:{article}"
        elif _UNIQUE_PARAGRAPH.match(line):
            paragraph, inciso = "unico", None
            key = f"art:{article or '?'}:par:{paragraph}"
        elif match := _PARAGRAPH.match(line):
            paragraph, inciso = match.group(1).lstrip("0") or "0", None
            key = f"art:{article or '?'}:par:{paragraph}"
        elif match := _ALINEA.match(line):
            key = f"art:{article or '?'}:par:{paragraph or '-'}:inc:{inciso or '-'}:al:{match.group(1).casefold()}"
        else:
            match = _INCISO.match(line)
            marker = (match.group(1) or match.group(2)) if match else None
            if marker and set(marker.upper()) <= _ROMAN and len(marker) <= 8:
                inciso = marker.upper()
                key = f"art:{article or '?'}:par:{paragraph or '-'}:inc:{inciso}"

        if key:
            occurrence[key] += 1
            unique_key = f"{key}#{occurrence[key]}"
            units.append({"key": unique_key, "line": line_number, "raw": line})
            active_key = unique_key
        elif units and active_key:
            units[-1]["raw"] = f"{units[-1]['raw']}\n{line}"
        else:
            occurrence["preamble"] += 1
            unique_key = f"preamble:{occurrence['preamble']}"
            units.append({"key": unique_key, "line": line_number, "raw": line})
            active_key = unique_key
    return units


def build_legal_diff(original_text: str, consolidated_text: str) -> list[dict[str, object]]:
    """Pair device blocks by their hierarchy and classify text-only changes.

    The function deliberately does not label an OCR difference as an amendment.
    It preserves every token and punctuation mark; whitespace is used only to
    distinguish formatting-only differences from changes in legal wording.
    """
    original = _units(original_text)
    consolidated = _units(consolidated_text)
    original_by_key = {str(unit["key"]): unit for unit in original}
    consolidated_by_key = {str(unit["key"]): unit for unit in consolidated}
    ordered_keys = [str(unit["key"]) for unit in original]
    ordered_keys.extend(
        str(unit["key"]) for unit in consolidated if str(unit["key"]) not in original_by_key
    )
    rows = []
    for key in ordered_keys:
        old = original_by_key.get(key)
        new = consolidated_by_key.get(key)
        old_text = str(old["raw"]) if old else ""
        new_text = str(new["raw"]) if new else ""
        if old is None:
            kind, label = "added", "Dispositivo presente somente no consolidado"
        elif new is None:
            kind, label = "removed", "Dispositivo presente somente no OCR"
        elif _comparable_text(old_text, key) == _comparable_text(new_text, key) and old_text != new_text:
            kind, label = "formatting", "Diferença de formatação/extração"
        elif _comparable_text(old_text, key) == _comparable_text(new_text, key):
            kind, label = "equal", "Texto equivalente"
        else:
            kind, label = "changed", "Diferença textual — requer revisão"
        rows.append(
            {
                "kind": kind,
                "label": label,
                "structural_key": key,
                "original_number": old["line"] if old else None,
                "original": old_text,
                "consolidated_number": new["line"] if new else None,
                "consolidated": new_text,
            }
        )
    return rows
