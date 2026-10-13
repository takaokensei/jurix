"""Owner-scoped, append-only snapshots for legal research collections."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.db import transaction
from django.db.models import Max, Q

from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.models import Collection, CollectionEvidenceVersion, Norma
from src.processing.normative_projection import persist_projection, project_norma_as_of


def save_collection_evidence(
    *,
    collection: Collection,
    owner_id: int,
    norma: Norma,
    as_of: date,
    device_key: str = "",
) -> CollectionEvidenceVersion:
    """Persist an explicit whole-norm or device-level historical reference.

    The linked snapshot always preserves the complete projection. ``device_key``
    scopes the collection version and its later impact comparison to one device.
    """
    if collection.user_id != owner_id:
        raise PermissionError("Somente o proprietário pode salvar evidências nesta coleção.")
    if norma.status != Norma.Status.CONSOLIDATED:
        raise ValueError("Somente normas consolidadas podem ser salvas como evidência temporal.")
    with transaction.atomic():
        locked_collection = Collection.objects.select_for_update().get(
            pk=collection.pk, user_id=owner_id
        )
        if not locked_collection.normas.filter(pk=norma.pk).exists():
            raise ValueError("Adicione a norma à coleção antes de salvar uma versão.")
        projection = project_norma_as_of(norma, as_of)
        if device_key and not any(
            item.source.structural_key == device_key for item in projection.devices
        ):
            raise ValueError(
                "O dispositivo não está disponível na projeção revisada para a data escolhida."
            )
        snapshot = persist_projection(projection)
        result = {
            NormativeSnapshot.Status.COMPLETE: CollectionEvidenceVersion.Result.COMPLETE,
            NormativeSnapshot.Status.PARTIAL: CollectionEvidenceVersion.Result.PARTIAL,
            NormativeSnapshot.Status.NOT_RECONSTRUCTABLE: CollectionEvidenceVersion.Result.INCONCLUSIVE,
        }.get(snapshot.status, CollectionEvidenceVersion.Result.INCONCLUSIVE)
        canonical = {
            "norma_id": norma.pk,
            "snapshot_id": snapshot.pk,
            "as_of": snapshot.as_of.isoformat(),
            "input_sha256": snapshot.input_sha256,
            "content_sha256": snapshot.content_sha256,
            "device_key": device_key,
            "result": result,
        }
        evidence_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        last_version = (
            CollectionEvidenceVersion.objects.filter(
                collection=locked_collection, norma=norma, device_key=device_key
            ).aggregate(value=Max("version"))["value"]
            or 0
        )
        return CollectionEvidenceVersion.objects.create(
            collection=locked_collection,
            owner_id=owner_id,
            norma=norma,
            snapshot=snapshot,
            device_key=device_key,
            version=last_version + 1,
            evidence_hash=evidence_hash,
            result=result,
        )


def collection_evidence_impact(collection: Collection, *, current_date: date) -> list[dict]:
    """Compare each latest saved version to a read-only current projection."""
    saved_normas = collection.evidence_versions.filter(owner_id=collection.user_id).order_by()
    total_references = saved_normas.values("norma_id", "device_key").distinct().count()
    reference_keys = list(saved_normas.values_list("norma_id", "device_key").distinct()[:51])
    visible_keys = reference_keys[:50]
    reference_filter = Q()
    for norma_id, device_key in visible_keys:
        reference_filter |= Q(norma_id=norma_id, device_key=device_key)
    versions = list(
        collection.evidence_versions.select_related("norma", "snapshot")
        .filter(owner_id=collection.user_id)
        .filter(reference_filter)
        .order_by("norma_id", "device_key", "-version", "-created_at")
    )
    latest_by_reference = {}
    for version in versions:
        latest_by_reference.setdefault((version.norma_id, version.device_key), version)
    impacts = []
    projections = {}
    for (norma_id, device_key), saved in latest_by_reference.items():
        if norma_id not in projections:
            projections[norma_id] = project_norma_as_of(norma_id, current_date)
        projection = projections[norma_id]
        current_status = projection.status
        comparable = current_status in {
            NormativeSnapshot.Status.COMPLETE,
            NormativeSnapshot.Status.PARTIAL,
        } and saved.snapshot.status in {
            NormativeSnapshot.Status.COMPLETE,
            NormativeSnapshot.Status.PARTIAL,
        }
        if device_key:
            current_device = next(
                (item for item in projection.devices if item.source.structural_key == device_key),
                None,
            )
            saved_device = saved.snapshot.dispositivos.filter(structural_key=device_key).first()
            comparable = bool(comparable and current_device and saved_device)
            content_changed = bool(
                comparable
                and (current_device.text, current_device.legal_status)
                != (saved_device.text, saved_device.legal_status)
            )
            provenance_changed = bool(
                comparable and current_device.provenance != saved_device.provenance_json
            )
        else:
            content_changed = bool(
                comparable and projection.content_sha256 != saved.snapshot.content_sha256
            )
            provenance_changed = bool(
                comparable and projection.input_sha256 != saved.snapshot.input_sha256
            )
        impacts.append(
            {
                "saved": saved,
                "device_key": device_key,
                "device_label": "",
                "current_status": current_status,
                "comparison": (
                    "changed"
                    if content_changed
                    else "provenance_changed"
                    if provenance_changed
                    else "unchanged"
                    if comparable
                    else "inconclusive"
                ),
                "content_changed": content_changed,
                "provenance_changed": provenance_changed,
            }
        )
    if total_references > len(visible_keys):
        impacts.append({"truncated": True, "remaining": total_references - len(visible_keys)})
    return impacts
