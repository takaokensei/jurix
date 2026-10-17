"""Stage the official LC 55/2004 original as a pending isolated-QA candidate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import fitz
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.ingestion.archive_import import _storage_root
from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.document_metadata import build_normative_identity

SOURCE_URL = "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf"
EXPECTED_FILENAME = "lc55-original-2004.pdf"
EXPECTED_SHA256 = "f4065608d85c99d72a02048fdce5c8072740c070308253dae1fcf9f8454093af"
MAX_PDF_BYTES = 5 * 1024 * 1024
EXPECTED_PAGE_COUNT = 34


def _validated_pdf(path: Path) -> tuple[Path, int, str]:
    qa_root = Path(settings.QA_ROOT).resolve()
    evidence_root = (qa_root / "evidence" / "lc55-2004").resolve()
    resolved = path.resolve(strict=True)
    if not evidence_root.is_dir() or not resolved.is_relative_to(evidence_root):
        raise ValueError("PDF deve estar no diretório de evidências QA da LC 55/2004")
    if resolved.name != EXPECTED_FILENAME or not resolved.is_file():
        raise ValueError("PDF não corresponde ao original oficial autorizado")
    size = resolved.stat().st_size
    if size < 8 or size > MAX_PDF_BYTES:
        raise ValueError("tamanho do PDF fora do limite QA")
    with resolved.open("rb") as stream:
        if not stream.read(8).startswith(b"%PDF-"):
            raise ValueError("arquivo não tem assinatura PDF válida")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    content_hash = digest.hexdigest()
    if content_hash != EXPECTED_SHA256:
        raise ValueError("SHA-256 não corresponde ao PDF oficial conferido")
    with fitz.open(resolved) as pdf:
        page_count = len(pdf)
    if page_count != EXPECTED_PAGE_COUNT:
        raise ValueError("quantidade de páginas não corresponde ao original conferido")
    return resolved, page_count, content_hash


def stage_lc55_original_candidate(*, pdf_path: Path, apply: bool = False) -> dict:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE")
        != "config.settings_normative_container_qa"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no container QA normativo isolado")

    source_path, page_count, content_hash = _validated_pdf(Path(pdf_path))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei complementar",
        series="municipal_lc",
        number="55",
        year=2004,
    )
    source_fingerprint = hashlib.sha256(f"{SOURCE_URL}\0{content_hash}".encode()).hexdigest()
    document_key = hashlib.sha256(f"bvn-original\0{source_fingerprint}".encode()).hexdigest()
    if not identity.identity_key:
        raise ValueError("identidade candidata interna inválida")

    if not apply:
        return {
            "mode": "dry-run",
            "source_url": SOURCE_URL,
            "content_sha256": content_hash,
            "size_bytes": source_path.stat().st_size,
            "page_count": page_count,
            "identity_status": "candidate",
            "edition_status": "original",
            "document_role": "original",
            "will_create_norma": False,
            "will_extract_text": False,
            "will_accept_text": False,
        }

    archive_root = _storage_root()
    destination = (
        archive_root / "sha256" / content_hash[:2] / content_hash[2:4] / f"{content_hash}.pdf"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != content_hash:
            raise ValueError("blob content-addressed existente não confere")
        copied = False
    else:
        temporary = destination.with_suffix(".pdf.part")
        try:
            with source_path.open("rb") as source, temporary.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != content_hash:
                raise ValueError("hash do PDF mudou durante o staging")
            try:
                os.link(temporary, destination)
                copied = True
            except FileExistsError:
                if hashlib.sha256(destination.read_bytes()).hexdigest() != content_hash:
                    raise ValueError("colisão no storage content-addressed") from None
                copied = False
        finally:
            temporary.unlink(missing_ok=True)

    metadata = {
        "identity_candidate": identity.identity_json,
        "identity_key": identity.identity_key,
        "identity_status": "candidate",
        "source_provenance": {
            "kind": "municipal_library",
            "unit": "Biblioteca Virtual do Natal",
            "official_url": SOURCE_URL,
            "retrieved_at": timezone.now().isoformat(),
            "content_sha256": content_hash,
        },
        "edition_candidate": {
            "kind": "original",
            "date": "2004-01-27",
            "date_basis": ["official document heading", "publication note in PDF"],
            "review_status": "unreviewed",
        },
    }
    with transaction.atomic():
        document, created = DocumentoNormativo.objects.get_or_create(
            document_key=document_key,
            defaults={
                "source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
                "source_ref": f"municipal_library:{source_fingerprint}",
                "original_filename": EXPECTED_FILENAME,
                "role": DocumentoNormativo.Role.ORIGINAL,
                "storage_key": destination.relative_to(archive_root).as_posix(),
                "size_bytes": source_path.stat().st_size,
                "content_sha256": content_hash,
                "official_url": SOURCE_URL,
                "collected_at": timezone.now(),
                "metadata_json": metadata,
                "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
                "review_status": DocumentoNormativo.ReviewStatus.PENDING,
            },
        )
        if (
            document.content_sha256 != content_hash
            or document.norma_id is not None
            or document.accepted_extraction_id is not None
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
            or document.role != DocumentoNormativo.Role.ORIGINAL
        ):
            raise ValueError("registro existente não corresponde a um original pendente íntegro")

    return {
        "mode": "applied",
        "document_id": str(document.public_id),
        "created": created,
        "blob_copied": copied,
        "source_url": SOURCE_URL,
        "content_sha256": content_hash,
        "page_count": page_count,
        "review_status": document.review_status,
        "document_role": document.role,
        "norma_linked": document.norma_id is not None,
        "text_accepted": document.accepted_extraction_id is not None,
        "will_create_norma": False,
        "will_extract_text": False,
        "will_accept_text": False,
    }


class Command(BaseCommand):
    help = "Stage the verified original LC 55/2004 PDF as a pending isolated-QA candidate."

    def add_arguments(self, parser):
        parser.add_argument("--pdf-path", required=True, type=Path)
        parser.add_argument("--apply", action="store_true", help="Persist one pending QA candidate.")

    def handle(self, *args, **options):
        try:
            result = stage_lc55_original_candidate(
                pdf_path=options["pdf_path"], apply=options["apply"]
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
