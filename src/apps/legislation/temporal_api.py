"""Public temporal/provenance endpoints for norma research."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from src.apps.legislation.models import Norma
from src.processing.conflict_detection import detect_for_norma
from src.processing.temporal_scope import build_norma_timeline, parse_iso_date, temporal_status


@require_GET
def norma_timeline_api(request: HttpRequest, pk: int) -> JsonResponse:
    norma = get_object_or_404(Norma, pk=pk)
    try:
        as_of = parse_iso_date(request.GET.get("as_of"), "as_of")
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    timeline = build_norma_timeline(norma)
    return JsonResponse({
        "success": True,
        "norma": {"id": norma.id, "ref": str(norma)},
        "as_of": as_of.isoformat() if as_of else None,
        "temporal_status": temporal_status(norma, as_of=as_of),
        "timeline": timeline,
        "count": len(timeline),
    })


@require_GET
def norma_conflicts_api(request: HttpRequest, pk: int) -> JsonResponse:
    norma = get_object_or_404(Norma, pk=pk)
    signals = detect_for_norma(norma)
    return JsonResponse({
        "success": True,
        "norma": {"id": norma.id, "ref": str(norma)},
        "advisory_only": True,
        "signals": signals,
        "count": len(signals),
    })
