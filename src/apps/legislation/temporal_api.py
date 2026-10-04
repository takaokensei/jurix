"""Public temporal/provenance endpoints for norma research."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.document_views import local_pdf_available
from src.apps.legislation.models import Norma
from src.processing.conflict_detection import detect_for_norma
from src.processing.normative_projection import project_norma_as_of
from src.processing.official_urls import safe_official_url
from src.processing.temporal_scope import build_norma_timeline, parse_iso_date, temporal_status


@require_GET
def norma_timeline_api(request: HttpRequest, pk: int) -> JsonResponse:
    norma = Norma.objects.filter(pk=pk).first()
    if norma is None:
        return JsonResponse(
            {"success": False, "error": f"Norma with ID {pk} not found"},
            status=404,
        )
    try:
        as_of = parse_iso_date(request.GET.get("as_of"), "as_of")
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    timeline = build_norma_timeline(norma, as_of=as_of)
    return JsonResponse(
        {
            "success": True,
            "norma": {"id": norma.id, "ref": str(norma)},
            "as_of": as_of.isoformat() if as_of else None,
            "temporal_status": temporal_status(norma, as_of=as_of),
            "timeline": timeline,
            "count": len(timeline),
        }
    )


@require_GET
def norma_conflicts_api(request: HttpRequest, pk: int) -> JsonResponse:
    norma = Norma.objects.filter(pk=pk).first()
    if norma is None:
        return JsonResponse(
            {"success": False, "error": f"Norma with ID {pk} not found"},
            status=404,
        )
    signals = detect_for_norma(norma)
    return JsonResponse(
        {
            "success": True,
            "norma": {"id": norma.id, "ref": str(norma)},
            "advisory_only": True,
            "signals": signals,
            "count": len(signals),
        }
    )


@require_GET
def norma_version_api(request: HttpRequest, pk: int) -> JsonResponse:
    """Read a materialized snapshot or compute a bounded, non-persisted projection."""
    if not getattr(settings, "NORMATIVE_HISTORY_ENABLED", False):
        return JsonResponse({"success": False, "error": "Recurso indisponível."}, status=404)
    norma = Norma.objects.select_related("documento_base").filter(pk=pk).first()
    if norma is None:
        return JsonResponse({"success": False, "error": "Norma não encontrada."}, status=404)
    try:
        as_of = parse_iso_date(request.GET.get("as_of"), "as_of")
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    if as_of is None:
        return JsonResponse({"success": False, "error": "Informe as_of no formato AAAA-MM-DD."}, status=400)
    projection = project_norma_as_of(norma, as_of)
    snapshot = NormativeSnapshot.objects.filter(
        norma=norma, as_of=as_of, input_sha256=projection.input_sha256
    ).first()
    document = norma.documento_base if projection.status != NormativeSnapshot.Status.NOT_RECONSTRUCTABLE else None
    return JsonResponse(
        {
            "success": True,
            "norma": {"id": norma.pk, "ref": str(norma)},
            "as_of": as_of.isoformat(),
            "status": projection.status,
            "snapshot_id": snapshot.pk if snapshot else None,
            "version_hash": projection.content_sha256,
            "input_hash": projection.input_sha256,
            "coverage": projection.coverage,
            "document": (
                {
                    "id": str(document.public_id),
                    "sha256": document.content_sha256,
                    "official_url": safe_official_url(document.official_url),
                    "local_evidence_url": f"/normas/documentos/{document.public_id}/",
                    "local_pdf_url": (
                        f"/normas/documentos/{document.public_id}/pdf/"
                        if local_pdf_available(document)
                        else None
                    ),
                }
                if document
                else None
            ),
            "devices": [
                {
                    "structural_key": item.source.structural_key,
                    "tipo": item.source.tipo,
                    "numero": item.source.numero,
                    "text": item.text,
                    "legal_status": item.legal_status,
                    "provenance": item.provenance,
                }
                for item in projection.devices[:200]
            ],
            "truncated": len(projection.devices) > 200,
        }
    )
