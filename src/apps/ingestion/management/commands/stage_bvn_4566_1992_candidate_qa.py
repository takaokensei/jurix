"""Stage the exact municipal BVN PDF for Law 4.566/1992 as conflicting QA evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pymupdf
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.ingestion.archive_import import _storage_root
from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.document_metadata import build_normative_identity

SOURCE_URL = "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf"
CATALOG_URL = "https://www2.natal.rn.gov.br/bvn/detalheBVN.php?valorRegistro=1871"
EXPECTED_FILENAME = "lei_4.566.pdf"
EXPECTED_SHA256 = "91484d38b8c6cee9e4cdc8467e479059d59a2cc521ff10ce22d96dd964be88fc"
EVIDENCE_RELATIVE_DIRECTORY = Path("evidence") / "lc258-4566-1992"
MAX_PDF_BYTES = 2 * 1024 * 1024


def _validated_pdf(path: Path) -> tuple[Path, int, str, str]:
    qa_root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    evidence_root = (qa_root / EVIDENCE_RELATIVE_DIRECTORY).resolve()
    resolved = path.expanduser().resolve(strict=True)
    if not evidence_root.is_dir() or not resolved.is_relative_to(evidence_root):
        raise ValueError("PDF deve estar no diretório QA exato do alvo LC 258/2024, Art. 260, II")
    if resolved.name != EXPECTED_FILENAME or not resolved.is_file():
        raise ValueError("arquivo não corresponde ao PDF municipal BVN allowlisted")
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
        raise ValueError("SHA-256 diverge do PDF BVN verificado; inspecione uma nova edição antes do staging")
    with pymupdf.open(resolved) as pdf:
        page_count = len(pdf)
        text = "\n".join(page.get_text("text") for page in pdf)
    normalized = " ".join(text.casefold().replace("\ufffd", " ").split())
    required_markers = (
        r"lei\s+n.{0,2}\s*4[.]566.{0,80}19\s+de\s+maio\s+de\s+1992",
        r"\bdecreta\s*:",
        r"art[.]\s*2o.{0,100}presente\s+decreto",
        r"art[.]\s*7o.{0,100}este\s+decreto",
        r"publicad[oa]\s+no\s+doe.{0,30}21/05/92",
    )
    if not all(re.search(pattern, normalized) for pattern in required_markers):
        raise ValueError("texto não confirma a ficha e o conflito documental conhecido da BVN")
    if page_count != 2:
        raise ValueError("quantidade de páginas diverge do PDF BVN verificado")
    return resolved, page_count, content_hash, text


def stage_bvn_4566_candidate(*, pdf_path: Path, apply: bool = False) -> dict:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") not in {
            "config.settings_normative_qa",
            "config.settings_normative_container_qa",
        }
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no ambiente QA normativo isolado")

    source_path, page_count, content_hash, _source_text = _validated_pdf(Path(pdf_path))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei ordinária",
        series="municipal_lo",
        number="4566",
        year=1992,
    )
    if not identity.identity_key:
        raise ValueError("identidade de catálogo candidata inválida")
    source_fingerprint = hashlib.sha256(f"{SOURCE_URL}\0{content_hash}".encode()).hexdigest()
    document_key = hashlib.sha256(f"bvn-candidate\0{source_fingerprint}".encode()).hexdigest()
    common = {
        "mode": "dry-run" if not apply else "applied",
        "source_url": SOURCE_URL,
        "catalog_url": CATALOG_URL,
        "content_sha256": content_hash,
        "size_bytes": source_path.stat().st_size,
        "page_count": page_count,
        "identity_status": "conflicting_evidence",
        "identity_source_candidate": identity.identity_json,
        "identity_conflict": {
            "catalogue": "BVN classifies the record as ordinary law",
            "pdf_body": "PDF says DECRETA, Art. 2 calls it presente Decreto, Art. 7 says este decreto",
            "publication_note": "DOE 21/05/1992",
        },
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
        "identity_status": "conflicting_evidence",
        "identity_conflict": common["identity_conflict"],
        "source_provenance": {
            "kind": "municipal_virtual_library",
            "unit": "Biblioteca Virtual do Natal / SEMURB",
            "catalog_url": CATALOG_URL,
            "official_url": SOURCE_URL,
            "retrieved_at": timezone.now().isoformat(),
            "content_sha256": content_hash,
        },
        "edition_candidate": {
            "kind": "source_document",
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
                "source_ref": f"municipal_virtual_library:{source_fingerprint}",
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
            or document.metadata_json.get("identity_status") != "conflicting_evidence"
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
    help = "Stage the verified BVN 4.566/1992 PDF as conflicting, non-RAG QA evidence."

    def add_arguments(self, parser):
        parser.add_argument("--pdf-path", required=True, type=Path)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_bvn_4566_candidate(pdf_path=options["pdf_path"], apply=options["apply"])
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
