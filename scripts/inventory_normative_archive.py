"""Create a read-only JSONL inventory of the received normative archive."""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.processing.archive_inventory import inventory_archive  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    qa_root_raw = os.environ.get("JURIX_QA_ROOT", "")
    if not qa_root_raw or os.environ.get("JURIX_QA_ONLY") != "1":
        parser.error("JURIX_QA_ONLY and JURIX_QA_ROOT are required")
    qa_root = Path(qa_root_raw).resolve()
    output = args.output.resolve()
    if not output.is_relative_to(qa_root) or output == qa_root:
        parser.error("output must be inside the isolated QA root")

    try:
        summary = inventory_archive(args.archive, output)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Inventory failed safely: {exc}", file=sys.stderr)
        return 2
    console_summary = dict(summary)
    for key in (
        "exact_content_duplicate_groups",
        "case_insensitive_name_collision_groups",
        "potential_filename_identity_collision_groups",
        "flagged_entries",
        "unhashed_pdf_entries",
    ):
        console_summary[f"{key}_count"] = len(console_summary.pop(key))
    print(json.dumps(console_summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
