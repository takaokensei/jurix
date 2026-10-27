"""Immutable operational source snapshots, separate from evaluation references."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
SCHEMA = "jurix-operational-pilot-v1"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_source_selection(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "jurix-pilot-source-selection-v1":
        raise ValueError("Unsupported pilot source selection")
    sources = data.get("documents", [])
    seen = set()
    for source in sources:
        digest = source.get("pdf_sha256", "")
        if not DIGEST.fullmatch(digest) or digest in seen:
            raise ValueError("Missing, duplicate or invalid source hash")
        seen.add(digest)
        identity = source["identity"]
        key = "|".join(str(identity[field]) for field in ("jurisdicao", "tipo", "numero", "ano"))
        if key != source["norma_key"]:
            raise ValueError("Typed identity does not match the norm key")
    # The operational schema does not accept benchmark labels at any nesting level.
    def check(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.startswith("expected_") or key in {"query", "queries", "answer", "answers"}:
                    raise ValueError("Evaluation labels must not enter the operational selection")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(data)
    if not sources:
        raise ValueError("Empty pilot source selection")
    return data


def verified_blob(root: Path, storage_key: str, expected_hash: str) -> Path:
    base = root.resolve()
    path = (base / storage_key).resolve()
    if not DIGEST.fullmatch(expected_hash) or not path.is_relative_to(base) or path == base:
        raise ValueError("Blob path escapes QA storage or hash is invalid")
    if path.is_symlink() or not path.is_file():
        raise ValueError("PDF blob is missing")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("Source is not a PDF")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected_hash:
        raise ValueError("PDF blob hash mismatch")
    return path


def build_source_record(spec: dict, extraction) -> dict:
    """Reuse the legal parser without accepting or persisting candidate segments."""
    from src.processing.device_revision import ordered_hierarchy_rows, parsed_device_identities
    from src.processing.document_metadata import normalize_document_number
    from src.processing.document_segmentation import (
        _explicit_device_status,
        _mask_normative_appendices,
        _offset_preserving_text,
        _source_page,
    )
    from src.processing.gazette_act_candidates import find_gazette_act_candidates
    from src.processing.legal_parser import LegalTextParser, classify_closing_segments

    text = extraction.legal_text
    if not text.strip() or content_hash(text.encode("utf-8")) != extraction.legal_text_sha256:
        raise ValueError("Extraction text missing or hash mismatch")
    parser = LegalTextParser()
    article_text = text
    # A PDF may contain many acts. Reuse the existing heading detector and keep
    # exact full-extraction offsets; never label every article with the first law.
    maps = extraction.page_map_json or [{"page": 1, "start": 0, "end": len(text)}]
    pages = [text[span["start"]:span["end"]] for span in maps]
    candidates = find_gazette_act_candidates(pages, max_pages=500).candidates
    identity = spec["identity"]
    matches = [item for item in candidates if (
        item.type_key_candidate == identity["tipo"]
        and normalize_document_number(item.number_candidate) == normalize_document_number(identity["numero"])
        and item.year_candidate in (None, identity["ano"])
    )]
    ranges = []
    for item in matches:
        act_ranges = []
        for span in item.spans:
            page = maps[span.page - 1]
            act_ranges.append((page["start"] + span.start_offset, page["start"] + span.end_offset))
        if act_ranges:
            ranges.append((min(left for left, _right in act_ranges), max(right for _left, right in act_ranges)))
    if ranges:
        chars = list(article_text)
        inside = bytearray(len(text))
        for start, end in ranges:
            inside[start:end] = b"\1" * (end - start)
        for position in range(len(chars)):
            if not inside[position] and chars[position] not in "\r\n":
                chars[position] = " "
        article_text = "".join(chars)
    # A previous act's annex must not hide the selected law later in a gazette.
    article_text, appendix = _mask_normative_appendices(article_text)
    closings = [item for item in classify_closing_segments(text) if item["kind"] == "editorial_colophon"]
    hierarchy = parser.build_hierarchy(parser.parse_legal_text(_offset_preserving_text(article_text)))
    identities = parsed_device_identities(hierarchy)
    rows = ordered_hierarchy_rows(hierarchy)
    devices = []
    for index, row in enumerate(rows):
        start = row["start_pos"]
        end = rows[index + 1]["start_pos"] if index + 1 < len(rows) else len(text)
        if appendix is not None and start < appendix < end:
            end = appendix
        containing = next(((left, right) for left, right in ranges if left <= start < right), None)
        if containing:
            # An article can continue on following source pages belonging to the
            # same act, but it must end before the next unrelated act.
            act_end = containing[1]
            for left, right in sorted(ranges):
                if act_end <= left and not text[act_end:left].strip():
                    act_end = right
            end = min(end, act_end)
        closing = next((item["start"] for item in closings if start < item["start"] < end), None)
        if closing is not None:
            end = closing
        if not 0 <= start < end <= len(text):
            raise ValueError("Parser span outside immutable extraction")
        key, _fingerprint = identities[row["index"]]
        devices.append({
            "device_key": key, "parent_key": identities[row["parent_index"]][0] if row.get("parent_index") is not None else None,
            "type": row["tipo"], "number": row["numero"], "start": start, "end": end,
            "page": _source_page(extraction, start), "marker": _explicit_device_status(row.get("texto", "")),
            "basis": "documentary_candidate",
        })
    return {
        **spec, "text": text, "text_sha256": extraction.legal_text_sha256,
        "extractor_version": extraction.extractor_version,
        "policy_fingerprint": extraction.policy_fingerprint,
        "extraction_status": extraction.status,
        "page_map": extraction.page_map_json, "page_count": extraction.page_count,
        "devices": devices,
        "coverage": {"reviewed": False, "entire_norm_consolidated": False,
                     "selected_source_only": True, "appendix_start": appendix,
                     "act_boundary_status": "candidate" if matches else "unresolved",
                     "act_spans": ranges, "detected_act_headings": len(candidates)},
    }


def publish_revision(pilot_root: Path, sources: list[dict], *, report: dict, event_bundle: dict | None = None) -> dict:
    """Write complete content before atomically activating it; never mutate a revision."""
    pilot_root.mkdir(parents=True, exist_ok=True)
    artifacts = {row["pdf_sha256"]: canonical_bytes(row) for row in sources}
    manifest = {
        "schema_version": SCHEMA, "parser_contract": "offset-preserving-candidate-v1",
        "event_bundle": event_bundle or {"events": [], "adoptions": [], "chain_readiness": []},
        "sources": [{"pdf_sha256": row["pdf_sha256"], "norma_key": row["norma_key"],
                     "source_role": row["source_role"],
                     "artifact_sha256": content_hash(artifacts[row["pdf_sha256"]])}
                    for row in sorted(sources, key=lambda item: item["pdf_sha256"])],
    }
    revision = content_hash(canonical_bytes(manifest))
    revisions = pilot_root / "revisions"
    revisions.mkdir(exist_ok=True)
    destination = revisions / revision
    staging = Path(tempfile.mkdtemp(prefix="pending-", dir=pilot_root))
    try:
        (staging / "sources").mkdir()
        for digest, data in artifacts.items():
            (staging / "sources" / f"{digest}.json").write_bytes(data)
        (staging / "manifest.json").write_bytes(canonical_bytes(manifest))
        if destination.exists():
            if (destination / "manifest.json").read_bytes() != canonical_bytes(manifest):
                raise ValueError("Existing revision has different content")
            for digest, data in artifacts.items():
                if (destination / "sources" / f"{digest}.json").read_bytes() != data:
                    raise ValueError("Existing revision source was modified")
        else:
            try:
                staging.rename(destination)
            except OSError:
                # Another builder may have published exactly the same content.
                if not destination.is_dir():
                    raise
                if (destination / "manifest.json").read_bytes() != canonical_bytes(manifest):
                    raise ValueError("Concurrent revision mismatch") from None
        # Operational clock/PKs belong in this report, never in the digest.
        report_path = pilot_root / "readiness.json"
        pointer = {"schema_version": SCHEMA, "corpus_revision": revision}
        for target, value in ((report_path, report), (pilot_root / "current.json", pointer)):
            fd, raw = tempfile.mkstemp(dir=pilot_root, prefix="activate-")
            path = Path(raw)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_bytes(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(path, target)
            finally:
                path.unlink(missing_ok=True)
    finally:
        # Remove only this function's verified staging directory, never a revision.
        if (
            staging.exists() and not staging.is_symlink()
            and staging.resolve().parent == pilot_root.resolve()
            and staging.name.startswith("pending-")
        ):
            shutil.rmtree(staging)
    return {**pointer, "sources": len(sources), "norms": len({row["norma_key"] for row in sources})}


def load_active_corpus(pilot_root: Path) -> dict | None:
    return load_corpus_revision(pilot_root)


def load_corpus_revision(pilot_root: Path, revision: str | None = None) -> dict | None:
    """Read an explicitly pinned revision without following a later activation."""
    pointer_path = pilot_root / "current.json"
    if revision is None and not pointer_path.is_file():
        return None
    pointer = {"schema_version": SCHEMA, "corpus_revision": revision} if revision is not None else json.loads(pointer_path.read_text(encoding="utf-8"))
    revision = pointer.get("corpus_revision", "")
    if not DIGEST.fullmatch(revision):
        raise ValueError("Invalid corpus revision")
    folder = pilot_root / "revisions" / revision
    data = (folder / "manifest.json").read_bytes()
    if content_hash(data) != revision:
        raise ValueError("Manifest integrity failed")
    manifest = json.loads(data)
    sources = []
    for item in manifest["sources"]:
        digest = item["pdf_sha256"]
        if not DIGEST.fullmatch(digest):
            raise ValueError("Invalid source hash")
        raw = (folder / "sources" / f"{digest}.json").read_bytes()
        if content_hash(raw) != item["artifact_sha256"]:
            raise ValueError("Source integrity failed")
        sources.append(json.loads(raw))
    bundle = manifest.get("event_bundle", {})
    return {**pointer, "sources": sources, **{key: value for key, value in bundle.items() if key != "schema_version"},
            "events_schema_version": bundle.get("schema_version")}


def has_active_source(pilot_root: Path, digest: str) -> bool:
    """Check bounded pilot membership without loading every extraction into RAM."""
    if not DIGEST.fullmatch(digest):
        return False
    try:
        pointer = json.loads((pilot_root / "current.json").read_text(encoding="utf-8"))
        revision = pointer["corpus_revision"]
        if not DIGEST.fullmatch(revision):
            return False
        raw = (pilot_root / "revisions" / revision / "manifest.json").read_bytes()
        return content_hash(raw) == revision and any(
            item["pdf_sha256"] == digest for item in json.loads(raw)["sources"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def resolve_pilot_query(question: str, sources: list[dict], *, context_keys: tuple[str, ...] = ()) -> dict:
    """Exact typed/alias resolution precedes similarity; unresolved items stay local."""
    from src.processing.document_metadata import normalize_document_number
    from src.processing.normative_query import classify_normative_query, requested_edition_scope
    from src.processing.normative_reference import (
        parse_normative_reference_query,
        parse_normative_references,
    )

    def fold(text):
        text = text.casefold().translate(str.maketrans({"º": "", "ª": "", "°": ""}))
        return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))

    expanded = fold(question)
    aliases = {}
    for source in sources:
        for alias in source.get("aliases", []):
            aliases.setdefault(fold(alias), set()).add(source["norma_key"])
    ambiguous_aliases = []
    for alias, keys in sorted(aliases.items(), key=lambda item: -len(item[0])):
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
        if not re.search(pattern, expanded):
            continue
        if len(keys) != 1:
            ambiguous_aliases.append({"reference": alias, "candidates": sorted(keys)})
            continue
        key = next(iter(keys))
        _jurisdiction, kind, number, year = key.split("|")
        expanded = re.sub(pattern, f"{kind.replace('_', ' ')} {number}/{year}", expanded)
    references = list(parse_normative_references(expanded))
    if not references:
        bare = parse_normative_reference_query(expanded)
        if bare:
            references = [bare]
    if not references and context_keys:
        keys = set(context_keys)
        if len(keys) == 1:
            _jurisdiction, kind, number, year = next(iter(keys)).split("|")
            expanded += f" {kind.replace('_', ' ')} {number}/{year}"
            references = list(parse_normative_references(expanded))
    edition_identity, edition_year = requested_edition_scope(expanded, references)
    groups = []
    for reference in references:
        matches = [source for source in sources if (
            (not reference.type_key or source["identity"]["tipo"] == reference.type_key)
            and normalize_document_number(source["identity"]["numero"]) == normalize_document_number(reference.number)
            and (reference.year is None or source["identity"]["ano"] == reference.year)
        )]
        wanted_edition = edition_year if reference.identity == edition_identity else None
        if wanted_edition is not None:
            matches = [source for source in matches if source.get("edition_year") == wanted_edition]
        keys = sorted({source["norma_key"] for source in matches})
        groups.append({
            "reference": reference.identity, "norma_keys": keys,
            "source_hashes": [source["pdf_sha256"] for source in matches],
            "requested_edition_year": wanted_edition,
            "status": "ambiguous" if len(keys) > 1 else "resolved" if keys else "not_found",
        })
    return {
        "retrieval_question": expanded, "intent": classify_normative_query(expanded).kind,
        "references": groups, "ambiguous_aliases": ambiguous_aliases,
        "status": "ambiguous" if ambiguous_aliases or any(item["status"] == "ambiguous" for item in groups)
        else "resolved" if groups and all(item["status"] == "resolved" for item in groups) else "partial" if groups else "thematic",
    }
