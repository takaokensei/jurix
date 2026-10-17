"""Restore only missing, hash-verified archive blobs in the isolated QA store."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import OuterRef, Subquery

from src.apps.ingestion.archive_import import (
    ArchiveImportError,
    _copy_verified,
    _manifest_records,
    _safe_entry_name,
    _storage_root,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.archive_inventory import sha256_file

MAX_RESTORE_BLOBS = 10
MAX_RESTORE_BYTES = 256 * 1024 * 1024


def _entry_sha256(archive: zipfile.ZipFile, row: dict) -> str:
    infos = archive.infolist()
    index = row.get("entry_index")
    if type(index) is not int or index < 0 or index >= len(infos):
        raise ArchiveImportError("índice do inventário não corresponde ao ZIP")
    info = infos[index]
    if info.filename != row.get("entry_name"):
        raise ArchiveImportError("membro do inventário não corresponde ao ZIP")
    if not _safe_entry_name(info.filename):
        raise ArchiveImportError("membro do inventário possui caminho inseguro")
    if info.file_size != row.get("uncompressed_bytes") or info.file_size > 128 * 1024 * 1024:
        raise ArchiveImportError("tamanho do membro excede ou diverge do limite do inventário")
    digest = hashlib.sha256()
    with archive.open(info, "r") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Restaura blobs ausentes do ZIP original para o storage isolado QA, sem alterar o banco."

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True, type=Path)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--limit", type=int, default=MAX_RESTORE_BLOBS)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        qa_root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
        temp_root = Path(__import__("tempfile").gettempdir()).resolve()
        manifest_path = options["manifest"].resolve()
        archive_path = options["archive"].resolve()
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
            or not qa_root.is_dir()
            or not qa_root.is_relative_to(temp_root)
            or not manifest_path.is_relative_to(qa_root)
            or manifest_path == qa_root
            or not archive_path.is_file()
            or archive_path.is_relative_to(qa_root)
        ):
            raise CommandError("Restauração exige ZIP externo e inventário dentro do QA isolado.")
        limit = options["limit"]
        if not 1 <= limit <= MAX_RESTORE_BLOBS:
            raise CommandError(f"--limit deve estar entre 1 e {MAX_RESTORE_BLOBS} blobs.")

        try:
            archive_hash = sha256_file(archive_path)
            rows, _manifest_hash = _manifest_records(manifest_path, archive_hash)
            by_hash = {row["content_sha256"]: row for row in rows}
            archive_root = (_storage_root()).resolve()
            latest = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
                "-created_at", "-pk"
            )
            pending = DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                accepted_extraction__isnull=True,
            ).annotate(
                latest_extraction_status=Subquery(latest.values("status")[:1])
            ).filter(
                latest_extraction_status__in=(
                    ExtracaoDocumento.Status.PARTIAL,
                    ExtracaoDocumento.Status.UNREADABLE,
                )
            ).exclude(storage_key="").exclude(content_sha256="")
            missing_documents = []
            for storage_key, digest in pending.values_list("storage_key", "content_sha256").iterator(
                chunk_size=250
            ):
                target = (archive_root / storage_key).resolve()
                if not target.is_relative_to(archive_root):
                    raise CommandError("Storage key fora da raiz QA; nenhuma restauração foi feita.")
                expected_target = (
                    archive_root / "sha256" / digest[:2] / digest[2:4] / f"{digest}.pdf"
                ).resolve()
                if target != expected_target:
                    raise CommandError("Storage key não corresponde ao hash content-addressed.")
                if target.exists():
                    if not target.is_file() or sha256_file(target) != digest:
                        raise CommandError("Blob existente diverge do hash QA; nenhuma restauração foi feita.")
                    continue
                missing_documents.append((storage_key, digest, by_hash.get(digest)))

            unique_rows = {}
            for storage_key, digest, row in missing_documents:
                if row is not None:
                    entry, storage_keys = unique_rows.setdefault(digest, (row, set()))
                    storage_keys.add(storage_key)
            selected = list(unique_rows.items())[:limit]
            selected_bytes = sum(
                int(row.get("uncompressed_bytes", 0)) for _digest, (row, _keys) in selected
            )
            if selected_bytes > MAX_RESTORE_BYTES:
                raise CommandError("Lote excede o orçamento de 256 MiB; nenhum blob foi restaurado.")
            unlisted_count = sum(row is None for _, _, row in missing_documents)
            with zipfile.ZipFile(archive_path, "r") as archive:
                for digest, (row, _storage_keys) in selected:
                    if _entry_sha256(archive, row) != digest:
                        raise CommandError("Hash do membro do ZIP diverge do inventário.")
                if options["apply"]:
                    restored = 0
                    for _digest, (row, storage_keys) in selected:
                        path, copied = _copy_verified(archive, row)
                        if any(path != (archive_root / key).resolve() for key in storage_keys):
                            raise CommandError("Storage key não corresponde ao caminho content-addressed.")
                        restored += int(copied)
                else:
                    restored = 0
        except (ArchiveImportError, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps({
            "mode": "apply" if options["apply"] else "dry-run",
            "pending_documents_with_missing_blobs": len(missing_documents),
            "unique_missing_blobs_in_inventory": len(unique_rows),
            "unique_missing_blobs_selected": len(selected),
            "selected_uncompressed_bytes": selected_bytes,
            "missing_document_hashes_absent_from_inventory": unlisted_count,
            "restored_blob_count": restored,
            "database_rows_changed": 0,
            "extractions_created": 0,
            "documents_accepted_or_promoted": 0,
            "content_or_identifiers_included": False,
        }, ensure_ascii=False, sort_keys=True))
