"""Pure, bounded projections over immutable IA pilot evidence, not legal approval."""

from __future__ import annotations

from datetime import date

from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.legal_diff import build_legal_diff
from src.processing.pilot_corpus import canonical_bytes, content_hash
from src.processing.pilot_events import device_candidates, device_span, evidence, temporal_evidence

KINDS = {"artigo": "art", "paragrafo": "par", "inciso": "inc", "alinea": "al", "item": "item"}


def device_paths(source: dict) -> dict[str, dict]:
    """Portable structural addresses; duplicate paths remain unresolved."""
    by_key = {row["device_key"]: row for row in source["devices"]}
    result, duplicates = {}, set()
    for row in source["devices"]:
        parts, current, visited = [], row, set()
        while current and current["device_key"] not in visited:
            visited.add(current["device_key"])
            kind = KINDS.get(current["type"])
            if kind:
                number = str(current["number"]).strip().rstrip("º°ª").casefold().replace("único", "unico")
                parts.append(f"{kind}:{number}")
            current = by_key.get(current.get("parent_key"))
        path = "/".join(reversed(parts))
        if path in result:
            duplicates.add(path)
        result[path] = row
    return {path: row for path, row in result.items() if path not in duplicates}


def _related(left: str | None, right: str) -> bool:
    return not left or left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _slots(source: dict, root_path: str, start: int, end: int) -> dict:
    result = {}
    for path in device_paths(source):
        if path == root_path or path.startswith(root_path + "/"):
            span = device_span(source, path)
            if span and start <= span[0] < span[1] <= end:
                result[path] = (span[0] - start, span[1] - start)
    return result


def _replace(text: str, slots: dict, path: str, value: str, *, new_slots=None):
    left, right = slots[path]
    delta = len(value) - (right - left)
    updated = {}
    for key, (start, end) in slots.items():
        if key == path or key.startswith(path + "/"):
            continue
        if path.startswith(key + "/"):
            updated[key] = (start, end + delta)
        elif start >= right:
            updated[key] = (start + delta, end + delta)
        else:
            updated[key] = (start, end)
    updated[path] = (left, left + len(value))
    for key, (start, end) in (new_slots or {}).items():
        updated[key] = (left + start, left + end)
    return text[:left] + value + text[right:], updated


def _replacement(event: dict, requested: str, sources: dict) -> tuple[str | None, dict]:
    """An adopted parent excerpt may supply its child, never an unrelated block."""
    target = event.get("target_device_path")
    value = event.get("new_text")
    if value is None:
        return None, {}
    source = sources.get(event["evidence"]["document_sha256"])
    if source is None:
        return None, {}
    quoted = event["evidence"]
    location = source["text"].find(value, quoted["start"], quoted["end"])
    if location < 0:
        return None, {}
    end = location + len(value)
    if requested.startswith((target or "") + "/"):
        span = device_span(source, requested)
        if not span or not location <= span[0] < span[1] <= end:
            return None, {}
        return source["text"][span[0]:span[1]], _slots(source, requested, *span)
    return value, _slots(source, target, location, end)


