"""Stage the official municipal PDF for Promulgated Law 275/2009 as QA evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

import pymupdf
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.ingestion.archive_import import _storage_root
from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.document_metadata import build_normative_identity

SOURCE_URL = (
    "https://www.natal.rn.gov.br/storage/app/media/semurb/legislacao/leis/"
    "5-lei-promulgada-275-2009-regulamenta-as-calcadas-no-municipio.pdf"
)
EXPECTED_FILENAME = "lei-promulgada-0275-2009-oficial.pdf"
OFFICIAL_FILENAME = "5-lei-promulgada-275-2009-regulamenta-as-calcadas-no-municipio.pdf"
EXPECTED_SHA256 = "29f571d740d56c51b47872a35ab1ba3d6894c682f71d59def9c1c8374f982652"
EXPECTED_PAGE_COUNT = 8
MAX_PDF_BYTES = 2 * 1024 * 1024


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("\ufffd", " "))
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).casefold().split())


def _validated_pdf(path: Path) -> tuple[Path, int, str, str]:
    qa_root = Path(settings.QA_ROOT).resolve()
    evidence_root = (qa_root / "evidence" / "lp275-2009").resolve()
    resolved = path.resolve(strict=True)
    if not evidence_root.is_dir() or not resolved.is_relative_to(evidence_root):
        raise ValueError("PDF deve estar no diretório de evidências QA da LP 275/2009")
    if resolved.name != EXPECTED_FILENAME or not resolved.is_file():
        raise ValueError("PDF não corresponde ao arquivo municipal autorizado")
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
        raise ValueError("SHA-256 diverge do PDF oficial previamente conferido")
    with pymupdf.open(resolved) as pdf:
        page_count = len(pdf)
        text = "\n".join(page.get_text("text") for page in pdf)
    normalized = _fold(text)
    if page_count != EXPECTED_PAGE_COUNT:
        raise ValueError("quantidade de páginas diverge do PDF oficial conferido")
    markers = (
        r"lei promulgada n.{0,3}0?275/2009",
        r"regulamentacao das calcadas no municipio de natal",
        r"art[.]\s*21\s*[-–:]\s*o rebaixamento de guias",
    )
    if not all(re.search(pattern, normalized) for pattern in markers):
        raise ValueError("texto extraído não confirma a identidade e o Art. 21 esperados")
    return resolved, page_count, content_hash, text


def stage_lp275_2009_candidate(*, pdf_path: Path, apply: bool = False) -> dict:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") not in {
            "config.settings_normative_qa",
            "config.settings_normative_container_qa",
        }
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no ambiente QA normativo isolado")

    source_path, page_count, content_hash, _text = _validated_pdf(Path(pdf_path))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei promulgada",
        series="municipal_lp",
        number="275",
        year=2009,
    )
    if not identity.identity_key:
        raise ValueError("identidade candidata interna inválida")
    source_fingerprint = hashlib.sha256(f"{SOURCE_URL}\0{content_hash}".encode()).hexdigest()
    document_key = hashlib.sha256(f"municipal-source\0{source_fingerprint}".encode()).hexdigest()
    common = {
        "mode": "dry-run" if not apply else "applied",
        "official_url": SOURCE_URL,
        "official_filename": OFFICIAL_FILENAME,
        "content_sha256": content_hash,
        "size_bytes": source_path.stat().st_size,
        "page_count": page_count,
        "identity_status": "candidate",
        "identity_candidate": identity.identity_json,
        "review_status": "pending",
        "will_create_norma": False,
        "will_accept_text": False,
        "will_enter_rag": False,
    }
    if not apply:
        return common

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
            "kind": "municipal_official_repository",
            "official_url": SOURCE_URL,
            "official_filename": OFFICIAL_FILENAME,
            "retrieved_at": timezone.now().isoformat(),
            "content_sha256": content_hash,
        },
        "edition_candidate": {
            "kind": "official_source_document",
            "review_status": "unreviewed",
            "rag_eligible": False,
        },
        "rag_eligible": False,
    }
    with transaction.atomic():
        document, created = DocumentoNormativo.objects.get_or_create(
            document_key=document_key,
            defaults={
                "source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
                "source_ref": f"municipal_official_repository:{source_fingerprint}",
                "original_filename": OFFICIAL_FILENAME,
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
            or document.metadata_json.get("identity_status") != "candidate"
            or document.metadata_json.get("rag_eligible") is not False
        ):
            raise ValueError("registro existente não corresponde ao candidato pendente esperado")
    return {
        **common,
        "document_id": str(document.public_id),
        "created": created,
        "blob_copied": copied,
        "review_status": document.review_status,
        "norma_linked": document.norma_id is not None,
        "text_accepted": document.accepted_extraction_id is not None,
    }


class Command(BaseCommand):
    help = "Stage the exact official Promulgated Law 275/2009 PDF as pending QA evidence."

    def add_arguments(self, parser):
        parser.add_argument("--pdf-path", required=True, type=Path)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_lp275_2009_candidate(
                pdf_path=options["pdf_path"], apply=options["apply"]
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
