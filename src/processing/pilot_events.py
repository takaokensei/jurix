"""Evidence-bound experimental events; never approves or changes legal records."""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.document_metadata import normalize_document_number
from src.processing.event_temporal_policy import event_temporal_decision
from src.processing.normative_reference import parse_normative_references
from src.processing.pilot_corpus import canonical_bytes, content_hash

_MONTHS = {name: index + 1 for index, name in enumerate((
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
))}
_HEADER = re.compile(
    r"^NATAL,\s*[^\n,]+,\s*(\d{1,2})\s+DE\s+([A-ZÇ]+)\s+DE\s+(\d{4})\b", re.I | re.M,
)
_COMMENCEMENT = re.compile(r"\b(?:esta\s+lei(?:\s+complementar)?|este\s+c[oó]digo)\s+entra\s+em\s+vigor\b", re.I)


def _number(value) -> str:
    return re.sub(r"[º°ª\s.]", "", str(value)).casefold().replace("único", "unico")


def device_candidates(source: dict, path: str) -> list[dict]:
    """Resolve a structural path inside one edition, preserving real ambiguity."""
    rows = source["devices"]
    selected = []
    parent_keys = None
    kinds = {"art": "artigo", "par": "paragrafo", "inc": "inciso", "al": "alinea"}
    by_key = {row["device_key"]: row for row in rows}
    for component in path.split("/"):
        kind, separator, number = component.partition(":")
        if not separator or kind not in kinds:
            return []
        selected = []
        for row in rows:
            if row["type"] != kinds[kind] or _number(row["number"]) != _number(number):
                continue
            parent = row.get("parent_key")
            visited = set()
            if parent_keys is not None:
                while parent and parent not in parent_keys and parent not in visited:
                    visited.add(parent)
                    parent = by_key.get(parent, {}).get("parent_key")
                if parent not in parent_keys:
                    continue
            selected.append(row)
        parent_keys = {row["device_key"] for row in selected}
    return selected


def device_span(source: dict, path: str) -> tuple[int, int] | None:
    matches = device_candidates(source, path)
    if len(matches) != 1:
        return None
    row = matches[0]
    keys = {row["device_key"]}
    descendants = []
    for candidate in source["devices"]:
        if candidate["device_key"] in keys or candidate.get("parent_key") in keys:
            keys.add(candidate["device_key"])
            descendants.append(candidate)
    return row["start"], max(item["end"] for item in descendants)


def evidence(source: dict, start: int, end: int, *, label: str = "") -> dict:
    if not 0 <= start < end <= len(source["text"]):
        raise ValueError("Evidence range outside immutable source")
    quote = source["text"][start:end]
    identity = {"pdf": source["pdf_sha256"], "text": source["text_sha256"], "start": start, "end": end}
    page = next((item["page"] for item in source["page_map"] if item["start"] <= start < item["end"]), None)
    return {
        "citation_id": "pilot:" + content_hash(canonical_bytes(identity)),
        "document_sha256": source["pdf_sha256"], "text_sha256": source["text_sha256"],
        "norma_key": source["norma_key"], "start": start, "end": end,
        "page": page, "quote": quote, "device_ref": label,
    }


def _target(value) -> tuple[str | None, str | None]:
    if isinstance(value, str) and value.startswith("Natal|"):
        parts = value.split("|")
        path = parts[4] if len(parts) > 4 else ""
        components = re.findall(r"(art|par|inc|al)(\d+|unico|[IVXLCDM]+)", path, re.I)
        return "BR-RN-NATAL|" + "|".join(parts[1:4]), "/".join(f"{kind}:{number}" for kind, number in components) or None
    literal = str(value.get("confirmed_identity") or "") if isinstance(value, dict) else str(value or "")
    refs = parse_normative_references(literal)
    if len(refs) != 1 or refs[0].year is None:
        return None, None
    ref = refs[0]
    key = f"BR-RN-NATAL|{ref.type_key}|{normalize_document_number(ref.number)}|{ref.year}"
    return key, f"art:{ref.article}" if ref.article else None


def _new_text(quote: str, path: str | None, action: str) -> str | None:
    if action == "REVOGA" or not path:
        return None
    kind, number = path.split("/")[-1].split(":")
    device_type = {"art": "artigo", "par": "paragrafo", "inc": "inciso", "al": "alinea"}[kind]
    candidate = quote.strip().strip("“”\" ")
    if re.search(r"\.{3,}|…|\.(?:\s+\.){2,}", candidate):
        return None  # An omitted passage cannot replace a complete target.
    if kind == "par":
        prefix = re.match(r"^§[ \t]*(\d+)[º°ª]?(?!\d)", candidate)
        # An ordinal followed by " - A regulamentação" starts the body, whereas
        # "§3-A" (or "§3º-A") identifies another paragraph.
        same_line_suffix = re.match(r"^§[ \t]*\d+(?:[º°ª]-|[ \t]*-)[ \t]*[A-Za-z]{1,2}\b", candidate)
        if prefix and _number(prefix.group(1)) == _number(number) and not same_line_suffix:
            return candidate
    # Exact adopted excerpts may contain a complete article and its subtree.
    # The projection replaces that subtree once, instead of duplicating children.
    if ConsolidationEngine._strip_label(candidate, device_type, number) is not None:
        return candidate
    passages = ConsolidationEngine._quoted_passages(quote)
    if len(passages) == 1 and kind in {"par", "inc", "al"}:
        return passages[0].strip()
    return None


