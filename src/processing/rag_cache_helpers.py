"""Helpers for restoring ORM relations on cached RAG sources."""

from typing import Any


def hydrate_cached_sources(
    sources: list[dict[str, Any]], *, dispositivo_model
) -> list[dict[str, Any]]:
    """Reattach current device/norm relations without issuing one query per source."""
    device_ids = [
        source["dispositivo_id"]
        for source in sources
        if isinstance(source, dict) and source.get("dispositivo_id")
    ]
    if not device_ids:
        return sources

    devices = {
        device.id: device
        for device in dispositivo_model.objects.filter(id__in=device_ids).select_related(
            "norma", "dispositivo_pai"
        )
    }
    for source in sources:
        device = devices.get(source.get("dispositivo_id"))
        if device:
            source["dispositivo"] = device
    return sources
