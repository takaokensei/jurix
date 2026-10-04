"""Inventory-verified, resumable import into the isolated QA staging area."""

from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.archive_import import ArchiveImportError, import_archive


class Command(BaseCommand):
    help = "Stage up to 40 inventoried PDFs in isolated QA; default mode is dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True, type=Path)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--resume")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        qa_root = Path(os.environ.get("JURIX_QA_ROOT", "")).resolve()
        manifest_path = options["manifest"].resolve()
        if not qa_root.is_dir() or os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("JURIX_QA_ONLY e JURIX_QA_ROOT são obrigatórios")
        if not manifest_path.is_relative_to(qa_root):
            raise CommandError("manifesto deve estar dentro da raiz QA isolada")
        try:
            result = import_archive(
                archive_path=options["archive"], manifest_path=manifest_path,
                apply=options["apply"], limit=options["limit"],
                batch_size=options["batch_size"], resume=options["resume"],
            )
        except (ArchiveImportError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