def temporal_evidence(norm_key: str, sources: list[dict]) -> dict:
    """Observe publication in its own official edition and reuse date calculation."""
    editions = [source for source in sources if source["norma_key"] == norm_key and (
        source.get("edition_kind") == "official_publication"
        or ("Diário Oficial" in source["text"][:500] and _HEADER.search(source["text"]))
    )]
    observations, clauses, colophons = [], [], []
    for source in sources:
        if source["norma_key"] != norm_key:
            continue
        for match in re.finditer(r"Publicad[ao][^\n]{0,90}?\b(\d{1,2})/(\d{1,2})/(\d{4})", source["text"], re.I):
            day, month, year = map(int, match.groups())
            colophons.append({"date": date(year, month, day).isoformat(), "evidence": evidence(source, match.start(), match.end(), label="Colofão")})
    for source in editions:
        for match in _HEADER.finditer(source["text"]):
            day, month, year = match.groups()
            if month.casefold() in _MONTHS:
                value = date(int(year), _MONTHS[month.casefold()], int(day))
                observations.append((value, evidence(source, match.start(), match.end(), label="Cabeçalho do Diário Oficial")))
        for row in source["devices"]:
            quote = source["text"][row["start"]:row["end"]]
            if row["type"] == "artigo" and _COMMENCEMENT.search(quote):
                clauses.append(evidence(source, row["start"], row["end"], label=f"Art. {row['number']}"))
    dates = {item[0] for item in observations}
    result = {
        "publication_on": None, "vigencia_on": None, "effective_on": None,
        "status": "unknown_date", "effect_scope": "textual_commencement_only",
        "publication_evidence": [], "commencement_evidence": clauses,
        "colophon_observations": colophons, "conflicts": [],
        "special_effects_on": None,
    }
    if len(dates) != 1 or len(clauses) != 1:
        return result
    published = next(iter(dates))
    result["publication_on"] = published.isoformat()
    result["publication_evidence"] = [observations[0][1]]
    for item in colophons:
        if item["date"] != published.isoformat():
            result["conflicts"].append({"kind": "colophon_differs_from_official_edition", **item})
    decision = event_temporal_decision(SimpleNamespace(
        acao="ALTERA", dispositivo_fonte=SimpleNamespace(texto=clauses[0]["quote"], norma=SimpleNamespace(data_publicacao=published)),
    ))
    if decision.effective_on:
        result.update({
            "status": "documentary_derived", "vigencia_on": decision.effective_on.isoformat(),
            "effective_on": decision.effective_on.isoformat(), "calculation_basis": decision.basis,
            "calculation_note": "Derivação experimental a partir do Diário e da cláusula; não é revisão jurídica independente.",
        })
    return result


