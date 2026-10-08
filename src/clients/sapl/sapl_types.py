"""Conservative SAPL type-label adapter with lossless unknown handling."""

from __future__ import annotations

import unicodedata

from src.processing.normative_reference import canonical_type

CATALOG_VERSION = "natal-type-catalog-observed-2026-10-v1"
PUBLIC_LABELS = {
    "lei": "Lei",
    "lei_complementar": "Lei Complementar",
    "lei_organica": "Lei Orgânica",
    "lei_organica_municipio": "Lei Orgânica do Município",
    "lei_promulgada": "Lei Promulgada",
    "decreto": "Decreto",
    "decreto_legislativo": "Decreto Legislativo",
    "decreto_lei": "Decreto-Lei",
    "resolucao": "Resolução",
    "portaria": "Portaria",
    "emenda": "Emenda",
    "emenda_constitucional": "Emenda Constitucional",
    "emenda_lei_organica": "Emenda à Lei Orgânica do Município",
    "lei_diretrizes_orcamentarias": "Lei de Diretrizes Orçamentárias",
    "regimento_interno": "Regimento Interno",
}

# The labels below were observed in the read-only Natal SAPL type catalogue.
# Match descriptions, never numeric IDs: IDs are installation-local and opaque.
CATALOG_LABEL_KEYS = {
    "emendaaleiorganicadomunicipio": "emenda_lei_organica",
    "leidediretrizesorcamentarias": "lei_diretrizes_orcamentarias",
    "leiorganicadomunicipio": "lei_organica_municipio",
    "regimentointerno": "regimento_interno",
}
TYPE_SERIES = {
    "lei": "municipal_lo",
    "lei_complementar": "municipal_lc",
    "decreto": "municipal_decreto",
    "lei_promulgada": "municipal_lp",
}


def classify_sapl_type(raw_value) -> dict[str, str | bool | None]:
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

    folded_label = unicodedata.normalize("NFKD", raw_label.casefold())
    normalized_label = "".join(
        character
        for character in folded_label
        if not unicodedata.combining(character) and character.isalnum()
    )
    key = CATALOG_LABEL_KEYS.get(normalized_label) or (
        canonical_type(raw_label) if raw_label else ""
    )
    recognized = key in PUBLIC_LABELS
    return {
        "raw_code": raw_code,
        "raw_label": raw_label or raw_code,
        "public_label": PUBLIC_LABELS.get(
            key,
            raw_label if raw_label and not raw_label.isdecimal() else "Tipo não identificado",
        ),
        "type_key": key if recognized else None,
        # Do not invent a series for ELO, LDO, Lei Orgânica or Regimento Interno.
        "series": TYPE_SERIES.get(key),
        "known": recognized,
        "catalog_version": CATALOG_VERSION,
    }


def resolve_norma_type_display(tipo, sapl_metadata=None) -> str:
    """Resolve a public label without treating an opaque numeric ID as a law.

    Current rows normally store a textual type. Legacy rows may store a
    catalog-local numeric ID, in which case only the original SAPL payload or
    the lossless ``_jurix_type_catalog`` metadata can disambiguate it.
    """
    raw_tipo = str(tipo or "").strip()
    direct = classify_sapl_type(raw_tipo)
    if direct["known"]:
        return str(direct["public_label"])
    if raw_tipo and not raw_tipo.isdecimal():
        # An explicit textual type is more reliable than any unrelated local ID.
        return str(direct["public_label"])

    metadata = sapl_metadata if isinstance(sapl_metadata, dict) else {}
    catalog_metadata = metadata.get("_jurix_type_catalog")
    if isinstance(catalog_metadata, dict):
        catalog_key = str(catalog_metadata.get("type_key") or "")
        if catalog_metadata.get("known") is True and catalog_key in PUBLIC_LABELS:
            return PUBLIC_LABELS[catalog_key]
        catalog_label = str(catalog_metadata.get("raw_label") or "").strip()
        if catalog_label and not catalog_label.isdecimal():
            return catalog_label

    candidates = [metadata.get("tipo")]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = classify_sapl_type(candidate)
        if resolved["known"]:
            return str(resolved["public_label"])
        raw_label = str(resolved.get("raw_label") or "").strip()
        if raw_label and not raw_label.isdecimal():
            return raw_label

    return "Tipo não identificado"
