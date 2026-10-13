"""Expose an explicit, sanitized build identity to workspace templates.

This module deliberately does not inspect Git or infer a revision from the
working tree. Release metadata must be supplied by the build environment.
"""

from __future__ import annotations

import re

from django.conf import settings

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_REVISION = re.compile(r"[a-fA-F0-9]{7,40}\Z")
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
    return {
        "version": version or "build local não identificado",
        "revision": revision or "não informada",
        "profile": profile,
        "corpus": corpus,
    }


def workspace_build_context(request) -> dict[str, dict[str, str]]:
    """Django context processor used by the shared workspace shell."""
    return {"jurix_build": build_identity(request)}