def build_pilot_events(sources: list[dict], adoptions: list[dict]) -> dict:
    """Validate adopted analysis against current blobs/text, retaining unresolved scope."""
    source_by_hash = {source["pdf_sha256"]: source for source in sources}
    primary = {source["norma_key"]: source for source in sources if source["source_role"] == "primary"}
    events, rejected, adoption_index = [], [], []
    temporal = {}
    for adoption in adoptions:
        payload = adoption["evidence_json"]
        source_map = {row["source_id"]: row["pdf_sha256"] for row in payload["sources"]}
        provenance = {key: adoption.get(key) for key in (
            "case_key", "revision", "review_draft_sha256", "review_report_sha256", "source_manifest_sha256",
        )}
        provenance["review_kind"] = "ai"
        adoption_index.append(provenance)
        for adopted in payload["events"]:
            old = adopted["evidence"]
            source = source_by_hash.get(source_map.get(old["source_id"]))
            if source is None or source["text_sha256"] != old["text_sha256"] or source["text"][old["start"]:old["end"]] != old["quote"]:
                rejected.append({"relation_key": adopted["relation_key"], "reason": "adopted_source_fingerprint_mismatch"})
                continue
            norm_key, path = _target(adopted["target"])
            base = primary.get(norm_key)
            span = device_span(base, path) if base and path else None
            is_conflict = "conflict" in adopted["target_resolution"]
            resolution = "conflict" if is_conflict else "resolved" if base and (span or adopted["action"] == "ADICIONA" or not path) else "unresolved"
            text_after = _new_text(old["quote"], path, adopted["action"])
            if adopted["action"] in {"ALTERA", "SUBSTITUI", "ADICIONA"} and not text_after:
                resolution = "conflict" if is_conflict else "partial"
            if source["norma_key"] not in temporal:
                temporal[source["norma_key"]] = temporal_evidence(source["norma_key"], sources)
            event = {
                "relation_key": adopted["relation_key"], "action": adopted["action"],
                "source_norma_key": source["norma_key"], "source_article": old["article"],
                "target_norma_key": norm_key, "target_device_path": path,
                "target_scope": "device" if path else "norma", "resolution": resolution,
                "evidence": evidence(source, old["start"], old["end"], label=f"Art. {old['article']}"),
                "base_evidence": evidence(base, *span, label=path) if span else (
                    evidence(base, base["coverage"]["act_spans"][0][0], min(base["coverage"]["act_spans"][0][0] + 350, base["coverage"]["act_spans"][0][1]), label="Epígrafe do ato-alvo")
                    if base and not path and base["coverage"].get("act_spans") else None
                ),
                "new_text": text_after, "new_text_status": "adopted_exact_excerpt" if text_after else "not_applicable" if adopted["action"] == "REVOGA" else "not_extracted",
                "temporal": temporal[source["norma_key"]], "adoption": provenance,
                "limitations": adoption.get("limitations_json", []),
                "assessment": adopted.get("documentary_assessment", ""),
            }
            event["target_edition_evidence"] = []
            if path:
                # A conflicting compilation is evidence, not an automatic fix to
                # the target's numbering. Observe the same parent article in
                # every selected alternative edition, without guessing its text.
                article_path = path.split("/")[0]
                for alternative in sources:
                    if alternative["norma_key"] != norm_key or alternative is base:
                        continue
                    alternative_span = device_span(alternative, article_path)
                    if alternative_span:
                        event["target_edition_evidence"].append(evidence(alternative, *alternative_span, label=article_path))
            event["event_id"] = "pilot-event:" + content_hash(canonical_bytes(event))
            events.append(event)
    # Enumerated siblings of an adopted repeal remain visible with no invented
    # target identity. Only an explicitly adopted item can become operative.
    enumerations = {(event["source_norma_key"], event["source_article"]) for event in events if event["action"] == "REVOGA"}
    for source_key, article in sorted(enumerations):
        source = primary[source_key]
        parents = device_candidates(source, f"art:{article}")
        if len(parents) != 1:
            continue
        parent_key = parents[0]["device_key"]
        for row in source["devices"]:
            if row.get("parent_key") != parent_key or row["type"] != "inciso":
                continue
            if any(event["evidence"]["document_sha256"] == source["pdf_sha256"] and event["evidence"]["start"] <= row["start"] < event["evidence"]["end"] for event in events):
                continue
            item = evidence(source, row["start"], row["end"], label=f"Art. {article}, inciso {row['number']}")
            events.append({
                "event_id": "pilot-unresolved:" + item["citation_id"].split(":")[1],
                "relation_key": None, "action": "REVOGA", "source_norma_key": source_key,
                "source_article": article, "target_norma_key": None, "target_device_path": None,
                "target_scope": "unresolved", "resolution": "unresolved", "evidence": item,
                "new_text": None, "base_evidence": None, "temporal": temporal[source_key],
                "assessment": "Referência literal ainda não adotada/resolvida; nenhum alvo atribuído.",
            })
    ready = []
    for adoption in adoptions:
        selected = [event for event in events if event.get("adoption", {}).get("case_key") == adoption["case_key"]]
        ready.append({
            "case_key": adoption["case_key"], "events": [event["event_id"] for event in selected],
            "documentary_events_ready": bool(selected) and not any(event["resolution"] == "unresolved" for event in selected),
            "dated_events": sum(bool(event["temporal"]["effective_on"]) for event in selected),
            "complete_replacements": sum(event["action"] in {"ALTERA", "SUBSTITUI"} and bool(event["new_text"]) and event["resolution"] == "resolved" for event in selected),
            "partial_repeals": sum(event["action"] == "REVOGA" and event["target_scope"] == "device" and event["resolution"] == "resolved" for event in selected),
            "conflicts": sum(event["resolution"] == "conflict" for event in selected),
        })
    return {
        "schema_version": "jurix-pilot-events-v1", "events": sorted(events, key=lambda item: item["event_id"]),
        "adoptions": sorted(adoption_index, key=lambda item: item["case_key"]),
        "rejected": rejected, "chain_readiness": ready,
    }
