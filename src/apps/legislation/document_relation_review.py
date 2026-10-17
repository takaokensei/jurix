"""Human review workflow for extracted relation candidates (non-operative)."""

from __future__ import annotations

import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
    ExtracaoDocumento,
    RevisaoEventoNormativoCandidato,
)
from src.apps.legislation.models import Norma


def _is_synthetic_norma(norma: Norma) -> bool:
    identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    return identity.get("synthetic_fixture") is True or identity.get("synthetic") is True


def can_review_document_relation(user) -> bool:
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm("legislation.review_eventonormativocandidato")
        and user.has_perm("legislation.view_documentonormativo")
    )


def candidate_target_normas(candidate: EventoNormativoCandidato) -> list[Norma]:
    """Resolve only an exact extracted municipal identity; never fuzzy-match."""
    reference = candidate.target_reference_json
    try:
        year = int(reference.get("year_candidate"))
    except (TypeError, ValueError):
        return []
    number = str(reference.get("number_candidate") or "").strip()
    type_key = str(reference.get("type_candidate") or "").strip()
    if not number or not type_key:
        return []

    from src.processing.document_metadata import (
        is_natal_municipal_jurisdiction,
        normalize_document_number,
    )
    from src.processing.normative_reference import canonical_type

    number_key = normalize_document_number(number)
    type_key = canonical_type(type_key)
    matches = []
    for norma in Norma.objects.filter(ano=year).only(
        "id", "tipo", "numero", "ano", "identity_json"
    ):
        if _is_synthetic_norma(norma):
            continue
        identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        jurisdiction = str(identity.get("jurisdiction") or "")
        if not is_natal_municipal_jurisdiction(jurisdiction):
            continue
        if (
            canonical_type(norma.tipo) == type_key
            and normalize_document_number(norma.numero) == number_key
        ):
            matches.append(norma)
    return matches


def candidate_target_type_conflicts(candidate: EventoNormativoCandidato) -> list[Norma]:
    """Find same-number/year municipal records whose legal species differs.

    These are review leads only. They are never resolved automatically and are
    kept separate from exact matches so the UI can make the identity conflict
    explicit before an authorized reviewer records a decision.
    """
    reference = candidate.target_reference_json
    try:
        year = int(reference.get("year_candidate"))
    except (TypeError, ValueError):
        return []
    number = str(reference.get("number_candidate") or "").strip()
    type_key = str(reference.get("type_candidate") or "").strip()
    if not number or not type_key:
        return []

    from src.processing.document_metadata import (
        is_natal_municipal_jurisdiction,
        normalize_document_number,
    )
    from src.processing.normative_reference import canonical_type

    number_key = normalize_document_number(number)
    type_key = canonical_type(type_key)
    conflicts = []
    for norma in Norma.objects.filter(ano=year).only(
        "id", "tipo", "numero", "ano", "identity_json"
    ):
        if _is_synthetic_norma(norma):
            continue
        identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        jurisdiction = str(identity.get("jurisdiction") or "")
        if not is_natal_municipal_jurisdiction(jurisdiction):
            continue
        if (
            normalize_document_number(norma.numero) == number_key
            and canonical_type(norma.tipo) != type_key
        ):
            conflicts.append(norma)
            if len(conflicts) >= 5:
                break
    return conflicts


def _candidate_target_article_preview(
    extraction: ExtracaoDocumento, article_number: str
) -> dict | None:
    """Return a bounded, explicitly unreviewed target-device excerpt from a candidate PDF."""
    if extraction.status != ExtracaoDocumento.Status.COMPLETE or not extraction.legal_text:
        return None

    from src.apps.ingestion.document_relation_candidates import prepare_candidate_devices
    from src.processing.legal_parser import classify_closing_segments

    def normalize(value: object) -> str:
        normalized = re.sub(r"[^0-9a-z]", "", str(value or "").casefold())
        return normalized.lstrip("0") or "0"

    try:
        wanted = normalize(article_number)
        devices = prepare_candidate_devices(extraction)
    except (TypeError, ValueError, ValidationError):
        return None
    matches = [
        device
        for device in devices
        if device.get("tipo") == "artigo" and normalize(device.get("numero")) == wanted
    ]
    if len(matches) != 1:
        return None

    device = matches[0]
    start = device.get("start_offset")
    end = device.get("end_offset")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end:
        return None
    colophon_starts = [
        segment["start"]
        for segment in classify_closing_segments(extraction.legal_text)
        if segment.get("kind") == "editorial_colophon"
        and isinstance(segment.get("start"), int)
        and start < segment["start"] < end
    ]
    if colophon_starts:
        end = min(colophon_starts)
    excerpt = extraction.legal_text[start:end].strip()
    if not excerpt:
        return None
    return {
        "article_number": str(device.get("numero") or article_number),
        "text": excerpt[:3000],
        "truncated": len(excerpt) > 3000,
        "page_index": device.get("page_index"),
        "review_status": "candidate_unreviewed",
        "extraction_sha256_prefix": extraction.extraction_sha256[:12],
    }


