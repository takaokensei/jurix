"""Write a compatibility v1 norm manifest or a provenance-first v2 pilot."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch, Q

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma


def _period_stratum(year) -> str:
    try:
        value = int(year)
    except (TypeError, ValueError):
        return "unknown"
    if value < 2000:
        return "before-2000"
    if value < 2010:
        return "2000-2009"
    if value < 2020:
        return "2010-2019"
    return "2020-plus"


def _document_strata(document: DocumentoNormativo) -> dict[str, str]:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity = metadata.get("identity_candidate")
    identity = identity if isinstance(identity, dict) else {}
    extraction = document.accepted_extraction
    accepted_extraction = extraction is not None
    if extraction is None:
        candidate_extractions = getattr(document, "pilot_extractions", None)
        if candidate_extractions:
            extraction = candidate_extractions[0]
    quality = extraction.quality_json if extraction and isinstance(extraction.quality_json, dict) else {}
    extraction_mode = quality.get("extraction_mode") or quality.get("source_mode")
    if not extraction_mode:
        # The current PDF extractor records per-page counts instead of a single
        # source_mode. Derive only what those counts prove; a missing/empty map
        # remains unknown and mixed native/OCR stays distinct from unreadable
        # pages so the pilot does not misrepresent extraction quality.
        page_methods = quality.get("page_methods")
        if isinstance(page_methods, dict):
            native = int(page_methods.get("native") or 0)
            ocr = int(page_methods.get("ocr") or 0)
            unreadable = int(page_methods.get("unreadable") or 0)
            if native > 0 and ocr > 0:
                extraction_mode = "mixed"
            elif ocr > 0 and native == 0:
                extraction_mode = "ocr"
            elif native > 0 and ocr == 0:
                extraction_mode = "native"
            elif unreadable > 0:
                extraction_mode = "unreadable"
    extraction_mode = str(extraction_mode or "unknown").casefold()
    if extraction_mode != "unknown" and not accepted_extraction:
        extraction_mode = f"candidate_{extraction_mode}"
    return {
        "act_type": str(identity.get("type") or "unidentified").casefold(),
        "period": _period_stratum(identity.get("year")),
        "source_kind": document.source_kind,
        "role": document.role,
        "extraction_mode": extraction_mode,
        "relation_density": "not-evaluated",
    }


def _stratified_documents(documents, sample_size: int):
    buckets = defaultdict(list)
    for document in documents:
        strata = _document_strata(document)
        key = tuple(strata[field] for field in sorted(strata))
        buckets[key].append((document, strata))
    for bucket in buckets.values():
        bucket.sort(key=lambda row: (row[0].archive_sha256 or row[0].content_sha256,
                                    row[0].entry_index if row[0].entry_index is not None else -1,
                                    row[0].document_key))

    selected = []
    # Round-robin stable strata; tied candidates are ordered by immutable hash/entry.
    while buckets and len(selected) < sample_size:
        exhausted = []
        for key in sorted(buckets):
            bucket = buckets[key]
            if bucket:
                selected.append(bucket.pop(0))
                if len(selected) >= sample_size:
                    break
            if not bucket:
                exhausted.append(key)
        for key in exhausted:
            buckets.pop(key, None)
    return selected


def _norma_candidates(corpus_limit: int, pilot_size: int, *, require_identity: bool = False):
    queryset = (
        Norma.objects.filter(sapl_id__isnull=False)
        .filter(
            ~Q(identity_json__synthetic_fixture=True)
            | Q(identity_json__synthetic_fixture__isnull=True)
        )
        .exclude(ementa="")
        .order_by("-ano", "tipo", "numero")
    )
    if require_identity:
        queryset = queryset.filter(identity_key__isnull=False).exclude(identity_key="")
    queryset = queryset[:corpus_limit]
    buckets = defaultdict(list)
    for norma in queryset:
        buckets[norma.tipo].append(norma)

    selected = []
    while buckets and len(selected) < pilot_size:
        exhausted = []
        for kind in sorted(buckets):
            bucket = buckets[kind]
            if bucket:
                selected.append(bucket.pop(0))
                if len(selected) >= pilot_size:
                    break
            if not bucket:
                exhausted.append(kind)
        for kind in exhausted:
            buckets.pop(kind, None)
    return selected


def _v1_record(norma: Norma) -> dict:
    return {
        "norma_id": norma.id,
        "sapl_id": norma.sapl_id,
        "identifier": f"{norma.tipo} {norma.numero}/{norma.ano}",
        "ementa": norma.ementa,
        "source_url": norma.sapl_url,
        "ai_review_status": "pending",
        "human_review_status": "pending",
        "annotation_status": "pending",
        "notes": "",
    }


def _v2_manifest(normas, selected_documents, available_documents):
    strata_counts = Counter(
        json.dumps(strata, ensure_ascii=False, sort_keys=True)
        for _, strata in selected_documents
    )
    rows = [{
        "schema_version": 2,
        "record_type": "manifest",
        "protocol": "graph-evaluation-v2",
        "sampling_method": "stable round-robin by act type, period, source, role and extraction mode",
        "available_document_count": len(available_documents),
        "selected_document_count": len(selected_documents),
        "selected_norma_candidate_count": len(normas),
        "strata_counts": [
            {"strata": json.loads(key), "document_count": count}
            for key, count in sorted(strata_counts.items())
        ],
        "human_review_required": True,
        "synthetic_fixtures_are_gold": False,
    }]
    rows.extend({
        "schema_version": 2,
        "record_type": "norma_review_candidate",
        "unit": "norma",
        "norma_key": norma.identity_key,
        "norma_id": norma.pk,
        "identifier": f"{norma.tipo} {norma.numero}/{norma.ano}",
        "source_url": norma.sapl_url,
        "human_review_status": "pending",
        "annotation_status": "pending",
        "synthetic_fixture": bool(
            (norma.identity_json or {}).get("synthetic_fixture")
        ),
        "gold_eligible": False,
        "selection_reason": "balanced candidate for human review; not an approval",
    } for norma in normas)
    rows.extend({
        "schema_version": 2,
        "record_type": "document_review_candidate",
        "unit": "document",
        "document_key": document.document_key,
        "document_id": str(document.public_id),
        "archive_sha256": document.archive_sha256,
        "document_sha256": document.content_sha256,
        "entry_index": document.entry_index,
        "entry_name": PurePosixPath((document.entry_name or document.original_filename).replace("\\", "/")).name,
        "source_kind": document.source_kind,
        "role": document.role,
        "review_status": document.review_status,
        "condition_of_use": document.condition_of_use,
        "extraction_status": document.extraction_status,
        "strata": strata,
        "human_review_required": True,
        "synthetic_fixture": bool((document.metadata_json or {}).get("synthetic")),
        "gold_eligible": False,
        "selection_reason": "deterministic stratified document candidate; hash and archive entry retained",
    } for document, strata in selected_documents)
    return rows


class Command(BaseCommand):
    help = "Cria um manifesto de revisão; candidatos nunca são aprovados automaticamente."

    def add_arguments(self, parser):
        parser.add_argument("--corpus-limit", type=int, default=300)
        parser.add_argument("--pilot-size", type=int, default=20)
        parser.add_argument("--document-sample-size", type=int, default=40)
        parser.add_argument("--schema-version", choices=("1", "2"), default="1")
        parser.add_argument(
            "--output",
            default="benchmarks/corpus/municipal_natal/pilot.jsonl",
        )

    def handle(self, *args, **options):
        corpus_limit = options["corpus_limit"]
        pilot_size = options["pilot_size"]
        document_sample_size = options["document_sample_size"]
        if corpus_limit < 1 or pilot_size < 1 or pilot_size > corpus_limit:
            raise CommandError("pilot-size deve ser >=1 e <= corpus-limit")
        if document_sample_size < 1 or document_sample_size > 50:
            raise CommandError("document-sample-size deve estar entre 1 e 50")

        out = Path(options["output"])
        if out.exists():
            raise CommandError(f"recusando sobrescrever manifesto existente: {out}")
        normas = _norma_candidates(
            corpus_limit,
            pilot_size,
            require_identity=options["schema_version"] == "2",
        )
        if options["schema_version"] == "1":
            rows = [_v1_record(norma) for norma in normas]
        else:
            documents = list(
                DocumentoNormativo.objects.filter(
                    source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                    norma__isnull=True,
                ).filter(
                    Q(metadata_json__synthetic=False)
                    | Q(metadata_json__synthetic__isnull=True)
                ).select_related("accepted_extraction").prefetch_related(
                    Prefetch(
                        "extracoes",
                        queryset=ExtracaoDocumento.objects.order_by("-created_at", "-pk"),
                        to_attr="pilot_extractions",
                    )
                ).order_by("document_key")
            )
            selected_documents = _stratified_documents(documents, document_sample_size)
            rows = _v2_manifest(normas, selected_documents, documents)

        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out.open("x", encoding="utf-8", newline="\n") as handle:
                for record in rows:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except FileExistsError as exc:
            raise CommandError(f"recusando sobrescrever manifesto existente: {out}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Manifesto v{options['schema_version']} escrito em {out} ({len(rows)} registros)."
            )
        )
