"""Read-only QA report matching archive filename candidates to the SAPL catalog."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from src.apps.legislation.document_models import DocumentoNormativo
from src.clients.sapl.sapl_client import SaplAPIClient
from src.processing.archive_sapl_crosswalk import summarize_crosswalk


class Command(BaseCommand):
    help = "Conta correspondências candidatas arquivo↔SAPL sem gravar dados."

    def add_arguments(self, parser):
        parser.add_argument("--max-pages", type=int, default=2)
        parser.add_argument("--page-size", type=int, default=100)

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE")
            not in {"config.settings_normative_qa", "config.settings_normative_container_qa"}
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
            or connections["default"].settings_dict.get("NAME") != "jurix_audit"
        ):
            raise CommandError("O crosswalk exige o banco e o perfil QA normativo isolado.")

        max_pages = options["max_pages"]
        page_size = options["page_size"]
        if not 1 <= max_pages <= 100 or not 1 <= page_size <= 100:
            raise CommandError("Use de 1 a 100 páginas e de 1 a 100 registros por página.")

        filenames = list(
            DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE
            ).values_list("original_filename", flat=True)
        )
        if not filenames:
            raise CommandError("Nenhum documento do acervo QA foi encontrado.")

        qa_root = Path(getattr(settings, "QA_ROOT", "")).resolve()
        if not qa_root.is_dir():
            raise CommandError("A raiz temporária QA não está disponível.")
        checkpoint_path = qa_root / "sapl-archive-crosswalk-cursor.json"
        if checkpoint_path.exists():
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError("Checkpoint do crosswalk QA inválido; preservado sem alteração.") from exc
            if checkpoint.get("schema_version") != 1 or not isinstance(checkpoint.get("records"), list):
                raise CommandError("Esquema de checkpoint incompatível; preservado sem alteração.")
        else:
            checkpoint = {
                "schema_version": 1,
                "records": [],
                "next_url": "",
                "offset": 0,
                "pages_scanned": 0,
                "total_entries": None,
                "type_labels": {},
                "complete": False,
            }

        records = checkpoint["records"]
        type_ids = {int(record["tipo"]) for record in records if record.get("tipo") is not None}
        seen_ids = {str(record["id"]) for record in records}
        requested_url = str(checkpoint.get("next_url") or "")
        offset = int(checkpoint.get("offset") or 0)
        total_entries = checkpoint.get("total_entries")
        pages_read = 0
        pages_scanned_start = int(checkpoint.get("pages_scanned") or 0)
        type_labels = {
            int(type_id): str(label)
            for type_id, label in (checkpoint.get("type_labels") or {}).items()
        }
        seen_urls: set[str] = set()
        client = SaplAPIClient()
        logging.getLogger("src.clients.sapl").setLevel(logging.WARNING)

        for _ in range(max_pages):
            page = (
                client._make_request_url(requested_url)
                if requested_url
                else client.fetch_normas_page(limit=page_size, offset=offset)
            )
            results = page.get("results")
            if not isinstance(results, list):
                raise CommandError("Formato de paginação inesperado do SAPL.")
            metadata = page.get("_jurix_pagination") or {}
            total_entries = metadata.get("total_entries", total_entries)
            if not results:
                break

            for record in results:
                identifier = str(record.get("id") or "")
                if not identifier or identifier in seen_ids:
                    raise CommandError("SAPL retornou registro ausente ou repetido; relatório cancelado.")
                seen_ids.add(identifier)
                records.append(
                    {
                        "id": identifier,
                        "tipo": record.get("tipo"),
                        "numero": record.get("numero"),
                        "ano": record.get("ano"),
                        "data_publicacao": record.get("data_publicacao"),
                    }
                )
                try:
                    type_ids.add(int(record.get("tipo")))
                except (TypeError, ValueError):
                    pass

            pages_read += 1
            offset += len(results)
            next_url = page.get("next")
            if not next_url:
                requested_url = ""
                break
            requested_url = client.validate_pagination_url(str(next_url))
            if requested_url in seen_urls:
                raise CommandError("SAPL repetiu a URL de paginação; relatório cancelado.")
            seen_urls.add(requested_url)
            checkpoint.update(
                {
                    "records": records,
                    "next_url": requested_url,
                    "offset": offset,
                    "pages_scanned": pages_scanned_start + pages_read,
                    "total_entries": total_entries,
                    "type_labels": {str(key): value for key, value in type_labels.items()},
                    "complete": False,
                }
            )
            self._save_checkpoint(checkpoint_path, checkpoint)
            time.sleep(0.2)

        type_labels = {}
        for type_id in sorted(type_ids):
            payload = client.fetch_norma_type_by_id(type_id)
            label = str(payload.get("descricao") or payload.get("sigla") or "").strip()
            if label:
                type_labels[type_id] = label
        checkpoint.update(
            {
                "records": records,
                "next_url": requested_url,
                "offset": offset,
                "pages_scanned": pages_scanned_start + pages_read,
                "total_entries": total_entries,
                "type_labels": {str(key): value for key, value in type_labels.items()},
                "complete": not bool(requested_url),
            }
        )
        self._save_checkpoint(checkpoint_path, checkpoint)

        report = summarize_crosswalk(filenames, records, type_labels)
        report.update(
            {
                "mode": "read-only",
                "pages_read": pages_read,
                "pages_scanned_total": checkpoint["pages_scanned"],
                "catalog_total_reported_by_sapl": total_entries,
                "catalog_scan_complete": checkpoint["complete"],
                "checkpoint_written": True,
                "review_or_promotion_performed": False,
                "database_writes_performed": False,
            }
        )
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _save_checkpoint(path: Path, checkpoint: dict) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".sapl-crosswalk-", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(checkpoint, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