def candidate_target_documents_for_candidates(candidates) -> dict[int, list[dict]]:
    """Batch-index local PDF leads by exact number/year, keeping species visible."""
    from src.processing.document_metadata import (
        is_natal_municipal_jurisdiction,
        normalize_document_number,
    )
    from src.processing.normative_reference import canonical_type

    references = {}
    years = set()
    for candidate in candidates:
        reference = candidate.target_reference_json
        try:
            year = int(reference.get("year_candidate"))
        except (AttributeError, TypeError, ValueError):
            continue
        number = normalize_document_number(str(reference.get("number_candidate") or ""))
        type_key = canonical_type(str(reference.get("type_candidate") or ""))
        if not number or not type_key:
            continue
        reference_type = str(reference.get("structural_type") or "")
        article_number = (
            str(reference.get("structural_article_number") or reference.get("structural_number") or "")
            if reference_type == "artigo"
            else ""
        )
        references[candidate.pk] = (year, number, type_key, article_number)
        years.add(year)

    if not years:
        return {}

    document_index = {}
    documents = DocumentoNormativo.objects.filter(
        source_kind__in=(
            DocumentoNormativo.SourceKind.ARCHIVE,
            DocumentoNormativo.SourceKind.SAPL,
        ),
        metadata_json__identity_candidate__year__in=years | {str(year) for year in years},
    ).only("id", "public_id", "source_kind", "review_status", "original_filename", "metadata_json")
    for document in documents:
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity = metadata.get("identity_candidate")
        if (
            not isinstance(identity, dict)
            or metadata.get("synthetic") is True
            or metadata.get("synthetic_fixture") is True
            or identity.get("synthetic") is True
            or identity.get("synthetic_fixture") is True
        ):
            continue
        if not is_natal_municipal_jurisdiction(str(identity.get("jurisdiction") or "")):
            continue
        try:
            year = int(identity.get("year"))
        except (TypeError, ValueError):
            continue
        number = normalize_document_number(str(identity.get("number") or ""))
        if year not in years or not number:
            continue
        key = (year, number)
        document_index.setdefault(key, []).append(
            (document, canonical_type(str(identity.get("type") or "")))
        )

    result = {}
    for candidate_id, (year, number, type_key, _article_number) in references.items():
        matches = [
            {"document": document, "identity_type": identity_type, "type_matches": identity_type == type_key}
            for document, identity_type in document_index.get((year, number), [])
        ]
        result[candidate_id] = sorted(
            matches,
            key=lambda item: (
                not item["type_matches"],
                item["document"].review_status != DocumentoNormativo.ReviewStatus.APPROVED,
                item["document"].pk,
            ),
        )

    preview_targets = list(
        dict.fromkeys(
            item["document"].pk
            for candidate_id, (_year, _number, _type_key, article_number) in references.items()
            if article_number
            for item in result.get(candidate_id, [])
            if item["type_matches"]
        )
    )[:20]
    latest_extraction_by_document = {}
    if preview_targets:
        extractions = ExtracaoDocumento.objects.filter(
            documento_id__in=preview_targets,
            status=ExtracaoDocumento.Status.COMPLETE,
        ).order_by("documento_id", "-created_at", "-pk")
        for extraction in extractions:
            latest_extraction_by_document.setdefault(extraction.documento_id, extraction)

    preview_cache = {}
    for candidate_id, (_year, _number, _type_key, article_number) in references.items():
        if not article_number:
            continue
        for item in result.get(candidate_id, []):
            if not item["type_matches"]:
                continue
            extraction = latest_extraction_by_document.get(item["document"].pk)
            if extraction is None:
                continue
            preview_key = (extraction.pk, article_number)
            if preview_key not in preview_cache:
                preview_cache[preview_key] = _candidate_target_article_preview(
                    extraction, article_number
                )
            if preview_cache[preview_key] is not None:
                item["device_preview"] = preview_cache[preview_key]
    return result


def candidate_target_documents(candidate: EventoNormativoCandidato) -> list[dict]:
    """Return local public-document leads without treating them as resolved norms."""
    return candidate_target_documents_for_candidates([candidate]).get(candidate.pk, [])


@transaction.atomic
def review_document_relation_candidate(
    *,
    candidate_id: int,
    actor,
    decision: str,
    reason: str,
    expected_fingerprint: str,
    target_norma_id: int | None = None,
) -> RevisaoEventoNormativoCandidato:
    """Record an append-only review of extraction only, never legal validity."""
    if not can_review_document_relation(actor):
        raise PermissionDenied("Você não tem permissão para revisar relações extraídas.")
    if decision not in RevisaoEventoNormativoCandidato.Decision.values:
        raise ValidationError("Decisão de revisão inválida.")
    if not reason or not reason.strip():
        raise ValidationError("Informe o motivo da revisão.")
    candidate = (
        EventoNormativoCandidato.objects.select_for_update()
        .select_related("extracao")
        .get(pk=candidate_id)
    )
    if not expected_fingerprint or expected_fingerprint != candidate.fingerprint:
        raise ValidationError("O candidato mudou; recarregue a evidência antes de revisar.")

    target = None
    if decision == RevisaoEventoNormativoCandidato.Decision.CONFIRM:
        if target_norma_id:
            allowed = {
                norma.pk
                for norma in candidate_target_normas(candidate)
            }
            if target_norma_id not in allowed:
                raise ValidationError(
                    "A norma escolhida não corresponde exatamente à espécie, número e ano extraídos."
                )
            target = Norma.objects.select_for_update().get(pk=target_norma_id)
    elif target_norma_id:
        raise ValidationError("Rejeição não pode registrar norma-alvo.")

    latest = candidate.revisoes.order_by("-created_at", "-pk").first()
    if (
        latest
        and latest.candidate_fingerprint == candidate.fingerprint
        and latest.source_extraction_sha256 == candidate.extracao.extraction_sha256
        and latest.decision == decision
        and latest.target_norma_id == (target.pk if target else None)
        and latest.reason == reason.strip()
        and latest.actor_id == actor.pk
    ):
        return latest
    return RevisaoEventoNormativoCandidato.objects.create(
        candidato=candidate,
        candidate_fingerprint=candidate.fingerprint,
        source_extraction_sha256=candidate.extracao.extraction_sha256,
        decision=decision,
        target_norma=target,
        reason=reason.strip(),
        actor=actor,
    )
