"""Stable identities and content fingerprints for parsed legal devices."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_component(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", plain)


def structural_key(parent_key: str, tipo: str, numero: str) -> str:
    identity = "\x1f".join((parent_key, normalize_component(tipo), normalize_component(numero)))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def revision_fingerprint(text: str, raw_text: str) -> str:
    payload = f"{text or ''}\x1f{raw_text or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parsed_device_identities(rows: list[dict]) -> dict[int, tuple[str, str]]:
    """Return stable key and content digest by parser index after tree validation."""
    by_index = {row["index"]: row for row in rows}
    identities: dict[int, tuple[str, str]] = {}

    def visit(index: int, active: set[int]) -> str:
        if index in identities:
            return identities[index][0]
        if index in active:
            raise ValueError("Não foi possível construir identidade: ciclo hierárquico.")
        active.add(index)
        row = by_index[index]
        parent_index = row.get("parent_index")
        parent_key = visit(parent_index, active) if parent_index is not None else "root"
        key = structural_key(parent_key, row["tipo"], row["numero"])
        digest = revision_fingerprint(row.get("texto", ""), row.get("full_match", ""))
        identities[index] = key, digest
        active.remove(index)
        return key

    for index in by_index:
        visit(index, set())
    if set(by_index) != set(identities):
        raise ValueError("Não foi possível construir identidade para todos os dispositivos.")
    return identities


def ordered_hierarchy_rows(rows: list[dict]) -> list[dict]:
    """Return rows parent-first, preserving parser order among siblings."""
    by_index = {row["index"]: row for row in rows}
    ordered: list[dict] = []
    complete: set[int] = set()

    def visit(index: int, active: set[int]) -> None:
        if index in active:
            raise ValueError("A hierarquia contém um ciclo.")
        if index in complete:
            return
        active.add(index)
        parent = by_index[index].get("parent_index")
        if parent is not None:
            visit(parent, active)
        active.remove(index)
        complete.add(index)
        ordered.append(by_index[index])

    for row in rows:
        visit(row["index"], set())
    return ordered


def legacy_device_identity_map(devices) -> dict[str, int]:
    """Map stable structural keys to existing legacy PKs without changing rows."""
    by_id = {device.pk: device for device in devices}
    cache: dict[int, str] = {}

    def key_for(device_id: int, active: set[int]) -> str:
        if device_id in cache:
            return cache[device_id]
        if device_id in active:
            raise ValueError("A hierarquia legada contém ciclo; reconciliação documental recusada.")
        device = by_id[device_id]
        active.add(device_id)
        parent = device.dispositivo_pai
        if parent and (parent.pk not in by_id or parent.norma_id != device.norma_id):
            raise ValueError("Dispositivo legado tem pai fora da Norma carregada.")
        parent_key = key_for(parent.pk, active) if parent else "root"
        result = device.structural_key or structural_key(parent_key, device.tipo, device.numero)
        active.remove(device_id)
        cache[device_id] = result
        return result

    result = {}
    for device_id in by_id:
        key = key_for(device_id, set())
        if key in result:
            raise ValueError("A Norma possui dispositivos legados com identidade estrutural duplicada.")
        result[key] = device_id
    return result
