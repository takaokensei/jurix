"""Expose an explicit, sanitized build identity to workspace templates.

This module deliberately does not inspect Git or infer a revision from the
working tree. Release metadata must be supplied by the build environment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.conf import settings

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_REVISION = re.compile(r"[a-fA-F0-9]{7,40}\Z")
_DIGEST = re.compile(r"[a-fA-F0-9]{64}\Z")
_PROFILES = {
    "local": "Local",
    "development": "Desenvolvimento",
    "qa": "QA isolado",
    "staging": "Pré-produção",
    "production": "Produção",
}


def _safe_version(value: object) -> str | None:
    candidate = str(value or "").strip()
    return candidate if _VERSION.fullmatch(candidate) else None


def _safe_revision(value: object) -> str | None:
    candidate = str(value or "").strip()
    return candidate.lower() if _REVISION.fullmatch(candidate) else None


def build_identity(request=None) -> dict[str, str]:
    """Return user-safe metadata; missing release fields remain explicitly unknown."""
    version = _safe_version(getattr(settings, "JURIX_BUILD_VERSION", ""))
    revision = _safe_revision(getattr(settings, "JURIX_BUILD_REVISION", ""))
    profile_key = str(getattr(settings, "JURIX_BUILD_PROFILE", "") or "").strip().lower()
    profile = _PROFILES.get(profile_key, "Ambiente não identificado")

    archive_qa = bool(
        request is not None
        and getattr(request, "GET", {}).get("corpus") == "archive-qa"
    )
    corpus = (
        "Acervo histórico local (QA)"
        if archive_qa
        else "Escopo padrão; corpus não certificado por esta tela"
    )
    result = {
        "version": version or "build local não identificado",
        "revision": revision or "não informada",
        "profile": profile,
        "corpus": corpus,
    }
    content = str(getattr(settings, "JURIX_BUILD_CONTENT_SHA256", "") or "")
    if _DIGEST.fullmatch(content):
        result["content_sha256"] = content.lower()
    return result


def instance_identity() -> dict:
    """Public QA identity contains no paths, credentials or inferred Git metadata."""
    identity = build_identity()
    active_revision = None
    root = getattr(settings, "QA_ROOT", None)
    if root:
        try:
            active = json.loads((Path(root) / "pilot" / "current.json").read_text(encoding="utf-8"))
            candidate = str(active.get("corpus_revision") or "")
            if _DIGEST.fullmatch(candidate):
                active_revision = candidate.lower()
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    model = str(getattr(settings, "OLLAMA_MODEL", "") or "")
    return {
        "version": identity["version"], "revision": identity["revision"],
        "content_sha256": identity.get("content_sha256"),
        "profile": str(getattr(settings, "JURIX_BUILD_PROFILE", "") or ""),
        "corpus_revision": active_revision,
        "generation": {
            "model": model if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", model) else None,
            "context_chars": int(getattr(settings, "RAG_MAX_CONTEXT_CHARS", 8000)),
        },
    }


def workspace_build_context(request) -> dict[str, dict[str, str]]:
    """Django context processor used by the shared workspace shell."""
    return {"jurix_build": build_identity(request)}
