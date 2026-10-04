"""Conservative, read-only temporal projections from reviewed source documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
    NormativeSnapshot,
    SnapshotDispositivo,
)
from src.apps.legislation.event_review import event_review_fingerprint, event_review_status
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica as LegalReview
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.device_revision import legacy_device_identity_map
from src.processing.event_temporal_policy import (
    _PUBLICATION_CLAUSE,
    _UNSUPPORTED_EFFECT,
    _has_exact_quote,
    temporal_candidate_fingerprint,
)


@dataclass(frozen=True)
class ProjectionDevice:
    source: DocumentoDispositivo
    text: str
    legal_status: str
    provenance: dict


@dataclass(frozen=True)
class NormativeProjection:
    norma_id: int
    as_of: date
    status: str
    input_sha256: str
    content_sha256: str
    devices: tuple[ProjectionDevice, ...]
    coverage: dict


def _temporal_decisions(events) -> dict[int, dict]:
    """Resolve date-review status with one batched query, not one query per event."""
    fingerprints = {}
    for event in events:
        basis = event.effective_date_basis if isinstance(event.effective_date_basis, dict) else {}
        quote = str(basis.get("evidence_quote") or "")
        if event.effective_on and quote and _has_exact_quote(event.dispositivo_fonte.texto, quote):
            try:
                review_id = UUID(str(basis.get("review_id") or ""))
            except (TypeError, ValueError, AttributeError):
                continue
            fingerprints[event.pk] = (
                temporal_candidate_fingerprint(event, event.effective_on, quote), review_id
            )
    approved = set()
    if fingerprints:
        approved = set(
            LegalReview.objects.filter(
                evento_id__in=fingerprints,
                target_fingerprint__in=[value[0] for value in fingerprints.values()],
                public_id__in=[value[1] for value in fingerprints.values()],
                decision=LegalReview.Decision.APPROVE,
            ).values_list("evento_id", "target_fingerprint", "public_id")
        )
    decisions = {}
    for event in events:
        action = event.acao.upper()
        publication = event.dispositivo_fonte.norma.data_publicacao
        if action in {"REFERENCIA", "REGULAMENTA"}:
            decisions[event.pk] = {"status": "not_applicable", "date": None, "operative": False}
        elif action not in {"ALTERA", "ADICIONA", "SUBSTITUI", "REVOGA"}:
            decisions[event.pk] = {"status": "unsupported", "date": None, "operative": False}
        elif _UNSUPPORTED_EFFECT.search(event.dispositivo_fonte.texto or ""):
            decisions[event.pk] = {"status": "unsupported", "date": None, "operative": False}
        elif event.effective_on and event.effective_date_status == "candidate" and event.pk in fingerprints:
            decisions[event.pk] = {"status": "candidate", "date": event.effective_on, "operative": False}
        elif event.effective_on and event.effective_date_status == "confirmed" and event.pk in fingerprints:
            relation_ok = event_review_status(event) == "confirmed"
            date_ok = (event.pk, *fingerprints[event.pk]) in approved
            decisions[event.pk] = {
                "status": "confirmed" if relation_ok and date_ok and event.validado else "candidate",
                "date": event.effective_on,
                "operative": bool(relation_ok and date_ok and event.validado and event.is_active),
            }
        elif _PUBLICATION_CLAUSE.search(event.dispositivo_fonte.texto or "") and publication:
            decisions[event.pk] = {"status": "candidate", "date": publication, "operative": False}
        else:
            decisions[event.pk] = {"status": "unknown", "date": None, "operative": False}
    return decisions


def _reviewed_base(norma: Norma):
    document = norma.documento_base
    if not document or document.norma_id != norma.pk:
        return None
    if (
        document.role != DocumentoNormativo.Role.ORIGINAL
        or document.review_status != DocumentoNormativo.ReviewStatus.APPROVED
        or document.condition_of_use
        not in {
            DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            DocumentoNormativo.ConditionOfUse.LICENSED,
        }
    ):
        return None
    if not document.accepted_extraction_id:
        return None
    extraction = document.accepted_extraction
    if extraction.status != ExtracaoDocumento.Status.COMPLETE:
        return None
    if not LegalReview.objects.filter(
        documento=document,
        decision=LegalReview.Decision.APPROVE,
        target_fingerprint=promotion_fingerprint(document),
    ).exists():
        return None
    published = norma.data_publicacao or norma.data_norma
    if not published:
        return None
    devices = list(
        DocumentoDispositivo.objects.filter(extracao=extraction).order_by("ordem", "pk")
    )
    return (document, extraction, published, devices) if devices else None


def _not_reconstructable(norma: Norma, as_of: date, reason: str) -> NormativeProjection:
    payload = {"norma": norma.pk, "as_of": as_of.isoformat(), "reason": reason}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return NormativeProjection(
        norma.pk, as_of, NormativeSnapshot.Status.NOT_RECONSTRUCTABLE, digest, digest, (),
        {"reason": reason, "device_count": 0, "applied_event_ids": [], "pending_event_ids": []},
    )


def project_norma_as_of(norma: Norma | int, as_of: date) -> NormativeProjection:
    """Project a reviewed historical state without mutating legal/source records."""
    if not isinstance(as_of, date):
        raise TypeError("as_of deve ser datetime.date")
    if isinstance(norma, int):
        norma = Norma.objects.select_related("documento_base__accepted_extraction").get(pk=norma)
    else:
        norma = Norma.objects.select_related("documento_base__accepted_extraction").get(pk=norma.pk)
    base = _reviewed_base(norma)
    if not base:
        return _not_reconstructable(norma, as_of, "base_document_not_reviewed_or_temporally_unknown")
    document, extraction, published, source_devices = base
    if published > as_of:
        return _not_reconstructable(norma, as_of, "base_document_not_yet_published")

    legacy = list(
        Dispositivo.objects.filter(norma=norma).select_related("dispositivo_pai").order_by("ordem", "pk")
    )
    try:
        legacy_by_key = legacy_device_identity_map(legacy)
    except ValueError:
        legacy_by_key = {}
    legacy_to_key = {pk: key for key, pk in legacy_by_key.items()}
    states = {}
    pending_reasons = []
    for device in source_devices:
        status = {
            DocumentoDispositivo.Marker.VETOED: "vetoed",
            DocumentoDispositivo.Marker.REVOKED: "revoked",
            DocumentoDispositivo.Marker.UNKNOWN: "unknown",
        }.get(device.marker, "in_force")
        if status == "unknown":
            pending_reasons.append(f"device_marker_unknown:{device.structural_key}")
        states[device.structural_key] = {
            "source": device,
            "text": device.texto,
            "status": status,
            "provenance": {"base_document_id": str(document.public_id), "base_extraction_id": extraction.pk},
        }

    all_events = list(
        EventoAlteracao.objects.filter(norma_alvo=norma)
        .select_related("dispositivo_fonte__norma", "dispositivo_alvo", "review_revision")
        .order_by("pk")
    )
    temporal_decisions = _temporal_decisions(all_events)
    candidates = []
    pending_ids = []
    for event in all_events:
        relation = event_review_status(event)
        temporal = temporal_decisions[event.pk]
        if relation != "confirmed" or temporal["status"] != "confirmed" or not temporal["operative"]:
            if temporal["status"] in {"unknown", "candidate", "unsupported"} or relation == "pending":
                pending_ids.append(event.pk)
            continue
        if temporal["date"] and temporal["date"] <= as_of:
            target_key = legacy_to_key.get(event.dispositivo_alvo_id)
            target_reference = event.target_reference_json if isinstance(event.target_reference_json, dict) else {}
            if (
                event.acao.upper() == "REVOGA"
                and event.dispositivo_alvo_id is None
                and target_reference.get("target_scope") == "norma"
            ):
                target_key = "__explicit_norma_target__"
            candidates.append((temporal["date"], target_key, event))

    # Material conflicts on the same date/target remain pending; never break ties by PK.
    conflict_ids = set()
    by_target_date = {}
    for effective_on, target_key, event in candidates:
        if not target_key:
            conflict_ids.add(event.pk)
            continue
        by_target_date.setdefault((effective_on, target_key), []).append(event)
    for group in by_target_date.values():
        actions = {(event.acao, event.dispositivo_fonte.texto) for event in group}
        if len(group) > 1 and len(actions) > 1:
            conflict_ids.update(event.pk for event in group)
    whole_norma_by_date = {}
    for effective_on, target_key, event in candidates:
        if target_key == "__explicit_norma_target__":
            whole_norma_by_date.setdefault(effective_on, []).append(event)
    for effective_on, whole_events in whole_norma_by_date.items():
        overlapping = [item[2] for item in candidates if item[0] == effective_on]
        if len(overlapping) > len(whole_events):
            conflict_ids.update(event.pk for event in overlapping)
        if len(whole_events) > 1 and len(
            {(event.acao, event.dispositivo_fonte.texto) for event in whole_events}
        ) > 1:
            conflict_ids.update(event.pk for event in whole_events)
    pending_ids.extend(sorted(conflict_ids))

    applied_ids = []
    for effective_on, target_key, event in sorted(
        (item for item in candidates if item[2].pk not in conflict_ids),
        key=lambda item: (item[0], item[1]),
    ):
        action = event.acao.upper()
        state = states.get(target_key)
        whole_norma = target_key == "__explicit_norma_target__" and action == "REVOGA"
        if state is None and not whole_norma:
            pending_ids.append(event.pk)
            continue
        provenance = {
            "base_document_id": str(document.public_id),
            "base_extraction_id": extraction.pk,
            "event_id": event.pk,
            "effective_on": effective_on.isoformat(),
            "source_norma_id": event.dispositivo_fonte.norma_id,
        }
        if action == "REVOGA":
            if whole_norma:
                affected = set(states)
            else:
                affected = {target_key}
                changed = True
                while changed:
                    changed = False
                    for key, candidate in states.items():
                        if candidate["source"].parent_key in affected and key not in affected:
                            affected.add(key)
                            changed = True
            for key in affected:
                states[key]["status"] = "revoked"
                states[key]["provenance"] = {**states[key]["provenance"], **provenance}
        elif action in {"ALTERA", "SUBSTITUI"}:
            if state["status"] in {"vetoed", "revoked"}:
                pending_ids.append(event.pk)
                continue
            new_text, reason = ConsolidationEngine._new_wording(event, event.dispositivo_fonte)
            if not new_text:
                pending_ids.append(event.pk)
                continue
            state["text"] = new_text
            state["status"] = "in_force"
            state["provenance"] = {**state["provenance"], **provenance, "action": action}
        else:
            # ADDITION placement requires structural evidence not represented by this adapter.
            pending_ids.append(event.pk)
            continue
        applied_ids.append(event.pk)

    projected = tuple(
        ProjectionDevice(
            source=states[device.structural_key]["source"],
            text=states[device.structural_key]["text"],
            legal_status=states[device.structural_key]["status"],
            provenance=states[device.structural_key]["provenance"],
        )
        for device in source_devices
    )
    pending_ids = sorted(set(pending_ids))
    status = (
        NormativeSnapshot.Status.PARTIAL
        if pending_ids or pending_reasons
        else NormativeSnapshot.Status.COMPLETE
    )
    content_payload = [
        [item.source.structural_key, item.text, item.legal_status, item.provenance]
        for item in projected
    ]
    content_hash = hashlib.sha256(
        json.dumps(content_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    input_payload = {
        "norma_id": norma.pk,
        "as_of": as_of.isoformat(),
        "document_sha256": document.content_sha256,
        "document_review_fingerprint": promotion_fingerprint(document),
        "extraction_sha256": extraction.extraction_sha256,
        "events": [
            [
                event.pk,
                event_review_fingerprint(event),
                event.norma_alvo_id,
                event.dispositivo_alvo_id,
                event.effective_on.isoformat() if event.effective_on else None,
                event.effective_date_status,
                event.effective_date_basis,
                event.review_revision_id,
            ]
            for event in all_events
        ],
        "base_publication_on": published.isoformat(),
        "content_sha256": content_hash,
        "policy": "normative-projection-v1",
    }
    input_hash = hashlib.sha256(
        json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    coverage = {
        "reason": "reviewed_source_projection",
        "base_document_id": str(document.public_id),
        "base_extraction_id": extraction.pk,
        "base_publication_on": published.isoformat(),
        "device_count": len(projected),
        "applied_event_ids": applied_ids,
        "pending_event_ids": pending_ids,
        "pending_reasons": pending_reasons,
    }
    return NormativeProjection(norma.pk, as_of, status, input_hash, content_hash, projected, coverage)


def persist_projection(projection: NormativeProjection) -> NormativeSnapshot:
    """Persist a deterministic projection append-only; caller controls transaction."""
    snapshot, created = NormativeSnapshot.objects.get_or_create(
        norma_id=projection.norma_id,
        as_of=projection.as_of,
        input_sha256=projection.input_sha256,
        defaults={
            "status": projection.status,
            "content_sha256": projection.content_sha256,
            "coverage_json": projection.coverage,
        },
    )
    if created:
        SnapshotDispositivo.objects.bulk_create([
            SnapshotDispositivo(
                snapshot=snapshot,
                base_device=item.source,
                structural_key=item.source.structural_key,
                text=item.text,
                legal_status=item.legal_status,
                provenance_json=item.provenance,
            )
            for item in projection.devices
        ])
    elif snapshot.content_sha256 != projection.content_sha256:
        raise ValueError("Input hash repetido produziu conteúdo divergente; snapshot não foi alterado.")
    return snapshot
