"""Bounded, authorization-aware traversal of reviewed normative relations."""

from __future__ import annotations

import hashlib
from collections import deque
from datetime import date
from uuid import UUID

from django.db.models import Prefetch, Q
from django.utils import timezone

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
    RevisaoEventoNormativoCandidato,
)
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


def _norma_node(norma: Norma, *, public_norma_ids: set[int], include_pending: bool) -> dict:
    if norma.pk in public_norma_ids:
        url = f"/normas/{norma.pk}/"
    elif include_pending and norma.documento_base_id:
        url = f"/normas/documentos/{norma.documento_base.public_id}/"
    else:
        url = None
    return {"id": f"norma:{norma.pk}", "kind": "norma", "label": str(norma), "url": url}


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
    """Return a bounded graph; caller must authorize include_pending as staff-only."""
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
    starting_public_normas = _public_norma_ids([norma])
    nodes[root_id] = _norma_node(
        norma, public_norma_ids=starting_public_normas, include_pending=include_pending
    )
    visited: set[int] = set()
    frontier = deque([(norma.pk, 0)])
    truncated = False
    selected_actions = set(actions)
    while frontier:
        current_id, current_depth = frontier.popleft()
        if current_depth >= depth or current_id in visited:
            continue
        visited.add(current_id)
        current_norma = Norma.objects.select_related("documento_base").get(pk=current_id)
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
            nodes.setdefault(
                source_id,
                _norma_node(
                    source_norma,
                    public_norma_ids=public_norma_ids,
                    include_pending=include_pending,
                ),
            )
            target_norma = event.norma_alvo
            if target_norma:
                target_id = f"norma:{target_norma.pk}"
                if target_id not in nodes and len(nodes) >= MAX_NODES:
                    truncated = True
                    continue
                if include_pending or target_norma.pk in public_norma_ids:
                    nodes.setdefault(
                        target_id,
                        _norma_node(
                            target_norma,
                            public_norma_ids=public_norma_ids,
                            include_pending=include_pending,
                        ),
                    )
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
            can_disclose_evidence = source_norma.pk in public_norma_ids or (
                include_pending and source_norma.documento_base_id is not None
            )
            source_document = source_norma.documento_base if can_disclose_evidence else None
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
                    "quote": evidence.get("quote") if can_disclose_evidence else None,
                    "document_id": str(source_document.public_id) if source_document else None,
                    "page": evidence.get("page") if can_disclose_evidence else None,
                },
                "official_url": safe_official_url(source_norma.documento_base.official_url) if source_norma.pk in public_norma_ids else None,
            }
            edges.setdefault(edge_id, edge)

        # Extracted document relations are visible only in the explicitly
        # authorized reviewer graph. They remain separate candidate edges and
        # never contribute to event traversal or temporal projection.
        if include_pending:
            source_document = (
                current_norma.documentos_normativos.filter(
                    review_status__in={
                        DocumentoNormativo.ReviewStatus.PENDING,
                        DocumentoNormativo.ReviewStatus.IN_REVIEW,
                    },
                    accepted_extraction__isnull=True,
                )
                .order_by("-created_at", "-pk")
                .first()
            )
            if (
                source_document
                and source_document.review_status
                in {DocumentoNormativo.ReviewStatus.PENDING, DocumentoNormativo.ReviewStatus.IN_REVIEW}
                and source_document.accepted_extraction_id is None
            ):
                latest_extraction = source_document.extracoes.order_by("-created_at", "-pk").first()
                if latest_extraction:
                    candidates = EventoNormativoCandidato.objects.filter(
                        extracao=latest_extraction
                    ).prefetch_related(
                        Prefetch(
                            "revisoes",
                            queryset=RevisaoEventoNormativoCandidato.objects.order_by(
                                "created_at", "pk"
                            ),
                        )
                    ).order_by("source_structural_key", "pk")[: MAX_EDGES - len(edges)]
                    for candidate in candidates:
                        reviews = list(candidate._prefetched_objects_cache.get("revisoes", []))
                        latest_review = reviews[-1] if reviews else None
                        reference = (
                            candidate.target_reference_json
                            if isinstance(candidate.target_reference_json, dict)
                            else {}
                        )
                        type_label = str(reference.get("type_candidate") or "Norma")
                        number = str(reference.get("number_candidate") or "")
                        year = str(reference.get("year_candidate") or "")
                        if not number or not year:
                            continue
                        target_norma = latest_review.target_norma if latest_review else None
                        if target_norma:
                            target_id = f"norma:{target_norma.pk}"
                            if target_id not in nodes and len(nodes) >= MAX_NODES:
                                truncated = True
                                continue
                            nodes.setdefault(
                                target_id,
                                _norma_node(
                                    target_norma,
                                    public_norma_ids=_public_norma_ids([target_norma]),
                                    include_pending=True,
                                ),
                            )
                            resolution = "resolved_candidate"
                        else:
                            identity = f"{type_label}|{number}|{year}"
                            target_id = "candidate:" + hashlib.sha256(
                                identity.encode("utf-8")
                            ).hexdigest()[:24]
                            if target_id not in nodes and len(nodes) >= MAX_NODES:
                                truncated = True
                                continue
                            nodes.setdefault(
                                target_id,
                                {
                                    "id": target_id,
                                    "kind": "candidate_target",
                                    "label": f"{type_label} nº {number}/{year} · alvo não resolvido",
                                    "url": None,
                                },
                            )
                            resolution = "unresolved_candidate"
                        evidence = candidate.evidence_json
                        decision = latest_review.decision if latest_review else None
                        if decision == RevisaoEventoNormativoCandidato.Decision.CONFIRM:
                            review_status = (
                                "candidate_confirmed"
                                if target_norma
                                else "candidate_text_confirmed_unresolved"
                            )
                        elif decision == RevisaoEventoNormativoCandidato.Decision.REJECT:
                            review_status = "candidate_rejected"
                        else:
                            review_status = "candidate_pending"
                        if selected_actions and candidate.action not in selected_actions:
                            continue
                        edge_id = f"document-candidate:{candidate.fingerprint}"
                        edges.setdefault(
                            edge_id,
                            {
                                "id": edge_id,
                                "source": f"norma:{current_norma.pk}",
                                "target": target_id,
                                "action": candidate.action,
                                "source_device_key": None,
                                "target_device_key": None,
                                "source_device": {
                                    "label": str(evidence.get("action_device") or candidate.source_device_label),
                                    "structural_key": None,
                                },
                                "target_device": {
                                    "label": (
                                        f"{reference.get('structural_type')} {reference.get('structural_number')}"
                                        if reference.get("structural_type")
                                        and reference.get("structural_number")
                                        else None
                                    ),
                                    "structural_key": None,
                                },
                                "resolution": resolution,
                                "review_status": review_status,
                                "effective_status": "not_assessed",
                                "effective_on": None,
                                "publication_on": None,
                                "evidence": {
                                    "quote": evidence.get("item_quote"),
                                    "document_id": str(source_document.public_id),
                                    "page": evidence.get("item_page")
                                    or evidence.get("target_page")
                                    or evidence.get("action_page"),
                                },
                                "official_url": None,
                            },
                        )
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


