"""Authorized cancellation endpoint for an individual answer stream."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from src.processing.generation_control import (
    ExpiredCancelToken,
    InvalidCancelToken,
    request_generation_cancel,
)


@require_POST
def cancel_generation_api(request):
    """Cancel only the active generation identified by a signed SSE token."""
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    if not isinstance(payload, dict) or set(payload) != {"cancel_token"}:
        return JsonResponse({"success": False, "error": "Invalid cancellation request"}, status=400)

    try:
        state = request_generation_cancel(request, payload["cancel_token"])
    except ExpiredCancelToken:
        return JsonResponse({"success": False, "error": "Cancellation token expired"}, status=410)
    except InvalidCancelToken:
        return JsonResponse({"success": False, "error": "Invalid cancellation token"}, status=403)
    except Exception:
        return JsonResponse({"success": False, "error": "Cancellation is temporarily unavailable"}, status=503)

    return JsonResponse(
        {
            "success": True,
            "cancelled": state == "cancelled",
            "state": state,
        }
    )
