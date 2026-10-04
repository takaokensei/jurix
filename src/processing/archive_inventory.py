"""Safe, read-only inventory for a received ZIP of normative documents."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from src.processing.document_metadata import normalize_document_number, parse_filename_metadata

SCHEMA_VERSION = 1
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class InventoryPolicy:
    max_entries: int = 50_000
    max_pdf_bytes: int = 128 * 1024 * 1024
    max_total_uncompressed_bytes: int = 8 * 1024 * 1024 * 1024
    max_compression_ratio: float = 500.0


DEFAULT_POLICY = InventoryPolicy()


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return sha256_stream(source)


def _normalized_entry_name(name: str) -> str:
    return name.replace("\\", "/")


def _unsafe_path(name: str) -> bool:
    normalized = _normalized_entry_name(name)
    return (
        not normalized
        or normalized.startswith("/")
        or normalized.startswith("//")
        or bool(re.match(r"^[a-zA-Z]:", normalized))
        or "\x00" in normalized
        or any(part == ".." for part in normalized.split("/"))
    )


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    unix_mode = info.external_attr >> 16
    return stat.S_IFMT(unix_mode) == stat.S_IFLNK


def _extension(name: str) -> str:
    suffix = Path(name.replace("\\", "/")).suffix.lower()
    return suffix or "[sem_extensao]"


def _entry_flags(info: zipfile.ZipInfo, policy: InventoryPolicy) -> list[str]:
    flags = []
    if _unsafe_path(info.filename):
        flags.append("unsafe_path")
    if _is_symlink(info):
        flags.append("symlink")
    if info.flag_bits & 0x1:
        flags.append("encrypted")
    if info.file_size > policy.max_pdf_bytes and _extension(info.filename) == ".pdf":
        flags.append("pdf_size_limit")
    if info.file_size and not info.compress_size:
        flags.append("invalid_compressed_size")
    elif info.compress_size and info.file_size / info.compress_size > policy.max_compression_ratio:
        flags.append("compression_ratio_limit")
    return flags


def _hash_pdf(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    with archive.open(info, "r") as source:
        return sha256_stream(source)


def _entry_record(
    info: zipfile.ZipInfo,
    index: int,
    archive_hash: str,
    content_hash: str | None,
    hash_status: str,
    flags: list[str],
) -> dict:
    filename_metadata = parse_filename_metadata(info.filename)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "entry",
        "archive_sha256": archive_hash,
        "entry_index": index,
        "entry_name": info.filename,
        "normalized_entry_name": _normalized_entry_name(info.filename),
        "extension": _extension(info.filename),
        "compressed_bytes": info.compress_size,
        "uncompressed_bytes": info.file_size,
        "content_sha256": content_hash,
        "hash_status": hash_status,
        "filename_metadata": filename_metadata.as_dict(),
        "flags": flags,
    }


def _summarize(records: list[dict], archive_hash: str, *, complete: bool) -> dict:
    extensions = Counter(record["extension"] for record in records)
    type_counts = Counter(
        record["filename_metadata"]["type_key"] or "unknown"
        for record in records
        if record["extension"] == ".pdf"
    )
    role_counts = Counter(
        record["filename_metadata"]["role"] for record in records if record["extension"] == ".pdf"
    )
    by_hash: dict[str, list[int]] = defaultdict(list)
    by_identity: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    for record in records:
        if record["content_sha256"]:
            by_hash[record["content_sha256"]].append(record["entry_index"])
        name_key = record["normalized_entry_name"].casefold()
        by_name[name_key].append(record["entry_index"])
        metadata = record["filename_metadata"]
        if metadata["type_key"] and metadata["series"] and metadata["number"]:
            # This is a filename-level candidate, not a confirmed legal identity.
            year_candidate = next(
                (
                    candidate["value"][:4]
                    for candidate in metadata["candidates"]
                    if candidate["field"] == "unclassified_filename_date"
                ),
                "unknown_year",
            )
            by_identity[
                (
                    metadata["type_key"],
                    metadata["series"],
                    f"{normalize_document_number(metadata['number'])}|{year_candidate}",
                )
            ].append(record["entry_index"])
    duplicates = [sorted(indices) for indices in by_hash.values() if len(indices) > 1]
    name_collisions = [sorted(indices) for indices in by_name.values() if len(indices) > 1]
    identity_collisions = [sorted(indices) for indices in by_identity.values() if len(indices) > 1]
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "summary",
        "archive_sha256": archive_hash,
        "complete": complete,
        "entry_count": len(records),
        "extension_counts": dict(sorted(extensions.items())),
        "filename_type_counts": dict(sorted(type_counts.items())),
        "filename_role_counts": dict(sorted(role_counts.items())),
        "exact_content_duplicate_groups": duplicates,
        "case_insensitive_name_collision_groups": name_collisions,
        "potential_filename_identity_collision_groups": identity_collisions,
        "flagged_entries": [
            {"entry_index": record["entry_index"], "flags": record["flags"]}
            for record in records
            if record["flags"]
        ],
        "unhashed_pdf_entries": [
            record["entry_index"]
            for record in records
            if record["extension"] == ".pdf" and record["hash_status"] != "hashed"
        ],
    }


def inventory_archive(
    archive_path: str | Path,
    output_path: str | Path,
    *,
    policy: InventoryPolicy = DEFAULT_POLICY,
) -> dict:
    """Write deterministic JSONL inventory; refuse to overwrite prior evidence."""
    archive_path = Path(archive_path)
    output_path = Path(output_path)
    if not archive_path.is_file():
        raise FileNotFoundError("archive input is not a readable file")
    if output_path.exists():
        raise FileExistsError("refusing to overwrite an existing inventory manifest")

    archive_hash = sha256_file(archive_path)
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > policy.max_entries:
            raise ValueError("archive entry count exceeds the configured safety limit")

        records: list[dict] = []
        remaining_budget = policy.max_total_uncompressed_bytes
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as output:
            complete = True
            for index, info in enumerate(infos):
                flags = _entry_flags(info, policy)
                content_hash = None
                hash_status = "not_selected"
                if _extension(info.filename) == ".pdf":
                    if flags:
                        hash_status = "blocked_by_entry_flags"
                        complete = False
                    elif info.file_size > remaining_budget:
                        flags.append("archive_batch_size_limit")
                        hash_status = "blocked_by_batch_limit"
                        complete = False
                    else:
                        remaining_budget -= info.file_size
                        try:
                            content_hash = _hash_pdf(archive, info)
                            hash_status = "hashed"
                        except (OSError, RuntimeError, zipfile.BadZipFile, EOFError):
                            flags.append("entry_read_error")
                            hash_status = "read_error"
                            complete = False
                record = _entry_record(info, index, archive_hash, content_hash, hash_status, flags)
                records.append(record)
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            summary = _summarize(records, archive_hash, complete=complete)
            output.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    return summary
