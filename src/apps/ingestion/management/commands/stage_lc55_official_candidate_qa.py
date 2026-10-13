"""Stage the official SEMURB LC 55/2004 PDF as an unreviewed QA candidate."""

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

SOURCE_URL = (
    "https://natal.rn.gov.br/storage/app/media/semurb/legislacao/"
    "35_Codigo_Obras_Atualizado_Julho_2019.pdf"
)
EXPECTED_FILENAME = "lc55-codigo-obras-consolidado-julho-2019.pdf"
MAX_PDF_BYTES = 25 * 1024 * 1024
EDITION_DATE = "2019-07"


def _validated_pdf(path: Path) -> tuple[Path, int, str]:
    qa_root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    evidence_root = (qa_root / "evidence" / "lc55-2004").resolve()
    resolved = path.expanduser().resolve(strict=True)
    if not evidence_root.is_dir() or not resolved.is_relative_to(evidence_root):
        raise ValueError("PDF deve estar no diretório de evidências QA da LC 55/2004")
    if resolved.name != EXPECTED_FILENAME or not resolved.is_file():
        raise ValueError("PDF não corresponde ao candidato municipal autorizado")
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
    with fitz.open(resolved) as pdf:
        page_count = len(pdf)
    if not 1 <= page_count <= 200:
        raise ValueError("quantidade de páginas fora do limite de processamento QA")
    return resolved, page_count, digest.hexdigest()


def stage_lc55_official_candidate(*, pdf_path: Path, apply: bool = False) -> dict:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no ambiente QA normativo isolado")

    source_path, page_count, content_hash = _validated_pdf(Path(pdf_path))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei complementar",
        series="municipal_lc",
        number="55",
        year=2004,
    )
    source_fingerprint = hashlib.sha256(f"{SOURCE_URL}\0{content_hash}".encode()).hexdigest()
    document_key = hashlib.sha256(f"municipal-repository\0{source_fingerprint}".encode()).hexdigest()
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
            "edition_status": "consolidated_copy",
            "edition_date": EDITION_DATE,
            "will_create_norma": False,
            "will_extract_text": False,
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
            "kind": "municipal_repository",
            "unit": "SEMURB/Natal",
            "official_url": SOURCE_URL,
            "retrieved_at": timezone.now().isoformat(),
            "content_sha256": content_hash,
        },
        "edition_candidate": {
            "kind": "consolidated_copy",
            "as_of": EDITION_DATE,
            "date_basis": ["official repository filename"],
            "review_status": "unreviewed",
        },
    }
    with transaction.atomic():
        document, created = DocumentoNormativo.objects.get_or_create(
            document_key=document_key,
            defaults={
                "source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
                "source_ref": f"municipal_repository:{source_fingerprint}",
                "original_filename": EXPECTED_FILENAME,
                "role": DocumentoNormativo.Role.UNDETERMINED,
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
        ):
            raise ValueError("registro existente não corresponde a um candidato pendente íntegro")

    return {
        "mode": "applied",
        "document_id": str(document.public_id),
        "created": created,
        "blob_copied": copied,
        "source_url": SOURCE_URL,
        "content_sha256": content_hash,
        "page_count": page_count,
        "review_status": document.review_status,
        "norma_linked": document.norma_id is not None,
        "text_accepted": document.accepted_extraction_id is not None,
        "will_create_norma": False,
        "will_extract_text": False,
    }


class Command(BaseCommand):
    help = "Stage the official municipal LC 55/2004 PDF as a pending isolated-QA candidate."

    def add_arguments(self, parser):
        parser.add_argument("--pdf-path", required=True, type=Path)
        parser.add_argument("--apply", action="store_true", help="Persist one pending QA candidate.")

    def handle(self, *args, **options):
        try:
            result = stage_lc55_official_candidate(
                pdf_path=options["pdf_path"], apply=options["apply"]
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
