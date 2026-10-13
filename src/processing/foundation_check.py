"""Read-only temporal comparison for explicitly cited normative authorities."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.norma_queries import consolidated_normas_for_product
from src.processing.corpus_coverage import current_corpus_coverage
from src.processing.corpus_identity import get_corpus_revision
from src.processing.document_metadata import TYPE_SERIES
from src.processing.foundation_reference_parser import (
    MAX_FOUNDATION_REFERENCES,
    parse_foundation_references,
)
from src.processing.normative_projection import project_norma_as_of
from src.processing.normative_reference import canonical_type, normalize_number

MAX_DISTINCT_NORMS = 20


class FoundationCheckCancelled(Exception):
    """Raised when the authenticated caller cancels an in-flight check."""


def _device_matches(projection, reference) -> list:
    devices = list(projection.devices)
    if not reference.article:
        return devices
    article_number = normalize_number(reference.article)
    articles = [
        item for item in devices
        if item.source.tipo.casefold() == "artigo"
        and normalize_number(item.source.numero) == article_number
    ]
    if len(articles) != 1:
        return []
    selected = articles
    parent_key = articles[0].source.structural_key
    for kind, number in (
        ("paragrafo", reference.paragraph),
        ("inciso", reference.item),
        ("alinea", reference.alinea),
    ):
        if not number:
            continue
        normalized = normalize_number(number)
        matches = [
            item for item in devices
            if item.source.tipo.casefold() == kind
            and item.source.parent_key == parent_key
            and (
                normalize_number(item.source.numero) == normalized
                or (kind == "paragrafo" and number == "único" and item.source.numero.casefold() == "único")
            )
        ]
        if len(matches) != 1:
            return []
        selected = matches
        parent_key = matches[0].source.structural_key
    return selected


def _projection_evidence(norma, projection, devices, as_of: date) -> list[dict]:
    evidence = []
    for projected in devices:
        key = (
            f"{norma.pk}:{as_of.isoformat()}:{projection.input_sha256}:"
            f"{projected.source.structural_key}:{projection.content_sha256}"
        )
        document = projected.source.extracao.documento
        evidence.append(
            {
                "evidence_id": "ev_" + hashlib.sha256(key.encode()).hexdigest()[:24],
                "document_id": str(document.public_id),
                "page": projected.source.page_index + 1 if projected.source.page_index is not None else None,
                "structural_key": projected.source.structural_key,
                "legal_status": projected.legal_status,
                "text": projected.text,
                "source_event_id": (getattr(projected, "provenance", None) or {}).get("event_id"),
                "source_norma_id": (getattr(projected, "provenance", None) or {}).get("source_norma_id"),
                "effective_on": (getattr(projected, "provenance", None) or {}).get("effective_on"),
                "input_sha256": projection.input_sha256,
                "content_sha256": projection.content_sha256,
            }
        )
    return evidence


def _resolve_norma(reference):
    if not reference.type_key or not reference.number or reference.year is None:
        return None, "incomplete_reference"
    candidates = list(
        consolidated_normas_for_product()
        .filter(ano=reference.year, numero__in={reference.number, _format_number(reference.number)})
        .order_by("pk")[:50]
    )
    matches = [
        norma for norma in candidates
        if canonical_type(norma.get_tipo_display_name()) == reference.type_key
    ]
    if not matches:
        return None, "not_found"
    if len(matches) != 1:
        return None, "ambiguous_identity"
    return matches[0], "resolved"


def _format_number(number: str) -> str:
    digits = normalize_number(number)
    first = len(digits) % 3 or 3
    return ".".join([digits[:first], *(digits[index : index + 3] for index in range(first, len(digits), 3))])


def _reviewed_scope_for(norma, coverage: dict, from_date: date, to_date: date) -> dict | None:
    """Return only an explicitly reviewed source scope covering this norm and period."""
    identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    jurisdiction = str(identity.get("jurisdiction") or "BR-RN-NATAL").strip().upper()
    series = identity.get("series") or TYPE_SERIES.get(
        canonical_type(norma.get_tipo_display_name())
    )
    if not series:
        return None

    for scope in coverage.get("sources_checked") or []:
        if not isinstance(scope, dict):
            continue
        if (
            str(scope.get("jurisdiction") or "").strip().upper() != jurisdiction
            or str(scope.get("series") or "").strip().casefold() != str(series).casefold()
            or scope.get("coverage_status") != "reviewed"
            or scope.get("missing_intervals") != []
            or scope.get("pending_review") != 0
        ):
            continue
        try:
            period_start = date.fromisoformat(str(scope.get("period_start")))
            period_end = date.fromisoformat(str(scope.get("period_end")))
            checked_until = date.fromisoformat(str(scope.get("checked_until")))
        except (TypeError, ValueError):
            continue
        if period_start <= from_date and period_end >= to_date and checked_until >= to_date:
            return {
                "source": scope.get("source"),
                "jurisdiction": jurisdiction,
                "series": series,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "checked_until": checked_until.isoformat(),
            }
    return None


def check_foundation(
    text: str,
    *,
    from_date: date,
    to_date: date,
    should_cancel=None,
    on_progress=None,
) -> dict:
    """Compare parsed citations against two explicit, read-only projections.

    The submitted text is parsed in memory only. This function never invokes an
    LLM, persists the input, or writes snapshots. Incomplete projections remain
    inconclusive; they are never treated as evidence of no change.
    """
    if (
        not isinstance(from_date, date)
        or isinstance(from_date, datetime)
        or not isinstance(to_date, date)
        or isinstance(to_date, datetime)
    ):
        raise TypeError("from_date e to_date devem ser datetime.date")
    if from_date >= to_date:
        raise ValueError("from_date deve ser anterior a to_date")
    references = parse_foundation_references(text)
    if len(references) > MAX_FOUNDATION_REFERENCES:
        raise ValueError("limite de referências excedido")

    corpus_revision = get_corpus_revision()
    corpus_coverage = current_corpus_coverage(corpus_revision or {})
    resolved: dict[str, tuple] = {}
    outcomes = []
    for reference in references:
        item = {
            "reference_id": reference.reference_id,
            "span": {"start": reference.start, "end": reference.end},
            "text": reference.text,
            "identity": {
                "type": reference.type_key,
                "number": reference.number,
                "year": reference.year,
                "article": reference.article,
                "paragraph": reference.paragraph,
                "item": reference.item,
                "alinea": reference.alinea,
            },
            "association": reference.association,
            "status": "inconclusive",
            "reason": None,
            "evidence": {"before": [], "after": []},
            "coverage": {"corpus": corpus_coverage},
        }
        if reference.requires_confirmation:
            item["status"] = "confirmation_required"
            item["reason"] = reference.ambiguity_reason or "confirme a norma associada a esta referência"
            outcomes.append(item)
            continue
        if not reference.article:
            item["reason"] = "cite ao menos um artigo para limitar a conferência temporal"
            outcomes.append(item)
            continue

        norma, resolution = _resolve_norma(reference)
        if not norma:
            item["status"] = "inconclusive"
            item["reason"] = {
                "not_found": "norma não localizada entre as normas consolidadas",
                "ambiguous_identity": "mais de uma norma corresponde à identidade citada",
                "incomplete_reference": "espécie, número e ano são necessários para localizar a norma",
            }[resolution]
            outcomes.append(item)
            continue
        item["norma_id"] = norma.pk
        item["norma"] = str(norma)
        resolved[str(norma.pk)] = (norma, [])
        outcomes.append(item)

    if len(resolved) > MAX_DISTINCT_NORMS:
        raise ValueError(f"limite de {MAX_DISTINCT_NORMS} normas distintas por conferência")

    projections = {}
    total_projections = max(1, len(resolved) * 2)
    completed_projections = 0
    for norma_id, (norma, _unused) in resolved.items():
        for as_of, label in ((from_date, "before"), (to_date, "after")):
            if should_cancel and should_cancel():
                raise FoundationCheckCancelled
            projections[(norma_id, label)] = project_norma_as_of(norma, as_of)
            completed_projections += 1
            if on_progress:
                on_progress(completed_projections, total_projections)
    if should_cancel and should_cancel():
        raise FoundationCheckCancelled

    for item in outcomes:
        norma_id = item.get("norma_id")
        if norma_id is None:
            continue
        before = projections[(str(norma_id), "before")]
        after = projections[(str(norma_id), "after")]
        if before.status != NormativeSnapshot.Status.COMPLETE or after.status != NormativeSnapshot.Status.COMPLETE:
            item["reason"] = "uma ou ambas as projeções temporais estão incompletas ou não são reconstruíveis"
            item["coverage"].update({"before": before.coverage, "after": after.coverage})
            continue
        before_devices = _device_matches(before, _reference_proxy(item["identity"]))
        after_devices = _device_matches(after, _reference_proxy(item["identity"]))
        if not before_devices or not after_devices:
            item["reason"] = "o dispositivo citado não foi localizado nos dois cortes temporais"
            item["coverage"].update({"before": before.coverage, "after": after.coverage})
            continue
        item["coverage"].update({"before": before.coverage, "after": after.coverage})
        item["evidence"] = {
            "before": _projection_evidence(
                resolved[str(norma_id)][0], before, before_devices, from_date
            ),
            "after": _projection_evidence(
                resolved[str(norma_id)][0], after, after_devices, to_date
            ),
        }
        before_states = {device.legal_status for device in before_devices}
        after_states = {device.legal_status for device in after_devices}
        if "unknown" in before_states or "unknown" in after_states:
            item["reason"] = "há evento temporal pendente ou conflitante no dispositivo citado"
        elif "revoked" in after_states:
            item["status"] = "revoked"
        elif "vetoed" in after_states:
            item["status"] = "vetoed"
        elif before_states != after_states or [device.text for device in before_devices] != [device.text for device in after_devices]:
            item["status"] = "changed"
        else:
            selected_scope = _reviewed_scope_for(
                resolved[str(norma_id)][0], corpus_coverage, from_date, to_date
            )
            item["coverage"]["selected_scope"] = selected_scope
            if selected_scope:
                item["status"] = "unchanged_in_checked_scope"
                item["reason"] = (
                    "Nenhuma diferença foi encontrada no escopo revisado "
                    f"{selected_scope['source']} / {selected_scope['series']} até "
                    f"{selected_scope['checked_until']}; isso não é uma afirmação fora desse escopo."
                )
            else:
                item["status"] = "inconclusive"
                item["observation"] = "same_projected_text"
                item["reason"] = (
                    "As redações projetadas coincidem, mas não há escopo de cobertura revisado "
                    "para esta série e estas datas; isso não permite afirmar que não houve alteração."
                )

    return {
        "comparison": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "corpus_revision": corpus_revision,
        "corpus_coverage": corpus_coverage,
        "references": outcomes,
        "count": len(outcomes),
        "summary": {
            status: sum(1 for outcome in outcomes if outcome["status"] == status)
            for status in (
                "changed", "revoked", "vetoed", "unchanged_in_checked_scope",
                "inconclusive", "confirmation_required",
            )
        },
        "persisted": False,
        "llm_used": False,
    }


def _reference_proxy(identity: dict):
    from types import SimpleNamespace

    return SimpleNamespace(**identity)
