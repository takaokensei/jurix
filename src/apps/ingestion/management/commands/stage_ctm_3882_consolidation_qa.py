"""Stage allowlisted official CTM consolidation editions as pending QA sources."""

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

EDITIONS = {
    "lei3882-1989-consolidado-exercicio-2021.pdf": {
        "source_url": "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2021.pdf",
        "value_year": 2021,
        "amendment_marker": "Lei Complementar nº 197/2021 (publicação listada em 18/06/2021)",
        "amendment_pattern": r"lei complementar n.{0,2}\s*197\b.{0,80}18/06/2021",
        "temporal_limit": "Declara valores atualizados para o exercício de 2021; não comprova alterações posteriores",
    },
    "lei3882-1989-consolidado-exercicio-2022.pdf": {
        "source_url": "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2022.pdf",
        "value_year": 2022,
        "amendment_marker": "Lei Complementar nº 217/2022",
        "amendment_pattern": r"lei complementar n.{0,2}\s*217/2022\b",
        "temporal_limit": "Não declara atualização posterior ao exercício de 2022",
    },
    "lei3882-1989-consolidado-exercicio-2024.pdf": {
        "source_url": "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2024.pdf",
        "value_year": 2024,
        "amendment_marker": "Lei Complementar nº 257 (publicação listada em 27/12/2024)",
        "amendment_pattern": r"lei complementar n.{0,2}\s*257\b",
        "temporal_limit": "Declara valores atualizados para o exercício de 2024; não comprova alterações posteriores",
    },
}
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 200


def _validated_pdf(path: Path) -> tuple[Path, int, str, dict]:
    qa_root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    evidence_root = (qa_root / "evidence" / "ctm-3882-1989").resolve()
    resolved = path.expanduser().resolve(strict=True)
    if not evidence_root.is_dir() or not resolved.is_relative_to(evidence_root):
        raise ValueError("PDF deve estar no diretório de evidências QA do CTM")
    edition = EDITIONS.get(resolved.name)
    if edition is None or not resolved.is_file():
        raise ValueError("PDF não corresponde à consolidação municipal autorizada")
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
    with pymupdf.open(resolved) as pdf:
        page_count = len(pdf)
        first_page = pdf[0].get_text("text") if page_count else ""
    normalized = " ".join(first_page.casefold().replace("\ufffd", "º").split())
    if not re.search(r"lei\s+n.{0,2}\s*3\.882.{0,50}11\s+de\s+dezembro\s+de\s+1989", normalized):
        raise ValueError("primeira página não confirma a Lei nº 3.882/1989")
    if not re.search(
        rf"valores\s+atualizados\s+para\s+o\s+exerc.{{1,2}}cio\s+de\s+{edition['value_year']}\b",
        normalized,
    ):
        raise ValueError(
            f"primeira página não confirma a edição do exercício de {edition['value_year']}"
        )
    if not re.search(edition["amendment_pattern"], normalized):
        raise ValueError("primeira página não confirma o marco de alteração declarado")
    if not 1 <= page_count <= MAX_PAGES:
        raise ValueError("quantidade de páginas fora do limite de processamento QA")
    return resolved, page_count, digest.hexdigest(), edition


def stage_ctm_consolidation(*, pdf_path: Path, apply: bool = False) -> dict:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no ambiente QA normativo isolado")

    source_path, page_count, content_hash, edition = _validated_pdf(Path(pdf_path))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="lei ordinária",
        series="municipal_lo",
        number="3882",
        year=1989,
    )
    if not identity.identity_key:
        raise ValueError("identidade candidata interna inválida")
    source_url = edition["source_url"]
    source_fingerprint = hashlib.sha256(f"{source_url}\0{content_hash}".encode()).hexdigest()
    document_key = hashlib.sha256(
        f"municipal-consolidation\0{source_fingerprint}".encode()
    ).hexdigest()
    if not apply:
        return {
            "mode": "dry-run",
            "source_url": source_url,
            "content_sha256": content_hash,
            "size_bytes": source_path.stat().st_size,
            "page_count": page_count,
            "identity_status": "candidate",
            "edition_kind": "official_consolidated_text",
            "declared_value_year": edition["value_year"],
            "amendment_list_includes": edition["amendment_marker"],
            "temporal_limit": edition["temporal_limit"],
            "will_create_norma": False,
            "will_extract_text": False,
            "will_accept_text": False,
            "will_enter_rag": False,
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
            "unit": "Secretaria Municipal de Finanças de Natal",
            "official_url": source_url,
            "retrieved_at": timezone.now().isoformat(),
            "content_sha256": content_hash,
        },
        "edition_candidate": {
            "kind": "official_consolidated_text",
            "declared_value_year": edition["value_year"],
            "amendment_list_includes": edition["amendment_marker"],
            "temporal_limit": edition["temporal_limit"],
            "review_status": "unreviewed",
        },
        "rag_eligible": False,
    }
    with transaction.atomic():
        document, created = DocumentoNormativo.objects.get_or_create(
            document_key=document_key,
            defaults={
                "source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
                "source_ref": f"municipal_consolidation:{source_fingerprint}",
                "original_filename": source_path.name,
                "role": DocumentoNormativo.Role.UNDETERMINED,
                "storage_key": destination.relative_to(archive_root).as_posix(),
                "size_bytes": source_path.stat().st_size,
                "content_sha256": content_hash,
                "official_url": source_url,
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
            raise ValueError("registro existente não corresponde a candidato pendente íntegro")

    return {
        "mode": "applied",
        "document_id": str(document.public_id),
        "created": created,
        "blob_copied": copied,
        "source_url": source_url,
        "content_sha256": content_hash,
        "page_count": page_count,
        "review_status": document.review_status,
        "norma_linked": document.norma_id is not None,
        "text_accepted": document.accepted_extraction_id is not None,
        "will_create_norma": False,
        "will_accept_text": False,
        "will_enter_rag": False,
    }


class Command(BaseCommand):
    help = "Stage allowlisted official municipal tax-code editions as pending QA evidence."

    def add_arguments(self, parser):
        parser.add_argument("--pdf-path", required=True, type=Path)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_ctm_consolidation(
                pdf_path=options["pdf_path"], apply=options["apply"]
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
