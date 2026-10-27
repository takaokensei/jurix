"""Stage only the SAPL LC 208 PDF, unlinked, when its QA Norma identity conflicts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.ingestion.management.commands.stage_sapl_normative_candidate_qa import (
    _ALLOWED_RECORDS,
    _existing_norma_conflicts,
    _validated_record,
)
from src.apps.ingestion.sapl_document_sync import (
    _matches_fingerprint,
    _sha256_file,
    _storage_root,
    _store_content_addressed_pdf,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.clients.sapl.sapl_client import SaplAPIClient


def _stage_unlinked_sapl_candidate(*, sapl_id: int, apply: bool = False) -> dict:
    """Keep an allowlisted official PDF inspectable without mutating Norma conflicts."""
    database = settings.DATABASES.get("default", {})
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
        or database.get("HOST") != "127.0.0.1"
        or str(database.get("PORT")) != "55432"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no PostgreSQL QA isolado :55432")

    client = SaplAPIClient(timeout=20, max_retries=1)
    try:
        if sapl_id not in {1160, 8823}:
            raise ValueError("somente LC 208/2022 e LC 261/2025 estão autorizadas para staging desacoplado")
        _record, pdf_url, candidate = _validated_record(client, sapl_id)
        identity = candidate["identity"]
        expected = _ALLOWED_RECORDS[sapl_id]
        existing_norma = Norma.objects.filter(sapl_id=sapl_id).first()
        conflicts = _existing_norma_conflicts(
            existing_norma,
            identity=identity,
            expected=expected,
            publication_date=candidate["publication_date"],
            pdf_url=pdf_url,
        ) if existing_norma else []
        if conflicts != ["identity_key"]:
            raise ValueError(
                "candidato desacoplado exige exclusivamente o conflito identity_key já diagnosticado"
            )

        fingerprint = client.fingerprint_pdf(pdf_url)
        if not fingerprint.startswith(("sha256:", "etag:", "last-modified:")):
            raise ValueError("fingerprint remoto SAPL inválido")

        if not apply:
            return {
                "mode": "dry-run",
                "sapl_id": sapl_id,
                "identity_key_candidate": identity.identity_key,
                "identity_conflicts": conflicts,
                "remote_fingerprint_kind": fingerprint.split(":", 1)[0],
                "will_create_unlinked_document_candidate": True,
                "will_link_to_norma": False,
                "will_mutate_existing_norma": False,
                "will_accept_text": False,
                "will_create_consolidation": False,
                "will_enter_rag": False,
            }

        root = _storage_root()
        staging_root = root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"sapl-{sapl_id}-unlinked-", dir=staging_root) as tmp:
            downloaded = Path(tmp) / "candidate.pdf"
            result = client.download_pdf_version(pdf_url, downloaded)
            if not _matches_fingerprint(fingerprint, result):
                raise ValueError("PDF baixado não corresponde ao fingerprint observado no SAPL")
            storage_key, _copied = _store_content_addressed_pdf(
                downloaded, root, result["content_sha256"]
            )

        document_key = hashlib.sha256(
            f"sapl-unlinked-v2:{sapl_id}:{result['content_sha256']}".encode()
        ).hexdigest()
        defaults = {
            "norma": None,
            "source_kind": DocumentoNormativo.SourceKind.SAPL,
            "source_ref": f"sapl-unlinked-v2:{sapl_id}:sha256:{result['content_sha256']}",
            "original_filename": Path(pdf_url.rsplit("/", 1)[-1]).name[:500],
            "role": DocumentoNormativo.Role.UNDETERMINED,
            "storage_key": storage_key,
            "size_bytes": result["size_bytes"],
            "content_sha256": result["content_sha256"],
            "official_url": pdf_url,
            "collected_at": timezone.now(),
            "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
            "metadata_json": {
                "sapl_id": sapl_id,
                "identity_candidate": identity.identity_json,
                "identity_status": "candidate",
                "identity_key": identity.identity_key,
                "identity_key_candidate": identity.identity_key,
                "publication_date_candidate": (
                    candidate["publication_date"].isoformat()
                    if candidate["publication_date"]
                    else None
                ),
                "remote_fingerprint": fingerprint,
                "source_provenance": {
                    "kind": "sapl_norma_pdf",
                    "official_url": pdf_url,
                },
                "candidate_reason": "official_source_unlinked_due_to_identity_conflict",
                "association_status": "identity_conflict_unlinked",
                "identity_conflicts": conflicts,
            },
            "extraction_status": DocumentoNormativo.ExtractionStatus.PENDING,
            "review_status": DocumentoNormativo.ReviewStatus.PENDING,
        }
        with transaction.atomic():
            document, created = DocumentoNormativo.objects.get_or_create(
                document_key=document_key,
                defaults=defaults,
            )
            if (
                document.content_sha256 != result["content_sha256"]
                or document.storage_key != storage_key
                or document.norma_id is not None
                or document.accepted_extraction_id is not None
                or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
            ):
                raise ValueError("candidato existente diverge do documento QA desacoplado esperado")
            if _sha256_file(root / storage_key) != result["content_sha256"]:
                raise ValueError("blob SAPL desacoplado falhou a verificação de integridade")

        return {
            "mode": "applied",
            "document_id": str(document.public_id),
            "created": created,
            "content_sha256": result["content_sha256"],
            "review_status": document.review_status,
            "norma_linked": document.norma_id is not None,
            "text_accepted": document.accepted_extraction_id is not None,
            "identity_conflicts": conflicts,
            "will_enter_rag": False,
        }
    finally:
        client.close()


def stage_lc208_unlinked_candidate(*, apply: bool = False) -> dict:
    """Keep the official LC 208 PDF inspectable without changing its Norma row."""
    return _stage_unlinked_sapl_candidate(sapl_id=1160, apply=apply)


def stage_lc261_unlinked_candidate(*, apply: bool = False) -> dict:
    """Keep the official LC 261 PDF inspectable without changing its Norma row."""
    return _stage_unlinked_sapl_candidate(sapl_id=8823, apply=apply)


class Command(BaseCommand):
    help = "Registra somente a fonte oficial LC 208/2022 como PDF QA não associado."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_lc208_unlinked_candidate(apply=options["apply"])
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
