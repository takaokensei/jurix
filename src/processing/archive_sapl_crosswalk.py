"""Conservative filename-to-SAPL identity crosswalk helpers."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import PurePath
from typing import Any

from src.processing.document_metadata import normalize_document_number, parse_filename_metadata
from src.processing.normative_reference import canonical_type

_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_NUMBER = re.compile(r"^\d[\d.]*[A-Za-z]?(?:-[A-Za-z0-9]+)?$")


def archive_identity_candidate(filename: str) -> tuple[str, str, int] | None:
    """Return a candidate key only when type, number and exactly one year are present.

    The year is still only a filename observation. Callers must never promote it
    to a publication date or a confirmed legal identity without review.
    """
    parsed = parse_filename_metadata(filename)
    if not parsed.type_key:
        return None

    years: set[int] = set()
    for candidate in parsed.candidates:
        if candidate.field == "unclassified_filename_date":
            try:
                years.add(date.fromisoformat(candidate.value).year)
            except ValueError:
                continue
    basename = PurePath(str(filename).replace("\\", "/")).name
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    tokens = [token for token in re.split(r"[_\s]+", stem) if token]
    numeric_tokens = []
    for segment in tokens:
        token = segment.strip(".,()[]{}")
        if _YEAR.fullmatch(token):
            years.add(int(token))
        elif re.fullmatch(r"\d{8}", token):
            try:
                years.add(date.fromisoformat(f"{token[:4]}-{token[4:6]}-{token[6:8]}").year)
            except ValueError:
                pass
        elif _NUMBER.fullmatch(token) and not re.fullmatch(r"\d{4}", token):
            numeric_tokens.append(token)
    if len(years) != 1:
        return None

    raw_number = parsed.number
    if not raw_number:
        # SAPL names commonly insert "no"/"nº" between type and number;
        # only accept a fallback when exactly one non-date number remains.
        if len(numeric_tokens) != 1:
            return None
        raw_number = numeric_tokens[0]
    number = normalize_document_number(raw_number)
    type_key = canonical_type(parsed.type_key)
    if not number or not type_key:
        return None
    return type_key, number, next(iter(years))


def catalog_identity_candidate(record: dict[str, Any], type_labels: dict[int, str]):
    """Return a SAPL key and whether its publication date is parseable."""
    try:
        type_id = int(record.get("tipo"))
        year = int(record.get("ano"))
    except (TypeError, ValueError):
        return None, False
    type_key = canonical_type(type_labels.get(type_id, ""))
    number = normalize_document_number(record.get("numero"))
    if not type_key or not number or not 1000 <= year <= 9999:
        return None, _parse_publication_date(record.get("data_publicacao")) is not None
    return (type_key, number, year), _parse_publication_date(record.get("data_publicacao")) is not None


def _parse_publication_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def summarize_crosswalk(archive_filenames: list[str], catalog_records, type_labels):
    """Summarize strict identity joins without returning row IDs or source text."""
    archive_by_key: dict[tuple[str, str, int], int] = defaultdict(int)
    archive_identifiable = 0
    archive_year_counts: dict[str, int] = defaultdict(int)
    archive_type_counts: dict[str, int] = defaultdict(int)
    for filename in archive_filenames:
        key = archive_identity_candidate(filename)
        if key:
            archive_identifiable += 1
            archive_by_key[key] += 1
            archive_type_counts[key[0]] += 1
            archive_year_counts[str(key[2])] += 1

    catalog_by_key: dict[tuple[str, str, int], list[bool]] = defaultdict(list)
    catalog_identifiable = 0
    catalog_with_publication_date = 0
    catalog_year_counts: dict[str, int] = defaultdict(int)
    catalog_type_counts: dict[str, int] = defaultdict(int)
    for record in catalog_records:
        key, has_publication_date = catalog_identity_candidate(record, type_labels)
        catalog_with_publication_date += int(has_publication_date)
        if key:
            catalog_type_counts[key[0]] += 1
        try:
            year = int(record.get("ano"))
            catalog_year_counts[str(year)] += 1
        except (TypeError, ValueError):
            pass
        if key:
            catalog_identifiable += 1
            catalog_by_key[key].append(has_publication_date)

    matched_unique = matched_with_date = ambiguous_catalog = ambiguous_archive = 0
    for key, archive_count in archive_by_key.items():
        catalog_matches = catalog_by_key.get(key, [])
        if archive_count > 1 and catalog_matches:
            ambiguous_archive += 1
        if len(catalog_matches) > 1 and archive_count:
            ambiguous_catalog += 1
        if archive_count == 1 and len(catalog_matches) == 1:
            matched_unique += 1
            matched_with_date += int(catalog_matches[0])

    return {
        "archive_pdf_count": len(archive_filenames),
        "archive_with_type_number_year_candidates": archive_identifiable,
        "archive_unique_candidate_identities": len(archive_by_key),
        "archive_candidate_counts_by_act_year": dict(sorted(archive_year_counts.items())),
        "archive_candidate_counts_by_type": dict(sorted(archive_type_counts.items())),
        "catalog_record_count": len(catalog_records),
        "catalog_with_type_number_year": catalog_identifiable,
        "catalog_with_parseable_publication_date": catalog_with_publication_date,
        "catalog_record_counts_by_act_year": dict(sorted(catalog_year_counts.items())),
        "catalog_candidate_counts_by_type": dict(sorted(catalog_type_counts.items())),
        "strict_unique_document_to_catalog_matches": matched_unique,
        "unique_matches_with_sapl_publication_date": matched_with_date,
        "ambiguous_archive_identity_groups": ambiguous_archive,
        "ambiguous_catalog_identity_groups": ambiguous_catalog,
        "unmatched_archive_identity_groups": sum(
            1 for key in archive_by_key if key not in catalog_by_key
        ),
        "filename_dates_are_publication_facts": False,
        "matches_are_reviewed_legal_identities": False,
    }


def rank_archive_candidates_by_publication(archive_rows, catalog_records, type_labels):
    """Return pending one-to-one identity candidates in SAPL publication order.

    ``archive_rows`` must contain ``document_id``, ``public_id``, ``filename``,
    ``storage_key``, ``content_sha256`` and ``size_bytes``. SAPL publication
    dates are ordering evidence only; missing dates fall back to act year and
    normalized number. This function does not confirm identity or legal effect.
    """
    archive_by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in archive_rows:
        key = archive_identity_candidate(str(row.get("filename") or ""))
        if key:
            archive_by_key[key].append(row)

    catalog_by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in catalog_records:
        key, _ = catalog_identity_candidate(record, type_labels)
        if key:
            catalog_by_key[key].append(record)

    ranked = []
    for key, documents in archive_by_key.items():
        records = catalog_by_key.get(key, [])
        if len(documents) != 1 or len(records) != 1:
            continue
        document = documents[0]
        publication_date = _parse_publication_date(records[0].get("data_publicacao"))
        ranked.append(
            {
                "document_id": document["document_id"],
                "public_id": str(document["public_id"]),
                "storage_key": document["storage_key"],
                "content_sha256": document["content_sha256"],
                "size_bytes": int(document["size_bytes"] or 0),
                "publication_date": publication_date.isoformat() if publication_date else None,
                "act_year": key[2],
                "act_number": key[1],
            }
        )

    def sort_key(item):
        # January 1 is a deterministic lower-bound proxy when SAPL has no
        # parseable publication date; the fallback remains explicitly marked.
        candidate_date = _parse_publication_date(item["publication_date"])
        ordering_date = candidate_date or date(item["act_year"], 1, 1)
        number = item["act_number"]
        number_sort = (0, int(number)) if number.isdecimal() else (1, number.casefold())
        return ordering_date, item["act_year"], number_sort, item["public_id"]

    return sorted(ranked, key=sort_key, reverse=True)


def rank_archive_candidates_for_qa_extraction(archive_rows, catalog_records, type_labels):
    """Order every archive PDF for QA extraction without linking unresolved identities.

    Unique filename-to-SAPL matches use SAPL publication date as a queue-priority
    candidate. All other rows fall back to a uniquely parsed filename year/number,
    then to stable public ID. The returned classification is operational metadata,
    not a reviewed publication fact, identity assertion, or legal-effect relation.
    """
    strict_matches = {
        item["public_id"]: item
        for item in rank_archive_candidates_by_publication(
            archive_rows, catalog_records, type_labels
        )
    }
    prioritized = []
    for row in archive_rows:
        public_id = str(row["public_id"])
        strict = strict_matches.get(public_id)
        filename_key = archive_identity_candidate(str(row.get("filename") or ""))
        if strict:
            act_year = strict["act_year"]
            act_number = strict["act_number"]
            publication_date = strict["publication_date"]
            basis = "sapl_publication_date_candidate" if publication_date else "sapl_year_number_fallback"
        elif filename_key:
            _type_key, act_number, act_year = filename_key
            publication_date = None
            basis = "filename_year_number_fallback"
        else:
            act_year = 0
            act_number = ""
            publication_date = None
            basis = "unresolved_stable_public_id"

        candidate_date = _parse_publication_date(publication_date)
        ordering_date = candidate_date or (date(act_year, 1, 1) if act_year else date.min)
        number_sort = (0, int(act_number)) if act_number.isdecimal() else (1, act_number.casefold())
        prioritized.append({
            **row,
            "publication_date_candidate": publication_date,
            "act_year_candidate": act_year or None,
            "act_number_candidate": act_number or None,
            "priority_basis": basis,
            "_sort_key": (ordering_date, act_year, number_sort, public_id),
        })

    prioritized.sort(key=lambda item: item["_sort_key"], reverse=True)
    for item in prioritized:
        item.pop("_sort_key", None)
    return prioritized
