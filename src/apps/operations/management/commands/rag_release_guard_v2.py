"""
Validate a JSONL stream of RAG result contracts.

This is intentionally independent from the live RAG API. It lets CI or an
operator feed recorded requests/responses into the same deterministic release
policy used to decide whether an artifact is safe to publish or cache.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.processing.rag_release_policy import ReleaseThresholds, evaluate_batch


class Command(BaseCommand):
    help = "Validate recorded RAG response contracts against release thresholds."

    def add_arguments(self, parser):
        parser.add_argument("jsonl", type=Path)
        parser.add_argument("--min-score", type=float, default=1.0)
        parser.add_argument("--min-source-recall", type=float, default=1.0)
        parser.add_argument("--min-citation-precision", type=float, default=1.0)
        parser.add_argument("--min-citation-recall", type=float, default=1.0)
        parser.add_argument("--max-answer-chars", type=int, default=24000)
        parser.add_argument("--json-output", type=Path)

    def handle(self, *args, **options):
        path: Path = options["jsonl"]
        if not path.is_file():
            raise CommandError(f"JSONL not found: {path}")

        rows = []
        with path.open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise CommandError(f"Invalid JSON at line {line_no}: {exc}") from exc
                if not isinstance(value, dict):
                    raise CommandError(f"Line {line_no} is not an object.")
                rows.append(value)

        thresholds = ReleaseThresholds(
            min_grounded_score=options["min_score"],
            min_source_recall=options["min_source_recall"],
            min_citation_precision=options["min_citation_precision"],
            min_citation_recall=options["min_citation_recall"],
            max_answer_chars=options["max_answer_chars"],
        )
        report = evaluate_batch(rows, thresholds=thresholds)

        if options["json_output"]:
            options["json_output"].write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if report["rejected"]:
            raise SystemExit(2)
