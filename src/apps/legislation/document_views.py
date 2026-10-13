"""Access-controlled HTML/PDF delivery for versioned normative documents."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.ingestion.document_review import (
    DocumentReviewBlocked,
    accept_document_extraction,
    extraction_review_fingerprint,
    review_document_segmentation,
    segmentation_review_fingerprint,
)
from src.apps.ingestion.norma_registry import register_reviewed_identity
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.document_metadata import compare_identity_to_epigraph
from src.processing.document_segmentation import segment_document_extraction
from src.processing.official_urls import safe_official_url


def _format_candidate_number(value: object) -> str:
    number = str(value or "").strip()
    if "." in number or not number.isdigit() or len(number) <= 3:
        return number
    return f"{int(number):,}".replace(",", ".")


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


class IdentityReviewForm(forms.Form):
    confirm_identity = forms.BooleanField(
        label="Comparei o tipo, número e ano com a epígrafe do documento original.",
        required=True,
    )
    reason = forms.CharField(
        label="Justificativa da conferência",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4, "autocomplete": "off"}),
    )
    confirmed_condition_of_use = forms.ChoiceField(
        label="Base para uso do documento",
        choices=(
            (DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED, "Registro público conferido"),
            (DocumentoNormativo.ConditionOfUse.LICENSED, "Documento licenciado"),
        ),
    )
    confirmed_identity_key = forms.CharField(widget=forms.HiddenInput)
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["confirm_identity"].widget.attrs.update({
            "id": "id_confirm_identity",
            "aria-describedby": "id_confirm_identity-error",
        })
        self.fields["confirmed_condition_of_use"].widget.attrs.update({
            "id": "id_confirmed_condition_of_use",
            "aria-describedby": "id_confirmed_condition_of_use-error",
        })
        self.fields["reason"].widget.attrs.update({
            "id": "id_reason",
            "aria-describedby": "id_reason-help id_reason-error",
        })

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Descreva o que foi conferido antes de registrar a identidade.")
        return reason


class ExtractionReviewForm(forms.Form):
    confirm_extraction = forms.BooleanField(
        label="Comparei o texto extraído com o PDF, inclusive limites dos dispositivos, anexos e colofão.",
        required=True,
    )
    reason = forms.CharField(
        label="Justificativa da conferência da extração",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4, "autocomplete": "off"}),
    )
    extraction_id = forms.IntegerField(widget=forms.HiddenInput)
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["confirm_extraction"].widget.attrs.update({
            "id": "id_confirm_extraction",
            "aria-describedby": "id_confirm_extraction-error",
        })
        self.fields["reason"].widget.attrs.update({
            "id": "id_extraction_reason",
            "aria-describedby": "id_extraction_reason-help id_extraction_reason-error",
        })

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Registre o cotejo feito entre a extração e o PDF.")
        return reason


class SegmentationReviewForm(forms.Form):
    confirm_segmentation = forms.BooleanField(
        label="Conferi a divisão e a hierarquia dos dispositivos contra o PDF original.",
        required=True,
    )
    reason = forms.CharField(
        label="Justificativa da revisão da segmentação",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4, "autocomplete": "off"}),
    )
    extraction_id = forms.IntegerField(widget=forms.HiddenInput)
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Registre os limites e a hierarquia cotejados no PDF.")
        return reason


class SegmentationGenerationForm(forms.Form):
    confirm_generation = forms.BooleanField(
        label="Entendo que a prévia é automática e não representa aprovação jurídica.",
        required=True,
    )
    extraction_id = forms.IntegerField(widget=forms.HiddenInput)
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)


def _reviewer_can_register_identity(request: HttpRequest) -> bool:
    user = request.user
    required_permissions = (
        "legislation.change_documentonormativo",
        "legislation.add_norma",
        "legislation.add_revisaojuridica",
    )
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perms(required_permissions)
    )


def _reviewer_can_accept_extraction(request: HttpRequest) -> bool:
    user = request.user
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perms((
            "legislation.change_documentonormativo",
            "legislation.add_revisaojuridica",
        ))
    )


def _reviewer_can_review_segmentation(request: HttpRequest) -> bool:
    return _reviewer_can_accept_extraction(request)


def _extraction_quality_summary(extraction: ExtracaoDocumento | None) -> dict | None:
    if extraction is None:
        return None
    quality = extraction.quality_json if isinstance(extraction.quality_json, dict) else {}
    page_methods = quality.get("page_methods")
    page_methods = page_methods if isinstance(page_methods, dict) else {}

    def page_numbers(key: str) -> list[int]:
        values = quality.get(key)
        if not isinstance(values, list):
            return []
        result = set()
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                page = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= page <= extraction.page_count:
                result.add(page)
        return sorted(result)

    def method_count(key: str) -> int:
        value = page_methods.get(key, 0)
        if isinstance(value, bool):
            return 0
        try:
            return max(0, min(int(value), extraction.page_count))
        except (TypeError, ValueError):
            return 0

    unreadable_pages = page_numbers("unreadable_pages")
    ocr_pages = [] if quality.get("staging_only") else page_numbers("ocr_pages_attempted")
    summary = {
        "native_pages": method_count("native"),
        "ocr_pages": method_count("ocr"),
        "unreadable_count": method_count("unreadable"),
        "unreadable_pages": unreadable_pages,
        "ocr_pages_list": ocr_pages,
        "ocr_pending_pages": unreadable_pages if quality.get("staging_only") else [],
        "staging_only": bool(quality.get("staging_only")),
        "ocr_unverified": quality.get("ocr_text_is_not_certified_verbatim") is True,
        "needs_review": (
            quality.get("needs_review") is True
            or extraction.status != ExtracaoDocumento.Status.COMPLETE
        ),
    }
    if not page_methods and not unreadable_pages and not ocr_pages and not summary["staging_only"]:
        return None
    return summary


def _document_evidence_context(
    request: HttpRequest,
    document: DocumentoNormativo,
    *,
    identity_review_form=None,
    extraction_review_form=None,
    segmentation_review_form=None,
    segmentation_generation_form=None,
):
    candidate_identity = (document.metadata_json or {}).get("identity_candidate") or {}
    candidate_type_labels = {
        "lei": "Lei",
        "lei_ordinaria": "Lei Ordinária",
        "lei_complementar": "Lei Complementar",
        "decreto": "Decreto",
        "lei_promulgada": "Lei Promulgada",
    }
    candidate_number = _format_candidate_number(candidate_identity.get("number"))
    candidate_year = candidate_identity.get("year")
    candidate_identity_label = (
        f"{candidate_type_labels.get(candidate_identity.get('type'), 'Norma')} nº "
        f"{candidate_number}/{candidate_year}"
        if candidate_number and candidate_year
        else ""
    )
    extraction = document.accepted_extraction
    latest_extraction = document.extracoes.order_by("-created_at", "-pk").first()
    candidate_extraction = False
    if (
        extraction is None
        and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
        and (
            _staff_can_view_candidate(request)
            or (
                getattr(settings, "DEBUG", False)
                and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
            )
        )
    ):
        extraction = latest_extraction
        candidate_extraction = extraction is not None
    reviewer_can_accept_extraction = _reviewer_can_accept_extraction(request)
    devices = list(extraction.dispositivos_documentais.order_by("ordem", "pk")) if extraction else []
    identity_key = str((document.metadata_json or {}).get("identity_key") or "")
    reviewer_can_register = _reviewer_can_register_identity(request)
    reviewer_can_inspect_history = bool(
        reviewer_can_register or reviewer_can_accept_extraction
    )
    can_review_identity = bool(
        reviewer_can_register
        and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
        and not document.norma_id
        and candidate_identity_label
        and identity_key
        and not document.conflicts_json
        and not (document.metadata_json or {}).get("synthetic")
    )
    if identity_review_form is None and can_review_identity:
        identity_review_form = IdentityReviewForm(initial={
            "confirmed_identity_key": identity_key,
            "expected_fingerprint": promotion_fingerprint(document),
        })
    can_review_extraction = bool(
        reviewer_can_accept_extraction
        and document.norma_id
        and document.norma.identity_key == identity_key
        and document.role == DocumentoNormativo.Role.ORIGINAL
        and document.condition_of_use in {
            DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            DocumentoNormativo.ConditionOfUse.LICENSED,
        }
        and not document.conflicts_json
        and not (document.metadata_json or {}).get("synthetic")
        and document.review_status != DocumentoNormativo.ReviewStatus.REJECTED
        and document.accepted_extraction_id is None
        and latest_extraction is not None
        and latest_extraction.status == "complete"
        and bool(latest_extraction.legal_text.strip())
    )
    if extraction_review_form is None and can_review_extraction:
        extraction_review_form = ExtractionReviewForm(initial={
            "extraction_id": latest_extraction.pk,
            "expected_fingerprint": extraction_review_fingerprint(document, latest_extraction),
        })
    reviewer_can_review_segmentation = _reviewer_can_review_segmentation(request)
    can_review_segmentation = bool(
        reviewer_can_review_segmentation
        and extraction
        and not candidate_extraction
        and _approved_public_document(document)
        and document.norma.documento_base_id == document.pk
        and document.accepted_extraction_id == extraction.pk
        and extraction.status == ExtracaoDocumento.Status.COMPLETE
        and not document.conflicts_json
        and not (document.metadata_json or {}).get("synthetic")
    )
    segmentation_fingerprint = (
        segmentation_review_fingerprint(document, extraction)
        if can_review_segmentation
        else ""
    )
    segmentation_reviewed = bool(
        can_review_segmentation
        and RevisaoJuridica.objects.filter(
            documento=document,
            decision=RevisaoJuridica.Decision.APPROVE,
            target_fingerprint=segmentation_fingerprint,
            reason__startswith="[segmentação documental revisada]",
        ).exists()
    )
    can_generate_segmentation = bool(can_review_segmentation and not devices)
    if segmentation_review_form is None and can_review_segmentation and devices and not segmentation_reviewed:
        segmentation_review_form = SegmentationReviewForm(initial={
            "extraction_id": extraction.pk,
            "expected_fingerprint": segmentation_fingerprint,
        })
    extraction_review_registered = bool(
        reviewer_can_accept_extraction
        and document.accepted_extraction_id
        and request.GET.get("extraction") == "accepted"
    )
    metadata_candidates = (
        extraction.metadata_candidates_json
        if extraction and isinstance(extraction.metadata_candidates_json, dict)
        else {}
    )
    epigraph = metadata_candidates.get("epigraph") or {}
    epigraph_candidates = epigraph.get("candidates", []) if isinstance(epigraph, dict) else []
    identity_epigraph_check = compare_identity_to_epigraph(candidate_identity, epigraph)
    epigraph_type_labels = {
        "lei": "Lei",
        "lei_ordinaria": "Lei Ordinária",
        "lei_complementar": "Lei Complementar",
        "decreto": "Decreto",
        "lei_promulgada": "Lei Promulgada",
    }
    epigraph_candidates = [
        {
            **candidate,
            "type_label": epigraph_type_labels.get(candidate.get("type_key"), "Norma"),
        }
        for candidate in epigraph_candidates
        if isinstance(candidate, dict)
    ] if isinstance(epigraph_candidates, list) else []
    publication_candidate = metadata_candidates.get("publication") or {}
    if not isinstance(publication_candidate, dict):
        publication_candidate = {}
    act_boundary_data = metadata_candidates.get("gazette_act_boundaries") or {}
    act_boundary_candidates = (
        act_boundary_data.get("candidates", [])
        if isinstance(act_boundary_data, dict)
        else []
    )
    act_type_labels = {
        "lei": "Lei",
        "lei_organica": "Lei Orgânica",
        "lei_complementar": "Lei Complementar",
        "lei_promulgada": "Lei Promulgada",
        "decreto": "Decreto",
        "decreto_lei": "Decreto-Lei",
        "decreto_legislativo": "Decreto Legislativo",
        "resolucao": "Resolução",
        "portaria": "Portaria",
        "edital": "Edital",
        "aviso": "Aviso",
        "extrato": "Extrato",
    }
    act_boundary_candidates = [
        {
            **candidate,
            "type_label": act_type_labels.get(
                candidate.get("type_key_candidate"), "Ato não classificado"
            ),
        }
        for candidate in act_boundary_candidates
        if isinstance(candidate, dict)
    ] if isinstance(act_boundary_candidates, list) else []
    review_history = []
    if reviewer_can_inspect_history:
        for review in document.revisoes_juridicas.select_related("actor").order_by(
            "-created_at", "-pk"
        )[:20]:
            if review.reason.startswith("[segmentação documental revisada]"):
                action_label = "Revisão da segmentação"
            elif review.reason.startswith("[extração documental revisada]"):
                action_label = "Revisão da extração"
            else:
                action_label = "Revisão documental"
            review_history.append({
                "action_label": action_label,
                "decision_label": review.get_decision_display(),
                "actor": review.actor.get_username(),
                "created_at": review.created_at,
                "reason": review.reason,
                "fingerprint_prefix": review.target_fingerprint[:12],
            })
    return {
        "document": document,
        "candidate_identity_label": candidate_identity_label,
        "extraction": extraction,
        "candidate_extraction": candidate_extraction,
        "extraction_quality_summary": _extraction_quality_summary(extraction),
        "devices": devices,
        "official_url": safe_official_url(document.official_url),
        "local_pdf_available": local_pdf_available(document),
        "can_review_identity": can_review_identity,
        "identity_review_form": identity_review_form,
        "can_review_extraction": can_review_extraction,
        "extraction_review_form": extraction_review_form,
        "reviewer_can_register": reviewer_can_register,
        "identity_review_registered": bool(
            reviewer_can_register
            and document.norma_id
            and request.GET.get("identity") == "registered"
        ),
        "extraction_review_registered": extraction_review_registered,
        "can_review_segmentation": can_review_segmentation,
        "can_generate_segmentation": can_generate_segmentation,
        "segmentation_reviewed": segmentation_reviewed,
        "segmentation_review_form": segmentation_review_form,
        "segmentation_fingerprint": segmentation_fingerprint,
        "segmentation_generation_fingerprint": (
            extraction_review_fingerprint(document, extraction)
            if can_generate_segmentation
            else ""
        ),
        "segmentation_generation_form": segmentation_generation_form or (
            SegmentationGenerationForm(initial={
                "extraction_id": extraction.pk,
                "expected_fingerprint": extraction_review_fingerprint(document, extraction),
            })
            if can_generate_segmentation
            else None
        ),
        "segmentation_generated": bool(
            reviewer_can_review_segmentation and request.GET.get("segmentation") == "generated"
        ),
        "epigraph_status": epigraph.get("status") if isinstance(epigraph, dict) else None,
        "epigraph_issues": epigraph.get("issues", []) if isinstance(epigraph, dict) else [],
        "epigraph_candidates": epigraph_candidates if isinstance(epigraph_candidates, list) else [],
        "identity_epigraph_check": identity_epigraph_check,
        "act_boundary_status": (
            act_boundary_data.get("status") if isinstance(act_boundary_data, dict) else None
        ),
        "act_boundary_source_text_complete": (
            act_boundary_data.get("source_text_complete")
            if isinstance(act_boundary_data, dict)
            else None
        ),
        "act_boundary_candidates": act_boundary_candidates,
        "publication_candidate_date": publication_candidate.get("data_publicacao"),
        "publication_effects_on_date": publication_candidate.get("vigencia_na_publicacao"),
        "review_history": review_history,
        "staff_can_view_candidate": _staff_can_view_candidate(request),
    }


@require_http_methods(["GET", "POST"])
def document_evidence_view(request: HttpRequest, document_id) -> HttpResponse:
    document = _authorized_document(request, document_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"review_identity", "accept_extraction", "generate_segmentation", "review_segmentation"}:
            return HttpResponse("Ação de revisão inválida.", status=400)
        if action == "review_identity" and not _reviewer_can_register_identity(request):
            raise PermissionDenied("Você não tem permissão para registrar identidade normativa.")
        if action == "accept_extraction" and not _reviewer_can_accept_extraction(request):
            raise PermissionDenied("Você não tem permissão para aceitar extração documental.")
        if action in {"generate_segmentation", "review_segmentation"} and not _reviewer_can_review_segmentation(request):
            raise PermissionDenied("Você não tem permissão para revisar a segmentação documental.")
        form = (
            IdentityReviewForm(request.POST) if action == "review_identity"
            else ExtractionReviewForm(request.POST) if action == "accept_extraction"
            else SegmentationReviewForm(request.POST) if action == "review_segmentation"
            else SegmentationGenerationForm(request.POST)
        )
        if form.is_valid():
            try:
                if action == "review_identity":
                    current_fingerprint = promotion_fingerprint(document)
                    if form.cleaned_data["expected_fingerprint"] != current_fingerprint:
                        raise DocumentReviewBlocked(
                            "O documento mudou desde a abertura. Recarregue e confira novamente."
                        )
                    register_reviewed_identity(
                        document_id=str(document.public_id),
                        reviewer=request.user,
                        reason=form.cleaned_data["reason"],
                        fingerprint=current_fingerprint,
                        confirmed_identity_key=form.cleaned_data["confirmed_identity_key"],
                        confirmed_condition_of_use=form.cleaned_data["confirmed_condition_of_use"],
                    )
                elif action == "accept_extraction":
                    accept_document_extraction(
                        document_id=str(document.public_id),
                        extraction_id=form.cleaned_data["extraction_id"],
                        reviewer=request.user,
                        reason=form.cleaned_data["reason"],
                        expected_fingerprint=form.cleaned_data["expected_fingerprint"],
                    )
                elif action == "generate_segmentation":
                    extraction = document.extracoes.get(pk=form.cleaned_data["extraction_id"])
                    expected = extraction_review_fingerprint(document, extraction)
                    if (
                        form.cleaned_data["expected_fingerprint"] != expected
                        or document.accepted_extraction_id != extraction.pk
                        or not _approved_public_document(document)
                    ):
                        raise DocumentReviewBlocked(
                            "Documento ou extração mudou; recarregue a ficha antes de gerar a prévia."
                        )
                    segment_document_extraction(extraction.pk)
                else:
                    review_document_segmentation(
                        document_id=str(document.public_id),
                        extraction_id=form.cleaned_data["extraction_id"],
                        reviewer=request.user,
                        reason=form.cleaned_data["reason"],
                        expected_fingerprint=form.cleaned_data["expected_fingerprint"],
                    )
            except (ValidationError, PermissionDenied, ExtracaoDocumento.DoesNotExist) as exc:
                error_messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
                if isinstance(exc, ExtracaoDocumento.DoesNotExist):
                    error_messages = ["A versão de extração não existe mais nesta ficha."]
                form.add_error(None, " ".join(error_messages))
                status = 409
            else:
                response = HttpResponse(status=303)
                status_name = {
                    "review_identity": "identity=registered",
                    "accept_extraction": "extraction=accepted",
                    "generate_segmentation": "segmentation=generated",
                    "review_segmentation": "segmentation=reviewed",
                }[action]
                response["Location"] = f"{request.path}?{status_name}"
                return _private_headers(response)
        else:
            status = 400
        for field_name in form.errors:
            if field_name in form.fields:
                form.fields[field_name].widget.attrs["aria-invalid"] = "true"
        context = _document_evidence_context(
            request,
            document,
            identity_review_form=form if action == "review_identity" else None,
            extraction_review_form=form if action == "accept_extraction" else None,
            segmentation_review_form=form if action == "review_segmentation" else None,
            segmentation_generation_form=form if action == "generate_segmentation" else None,
        )
        # Keep the panel visible on an invalid or stale POST so the reviewer can
        # correct the form without losing the evidence they were comparing.
        if action == "review_identity":
            context["can_review_identity"] = True
        elif action == "accept_extraction":
            context["can_review_extraction"] = True
        else:
            context["can_review_segmentation"] = True
        return _private_headers(render(
            request, "legislation/document_evidence.html", context, status=status
        ))

    context = _document_evidence_context(request, document)
    return _private_headers(
        render(request, "legislation/document_evidence.html", context)
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
