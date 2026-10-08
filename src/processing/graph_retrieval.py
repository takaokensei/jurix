"""Bounded evidence expansion for explicit normative-relation questions."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.apps.legislation.models import Dispositivo
from src.processing.normative_graph import build_normative_graph

MAX_GRAPH_EVIDENCE = 8
MAX_GRAPH_SEEDS = 3
MODIFICATION_ACTIONS = frozenset({"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA"})
REFERENCE_ACTIONS = frozenset({"REFERENCIA"})


def _norma_id_from_node(node_id: Any) -> int | None:
    prefix, _, raw_id = str(node_id or "").partition(":")
    if prefix != "norma":
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _device_for_key(norma_id: int, key: str | None):
    if not key:
        return None
    return (
        Dispositivo.objects.select_related("norma", "dispositivo_pai")
        .filter(norma_id=norma_id, structural_key=key, is_active=True)
        .first()
    )


def _evidence_row(device, event: dict, *, role: str, relation_intent: str) -> dict:
    action = str(event.get("action") or "").upper()
    if action == "REFERENCIA":
        relation_label = "remissão; não é evidência de alteração"
    else:
        relation_label = f"relação normativa {action.lower()}"
    quote = str((event.get("evidence") or {}).get("quote") or "").strip()
    return {
        "dispositivo": device,
        "similarity_score": 0.0,
        "semantic_score": 0.0,
        "lexical_score": 0.0,
        "retrieval_score": 0.0,
        "distance": 1.0,
        "match_kind": "normative_graph_relation",
        "retrieval_strategy": "one_hop_reviewed_graph",
        "evidence_scope": "relation_context",
        "graph_relation": {
            "event_id": event.get("id"),
            "action": action,
            "intent": relation_intent,
            "role": role,
            "label": relation_label,
            "source_norma_id": _norma_id_from_node(event.get("source")),
            "target_norma_id": _norma_id_from_node(event.get("target")),
            "source_device_key": event.get("source_device_key"),
            "target_device_key": event.get("target_device_key"),
            "review_status": event.get("review_status"),
            "effective_status": event.get("effective_status"),
            "effective_on": event.get("effective_on"),
            "publication_on": event.get("publication_on"),
            "quote": quote,
            "official_url": event.get("official_url"),
            "resolution": event.get("resolution"),
        },
    }


def expand_relation_evidence(
    question: str,
    baseline_rows: list[dict],
    *,
    relation_intent: str,
    as_of: date | None = None,
    max_additional: int = MAX_GRAPH_EVIDENCE,
) -> tuple[list[dict], dict[str, Any]]:
    """Add at most eight one-hop, reviewed, text-backed relation sources.

    The graph's edge is not treated as content evidence by itself. Modification
    claims require the event source quote and a resolved target device. Reference
    edges are kept explicitly distinct and never represented as amendments.
    """
    cap = min(MAX_GRAPH_EVIDENCE, max(0, int(max_additional)))
    trace: dict[str, Any] = {
        "enabled": True,
        "intent": relation_intent,
        "seed_norma_ids": [],
        "added": [],
        "discarded": [],
        "additional_evidence_limit": cap,
    }
    if relation_intent not in {"modification", "reference", "mixed"} or not cap:
        return list(baseline_rows), trace

    seeds = {}
    seen = set()
    for row in baseline_rows:
        device = row.get("dispositivo")
        norma = getattr(device, "norma", None)
        if norma and norma.pk not in seeds:
            seeds[norma.pk] = norma
        if device and getattr(device, "structural_key", None):
            seen.add((getattr(device, "norma_id", None), device.structural_key))
    seed_ids = sorted(seeds)
    trace["seed_norma_ids"] = seed_ids[:MAX_GRAPH_SEEDS]
    if len(seed_ids) > MAX_GRAPH_SEEDS:
        trace["discarded"].append(
            {
                "reason": "graph_seed_budget_exhausted",
                "omitted_norma_ids": seed_ids[MAX_GRAPH_SEEDS:],
            }
        )
    if not seeds:
        trace["discarded"].append({"reason": "no_retrieved_norma_seed"})
        return list(baseline_rows), trace

    if relation_intent == "reference":
        allowed_actions = REFERENCE_ACTIONS
    elif relation_intent == "mixed":
        allowed_actions = MODIFICATION_ACTIONS | REFERENCE_ACTIONS
    else:
        allowed_actions = MODIFICATION_ACTIONS
    additions = []
    baseline_rows = [dict(row) if isinstance(row, dict) else row for row in baseline_rows]
    existing_rows = {}
    for row in baseline_rows:
        device = row.get("dispositivo") if isinstance(row, dict) else None
        identity = (getattr(device, "norma_id", None), getattr(device, "structural_key", None))
        if identity[0] and identity[1]:
            existing_rows.setdefault(identity, []).append(row)
    annotated_existing = set()
    event_paths = set()
    for norma_id in seed_ids[:MAX_GRAPH_SEEDS]:
        norma = seeds[norma_id]
        try:
            graph = build_normative_graph(
                norma,
                depth=1,
                as_of=as_of,
                actions=tuple(sorted(allowed_actions)),
            )
        except Exception as exc:  # Preserve baseline retrieval on a graph service failure.
            trace["discarded"].append(
                {"norma_id": norma_id, "reason": "graph_lookup_failed", "kind": type(exc).__name__}
            )
            continue
        root_id = f"norma:{norma_id}"
        trace.setdefault("graph_truncated", False)
        trace["graph_truncated"] = trace["graph_truncated"] or bool(graph.get("truncated"))
        for edge in graph.get("edges", []):
            action = str(edge.get("action") or "").upper()
            if action not in allowed_actions:
                trace["discarded"].append(
                    {"event_id": edge.get("id"), "reason": "action_does_not_match_intent"}
                )
                continue
            source_id = _norma_id_from_node(edge.get("source"))
            target_id = _norma_id_from_node(edge.get("target"))
            if root_id not in {edge.get("source"), edge.get("target")}:
                continue
            source_device = _device_for_key(source_id, edge.get("source_device_key"))
            target_device = _device_for_key(target_id, edge.get("target_device_key"))
            quote = str((edge.get("evidence") or {}).get("quote") or "").strip()
            if not source_device or not quote or quote not in (source_device.texto or ""):
                trace["discarded"].append(
                    {"event_id": edge.get("id"), "reason": "source_quote_not_verifiable"}
                )
                continue
            if target_device and target_device.norma_id != target_id:
                trace["discarded"].append(
                    {"event_id": edge.get("id"), "reason": "target_device_norma_mismatch"}
                )
                continue
            if action in MODIFICATION_ACTIONS and not target_device:
                trace["discarded"].append(
                    {"event_id": edge.get("id"), "reason": "target_device_text_unavailable"}
                )
                continue
            if action == "REFERENCIA" and not target_device:
                trace["discarded"].append(
                    {"event_id": edge.get("id"), "reason": "reference_target_text_unavailable"}
                )
                continue

            event_path = {
                "event_id": edge.get("id"),
                "action": action,
                "source_norma_id": source_id,
                "target_norma_id": target_id,
                "effective_status": edge.get("effective_status"),
                "effective_on": edge.get("effective_on"),
                "resolution": edge.get("resolution"),
            }
            if event_path["event_id"] in event_paths:
                continue
            event_paths.add(event_path["event_id"])
            role_devices = [(source_device, "modifying_device" if action in MODIFICATION_ACTIONS else "referencing_device")]
            role_devices.append((target_device, "target_device"))
            for device, role in role_devices:
                identity = (device.norma_id, device.structural_key)
                if identity in seen:
                    # A semantic result can already contain the exact article
                    # that the graph resolved. Keep its score/order, but enrich
                    # it with the reviewed relation instead of silently losing
                    # the graph edge during de-duplication.
                    for existing in existing_rows.get(identity, []):
                        if not existing.get("graph_relation"):
                            relation_row = _evidence_row(
                                device, edge, role=role, relation_intent=relation_intent
                            )
                            existing.update({
                                "match_kind": relation_row["match_kind"],
                                "retrieval_strategy": relation_row["retrieval_strategy"],
                                "evidence_scope": relation_row["evidence_scope"],
                                "graph_relation": relation_row["graph_relation"],
                            })
                            annotated_existing.add(identity)
                            break
                    continue
                if len(additions) >= cap:
                    trace["discarded"].append(
                        {"event_id": edge.get("id"), "reason": "additional_evidence_budget_exhausted"}
                    )
                    break
                seen.add(identity)
                additions.append(
                    _evidence_row(device, edge, role=role, relation_intent=relation_intent)
                )
            trace["added"].append(event_path)

    trace["added_evidence_count"] = len(additions)
    trace["annotated_existing_evidence_count"] = len(annotated_existing)
    return list(baseline_rows) + additions, trace
