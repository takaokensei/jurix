"""One evidence-bound pilot DTO for comparison, graph, chat and exports."""

from __future__ import annotations

from urllib.parse import urlencode

from src.processing.pilot_corpus import canonical_bytes, content_hash
from src.processing.pilot_events import evidence
from src.processing.pilot_projection import device_paths, project_pilot_device

TYPE_LABELS = {"lei": "Lei Ordinária", "lei_complementar": "Lei Complementar", "lei_promulgada": "Lei Promulgada", "decreto": "Decreto"}
STATUS_LABELS = {"reconstructed": "Reconstrução no escopo", "partial": "Comparação parcial", "conflict": "Conflito documental", "unknown_date": "Data não comprovada", "out_of_coverage": "Fora da cobertura"}
LEGAL_LABELS = {"no_change_found_in_scope": "Sem alteração localizada no escopo", "changed_in_scope": "Redação alterada no escopo", "revoked_in_scope": "Revogado no escopo", "partially_revoked_in_scope": "Revogação parcial no escopo", "base_revoked_or_vetoed": "Marca de revogação ou veto na base", "not_determined": "Não determinado"}


def norm_label(key: str) -> str:
    _jurisdiction, kind, number, year = key.split("|")
    return f"{TYPE_LABELS.get(kind, kind)} nº {int(number):,}/{year}".replace(",", ".")


def device_label(path: str | None) -> str:
    if not path:
        return "Norma inteira"
    labels = {"art": "Art.", "par": "§", "inc": "inciso", "al": "alínea", "item": "item"}
    return ", ".join("Parágrafo único" if kind == "par" and number == "unico" else f"{labels.get(kind, kind)} {number.upper() if kind == 'inc' else number}" for kind, number in (part.split(":", 1) for part in path.split("/")))


def casefile_url(key: str, revision: str, **options) -> str:
    return "/explorar/piloto/?" + urlencode({"norma": key, "revision": revision, **{key: value for key, value in options.items() if value is not None}}, doseq=True)


def source_url(digest: str, revision: str, page: int | None = None) -> str:
    return f"/explorar/fontes/{digest}/?revision={revision}" + (f"#page={page}" if page else "")


def render_pilot_casefile_markdown(casefile: dict) -> str:
    """Portable references are resolved by document hash in the destination build."""
    from src.processing.evidence_export import (
        _markdown_label,
        build_evidence_package,
        render_evidence_markdown,
    )

    lines = [f"# {_markdown_label(casefile['label'])}", "", "Consolidação experimental por IA, limitada ao corpus processado.",
             f"Dossiê: `{casefile['casefile_id']}`", f"Corpus: `{casefile['corpus_revision']}`", ""]
    for device in casefile["devices"]:
        lines.extend([f"## {device['label']} — {device['status_label']}", "", f"{device['legal_label']}.", "",
                      "Redação documental anterior:", "", device["before"] or "Não disponível.", "",
                      "Resultado no escopo:", "", device["after"] if device["after"] else "Revogado no escopo." if device["after"] == "" else "Redação não determinada; consulte os eventos e conflitos.", ""])
        lines.extend(device["notes"])
    package = build_evidence_package(casefile_citation_sources(casefile), include_excerpts=True, corpus_revision={
        "digest": casefile["corpus_revision"], "completeness": "partial", "source": "ai_pilot",
    })
    lines.extend(["", render_evidence_markdown(package)])
    return "\n".join(lines)


def casefile_citation_sources(casefile: dict) -> list[dict]:
    """Adapt exact dossier evidence to the existing citation/export contract."""
    return [evidence_citation_source(row, revision=casefile["corpus_revision"], casefile_id=casefile["casefile_id"]) for row in casefile["sources"]]


def evidence_citation_source(row: dict, *, revision: str, casefile_id: str) -> dict:
    """One serializer input for both indexed articles and dossier evidence."""
    label = row.get("label") or f"{norm_label(row['norma_key'])}, {device_label(row['device_ref']) if ':' in row['device_ref'] else row['device_ref']}"
    return {
        "citation_id": row["citation_id"], "citation_index": row["citation_index"],
        "citation_label": label, "norma_ref": norm_label(row["norma_key"]), "norma_key": row["norma_key"],
        "dispositivo_ref": device_label(row["device_ref"]) if ":" in row["device_ref"] else row["device_ref"],
        "full_text": row["quote"], "evidence_text": row["quote"],
        "document_sha256": row["document_sha256"], "text_sha256": row["text_sha256"],
        "page": row.get("page"), "span": {"start": row["start"], "end": row["end"]},
        "local_pdf_url": source_url(row["document_sha256"], revision, row.get("page")), "span_basis": "exact_immutable_extraction",
        "evidence_scope": "ai_pilot", "source_kind": "documentary_pilot", "source_type": "Fonte documental",
        "casefile_id": casefile_id, "corpus_revision": revision,
        "retrieval_strategy": "pilot_casefile", "similarity_score": None,
        "status_label": "Análise IA adotada no piloto",
    }