def build_candidate_document_graph(
    document: DocumentoNormativo,
    *,
    actions: tuple[str, ...] = (),
) -> dict:
    """Build a direct, non-operative graph for one unlinked pending PDF.

    The root remains a document identity candidate rather than a ``Norma``;
    this lets a reviewer inspect extracted links before identity approval.
    """
    if any(action not in VALID_ACTIONS for action in actions):
        raise ValueError("ação de relação inválida")
    if (
        document.source_kind not in {
            DocumentoNormativo.SourceKind.ARCHIVE,
            DocumentoNormativo.SourceKind.SAPL,
        }
        or document.review_status not in {
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        }
        or document.accepted_extraction_id is not None
    ):
        raise ValueError("documento não elegível para grafo de revisão")

    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity = metadata.get("identity_candidate")
    identity = identity if isinstance(identity, dict) else {}
    if any(
        value is True
        for value in (
            metadata.get("synthetic"),
            metadata.get("synthetic_fixture"),
            identity.get("synthetic"),
            identity.get("synthetic_fixture"),
        )
    ):
        raise ValueError("documento sintético não pode ser exibido como candidato real")

    type_label = str(identity.get("type") or "Norma não identificada")[:100]
    number = str(identity.get("number") or "").strip()[:40]
    year = str(identity.get("year") or "").strip()[:4]
    if number and year.isdecimal():
        root_label = f"{type_label} nº {number}/{year} · identidade pendente"
    else:
        root_label = f"Documento pendente · {document.original_filename or document.public_id}"
    root_id = f"candidate-document:{document.public_id}"
    nodes = {
        root_id: {
            "id": root_id,
            "kind": "candidate_document",
            "label": root_label[:180],
            "url": f"/normas/documentos/{document.public_id}/",
        }
    }
    edges = {}
    truncated = False
    latest_extraction = document.extracoes.order_by("-created_at", "-pk").first()
    if latest_extraction is not None:
        candidates = list(
            EventoNormativoCandidato.objects.filter(extracao=latest_extraction)
            .prefetch_related(
                Prefetch(
                    "revisoes",
                    queryset=RevisaoEventoNormativoCandidato.objects.select_related(
                        "target_norma__documento_base"
                    ).order_by("created_at", "pk"),
                )
            )
            .order_by("source_structural_key", "pk")[: MAX_EDGES + 1]
        )
        from src.apps.legislation.document_relation_review import (
            candidate_target_documents_for_candidates,
        )

        target_document_index = candidate_target_documents_for_candidates(candidates)
        truncated = len(candidates) > MAX_EDGES
        for candidate in candidates[:MAX_EDGES]:
            if actions and candidate.action not in actions:
                continue
            reference = (
                candidate.target_reference_json
                if isinstance(candidate.target_reference_json, dict)
                else {}
            )
            target_type = str(reference.get("type_candidate") or "Norma")[:100]
            target_number = str(reference.get("number_candidate") or "").strip()[:40]
            target_year = str(reference.get("year_candidate") or "").strip()[:4]
            if not target_number or not target_year.isdecimal():
                continue
            reviews = list(candidate._prefetched_objects_cache.get("revisoes", []))
            latest_review = reviews[-1] if reviews else None
            target_norma = latest_review.target_norma if latest_review else None
            if target_norma:
                target_id = f"norma:{target_norma.pk}"
                target_url = (
                    f"/normas/documentos/{target_norma.documento_base.public_id}/"
                    if target_norma.documento_base_id
                    else None
                )
                target_label = str(target_norma)
                target_kind = "norma_candidate"
                resolution = "resolved_candidate"
            else:
                target_identity = f"{target_type}|{target_number}|{target_year}"
                target_id = "candidate-target:" + hashlib.sha256(
                    target_identity.encode("utf-8")
                ).hexdigest()[:24]
                target_url = None
                target_label = f"{target_type} nº {target_number}/{target_year} · alvo não resolvido"
                target_kind = "candidate_target"
                resolution = "unresolved_candidate"
            if target_id not in nodes and len(nodes) >= MAX_NODES:
                truncated = True
                break
            nodes.setdefault(
                target_id,
                {"id": target_id, "kind": target_kind, "label": target_label[:180], "url": target_url},
            )
            decision = latest_review.decision if latest_review else None
            if decision == RevisaoEventoNormativoCandidato.Decision.CONFIRM:
                review_status = (
                    "candidate_confirmed"
                    if target_norma
                    else "candidate_text_confirmed_unresolved"
                )
            elif decision == RevisaoEventoNormativoCandidato.Decision.REJECT:
                review_status = "candidate_rejected"
            else:
                review_status = "candidate_pending"
            if latest_extraction.extraction_sha256 != candidate.evidence_json.get(
                "source_extraction_sha256"
            ):
                review_status = "stale_candidate"
            edge_id = f"document-candidate:{candidate.fingerprint}"
            evidence = candidate.evidence_json if isinstance(candidate.evidence_json, dict) else {}
            target_document_leads = target_document_index.get(candidate.pk, [])
            serialized_target_documents = [
                {
                    "url": f"/normas/documentos/{item['document'].public_id}/",
                    "filename": str(item["document"].original_filename or "PDF sem nome")[:180],
                    "source": item["document"].get_source_kind_display(),
                    "review_status": item["document"].get_review_status_display(),
                    "identity_type": item["identity_type"],
                    "type_matches": item["type_matches"],
                }
                for item in target_document_leads[:5]
            ]
            edges[edge_id] = {
                "id": edge_id,
                "source": root_id,
                "target": target_id,
                "action": candidate.action,
                "source_device_key": candidate.source_structural_key or None,
                "target_device_key": None,
                "source_device": {
                    "label": str(evidence.get("action_device") or candidate.source_device_label),
                    "structural_key": candidate.source_structural_key or None,
                },
                "target_device": {
                    "label": (
                        f"{reference.get('structural_type')} {reference.get('structural_number')}"
                        if reference.get("structural_type") and reference.get("structural_number")
                        else None
                    ),
                    "structural_key": None,
                },
                "resolution": resolution,
                "review_status": review_status,
                "effective_status": "not_assessed",
                "effective_on": None,
                "publication_on": None,
                "evidence": {
                    "quote": evidence.get("item_quote"),
                    "document_id": str(document.public_id),
                    "page": evidence.get("item_page")
                    or evidence.get("target_page")
                    or evidence.get("action_page"),
                    "target_document_candidates": serialized_target_documents,
                    "target_document_candidates_truncated": len(target_document_leads) > 5,
                },
                "official_url": None,
            }

    return {
        "root_id": root_id,
        "scope": {"as_of": None, "depth": 1},
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "truncated": truncated,
        "limits": {"nodes": MAX_NODES, "edges": MAX_EDGES},
        "filters": {"actions": sorted(actions), "include_pending": True},
    }
