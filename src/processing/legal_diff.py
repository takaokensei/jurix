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


def build_version_diff(
    before_devices,
    after_devices,
    *,
    before_complete: bool,
    after_complete: bool,
) -> list[dict[str, object]]:
    """Compare immutable projected devices without treating partial absence as deletion."""

    def index_devices(devices):
        indexed = {}
        for item in devices:
            source = item.get("source") if isinstance(item, dict) else item.source
            key = (item.get("structural_key") if isinstance(item, dict) else None) or source.structural_key
            if not key or key in indexed:
                raise ValueError("dispositivos projetados exigem structural_key única")
            text = item.get("text", "") if isinstance(item, dict) else item.text
            status = item.get("legal_status", "unknown") if isinstance(item, dict) else item.legal_status
            order = item.get("order", 0) if isinstance(item, dict) else getattr(source, "ordem", 0)
            if isinstance(item, dict):
                label = item.get("label") or _structural_display_label(key)
            else:
                label = _device_display_label(source.tipo, source.numero)
            indexed[key] = {
                "key": key,
                "label": label,
                "text": str(text or ""),
                "status": str(status or "unknown"),
                "order": order,
            }
        return indexed

    before = index_devices(before_devices)
    after = index_devices(after_devices)
    keys = sorted(
        before.keys() | after.keys(),
        key=lambda key: ((before.get(key) or after[key])["order"], key),
    )
    rows = []
    complete_pair = before_complete and after_complete
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        old_text = old["text"] if old else ""
        new_text = new["text"] if new else ""
        old_status = old["status"] if old else None
        new_status = new["status"] if new else None
        if old is None or new is None:
            if not complete_pair:
                kind, label = "coverage_unknown", "Ausência não conclusiva — cobertura parcial"
            elif old is None:
                kind, label = "added", "Dispositivo adicionado entre as projeções"
            else:
                kind, label = "removed", "Dispositivo ausente na projeção posterior"
        elif "vetoed" in {old_status, new_status} and old_status != new_status:
            kind, label = "vetoed", "Dispositivo vetado em uma das projeções"
        elif new_status == "revoked" and old_status != "revoked":
            kind, label = "revoked", "Dispositivo marcado como revogado na projeção posterior"
        elif _compact(old_text) != _compact(new_text):
            kind, label = "changed", "Diferença textual estrutural — não equivale à validação jurídica da alteração"
        elif old_status != new_status:
            kind, label = "status_changed", "Situação do dispositivo difere entre projeções"
        elif old_text != new_text:
            kind, label = "formatting", "Diferença somente de formatação"
        else:
            kind, label = "equal", "Texto e situação equivalentes nas projeções"
        rows.append(
            {
                "structural_key": key,
                "device_label": (new or old)["label"],
                "before": old_text,
                "after": new_text,
                "before_status": old_status,
                "after_status": new_status,
                "kind": kind,
                "label": label,
            }
        )
    return rows


def _device_display_label(kind: object, number: object) -> str:
    """Translate parser device types into short, readable Brazilian legal labels."""
    normalized = str(kind or "").strip().casefold().replace("-", "_")
    number = str(number or "").strip()
    labels = {
        "artigo": "Art.",
        "art": "Art.",
        "paragrafo": "§",
        "parágrafo": "§",
        "paragrafo_unico": "Parágrafo único",
        "inciso": "Inciso",
        "alinea": "Alínea",
        "item": "Item",
    }
    label = labels.get(normalized, "Dispositivo")
    return f"{label} {number}".strip()


def _structural_display_label(key: str) -> str:
    """Readable fallback for lightweight adapter/test dictionaries."""
    match = re.fullmatch(r"art:(\d+)(?::par:([^:]+))?(?::inc:([^:]+))?(?::al:([^:]+))?(?:#\d+)?", key)
    if not match:
        return "Dispositivo normativo"
    article, paragraph, inciso, alinea = match.groups()
    parts = [f"Art. {article}º"]
    if paragraph == "unico":
        parts.append("parágrafo único")
    elif paragraph:
        parts.append(f"§ {paragraph}º")
    if inciso:
        parts.append(f"inciso {inciso}")
    if alinea:
        parts.append(f"alínea {alinea}")
    return ", ".join(parts)
