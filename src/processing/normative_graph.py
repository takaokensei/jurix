"""Bounded, authorization-aware traversal of reviewed normative relations."""

from __future__ import annotations

import hashlib
from collections import deque
from datetime import date
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.event_review import event_review_fingerprint, event_review_status
from src.apps.legislation.models import EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.event_temporal_policy import (
    _UNSUPPORTED_EFFECT,
    _has_exact_quote,
    temporal_candidate_fingerprint,
)
from src.processing.official_urls import safe_official_url

MAX_NODES = 40
MAX_EDGES = 80
MAX_DEPTH = 2
VALID_ACTIONS = frozenset({"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA", "REGULAMENTA", "REFERENCIA"})


def _public_norma_ids(normas) -> set[int]:
    documents = {}
    for norma in normas:
        document = getattr(norma, "documento_base", None)
        if (
            document
            and document.norma_id == norma.pk
            and document.review_status == DocumentoNormativo.ReviewStatus.APPROVED
            and document.condition_of_use
            in {DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED, DocumentoNormativo.ConditionOfUse.LICENSED}
            and document.role == DocumentoNormativo.Role.ORIGINAL
        ):
            documents[norma.pk] = document
    if not documents:
        return set()
    fingerprints = {
        (document.pk, promotion_fingerprint(document)): norma_id
        for norma_id, document in documents.items()
    }
    reviewed = set(
        RevisaoJuridica.objects.filter(
            documento_id__in=[document.pk for document in documents.values()],
            decision=RevisaoJuridica.Decision.APPROVE,
            target_fingerprint__in=[fingerprint for _doc_id, fingerprint in fingerprints],
        ).values_list("documento_id", "target_fingerprint")
    )
    return {fingerprints[pair] for pair in reviewed if pair in fingerprints}


def _event_temporal_status(event, reviewed_date_fingerprints: set[tuple[int, str, UUID]]) -> tuple[str, str | None]:
    action = event.acao.upper()
    source_norma = event.dispositivo_fonte.norma
    publication = source_norma.data_publicacao
    if action in {"REFERENCIA", "REGULAMENTA"}:
        return "not_applicable", publication.isoformat() if publication else None
    if action not in {"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA"}:
        return "unsupported", None
    text = event.dispositivo_fonte.texto or ""
    if _UNSUPPORTED_EFFECT.search(text):
        return "unsupported", None
    effective = event.effective_on
    basis = event.effective_date_basis if isinstance(event.effective_date_basis, dict) else {}
    quote = str(basis.get("evidence_quote") or "")
    if not effective or event.effective_date_status not in {"candidate", "confirmed"} or not _has_exact_quote(text, quote):
        return "unknown", None
    if event.effective_date_status == "candidate":
        return "candidate", effective.isoformat()
    fingerprint = temporal_candidate_fingerprint(event, effective, quote)
    review_id = str(basis.get("review_id") or "")
    try:
        review_uuid = UUID(review_id)
    except (TypeError, ValueError, AttributeError):
        review_uuid = None
    relation_ok = event_review_status(event) == "confirmed"
    date_ok = (event.pk, fingerprint, review_uuid) in reviewed_date_fingerprints if review_uuid else False
    if relation_ok and date_ok and event.validado:
        return "confirmed", effective.isoformat()
    return "candidate", effective.isoformat()


def _device_reference(device) -> dict | None:
    if device is None:
        return None
    kind = device.get_tipo_display()
    return {
        "label": device.caminho or f"{kind} {device.numero}".strip(),
        "structural_key": device.structural_key or None,
    }