def project_pilot_device(corpus: dict, norma_key: str, path: str, *, as_of: date | str | None = None,
                         source_sha256: str | None = None) -> dict:
    """Reconstruct a device only within declared inputs and civil-date bounds.

    No database writes, LLM, Gold labels or reviewed-path guard changes. Unknown
    dates allow documentary comparison but cannot be silently applied on a date.
    """
    day = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    sources = {source["pdf_sha256"]: source for source in corpus["sources"]}
    bases = [source for source in corpus["sources"] if source["norma_key"] == norma_key and (
        source["pdf_sha256"] == source_sha256 if source_sha256 else source["source_role"] == "primary"
    )]
    result = {
        "schema_version": "jurix-pilot-projection-v1", "basis": "ai_pilot",
        "corpus_revision": corpus["corpus_revision"], "norma_key": norma_key,
        "device_path": path, "as_of": day.isoformat() if day else None,
        "status": "out_of_coverage", "legal_status": "not_determined",
        "before": None, "after": None, "base_evidence": None,
        "events": [], "applied_events": [], "pending_events": [], "conflicts": [],
        "interval": {"start": None, "end": None}, "diff": [],
        "coverage": {"entire_norm_consolidated": False, "universal_validity": False},
        "notes": [],
    }
    if len(bases) != 1:
        result["notes"].append("Edição-base ausente ou ambígua no corpus.")
        return _finish(result)
    base = bases[0]
    span = device_span(base, path)
    events = {event["event_id"]: event for event in corpus.get("events", []) if (
        event.get("target_norma_key") == norma_key and _related(event.get("target_device_path"), path)
    )}
    ordered = sorted(events.values(), key=lambda item: (item["temporal"].get("effective_on") or "9999-12-31", item["event_id"]))
    result["events"] = ordered
    if span is None:
        # Addition of a missing child still needs its unambiguous parent.
        parent = path.rpartition("/")[0]
        if not parent or not device_span(base, parent) or not any(
            event["action"] == "ADICIONA" and event.get("target_device_path") == path for event in ordered
        ):
            result["notes"].append("Dispositivo ausente ou duplicado na edição-base; nenhum texto foi inventado.")
            return _finish(result)
        before, slots = "", {path: (0, 0)}
    else:
        before = base["text"][span[0]:span[1]]
        result["base_evidence"] = evidence(base, *span, label=path)
        slots = _slots(base, path, *span)
    result.update({"before": before, "after": before, "status": "reconstructed", "legal_status": "no_change_found_in_scope"})
    base_temporal = temporal_evidence(norma_key, corpus["sources"])
    base_from = base.get("base_valid_from") or base_temporal.get("effective_on")
    compiled = "compilation" in base.get("edition_kind", "")
    if day and ((compiled and not base.get("edition_year") and not base_from) or (
        base.get("edition_year") and day.year <= base["edition_year"]
    ) or (base_from and day < date.fromisoformat(base_from))):
        result.update({"status": "out_of_coverage", "after": None})
        result["notes"].append("A edição-base não permite reconstruir o período solicitado.")
        return _finish(result)
    if day and not base_from and not base.get("edition_year"):
        result["status"] = "partial"
        result["notes"].append("Data inicial da edição-base não comprovada; cotejo documental disponível.")
    revoked = any((row.get("marker") or row.get("legal_status", row.get("status"))) in {"revoked", "vetoed", "vetado", "revogado"} for row in device_candidates(base, path))
    revoked_paths = {path} if revoked else set()
    if revoked:
        result.update({"status": "partial", "legal_status": "base_revoked_or_vetoed"})
    # Same-day material competitors are conflicts; event hash is only display order.
    collisions = set()
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            effect = left["temporal"].get("effective_on")
            if effect and effect == right["temporal"].get("effective_on") and _related(left.get("target_device_path"), right.get("target_device_path") or path):
                if (left["action"], left.get("new_text")) != (right["action"], right.get("new_text")):
                    collisions.update((left["event_id"], right["event_id"]))
    current = before
    for event in ordered:
        event_id, temporal = event["event_id"], event["temporal"]
        for observation in temporal.get("conflicts", []):
            if observation.get("kind") == "colophon_differs_from_official_edition":
                note = f"O colofão indica {observation['date']}, enquanto o Diário indica {temporal.get('publication_on')}. A derivação experimental usa a edição do Diário; efeitos especiais não são presumidos."
                if note not in result["notes"]:
                    result["notes"].append(note)
        effect, until = temporal.get("effective_on"), temporal.get("end_on")
        if day and effect and date.fromisoformat(effect) > day:
            result["interval"]["end"] = min(filter(None, (result["interval"]["end"], effect)))
            continue
        if event_id in collisions or event["resolution"] == "conflict":
            result["conflicts"].append(event_id)
            continue
        if event["resolution"] != "resolved":
            result["pending_events"].append(event_id)
            continue
        if until and day and day >= date.fromisoformat(until):
            # An expired amendment does not automatically resurrect its old text.
            result["pending_events"].append(event_id)
            result["notes"].append("Fim de efeito registrado; restauração de redação não presumida.")
            continue
        if day and not effect:
            result["pending_events"].append(event_id)
            continue
        target = event.get("target_device_path")
        if compiled and (not base.get("edition_year") or (effect and int(effect[:4]) <= base["edition_year"])):
            if event_id in base.get("incorporated_event_ids", []):
                continue
            result["pending_events"].append(event_id)
            result["notes"].append("Incorporação do evento à compilação-base não comprovada; efeito não reaplicado.")
            continue
        if event["action"] == "REVOGA":
            if not target or target == path or path.startswith(target + "/"):
                revoked = True
                current = ""
                result["legal_status"] = "revoked_in_scope"
                revoked_paths.add(path)
            elif target in slots:
                current, slots = _replace(current, slots, target, "")
                revoked_paths.add(target)
                result["legal_status"] = "partially_revoked_in_scope"
            else:
                result["pending_events"].append(event_id)
                continue
        elif revoked or any(_related(retired, target or path) for retired in revoked_paths):
            result["pending_events"].append(event_id)
            result["notes"].append("Redação revogada/vetada não restaurada automaticamente por evento posterior.")
            continue
        elif event["action"] in {"ALTERA", "SUBSTITUI", "ADICIONA"}:
            replacement_path = path if target == path or path.startswith(target + "/") else target
            value, new_slots = _replacement(event, replacement_path, sources)
            if value is None:
                result["pending_events"].append(event_id)
                continue
            if replacement_path not in slots and event["action"] == "ADICIONA":
                parent = replacement_path.rpartition("/")[0]
                if parent in slots:
                    end = slots[parent][1]
                    slots[replacement_path] = (end, end)
                    value = "\n" + value
            if replacement_path not in slots:
                result["pending_events"].append(event_id)
                continue
            if event["action"] == "ADICIONA":
                start, end = slots[replacement_path]
                existing = current[start:end].strip()
                if existing:
                    if " ".join(existing.split()) == " ".join(value.split()):
                        result["notes"].append("Acréscimo já presente na edição; texto não duplicado.")
                        continue
                    result["pending_events"].append(event_id)
                    result["notes"].append("O alvo do acréscimo já contém texto divergente; substituição não presumida.")
                    continue
            # A quoted replacement body may omit its label. Keep the exact label
            # already present in the base, rather than dropping a paragraph out
            # of its hierarchy or inventing another structural number.
            start, end = slots[replacement_path]
            existing = current[start:end]
            kind, number = replacement_path.split("/")[-1].split(":")
            device_type = {"art": "artigo", "par": "paragrafo", "inc": "inciso", "al": "alinea"}.get(kind)
            if device_type:
                body = ConsolidationEngine._strip_label(existing, device_type, number)
                if body is not None and ConsolidationEngine._strip_label(value, device_type, number) is None:
                    prefix = existing[:len(existing) - len(body)]
                    value = prefix + value
                    new_slots = {key: (left + len(prefix), right + len(prefix)) for key, (left, right) in new_slots.items()}
            current, slots = _replace(current, slots, replacement_path, value, new_slots=new_slots)
            result["legal_status"] = "changed_in_scope"
        else:
            continue
        result["applied_events"].append(event_id)
        if effect:
            result["interval"]["start"] = effect
    result["after"] = current
    if result["conflicts"]:
        result.update({"status": "conflict", "after": None})
    elif result["pending_events"]:
        result["status"] = "unknown_date" if all(
            events[key]["resolution"] == "resolved" and not events[key]["temporal"].get("effective_on")
            for key in result["pending_events"]
        ) else "partial"
        if day:
            result["after"] = None
    elif any(not events[key]["temporal"].get("effective_on") for key in result["applied_events"]):
        result["status"] = "unknown_date"
    result["diff"] = build_legal_diff(before, result["after"]) if result["after"] is not None else []
    result["coverage"].update({"edition_sha256": base["pdf_sha256"], "edition_year": base.get("edition_year"), "base_valid_from": base_from})
    return _finish(result)


def _finish(result: dict) -> dict:
    return {**result, "projection_id": content_hash(canonical_bytes(result))}
