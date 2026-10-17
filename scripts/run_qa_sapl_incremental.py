"""Run one explicitly bounded SAPL metadata page against the isolated QA DB."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _validate_checkpoint_page(*, checkpoint, page: dict, client, limit: int) -> list[dict]:
    """Return one exact checkpoint page or refuse before any write."""
    cursor_url = str(checkpoint.last_cursor_url or "")
    if not cursor_url or checkpoint.last_cursor < 1:
        raise SystemExit("QA replay refused: no partial checkpoint URL/cursor exists.")
    safe_url = client.validate_pagination_url(cursor_url)
    query = parse_qs(urlparse(safe_url).query)
    try:
        page_number = int(query.get("page", [""])[0])
        page_start = int((page.get("_jurix_pagination") or {})["start_index"]) - 1
        page_end = int((page.get("_jurix_pagination") or {})["end_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("QA replay refused: checkpoint page metadata is incomplete.") from exc

    records = page.get("results")
    if (
        query.get("tipo") != ["1"]
        or query.get("ano") != ["2026"]
        or page_number != checkpoint.last_cursor // limit + 1
        or page_start != checkpoint.last_cursor
        or page_end - page_start > limit
        or not isinstance(records, list)
        or not records
        or len(records) != page_end - page_start
        or any(
            not isinstance(item, dict)
            or item.get("ano") != 2026
            or str(item.get("tipo")) != "1"
            or item.get("id") is None
            for item in records
        )
    ):
        raise SystemExit("QA replay refused: fetched page does not match the exact checkpoint scope.")
    return records


def _validate_existing_replay_anchors(Norma, records: list[dict]) -> int:
    """Reject conflicts with existing rows and return the matching row count.

    A restored QA database can retain the exact partial cursor while its page
    rows are absent. The caller validates the cursor URL and complete page
    scope before this check, so zero local rows is safe to replay through the
    idempotent SAPL-ID upsert. Any rows that do exist must still be pending and
    match the upstream identity exactly.
    """
    ids = [int(item["id"]) for item in records]
    if len(ids) != len(set(ids)):
        raise SystemExit("QA replay refused: fetched page contains duplicate SAPL IDs.")
    existing = {
        row.sapl_id: row
        for row in Norma.objects.filter(sapl_id__in=ids).only(
            "sapl_id", "numero", "ano", "status", "pdf_path", "texto_consolidado"
        )
    }
    by_id = {int(item["id"]): item for item in records}
    for sapl_id, row in existing.items():
        source = by_id[sapl_id]
        if (
            row.status != "pending"
            or row.pdf_path
            or row.texto_consolidado
            or str(row.numero) != str(source.get("numero") or "")
            or row.ano != source.get("ano")
        ):
            raise SystemExit("QA replay refused: an existing row is not a matching pending metadata row.")
    return len(existing)


def main() -> int:
    expected = {
        "JURIX_QA_ONLY": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
        "DATABASE_URL": "postgresql://jurix_audit:audit-only-local-fixture@127.0.0.1:55432/jurix_audit",
        "REDIS_URL": "redis://127.0.0.1:16380/0",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise SystemExit("Refusing SAPL sync outside the dedicated normative QA environment.")
    normal_run = sys.argv[1:] == [
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "1"
    ]
    metadata_only_run = sys.argv[1:] == [
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "4",
        "--metadata-only",
    ]
    repair_run = sys.argv[1:] == [
        "--repair-checkpoint-page", "--tipo", "1", "--ano", "2026", "--limit", "10"
    ]
    if not normal_run and not metadata_only_run and not repair_run:
        raise SystemExit("Only one bounded SAPL 2026 type-1 QA page or exact-checkpoint replay is allowed.")

    os.environ["SAPL_INCREMENTAL_MAX_PAGES"] = "4" if metadata_only_run else "1"
    os.environ["SAPL_INCREMENTAL_OVERLAP_PAGES"] = "3"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import django

    django.setup()

    from src.apps.ingestion.sapl_sync import _process_payload, run_incremental_sync

    if repair_run:
        from src.apps.ingestion.sapl_sync import _scope_fingerprint
        from src.apps.legislation.models import Norma
        from src.apps.operations.models import SaplSyncState
        from src.clients.sapl.sapl_client import SaplAPIClient

        checkpoint = SaplSyncState.objects.filter(
            source="sapl", filter_fingerprint=_scope_fingerprint("1", 2026)
        ).first()
        if checkpoint is None:
            raise SystemExit("QA replay refused: no SAPL checkpoint exists for type 1/year 2026.")
        client = SaplAPIClient()
        try:
            page_url = client.validate_pagination_url(checkpoint.last_cursor_url)
            page = client._make_request_url(page_url)
            records = _validate_checkpoint_page(
                checkpoint=checkpoint, page=page, client=client, limit=10
            )
            anchored_rows = _validate_existing_replay_anchors(Norma, records)
            for item in records:
                _process_payload(item, client=client)
        finally:
            client.close()
        print(json.dumps({"replayed_metadata_rows": len(records), "existing_rows_anchored": anchored_rows, "pdf_downloads": 0, "checkpoint_advanced": False}, sort_keys=True))
        return 0

    result = run_incremental_sync(
        limit=10,
        tipo="1",
        ano=2026,
        fingerprint_pdfs=not metadata_only_run,
    )
    summary = {
        key: result.get(key)
        for key in (
            "success", "partial", "fetched", "changed", "unchanged", "failed",
            "pages", "cursor_start", "cursor_end", "safe_stop", "unchanged_pages",
        )
    }
    if metadata_only_run:
        summary["metadata_only"] = True
        summary["pdf_fingerprints"] = False
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("fetched", 0) > 0 and result.get("failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