def build_normative_graph(
    start: Norma | int,
    *,
    depth: int = 1,
    as_of: date | None = None,
    actions: tuple[str, ...] = (),
    include_pending: bool = False,
) -> dict:
    """Return a bounded BFS graph; unreviewed relations are staff-only candidates."""
    if not 1 <= depth <= MAX_DEPTH:
        raise ValueError("depth deve ser 1 ou 2")
    if any(action not in VALID_ACTIONS for action in actions):
        raise ValueError("ação de relação inválida")
    as_of = as_of or timezone.localdate()
    norma = Norma.objects.select_related("documento_base__accepted_extraction").filter(pk=getattr(start, "pk", start)).first()
    if norma is None:
        raise Norma.DoesNotExist
    if not include_pending and norma.pk not in _public_norma_ids([norma]):
        return {"scope": {}, "nodes": [], "edges": [], "truncated": False, "limits": {"nodes": MAX_NODES, "edges": MAX_EDGES}}

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    root_id = f"norma:{norma.pk}"
    nodes[root_id] = {"id": root_id, "kind": "norma", "label": str(norma), "url": f"/normas/{norma.pk}/"}
    visited: set[int] = set()
    frontier = deque([(norma.pk, 0)])
    truncated = False
    selected_actions = set(actions)
    while frontier:
        current_id, current_depth = frontier.popleft()
        if current_depth >= depth or current_id in visited:
            continue
        visited.add(current_id)
        queryset = (
            EventoAlteracao.objects.filter(Q(norma_alvo_id=current_id) | Q(dispositivo_fonte__norma_id=current_id))
            .select_related(
                "dispositivo_fonte__norma__documento_base",
                "dispositivo_fonte__norma__documento_base__accepted_extraction",
                "dispositivo_alvo",
                "dispositivo_alvo__norma",
                "norma_alvo__documento_base",
                "norma_alvo__documento_base__accepted_extraction",
                "review_revision",
            )
            .order_by("pk")[: MAX_EDGES - len(edges) + 1]
        )
        batch = list(queryset)
        if len(batch) + len(edges) > MAX_EDGES:
            batch = batch[: MAX_EDGES - len(edges)]
            truncated = True
        event_ids = [event.pk for event in batch]
        related_normas = {}
        for event in batch:
            related_normas[event.dispositivo_fonte.norma_id] = event.dispositivo_fonte.norma
            if event.norma_alvo_id:
                related_normas[event.norma_alvo_id] = event.norma_alvo
        public_norma_ids = _public_norma_ids(list(related_normas.values()))
        date_candidates = {}
        for event in batch:
            basis = event.effective_date_basis if isinstance(event.effective_date_basis, dict) else {}
            if event.effective_on and basis.get("evidence_quote"):
                fp = temporal_candidate_fingerprint(event, event.effective_on, basis["evidence_quote"])
                try:
                    review_uuid = UUID(str(basis.get("review_id") or ""))
                except (TypeError, ValueError, AttributeError):
                    continue
                date_candidates[event.pk] = (fp, review_uuid)
        approved_dates = set()
        if date_candidates:
            approved_rows = RevisaoJuridica.objects.filter(
                evento_id__in=event_ids,
                target_fingerprint__in=[value[0] for value in date_candidates.values()],
                public_id__in=[value[1] for value in date_candidates.values()],
                decision=RevisaoJuridica.Decision.APPROVE,
            ).values_list("evento_id", "target_fingerprint", "public_id")
            approved_dates = set(approved_rows)

        for event in batch:
            action = event.acao.upper()
            if selected_actions and action not in selected_actions:
                continue
            source_norma = event.dispositivo_fonte.norma
            if not include_pending and source_norma.pk not in public_norma_ids:
                continue
            relation_status = event_review_status(event)
            temporal_status, effective_on = _event_temporal_status(event, approved_dates)
            if relation_status != "confirmed" and not include_pending:
                continue
            if as_of:
                if action in {"REFERENCIA", "REGULAMENTA"}:
                    if source_norma.data_publicacao and source_norma.data_publicacao > as_of:
                        continue
                elif temporal_status == "confirmed" and effective_on and date.fromisoformat(effective_on) > as_of:
                    continue
                elif temporal_status != "confirmed" and not include_pending:
                    continue

            source_id = f"norma:{source_norma.pk}"
            if source_id not in nodes and len(nodes) >= MAX_NODES:
                truncated = True
                continue
            nodes.setdefault(source_id, {"id": source_id, "kind": "norma", "label": str(source_norma), "url": f"/normas/{source_norma.pk}/"})
            target_norma = event.norma_alvo
            if target_norma:
                target_id = f"norma:{target_norma.pk}"
                if target_id not in nodes and len(nodes) >= MAX_NODES:
                    truncated = True
                    continue
                if include_pending or target_norma.pk in public_norma_ids:
                    nodes.setdefault(target_id, {"id": target_id, "kind": "norma", "label": str(target_norma), "url": f"/normas/{target_norma.pk}/"})
                else:
                    continue
                if target_norma.pk not in visited and current_depth + 1 < depth:
                    frontier.append((target_norma.pk, current_depth + 1))
            else:
                reference = event.target_reference_json if isinstance(event.target_reference_json, dict) else {}
                external_key = str(reference.get("external_identity_key") or "")
                if not include_pending or not external_key:
                    continue
                target_id = "external:" + hashlib.sha256(external_key.encode()).hexdigest()[:24]
                nodes.setdefault(target_id, {"id": target_id, "kind": "external", "label": "Referência externa não resolvida", "url": None})

            edge_id = f"event:{event.pk}:{event.revision_fingerprint or event_review_fingerprint(event)[:16]}"
            evidence = event.evidence_json if isinstance(event.evidence_json, dict) else {}
            edge = {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "action": action,
                "source_device_key": event.dispositivo_fonte.structural_key or None,
                "target_device_key": event.dispositivo_alvo.structural_key if event.dispositivo_alvo_id else None,
                "source_device": _device_reference(event.dispositivo_fonte),
                "target_device": _device_reference(event.dispositivo_alvo),
                "resolution": "resolved" if event.dispositivo_alvo_id else ("external" if target_norma else "unresolved"),
                "review_status": relation_status,
                "effective_status": temporal_status,
                "effective_on": effective_on,
                "publication_on": source_norma.data_publicacao.isoformat() if source_norma.data_publicacao else None,
                "evidence": {
                    "quote": evidence.get("quote") if source_norma.pk in public_norma_ids else None,
                    "document_id": str(source_norma.documento_base.public_id) if source_norma.pk in public_norma_ids else None,
                    "page": evidence.get("page") if source_norma.pk in public_norma_ids else None,
                },
                "official_url": safe_official_url(source_norma.documento_base.official_url) if source_norma.pk in public_norma_ids else None,
            }
            edges.setdefault(edge_id, edge)
            if len(edges) >= MAX_EDGES:
                truncated = True
                break
        if truncated and len(edges) >= MAX_EDGES:
            break
    return {
        "scope": {"as_of": as_of.isoformat() if as_of else None, "depth": depth},
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "truncated": truncated,
        "limits": {"nodes": MAX_NODES, "edges": MAX_EDGES},
        "filters": {"actions": sorted(selected_actions), "include_pending": include_pending},
    }
