"""Strictly bounded HTTP API for reviewed normative relations."""

from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from src.apps.legislation.models import Norma
from src.processing.cache_service import CacheService
from src.processing.corpus_coverage import current_corpus_coverage
from src.processing.corpus_identity import get_corpus_revision
from src.processing.normative_graph import VALID_ACTIONS, build_normative_graph
from src.processing.temporal_scope import parse_iso_date


def _strict_bool(value: str | None, name: str) -> bool:
    if value is None:
        return False
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{name} deve ser true ou false.")


def _staff_can_view_pending(user) -> bool:
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm("legislation.view_eventoalteracao")
    )


@require_GET
def norma_relations_api(request: HttpRequest, pk: int) -> JsonResponse:
    if not getattr(settings, "NORMATIVE_GRAPH_ENABLED", False):
        return JsonResponse({"success": False, "error": "Recurso indisponível."}, status=404)
    try:
        raw_depth = request.GET.get("depth", "1")
        if raw_depth not in {"1", "2"}:
            raise ValueError("depth deve ser 1 ou 2.")
        depth = int(raw_depth)
        as_of = parse_iso_date(request.GET.get("as_of"), "as_of")
        as_of = as_of or timezone.localdate()
        include_pending = _strict_bool(request.GET.get("include_pending"), "include_pending")
        raw_actions = request.GET.get("actions", "")
        actions = tuple(sorted({action.strip().upper() for action in raw_actions.split(",") if action.strip()}))
        if any(action not in VALID_ACTIONS for action in actions):
            raise ValueError("actions contém uma ação inválida.")
        if include_pending and not _staff_can_view_pending(request.user):
            return JsonResponse({"success": False, "error": "Permissão insuficiente."}, status=403)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    norma = Norma.objects.filter(pk=pk).first()
    if norma is None:
        return JsonResponse({"success": False, "error": "Norma não encontrada."}, status=404)
    principal = f"staff:{request.user.pk}" if include_pending else "public"
    corpus_digest = CacheService.get_corpus_revision_digest()
    cache_payload = {
        "norma": pk,
        "depth": depth,
        "as_of": as_of.isoformat() if as_of else None,
        "actions": actions,
        "include_pending": include_pending,
        "principal": principal,
        "policy": "normative-graph-v2",
        "corpus": corpus_digest,
    }
    cache_key = "jurix:normative-graph:" + hashlib.sha256(
        json.dumps(cache_payload, sort_keys=True).encode()
    ).hexdigest()
    if corpus_digest != "unavailable":
        try:
            cached = cache.get(cache_key)
            if cached is not None:
                return JsonResponse(cached)
        except Exception:
            pass
    try:
        graph = build_normative_graph(
            norma,
            depth=depth,
            as_of=as_of,
            actions=actions,
            include_pending=include_pending,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    body = {
        "success": True,
        "norma": {"id": norma.pk, "ref": str(norma)},
        "corpus_coverage": current_corpus_coverage(get_corpus_revision()),
        **graph,
    }
    if corpus_digest != "unavailable":
        try:
            cache.set(cache_key, body, timeout=45)
        except Exception:
            pass
    return JsonResponse(body)
