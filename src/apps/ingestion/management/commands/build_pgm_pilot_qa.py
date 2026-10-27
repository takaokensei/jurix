"""Build an immutable operational corpus from real QA PDFs and extractions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import (
    AIPilotAdoption,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.processing.document_extraction import extract_pdf_document
from src.processing.pilot_corpus import (
    build_source_record,
    load_source_selection,
    publish_revision,
    verified_blob,
)

SELECTION = Path("benchmarks/corpus/municipal_natal/pilot-source-selection.v1.json")


def _download_pdf(url: str, destination: Path, digest: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "natal.rn.gov.br", "www.natal.rn.gov.br", "www2.natal.rn.gov.br", "sapl.natal.rn.leg.br",
    } or parsed.username or parsed.password:
        raise ValueError("Missing PDF has no allowlisted official source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(dir=destination.parent, prefix="pdf-")
    path = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream, urlopen(url, timeout=30) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != parsed.hostname:
                raise ValueError("Official PDF redirected to another host")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 128 * 1024 * 1024:
                    raise ValueError("PDF exceeds pilot download budget")
                stream.write(chunk)
        verified_blob(destination.parent, path.name, digest)
        if destination.exists():
            verified_blob(destination.parent, destination.name, digest)
        else:
            path.replace(destination)
    finally:
        path.unlink(missing_ok=True)


def _candidate_extraction(document, pdf: Path):
    existing = document.extracoes.exclude(legal_text="").order_by("-created_at", "-pk").first()
    if existing:
        return existing
    # Missing extraction only: bounded native extraction, no background OCR flood.
    result = extract_pdf_document(str(pdf), max_pages=200, max_ocr_pages=0, ocr_timeout_seconds=15)
    extraction, _created = ExtracaoDocumento.objects.get_or_create(
        documento=document, extractor_version=result["extractor_version"],
        policy_fingerprint=result["policy_fingerprint"],
        defaults={
            "text_version": result["text_version"], "raw_text": result["raw_text"],
            "legal_text": result["legal_text"], "page_count": result["page_count"],
            "page_map_json": result["source_map"],
            "metadata_candidates_json": result["metadata_candidates"],
            "quality_json": {**result["quality"], "pilot_candidate_only": True},
            "status": ExtracaoDocumento.Status.COMPLETE if result["complete"] else ExtracaoDocumento.Status.PARTIAL,
            "extraction_sha256": result["extraction_sha256"],
        },
    )
    # accepted_extraction and document review fields are deliberately not modified.
    return extraction


class Command(BaseCommand):
    help = "Monta o corpus operacional no QA sem aceitar, revisar ou promover fontes."

    def add_arguments(self, parser):
        parser.add_argument("--fetch-missing", action="store_true")

    def handle(self, *args, **options):
        if os.environ.get("JURIX_QA_ONLY") != "1" or os.environ.get("DJANGO_SETTINGS_MODULE") not in {
            "config.settings_normative_qa", "config.settings_normative_container_qa",
        }:
            raise CommandError("Pilot builder only accepts the isolated normative QA settings")
        root = Path(settings.QA_ROOT).resolve()
        if root == Path(tempfile.gettempdir()).resolve() or not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise CommandError("Pilot root must remain inside isolated QA temp storage")
        selection = load_source_selection(Path(settings.BASE_DIR) / SELECTION)
        archive = root / "normative-archive"
        before = list(DocumentoNormativo.objects.order_by("pk").values_list(
            "pk", "review_status", "accepted_extraction_id", "norma_id",
        ))
        sources, failures = [], []
        for spec in selection["documents"]:
            digest = spec["pdf_sha256"]
            storage_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}.pdf"
            try:
                pdf = archive / storage_key
                if not pdf.is_file() and options["fetch_missing"]:
                    _download_pdf(spec.get("official_url") or "", pdf, digest)
                pdf = verified_blob(archive, storage_key, digest)
                # Duplicate source records may share a PDF: prefer one with usable text.
                candidates = list(DocumentoNormativo.objects.filter(content_sha256=digest).order_by("created_at", "pk"))
                document = next((item for item in candidates if item.extracoes.exclude(legal_text="").exists()), None)
                if document is None:
                    document = candidates[0] if candidates else None
                if document is None:
                    document = DocumentoNormativo.objects.create(
                        document_key=hashlib.sha256(f"pilot-public-source:{digest}".encode()).hexdigest(),
                        source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
                        source_ref=spec.get("official_url") or f"sha256:{digest}",
                        storage_key=storage_key, size_bytes=pdf.stat().st_size, content_sha256=digest,
                        official_url=spec.get("official_url"),
                        original_filename=Path(urlparse(spec.get("official_url") or "").path).name,
                        metadata_json={"pilot_source": True, "identity_candidate": spec["identity"]},
                    )
                extraction = _candidate_extraction(document, pdf)
                record = build_source_record(spec, extraction)
                if not record["devices"] and spec["source_role"] == "primary":
                    raise ValueError("Primary source has no parseable devices")
                sources.append(record)
                self.stderr.write(f"Source {len(sources)}/{len(selection['documents'])}: {spec['norma_key']}")
            except (OSError, ValueError) as exc:
                failures.append({"pdf_sha256": digest, "norma_key": spec["norma_key"], "reason": str(exc)})
        after = list(DocumentoNormativo.objects.filter(pk__in=[row[0] for row in before]).order_by("pk").values_list(
            "pk", "review_status", "accepted_extraction_id", "norma_id",
        ))
        if before != after:
            raise CommandError("Preexisting document review/acceptance/identity changed during build")
        report = {
            "schema_version": "jurix-pilot-readiness-v1", "expected_sources": len(selection["documents"]),
            "processed_sources": len(sources), "failures": failures,
            "source_integrity_ready": not failures, "chain_projection_ready": False,
            "chain_projection_note": "Document/relationship/date readiness is checked in M-05/M-06; source inventory alone is insufficient.",
            "preexisting_document_state_preserved": True,
        }
        if failures:
            # Report failure without activating an incomplete revision.
            root.joinpath("pilot").mkdir(exist_ok=True)
            path = root / "pilot" / "readiness.failed.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            raise CommandError(json.dumps(report, ensure_ascii=False))
        from src.processing.pilot_events import build_pilot_events

        adoptions = list(AIPilotAdoption.objects.filter(decision="adopted_for_pilot").values(
            "case_key", "revision", "review_draft_sha256", "review_report_sha256",
            "source_manifest_sha256", "evidence_json", "limitations_json",
        ))
        bundle = build_pilot_events(sources, adoptions)
        report["chain_readiness"] = bundle["chain_readiness"]
        report["rejected_adoptions"] = bundle["rejected"]
        report["chain_projection_ready"] = bool(
            len(bundle["chain_readiness"]) >= 3 and not bundle["rejected"]
            and any(item["complete_replacements"] for item in bundle["chain_readiness"])
            and any(item["partial_repeals"] and item["dated_events"] for item in bundle["chain_readiness"])
        )
        report["chain_projection_note"] = "Readiness documental; a execução da projeção e D-1/D/D+1 ainda precisam dos testes M-06."
        if bundle["rejected"]:
            raise CommandError("Adoção desatualizada: fingerprint não corresponde às fontes operacionais.")
        result = publish_revision(root / "pilot", sources, report=report, event_bundle=bundle)
        result["events"] = len(bundle["events"])
        self.stdout.write(json.dumps(result, ensure_ascii=False))
