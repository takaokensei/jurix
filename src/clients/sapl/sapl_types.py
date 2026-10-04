"""Conservative SAPL type-label adapter with lossless unknown handling."""

from __future__ import annotations

from src.processing.normative_reference import canonical_type

CATALOG_VERSION = "natal-explicit-label-aliases-v1"
PUBLIC_LABELS = {
    "lei": "Lei",
    "lei_complementar": "Lei Complementar",
    "lei_organica": "Lei Orgânica",
    "lei_promulgada": "Lei Promulgada",
    "decreto": "Decreto",
    "decreto_legislativo": "Decreto Legislativo",
    "decreto_lei": "Decreto-Lei",
    "resolucao": "Resolução",
    "portaria": "Portaria",
    "emenda": "Emenda",
    "emenda_constitucional": "Emenda Constitucional",
}


def classify_sapl_type(raw_value) -> dict[str, str | bool]:
    """Preserve the incoming code/label; only normalize recognized text labels."""
    raw_code = ""
    raw_label = ""
    if isinstance(raw_value, dict):
        raw_code = str(raw_value.get("id") or raw_value.get("codigo") or "").strip()
        raw_label = str(raw_value.get("descricao") or raw_value.get("sigla") or "").strip()
    else:
        raw_label = str(raw_value or "").strip()
        if raw_label.isdecimal():
            raw_code, raw_label = raw_label, ""

    # The only legacy numeric code retained is code 1, covered by existing
    # stored-corpus contracts. All other numeric codes stay opaque.
    if raw_code == "1" and not raw_label:
        raw_label = "Lei"
    key = canonical_type(raw_label) if raw_label else ""
    recognized = key in PUBLIC_LABELS
    return {
        "raw_code": raw_code,
        "raw_label": raw_label or raw_code,
        "public_label": PUBLIC_LABELS.get(key, raw_label or raw_code),
        "known": recognized,
        "catalog_version": CATALOG_VERSION,
    }
