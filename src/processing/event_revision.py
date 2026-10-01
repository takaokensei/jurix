"""Deterministic identity for safely reconciling extracted legal events."""

from __future__ import annotations

import hashlib
import json
import re

EXTRACTOR_VERSION = "regex-v1"


def event_revision_identity(
    *,
    source_identity: str,
    source_revision: str,
    action: str,
    target_text: str,
    reference_type: str,
    reference_number: str,
    target_norma_id: int | None,
    occurrence: int,
    extractor_version: str = EXTRACTOR_VERSION,
) -> tuple[str, dict[str, object]]:
    """Fingerprint source evidence plus extraction output; return safe provenance."""

    def normalize(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()

    provenance: dict[str, object] = {
        "schema_version": 1,
        "extractor_version": extractor_version,
        "source_identity": source_identity,
        "source_revision": source_revision,
        "action": normalize(action),
        "target_text": normalize(target_text),
        "reference_type": normalize(reference_type),
        "reference_number": normalize(reference_number),
        "target_norma_id": target_norma_id,
        "occurrence": occurrence,
    }
    payload = json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), provenance