def build_pilot_casefile(corpus: dict, norma_key: str, *, paths: tuple[str, ...] = (), as_of=None,
                         source_sha256: str | None = None) -> dict:
    """No Gold input, hardcoded case law, DB PK or persisted localhost identity."""
    selected = [row for row in corpus["sources"] if row["norma_key"] == norma_key and (
        row["pdf_sha256"] == source_sha256 if source_sha256 else row["source_role"] == "primary"
    )]
    if len(selected) != 1:
        raise ValueError("A edição da norma está ausente ou é ambígua.")
    base = selected[0]
    relevant = [event for event in corpus.get("events", []) if norma_key in {event["source_norma_key"], event.get("target_norma_key")}]
    available = device_paths(base)
    if not paths:
        suggested = {
            event["target_device_path"] if event["target_device_path"] in available else event["target_device_path"].split("/")[0]
            for event in relevant if event.get("target_norma_key") == norma_key and event.get("target_device_path")
        }
        suggested.update(f"art:{event['source_article']}" for event in relevant if event["source_norma_key"] == norma_key)
        paths = tuple(path for path in available if path in suggested) or tuple(path for path in available if "/" not in path)[:12]
    if len(paths) > 40:
        raise ValueError("Selecione no máximo 40 dispositivos por comparação.")
    projections = [project_pilot_device(corpus, norma_key, path, as_of=as_of, source_sha256=base["pdf_sha256"]) for path in dict.fromkeys(paths)]
    raw_sources = {}
    def add(item):
        if item:
            raw_sources[item["citation_id"]] = item
    for projection in projections:
        add(projection["base_evidence"])
    for event in relevant:
        add(event["evidence"])
        add(event.get("base_evidence"))
        for item in event.get("target_edition_evidence", []):
            add(item)
        for key in ("publication_evidence", "commencement_evidence"):
            for item in event["temporal"].get(key, []):
                add(item)
        for item in event["temporal"].get("conflicts", []):
            add(item.get("evidence"))
    # Exact requested articles remain useful even without any adopted relation.
    if not raw_sources and available:
        row = next(iter(available.values()))
        add(evidence(base, row["start"], row["end"], label=device_label(next(iter(available)))))
    revision = corpus["corpus_revision"]
    case_id = content_hash(canonical_bytes({
        "schema": "jurix-pilot-casefile-v1", "corpus_revision": revision, "norma": norma_key,
        "edition": base["pdf_sha256"], "as_of": str(as_of) if as_of else None,
        "projections": [row["projection_id"] for row in projections], "events": [row["event_id"] for row in relevant],
        "sources": sorted(raw_sources),
    }))
    sources = [{**item, "citation_index": index, "label": f"{norm_label(item['norma_key'])}, {device_label(item['device_ref']) if ':' in item['device_ref'] else item['device_ref']}",
                "pdf_url": source_url(item["document_sha256"], revision, item.get("page")),
                "casefile_id": case_id, "corpus_revision": revision}
               for index, item in enumerate(raw_sources.values(), 1)]
    nodes = {norma_key: {"id": norma_key, "label": norm_label(norma_key), "url": casefile_url(norma_key, revision)}}
    edges = []
    for event in relevant:
        origin = event["source_norma_key"]
        target = event.get("target_norma_key") or "unresolved:" + event["event_id"]
        nodes.setdefault(origin, {"id": origin, "label": norm_label(origin), "url": casefile_url(origin, revision)})
        nodes.setdefault(target, {"id": target, "label": norm_label(target) if event.get("target_norma_key") else f"Alvo não resolvido · {event['evidence']['device_ref']}", "url": casefile_url(target, revision) if event.get("target_norma_key") else None})
        edges.append({
            "id": event["event_id"], "event_id": event["event_id"], "source": origin, "target": target,
            "action": event["action"], "source_device": {"label": event["evidence"].get("device_ref") or f"Art. {event['source_article']}"},
            "target_device": {"label": device_label(event.get("target_device_path")) if event.get("target_norma_key") else "Identidade ainda não resolvida"},
            "review_status": "ai_pilot", "resolution": event["resolution"],
            "publication_on": event["temporal"].get("publication_on"),
            "effective_on": event["temporal"].get("effective_on"), "effective_status": event["temporal"]["status"],
            "evidence": event["evidence"], "local_pdf_url": source_url(event["evidence"]["document_sha256"], revision, event["evidence"].get("page")),
            "casefile_id": case_id, "corpus_revision": revision,
        })
    return {
        "schema_version": "jurix-pilot-casefile-v1", "casefile_id": case_id, "corpus_revision": revision,
        "basis": "ai_pilot", "norma_key": norma_key, "label": norm_label(norma_key),
        "as_of": str(as_of) if as_of else None, "edition_sha256": base["pdf_sha256"],
        "coverage": {"selected_devices": len(projections), "available_devices": len(available), "entire_norm_consolidated": False},
        "devices": [{**item, "label": device_label(item["device_path"]), "status_label": STATUS_LABELS[item["status"]], "legal_label": LEGAL_LABELS[item["legal_status"]]} for item in projections],
        "events": relevant, "sources": sources,
        "conflicts": sorted({key for item in projections for key in item["conflicts"]}),
        "graph": {"root_id": norma_key, "nodes": list(nodes.values()), "edges": edges, "truncated": False},
        "available_paths": [{"path": path, "label": device_label(path)} for path in available if "/" not in path],
    }
