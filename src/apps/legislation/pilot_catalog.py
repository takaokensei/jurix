"""Batched discovery of operational pilot sources in the common norm library."""

from __future__ import annotations

import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.urls import reverse

from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.pilot_corpus import load_corpus_revision, resolve_pilot_query

TYPE_LABELS = {
    "lei": "Lei Ordinária", "lei_complementar": "Lei Complementar",
    "lei_promulgada": "Lei Promulgada", "decreto": "Decreto",
}


@lru_cache(maxsize=2)
def _corpus(root: str, revision: str):
    # Revision is immutable; a newly activated pointer selects a different key.
    return load_corpus_revision(Path(root), revision)


def operational_pilot(revision: str | None = None) -> dict | None:
    """One QA-only loader for catalogue, dossier and assistant, pinned by revision."""
    root = getattr(settings, "QA_ROOT", None)
    if not (root and os.environ.get("JURIX_QA_ONLY") == "1"
            and getattr(settings, "JURIX_BUILD_PROFILE", "") == "qa"
            and getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)):
        return None
    folder = Path(root) / "pilot"
    if revision is None:
        if not (folder / "current.json").is_file():
            return None
        revision = json.loads((folder / "current.json").read_text(encoding="utf-8"))["corpus_revision"]
    return _corpus(str(folder), revision)


def _fold(value):
    return "".join(char for char in unicodedata.normalize("NFKD", str(value).casefold()) if not unicodedata.combining(char))


def pilot_catalog_context(request) -> dict:
    scope = request.GET.get("escopo", "todos")
    if scope not in {"todos", "experimental", "documentos", "revisadas"}:
        scope = "todos"
    result = {"selected_scope": scope, "pilot_entries": [], "pilot_total": 0, "pilot_error": False}
    root = getattr(settings, "QA_ROOT", None)
    if not (
        root and os.environ.get("JURIX_QA_ONLY") == "1"
        and getattr(settings, "JURIX_BUILD_PROFILE", "") == "qa"
        and getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        return result
    pilot_root = Path(root) / "pilot"
    if not (pilot_root / "current.json").is_file():
        return result
    try:
        revision = json.loads((pilot_root / "current.json").read_text(encoding="utf-8"))["corpus_revision"]
        corpus = _corpus(str(pilot_root), revision)
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, "pilot_error": True}
    result.update({
        "pilot_total": len({row["norma_key"] for row in corpus["sources"]}),
        "pilot_revision": corpus["corpus_revision"],
        "pilot_available_types": sorted({row["identity"]["tipo"] for row in corpus["sources"]}),
        "pilot_available_years": sorted({row["identity"]["ano"] for row in corpus["sources"]}),
    })
    if scope not in {"todos", "experimental"}:
        return result
    query = str(request.GET.get("q", ""))[:500].strip()
    resolution = resolve_pilot_query(query, corpus["sources"]) if query else None
    result["pilot_reference_exact"] = bool(resolution and resolution["references"] and resolution["status"] == "resolved")
    exact_keys = set()
    if resolution and resolution["references"]:
        exact_keys = {key for group in resolution["references"] for key in group["norma_keys"]}
    grouped = {}
    for row in corpus["sources"]:
        if row["source_role"] == "primary":
            grouped.setdefault(row["norma_key"], row)
    entries = []
    for key, row in grouped.items():
        identity = row["identity"]
        if query and resolution["references"] and key not in exact_keys:
            continue
        label = f"{TYPE_LABELS.get(identity['tipo'], identity['tipo'])} nº {int(identity['numero']):,}/{identity['ano']}".replace(",", ".")
        searchable = " ".join([label, row.get("title", ""), *row.get("aliases", [])])
        if query and not resolution["references"] and not all(term in _fold(searchable) for term in _fold(query).split()):
            continue
        year = request.GET.get("ano", "")
        if year and str(identity["ano"]) != year:
            continue
        kind = request.GET.get("tipo", "")
        if kind and kind not in {identity["tipo"], {"lei": "1", "lei_complementar": "2"}.get(identity["tipo"])}:
            continue
        entries.append({
            "label": label, "norma_key": key, "pdf_sha256": row["pdf_sha256"],
            "casefile_url": reverse("workspace:pilot_casefile") + "?" + urlencode({
                "norma": key, "revision": corpus["corpus_revision"],
            }),
            "year": identity["ano"], "number": int(identity["numero"]),
            "edition_year": row.get("edition_year"), "device_count": len(row["devices"]),
            "source_count": sum(source["norma_key"] == key for source in corpus["sources"]),
            "page": row["devices"][0].get("page") if row["devices"] else None,
        })
    entries.sort(key=lambda item: (item["year"], item["number"]), reverse=request.GET.get("ordenar") != "antigas")
    page = Paginator(entries, 18).get_page(request.GET.get("piloto_pagina", "1"))
    hashes = [row["pdf_sha256"] for row in page.object_list]
    documents = {}
    for document in DocumentoNormativo.objects.filter(content_sha256__in=hashes).order_by("created_at").only("content_sha256", "public_id"):
        documents[document.content_sha256] = document
    for row in page.object_list:
        document = documents.get(row["pdf_sha256"])
        if document:
            row["evidence_url"] = reverse("legislation:document_evidence", kwargs={"document_id": document.public_id})
            row["pdf_url"] = reverse("legislation:document_pdf", kwargs={"document_id": document.public_id})
            if row["page"]:
                row["pdf_url"] += f"#page={row['page']}"
    return {**result, "pilot_entries": page.object_list, "pilot_page": page, "pilot_filtered_count": len(entries)}


def pilot_document_context(document) -> dict | None:
    root = getattr(settings, "QA_ROOT", None)
    if not root or os.environ.get("JURIX_QA_ONLY") != "1" or getattr(settings, "JURIX_BUILD_PROFILE", "") != "qa":
        return None
    try:
        folder = Path(root) / "pilot"
        pointer = json.loads((folder / "current.json").read_text(encoding="utf-8"))
        corpus = _corpus(str(folder), pointer["corpus_revision"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    source = next((item for item in corpus["sources"] if item["pdf_sha256"] == document.content_sha256), None)
    if source is None:
        return None
    articles = [item for item in source["devices"] if item.get("type") == "artigo"]
    entries = []
    for index, article in enumerate(articles):
        start = article["start"]
        end = articles[index + 1]["start"] if index + 1 < len(articles) else max(
            (item["end"] for item in source["devices"]), default=article["end"],
        )
        containing = next((span for span in source["coverage"].get("act_spans", []) if span[0] <= start < span[1]), None)
        if containing:
            end = min(end, containing[1])
        entries.append({
            "key": article["device_key"], "label": f"Art. {article['number']}",
            "text": source["text"][start:end], "page": article.get("page"),
        })
    identity = source["identity"]
    return {
        "corpus_revision": corpus["corpus_revision"], "articles": entries,
        "label": f"{TYPE_LABELS.get(identity['tipo'], identity['tipo'])} nº {identity['numero']}/{identity['ano']}",
    }
