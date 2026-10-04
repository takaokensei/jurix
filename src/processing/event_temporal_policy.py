"""Fail-closed temporal policy for extracted normative events."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

_PUBLICATION_CLAUSE = re.compile(
    r"\b(?:esta\s+lei|este\s+decreto|a\s+presente\s+norma|a\s+presente\s+lei)"
    r"[^.;\n]{0,180}?\bentra(?:r[aá])?\s+em\s+vigor\s+na\s+data\s+de\s+sua\s+publica[çc][ãa]o\b[^.;\n]*[.]?",
    re.IGNORECASE,
)
_UNSUPPORTED_EFFECT = re.compile(
    r"\b(?:retroativ\w*|retroag\w*|enquanto\s+perdurar|enquanto\s+durar|"
    r"condicionado\s+a|desde\s+que|ap[oó]s\s+\d+\s+dias|vacatio\s+de\s+\d+)\b",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class EventTemporalDecision:
    effective_on: date | None
    status: str
    basis: dict[str, Any]
    reason: str
    publication_on: date | None = None
    operative: bool = False


def temporal_candidate_fingerprint(event, effective_on: date, evidence_quote: str) -> str:
    """Fingerprint the relation evidence together with the proposed effect date."""
    from src.apps.legislation.event_review import event_review_fingerprint

    payload = [
        event_review_fingerprint(event),
        effective_on.isoformat(),
        _SPACE_RE.sub(" ", evidence_quote or "").strip(),
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _has_exact_quote(source_text: str, quote: str) -> bool:
    normalized_source = _SPACE_RE.sub(" ", source_text or "").strip()
    normalized_quote = _SPACE_RE.sub(" ", quote or "").strip()
    return len(normalized_quote) >= 12 and normalized_quote in normalized_source


def _date_review_exists(event, basis: dict[str, Any], effective_on: date, quote: str) -> bool:
    review_id = basis.get("review_id")
    if not review_id:
        return False
    try:
        review_id = UUID(str(review_id))
    except (TypeError, ValueError, AttributeError):
        return False
    from src.apps.legislation.review_models import RevisaoJuridica

    fingerprint = temporal_candidate_fingerprint(event, effective_on, quote)
    return RevisaoJuridica.objects.filter(
        public_id=review_id,
        evento_id=event.pk,
        target_fingerprint=fingerprint,
        decision=RevisaoJuridica.Decision.APPROVE,
    ).exists()


def event_temporal_decision(event) -> EventTemporalDecision:
    """Classify one event; only a current, separately reviewed date is operative."""
    action = str(getattr(event, "acao", "")).upper()
    source_device = getattr(event, "dispositivo_fonte", None)
    source_norma = getattr(source_device, "norma", None) if source_device else None
    publication_on = getattr(source_norma, "data_publicacao", None)
    if action in {"REFERENCIA", "REGULAMENTA"}:
        return EventTemporalDecision(
            None,
            "not_applicable",
            {
                "kind": "document_availability",
                "publication_on": publication_on.isoformat() if publication_on else None,
            },
            "A referência/regulamentação não é tratada como alteração temporal da redação.",
            publication_on=publication_on,
            operative=False,
        )
    if action not in {"ALTERA", "ADICIONA", "SUBSTITUI", "REVOGA"}:
        return EventTemporalDecision(
            None, "unsupported", {}, "A ação jurídica não está coberta pela política temporal."
        )

    source_text = getattr(source_device, "texto", "") if source_device else ""
    if _UNSUPPORTED_EFFECT.search(source_text):
        return EventTemporalDecision(
            None,
            "unsupported",
            {"kind": "conditional_or_retroactive_effect"},
            "O texto contém efeito condicional/retroativo que exige análise jurídica específica.",
            publication_on=publication_on,
        )

    stored_on = getattr(event, "effective_on", None)
    stored_status = getattr(event, "effective_date_status", "unknown")
    basis = getattr(event, "effective_date_basis", {}) or {}
    quote = str(basis.get("evidence_quote") or "") if isinstance(basis, dict) else ""
    if (
        stored_on
        and stored_status in {"candidate", "confirmed"}
        and _has_exact_quote(source_text, quote)
    ):
        if stored_status == "candidate":
            return EventTemporalDecision(
                stored_on,
                "candidate",
                dict(basis),
                "A data está sustentada por trecho literal, mas ainda requer confirmação humana.",
                publication_on=publication_on,
            )
        from src.apps.legislation.event_review import event_review_status

        relation_confirmed = event_review_status(event) == "confirmed"
        date_reviewed = _date_review_exists(event, basis, stored_on, quote)
        if relation_confirmed and date_reviewed and event.validado:
            return EventTemporalDecision(
                stored_on,
                "confirmed",
                dict(basis),
                "Data de efeito e relação com o alvo foram revisadas separadamente.",
                publication_on=publication_on,
                operative=bool(getattr(event, "is_active", True)),
            )
        return EventTemporalDecision(
            stored_on,
            "candidate",
            dict(basis),
            "A confirmação da data ou da relação está ausente ou desatualizada.",
            publication_on=publication_on,
        )

    publication_clause = _PUBLICATION_CLAUSE.search(source_text or "")
    if publication_clause and publication_on:
        return EventTemporalDecision(
            publication_on,
            "candidate",
            {
                "kind": "publication_clause",
                "evidence_quote": publication_clause.group(0).strip(),
                "publication_on": publication_on.isoformat(),
            },
            "A cláusula aponta para a publicação, mas a data de efeito ainda não foi revisada.",
            publication_on=publication_on,
        )
    return EventTemporalDecision(
        None,
        "unknown",
        {},
        "Não há data e fundamento temporal confirmados para este evento.",
        publication_on=publication_on,
    )
