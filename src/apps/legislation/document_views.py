"""Access-controlled HTML/PDF delivery for versioned normative documents."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.official_urls import safe_official_url


def _approved_public_document(document: DocumentoNormativo) -> bool:
    return bool(
        document.norma_id
        and document.review_status == DocumentoNormativo.ReviewStatus.APPROVED
        and document.role == DocumentoNormativo.Role.ORIGINAL
        and document.condition_of_use
        in {DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED, DocumentoNormativo.ConditionOfUse.LICENSED}
        and document.accepted_extraction_id
        and RevisaoJuridica.objects.filter(
            documento=document,
            decision=RevisaoJuridica.Decision.APPROVE,
            target_fingerprint=promotion_fingerprint(document),
        ).exists()
    )


def _staff_can_view_candidate(request: HttpRequest) -> bool:
    user = request.user
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm("legislation.view_documentonormativo")
    )


def _authorized_document(request: HttpRequest, document_id) -> DocumentoNormativo:
    document = (
        DocumentoNormativo.objects.select_related("norma", "accepted_extraction")
        .filter(public_id=document_id)
        .first()
    )
    if document is None:
        raise Http404("Documento não encontrado.")
    qa_archive_review = bool(
        getattr(settings, "DEBUG", False)
        and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
        and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
        and document.review_status in {
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        }
    )
    if (
        not _approved_public_document(document)
        and not _staff_can_view_candidate(request)
        and not qa_archive_review
    ):
        # Deliberately hide candidate existence from anonymous/unauthorized users.
        raise Http404("Documento não encontrado.")
    return document


def _storage_root() -> Path:
    configured = getattr(settings, "NORMATIVE_ARCHIVE_ROOT", None)
    if configured:
        root = Path(configured)
    else:
        root = Path(getattr(settings, "QA_ROOT", settings.MEDIA_ROOT)) / "normative-archive"
    return root.resolve()


def _document_path(document: DocumentoNormativo) -> Path:
    raw = str(document.storage_key or "").replace("\\", "/")
    key = PurePosixPath(raw)
    if (
        not raw
        or key.is_absolute()
        or raw.startswith("//")
        or ".." in key.parts
        or (len(raw) > 1 and raw[1] == ":")
        or "\x00" in raw
    ):
        raise Http404("Documento indisponível.")
    root = _storage_root()
    candidate = (root / Path(*key.parts)).resolve(strict=False)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise Http404("Documento indisponível.")
    return candidate


def local_pdf_available(document: DocumentoNormativo) -> bool:
    try:
        _document_path(document)
    except Http404:
        return False
    return True


def _private_headers(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def document_evidence_view(request: HttpRequest, document_id) -> HttpResponse:
    document = _authorized_document(request, document_id)
    candidate_identity = (document.metadata_json or {}).get("identity_candidate") or {}
    candidate_type_labels = {
        "lei": "Lei",
        "lei_ordinaria": "Lei Ordinária",
        "lei_complementar": "Lei Complementar",
        "decreto": "Decreto",
        "lei_promulgada": "Lei Promulgada",
    }
    candidate_number = candidate_identity.get("number")
    candidate_year = candidate_identity.get("year")
    candidate_identity_label = (
        f"{candidate_type_labels.get(candidate_identity.get('type'), 'Norma')} nº "
        f"{candidate_number}/{candidate_year}"
        if candidate_number and candidate_year
        else ""
    )
    extraction = document.accepted_extraction
    candidate_extraction = False
    if (
        extraction is None
        and getattr(settings, "DEBUG", False)
        and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
        and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    ):
        extraction = document.extracoes.order_by("-created_at", "-pk").first()
        candidate_extraction = extraction is not None
    devices = list(extraction.dispositivos_documentais.order_by("ordem", "pk")) if extraction else []
    return _private_headers(
        render(
            request,
            "legislation/document_evidence.html",
            {
                "document": document,
                "candidate_identity_label": candidate_identity_label,
                "extraction": extraction,
                "candidate_extraction": candidate_extraction,
                "devices": devices,
                "official_url": safe_official_url(document.official_url),
                "local_pdf_available": local_pdf_available(document),
            },
        )
    )


@require_GET
def document_pdf_view(request: HttpRequest, document_id) -> HttpResponse:
    document = _authorized_document(request, document_id)
    path = _document_path(document)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if digest.hexdigest() != document.content_sha256 or size != document.size_bytes:
        raise Http404("Documento indisponível.")
    response = FileResponse(path.open("rb"), content_type="application/pdf", as_attachment=False)
    response["Content-Disposition"] = f'inline; filename="document-{document.public_id}.pdf"'
    return _private_headers(response)
