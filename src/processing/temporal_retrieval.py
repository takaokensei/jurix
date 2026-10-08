"""Lexical retrieval over reviewed, date-bounded normative projections.

Historical requests never read the latest dispositivo text as their evidence.
Projection and snapshot identities are checked before a source is returned.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from django.db.models import Q

from src.apps.legislation.document_models import NormativeSnapshot, SnapshotDispositivo
from src.apps.legislation.models import Dispositivo, Norma
from src.processing.device_revision import legacy_device_identity_map
from src.processing.normative_projection import NormativeProjection, project_norma_as_of
from src.processing.normative_reference import parse_normative_references
from src.processing.rag_context_builder import EvidenceRows
from src.processing.temporal_scope import TemporalScope

MAX_TEMPORAL_CANDIDATE_NORMAS = 12
MAX_TEMPORAL_SNAPSHOT_CANDIDATES = 36
_STOPWORDS = {
    "para", "como", "sobre", "entre", "essa", "este", "esta", "esse", "isso",
    "que", "uma", "por", "dos", "das", "com", "sem", "nos", "nas", "aos",
    "pelos", "pelas", "qual", "quais", "onde", "quando", "quem", "porque",
    "são", "ser", "tem", "mais", "menos", "muito", "muita", "muitas",
    "muitos", "uns", "umas",
}


class TemporalDeviceEvidence:
    """Read-only presentation adapter: current identity, projected legal text."""

    def __init__(self, legacy: Dispositivo, projected, as_of: date):
        self._legacy = legacy
        self.id = legacy.pk
        self.norma = legacy.norma
        self.norma_id = legacy.norma_id
        self.dispositivo_pai = legacy.dispositivo_pai
        self.dispositivo_pai_id = legacy.dispositivo_pai_id
        self.tipo = projected.source.tipo
        self.numero = projected.source.numero
        self.ordem = projected.source.ordem
        self.texto = projected.text
        self.parent_key = getattr(projected.source, "parent_key", None)
        self.legal_status = projected.legal_status
        self.as_of = as_of
        self.structural_key = projected.source.structural_key
        self.provenance = dict(projected.provenance or {})

    def get_full_identifier(self) -> str:
        """Build the identifier from the projected, not current, hierarchy."""
        return self.get_caminho_completo()

    def get_caminho_completo(self) -> str:
        parts = [str(self._legacy)]
        visited = {self.id}
        parent = self.dispositivo_pai
        while parent and len(visited) < 64:
            if parent.id in visited:
                parts.insert(0, "[ciclo hierárquico detectado]")
                break
            visited.add(parent.id)
            parts.insert(0, str(parent._legacy))
            parent = parent.dispositivo_pai
        return " > ".join(parts)

    def __getattr__(self, name):
        return getattr(self._legacy, name)


def _query_tokens(query: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\wÀ-ÿ]{3,}", query or "")
        if token.casefold() not in _STOPWORDS
    }


def _lexical_score(tokens: set[str], text: str) -> float:
    if not tokens:
        return 0.0
    words = {
        token.casefold()
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text or "")
        if token.casefold() not in _STOPWORDS
    }
    overlap = tokens & words
    if not overlap:
        return 0.0
    recall = len(overlap) / len(tokens)
    density = len(overlap) / max(1.0, math.sqrt(len(words)))
    return min(1.0, recall * 0.75 + min(0.25, density))


def _device_adapters(
    norma: Norma, projection: NormativeProjection
) -> tuple[list[TemporalDeviceEvidence], int]:
    legacy_devices = list(
        Dispositivo.objects.filter(norma_id=norma.pk)
        .select_related("norma", "dispositivo_pai")
        .order_by("ordem", "pk")
    )
    try:
        devices_by_id = {device.pk: device for device in legacy_devices}
        legacy_by_key = {
            key: devices_by_id[device_id]
            for key, device_id in legacy_device_identity_map(legacy_devices).items()
            if device_id in devices_by_id
        }
    except (ValueError, StopIteration):
        return [], len(projection.devices)

    adapters = []
    missing_anchor_count = 0
    seen_keys = set()
    for projected in projection.devices:
        key = projected.source.structural_key
        if not key or key in seen_keys:
            missing_anchor_count += 1
            continue
        seen_keys.add(key)
        legacy = legacy_by_key.get(key)
        if legacy is None:
            # Do not fabricate an article URL or cite a latest-text fallback.
            missing_anchor_count += 1
            continue
        adapters.append(TemporalDeviceEvidence(legacy, projected, projection.as_of))
    adapters_by_key = {adapter.structural_key: adapter for adapter in adapters}
    for adapter in adapters:
        if not adapter.parent_key:
            adapter.dispositivo_pai = None
            adapter.dispositivo_pai_id = None
            continue
        parent = adapters_by_key.get(adapter.parent_key)
        if parent is None:
            missing_anchor_count += 1
            adapter.dispositivo_pai = None
            adapter.dispositivo_pai_id = None
            continue
        adapter.dispositivo_pai = parent
        adapter.dispositivo_pai_id = parent.id
    return adapters, missing_anchor_count


def _scope_allows(norma: Norma, scope: TemporalScope) -> bool:
    """Apply publication/as-of constraints without relaxing unknown dates."""
    return scope.contains_publication(norma.data_publicacao)


def _temporal_citation_id(
    norma_id: object, structural_key: object, version_hash: object
) -> str | None:
    """Return a citation identity tied to the exact projected device version."""
    structural = str(structural_key or "").lower()
    version = str(version_hash or "").lower()
    if not norma_id or not re.fullmatch(r"[a-f0-9]{64}", structural):
        return None
    if not re.fullmatch(r"[a-f0-9]{64}", version):
        return None
    return f"jurix:norma:{norma_id}:version:{version}:device:{structural}"


def _projection_rows(
    norma: Norma,
    query: str,
    as_of: date,
    *,
    max_sources: int,
    overview_selector: Callable[[list[Any]], tuple[list[Any], dict[str, Any]]] | None,
    scope: TemporalScope,
    require_materialized_snapshot: bool = False,
    lexical_tokens: set[str] | None = None,
) -> EvidenceRows:
    if not _scope_allows(norma, scope):
        return EvidenceRows(
            reason_code="historical_publication_outside_scope",
            coverage={"as_of": as_of.isoformat(), "complete": False, "selected_normas": 0},
        )

    projection = project_norma_as_of(norma, as_of)
    if projection.status == NormativeSnapshot.Status.NOT_RECONSTRUCTABLE:
        return EvidenceRows(
            reason_code="historical_version_unavailable",
            coverage={
                "as_of": as_of.isoformat(),
                "status": projection.status,
                "reason": projection.coverage.get("reason"),
                "complete": False,
                "selected_normas": 0,
            },
        )

    snapshot = NormativeSnapshot.objects.filter(
        norma_id=norma.pk,
        as_of=as_of,
        input_sha256=projection.input_sha256,
        content_sha256=projection.content_sha256,
        status=projection.status,
    ).first()
    if require_materialized_snapshot and snapshot is None:
        return EvidenceRows(
            reason_code="historical_snapshot_unavailable",
            coverage={
                "as_of": as_of.isoformat(),
                "status": projection.status,
                "complete": False,
                "selected_normas": 0,
                "reason": "no_current_materialized_snapshot_for_projection",
            },
        )

    adapters, missing_anchors = _device_adapters(norma, projection)
    overview_coverage = None
    if overview_selector is not None:
        adapters, overview_coverage = overview_selector(adapters)
        max_sources = min(48, max(1, int(max_sources)))
    else:
        parsed = parse_normative_references(query)
        article = (
            parsed[0].article
            if len(parsed) == 1 and not parsed[0].ambiguous and parsed[0].article
            else None
        )
        if article:
            from src.processing.target_resolver import article_key

            matching = [
                row for row in adapters
                if row.tipo == "artigo" and article_key(row.numero) == article_key(article)
            ]
            if len(matching) != 1:
                return EvidenceRows(
                    reason_code="requested_device_not_in_historical_version",
                    coverage={
                        "as_of": as_of.isoformat(),
                        "status": projection.status,
                        "complete": False,
                        "selected_normas": 1,
                        "requested_article": article,
                    },
                )
            article_id = matching[0].id
            selected_ids = {article_id}
            changed = True
            while changed:
                changed = False
                for row in adapters:
                    if row.id in selected_ids:
                        continue
                    parent_id = row.dispositivo_pai_id
                    if parent_id in selected_ids:
                        selected_ids.add(row.id)
                        changed = True
            adapters = [row for row in adapters if row.id in selected_ids]

    aggregate_coverage = {
        **(overview_coverage or {}),
        **projection.coverage,
        "as_of": as_of.isoformat(),
        "status": projection.status,
        "complete": bool(
            projection.status == NormativeSnapshot.Status.COMPLETE
            and not missing_anchors
            and (overview_coverage is None or overview_coverage.get("complete"))
        ),
        "projected_devices": len(projection.devices),
        "citation_anchor_unavailable": missing_anchors,
        "snapshot_id": snapshot.pk if snapshot else None,
        "version_hash": projection.content_sha256,
        "input_hash": projection.input_sha256,
        "policy": "normative-projection-v1",
    }

    tokens = lexical_tokens if lexical_tokens is not None else _query_tokens(query)
    rows = []
    for device in adapters:
        score = 1.0 if overview_selector is not None else _lexical_score(tokens, device.texto)
        if overview_selector is None and not parse_normative_references(query):
            if score <= 0:
                continue
        if overview_selector is None and parse_normative_references(query):
            references = parse_normative_references(query)
            if references and references[0].article:
                score = max(score, 0.8)
        history_state = {
            "in_force": "Texto projetado para a data consultada.",
            "revoked": "Evidência histórica de dispositivo revogado nesta data; não representa regra vigente.",
            "vetoed": "Dispositivo vetado na projeção; não usar como regra vigente.",
            "unknown": "Situação jurídica indeterminada na projeção histórica.",
        }.get(device.legal_status, "Situação histórica não classificada.")
        rows.append(
            {
                "dispositivo": device,
                "citation_id": _temporal_citation_id(
                    norma.pk,
                    device.structural_key,
                    projection.content_sha256,
                ),
                "similarity_score": score,
                "semantic_score": 0.0,
                "lexical_score": score,
                "retrieval_score": score,
                "distance": round(1.0 - score, 4),
                "match_kind": "historical_overview"
                if overview_selector is not None
                else "historical_projection",
                "retrieval_strategy": "temporal_snapshot"
                if snapshot
                else "temporal_projection",
                "evidence_scope": "complete"
                if aggregate_coverage["complete"]
                else "partial",
                "temporal_version": {
                    "as_of": as_of.isoformat(),
                    "legal_status": device.legal_status,
                    "status_note": history_state,
                    "snapshot_id": snapshot.pk if snapshot else None,
                    "version_hash": projection.content_sha256,
                    "input_hash": projection.input_sha256,
                    "policy": "normative-projection-v1",
                    "provenance": device.provenance,
                },
                "coverage": aggregate_coverage,
                "context": {
                    "hierarchy": device.get_caminho_completo(),
                    "parent": str(device.dispositivo_pai) if device.dispositivo_pai else None,
                },
            }
        )
    rows.sort(key=lambda item: (-item["retrieval_score"], item["dispositivo"].ordem))
    rows = rows[:max_sources]
    for index, row in enumerate(rows, start=1):
        row["citation_index"] = index
    aggregate_coverage["selected_devices"] = len(rows)
    aggregate_coverage["context_complete"] = bool(
        aggregate_coverage["complete"]
        and len(rows) == int(overview_coverage.get("selected_devices", len(rows))
                             if overview_coverage else len(rows))
    )
    for row in rows:
        row["coverage"] = aggregate_coverage
        row["evidence_scope"] = "complete" if aggregate_coverage["context_complete"] else "partial"
    reason = None if rows else (
        "no_historical_lexical_match" if overview_selector is None else "no_historical_devices"
    )
    return EvidenceRows(rows, reason_code=reason, coverage=aggregate_coverage)


def retrieve_historical_norma(
    norma: Norma,
    query: str,
    as_of: date,
    *,
    max_sources: int,
    overview_selector=None,
    scope: TemporalScope | None = None,
) -> EvidenceRows:
    """Retrieve projected text for an explicitly selected or cited Norma."""
    return _projection_rows(
        norma,
        query,
        as_of,
        max_sources=max_sources,
        overview_selector=overview_selector,
        scope=scope or TemporalScope(as_of=as_of),
    )


def retrieve_historical_corpus(
    query: str,
    as_of: date,
    *,
    max_sources: int,
    scope: TemporalScope | None = None,
    norma_status: str = "consolidated",
    source_scope: str = "municipal",
    norma_type: str | None = None,
    year: int | None = None,
) -> EvidenceRows:
    """Search only fresh materialized snapshots; never fall back to current text."""
    tokens = sorted(_query_tokens(query))[:8]
    if not tokens:
        return EvidenceRows(
            reason_code="historical_query_not_supported",
            coverage={"as_of": as_of.isoformat(), "complete": False, "selected_normas": 0},
        )
    token_query = Q()
    for token in tokens:
        token_query |= Q(text__icontains=token)

    candidates = list(
        SnapshotDispositivo.objects.filter(
            snapshot__as_of=as_of,
            snapshot__status__in=[
                NormativeSnapshot.Status.COMPLETE,
                NormativeSnapshot.Status.PARTIAL,
            ],
        )
        .filter(token_query)
        .order_by("snapshot__norma_id", "snapshot_id", "pk")
        .values("snapshot__norma_id", "snapshot_id")
        .distinct()[:MAX_TEMPORAL_SNAPSHOT_CANDIDATES]
    )
    norma_ids = list(dict.fromkeys(int(row["snapshot__norma_id"]) for row in candidates))[
        :MAX_TEMPORAL_CANDIDATE_NORMAS
    ]
    combined = []
    considered = 0
    skipped_stale = 0
    norma_queryset = Norma.objects.filter(pk__in=norma_ids)
    if norma_status != "all":
        norma_queryset = norma_queryset.filter(status=norma_status)
    if norma_type:
        norma_queryset = norma_queryset.filter(tipo=norma_type)
    if year is not None:
        norma_queryset = norma_queryset.filter(ano=year)
    if source_scope != "all":
        norma_queryset = norma_queryset.filter(
            Q(sapl_url__icontains="sapl.natal.rn.leg.br") | Q(sapl_url="")
        )
    for norma in norma_queryset.order_by("pk"):
        considered += 1
        result = _projection_rows(
            norma,
            query,
            as_of,
            max_sources=max_sources,
            overview_selector=None,
            scope=scope or TemporalScope(as_of=as_of),
            require_materialized_snapshot=True,
            lexical_tokens=set(tokens),
        )
        if result.reason_code == "historical_snapshot_unavailable":
            skipped_stale += 1
        combined.extend(result)

    combined.sort(key=lambda item: (-item["retrieval_score"], item["dispositivo"].ordem))
    selected = combined[:max_sources]
    coverage = {
        "strategy": "bounded_historical_lexical",
        "as_of": as_of.isoformat(),
        "candidate_normas": len(norma_ids),
        "checked_normas": considered,
        "skipped_stale_snapshots": skipped_stale,
        "selected_devices": len(selected),
        "complete": False,
        "context_complete": False,
        "reason": "bounded_snapshot_candidate_scan",
        "policy": "normative-projection-v1",
    }
    for index, row in enumerate(selected, start=1):
        row["citation_index"] = index
        row["coverage"] = coverage
        row["evidence_scope"] = "partial"
    return EvidenceRows(
        selected,
        reason_code=None if selected else "historical_evidence_unavailable",
        coverage=coverage,
    )
