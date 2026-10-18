"""Compose a public, source-bound normative casefile from existing services."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.urls import reverse

from src.apps.legislation.models import Norma
from src.processing.corpus_identity import get_corpus_revision
from src.processing.evidence_export import build_evidence_package
from src.processing.normative_graph import build_normative_graph
from src.processing.normative_projection import project_norma_as_of
from src.processing.official_urls import safe_official_url


def _source_identity(norma_id: int, as_of: date, structural_key: str, input_hash: str) -> str:
    payload = f"{norma_id}\0{as_of.isoformat()}\0{structural_key}\0{input_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _norma_id(node_id) -> int | None:
    prefix, _, raw_id = str(node_id or "").partition(":")
    if prefix != "norma":
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _document_device_label(device) -> str:
    """Render a stable, human-readable label from the immutable segmentation fields."""
    kind = str(device.tipo or "").strip().casefold()
    number = str(device.numero or "").strip()
    prefix = {
        "artigo": "Art.",
        "art": "Art.",
        "paragrafo": "§",
        "parágrafo": "§",
        "inciso": "inciso",
        "alinea": "alínea",
        "alínea": "alínea",
        "item": "item",
        "titulo": "Título",
        "título": "Título",
        "capitulo": "Capítulo",
        "capítulo": "Capítulo",
        "secao": "Seção",
        "seção": "Seção",
    }.get(kind, kind.capitalize() or "Dispositivo")
    if prefix == "§" and number.startswith("§"):
        return number
    return f"{prefix} {number}".strip()


def _casefile_digest(
    norma_id: int,
    as_of: date,
    *,
    corpus_revision: dict | None,
    projection,
    graph: dict | None,
    evidence_package: dict,
) -> str:
    """Identify the actual casefile inputs and content, excluding generation time."""
    revision = corpus_revision if isinstance(corpus_revision, dict) else {}
    graph_value = graph if isinstance(graph, dict) else None
    if graph_value is not None:
        graph_value = {
            "scope": graph_value.get("scope"),
            "nodes": sorted(
                (row for row in graph_value.get("nodes", []) if isinstance(row, dict)),
                key=lambda row: str(row.get("id") or ""),
            ),
            "edges": sorted(
                (row for row in graph_value.get("edges", []) if isinstance(row, dict)),
                key=lambda row: str(row.get("id") or ""),
            ),
            "truncated": graph_value.get("truncated"),
            "filters": graph_value.get("filters"),
        }
    evidence = evidence_package if isinstance(evidence_package, dict) else {}
    payload = {
        "schema": "jurix-normative-casefile-v2",
        "norma_id": norma_id,
        "as_of": as_of.isoformat(),
        "corpus_revision": {
            "revision": revision.get("revision"),
            "digest": revision.get("digest"),
        },
        "projection": (
            {
                "status": projection.status,
                "input_sha256": projection.input_sha256,
                "content_sha256": projection.content_sha256,
            }
            if projection is not None
            else None
        ),
        "graph": graph_value,
        "evidence": {
            "schema_version": evidence.get("schema_version"),
            "corpus_coverage": evidence.get("corpus_coverage"),
            "sources": evidence.get("sources", []),
        },
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_normative_casefile(
    norma: Norma | int,
    *,
    as_of: date,
    include_projection: bool = True,
    include_graph: bool = True,
    graph_depth: int = 1,
    graph_actions: tuple[str, ...] = (),
    include_pending: bool = False,
    user=None,
) -> dict:
    """Return one read-only case payload for comparison, graph and evidence export.

    Projections use only reviewed source documents and confirmed temporal
    decisions. The public graph excludes pending candidate relations. Callers
    may omit either computation when they only need one part of the casefile.
    """
    if not isinstance(as_of, date):
        raise TypeError("as_of deve ser datetime.date")
    if include_pending and not (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_staff", False)
        and user.has_perm("legislation.view_eventoalteracao")
        and user.has_perm("legislation.view_documentonormativo")
        and user.has_perm("legislation.review_eventonormativocandidato")
    ):
        raise PermissionError("Permissão insuficiente para incluir relações candidatas.")
    selected_norma = Norma.objects.select_related(
        "documento_base__accepted_extraction"
    ).get(pk=getattr(norma, "pk", norma))
    projection = project_norma_as_of(selected_norma, as_of) if include_projection else None
    graph = (
        build_normative_graph(
            selected_norma,
            depth=graph_depth,
            as_of=as_of,
            actions=graph_actions,
            include_pending=include_pending,
        )
        if include_graph
        else None
    )

    sources = []
    source_document = selected_norma.documento_base
    if projection is not None and projection.devices and source_document is not None:
        document_public_id = str(source_document.public_id)
        local_pdf_url = reverse(
            "legislation:document_pdf", args=(source_document.public_id,)
        )
        official_url = safe_official_url(source_document.official_url) or safe_official_url(
            selected_norma.sapl_url
        )
        for index, device in enumerate(projection.devices, start=1):
            structural_key = str(device.source.structural_key or device.source.pk)
            citation_digest = _source_identity(
                selected_norma.pk, as_of, structural_key, projection.input_sha256
            )
            device_label = _document_device_label(device.source)
            temporal_version = {
                "as_of": as_of.isoformat(),
                "legal_status": device.legal_status,
                "version_hash": projection.content_sha256,
                "input_hash": projection.input_sha256,
                "source_document_id": document_public_id,
                "policy": "normative-projection-v2",
            }
            coverage = {
                "as_of": as_of.isoformat(),
                "version_hash": projection.content_sha256,
                "input_hash": projection.input_sha256,
                "status": projection.status,
                "policy": "normative-projection-v2",
                "complete": projection.status == "complete",
                "projected_devices": len(projection.devices),
            }
            sources.append(
                {
                    "citation_id": f"casefile:{selected_norma.pk}:{citation_digest}",
                    "citation_index": index,
                    "citation_label": f"{selected_norma} · {device_label} · texto projetado em {as_of:%d/%m/%Y}",
                    "norma_ref": str(selected_norma),
                    "norma_id": str(selected_norma.pk),
                    "dispositivo_ref": device_label,
                    "source_type": "projeção temporal revisada",
                    "source_kind": source_document.source_kind,
                    "status_label": device.legal_status,
                    "evidence_scope": "reviewed_temporal_projection",
                    "source_id": document_public_id,
                    "document_sha256": source_document.content_sha256,
                    "data_publicacao": selected_norma.data_publicacao,
                    "source_url": official_url,
                    "local_pdf_url": local_pdf_url,
                    "evidence_text": device.text,
                    "temporal_status": projection.status,
                    "temporal_version": temporal_version,
                    "coverage": coverage,
                }
            )

    if graph is not None:
        nodes_by_id = {node.get("id"): node for node in graph.get("nodes", [])}
        for edge in graph.get("edges", []):
            evidence = edge.get("evidence") if isinstance(edge.get("evidence"), dict) else {}
            quote = str(evidence.get("quote") or "").strip()
            if not quote:
                continue
            source_id = _norma_id(edge.get("source"))
            target_id = _norma_id(edge.get("target"))
            source_node = nodes_by_id.get(edge.get("source"), {})
            source_public_id = evidence.get("document_id")
            local_pdf_url = (
                reverse("legislation:document_pdf", args=(source_public_id,))
                if source_public_id
                else None
            )
            sources.append(
                {
                    "citation_id": f"{edge.get('id')}:{as_of.isoformat()}",
                    "citation_index": len(sources) + 1,
                    "citation_label": (
                        f"{source_node.get('label', 'Ato relacionado')} · "
                        f"{(edge.get('source_device') or {}).get('label', 'dispositivo fonte')}"
                    ),
                    "norma_ref": source_node.get("label"),
                    "norma_id": str(source_id) if source_id else None,
                    "dispositivo_ref": (edge.get("source_device") or {}).get("label"),
                    "source_type": "evidência de relação revisada",
                    "source_kind": "normative_graph",
                    "status_label": edge.get("review_status"),
                    "evidence_scope": "reviewed_normative_relation",
                    "source_id": source_public_id,
                    "page": (evidence.get("page") if isinstance(evidence.get("page"), int) else None),
                    "source_url": edge.get("official_url"),
                    "local_pdf_url": local_pdf_url,
                    "evidence_text": quote,
                    "graph_relation": {
                        "event_id": str(edge.get("id") or ""),
                        "action": edge.get("action"),
                        "label": edge.get("action"),
                        "review_status": edge.get("review_status"),
                        "effective_status": edge.get("effective_status"),
                        "effective_on": edge.get("effective_on"),
                        "publication_on": edge.get("publication_on"),
                        "source_norma_id": source_id,
                        "target_norma_id": target_id,
                        "source_device_key": edge.get("source_device_key"),
                        "target_device_key": edge.get("target_device_key"),
                        "resolution": edge.get("resolution"),
                        "quote": quote,
                    },
                }
            )

    revision = get_corpus_revision()
    coverage = projection.coverage.get("corpus_coverage") if projection is not None else None
    evidence_package = build_evidence_package(
        sources,
        corpus_revision=revision,
        corpus_coverage=coverage,
        include_excerpts=True,
    )
    casefile_digest = _casefile_digest(
        selected_norma.pk,
        as_of,
        corpus_revision=revision,
        projection=projection,
        graph=graph,
        evidence_package=evidence_package,
    )
    return {
        "casefile_id": casefile_digest,
        "casefile_schema_version": "jurix-normative-casefile-v2",
        "norma": selected_norma,
        "as_of": as_of,
        "projection": projection,
        "projected_devices": [
            {
                "label": _document_device_label(device.source),
                "text": device.text,
                "legal_status": device.legal_status,
            }
            for device in projection.devices
        ] if projection is not None else [],
        "graph": graph,
        "evidence_package": evidence_package,
    }
