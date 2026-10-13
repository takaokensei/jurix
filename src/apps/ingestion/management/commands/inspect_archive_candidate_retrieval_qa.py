"""Read-only diagnosis for an exact archive-PDF article lookup in isolated QA."""

from __future__ import annotations

import json
import os
import re
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.normative_query import classify_normative_query
from src.processing.normative_reference import parse_normative_references
from src.processing.qa_archive_rag import (
    _archive_retrieval_candidates,
    _article_rows,
    _candidate_identity,
    _enumerated_topic_facets,
    _facet_match_strength,
    _fold,
    _latest_extraction,
    retrieve_archive_evidence,
)


class Command(BaseCommand):
    help = "Diagnóstico somente-leitura da recuperação de um artigo de PDF arquivado no QA."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True, help="UUID público do candidato QA.")
        parser.add_argument("--question", required=True, help="Pergunta exata submetida ao RAG.")

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        ):
            raise CommandError("Este diagnóstico exige o ambiente QA normativo isolado.")

        try:
            document_id = UUID(options["document_id"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("--document-id precisa ser um UUID válido.") from exc

        question = str(options["question"] or "").strip()
        if not question or len(question) > 500:
            raise CommandError("--question precisa conter de 1 a 500 caracteres.")

        try:
            document = DocumentoNormativo.objects.get(public_id=document_id)
        except DocumentoNormativo.DoesNotExist as exc:
            raise CommandError("Documento candidato não encontrado no banco QA.") from exc

        if (
            document.source_kind != DocumentoNormativo.SourceKind.ARCHIVE
            or document.accepted_extraction_id is not None
            or document.review_status not in {
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            }
        ):
            raise CommandError("Diagnóstico permitido somente para candidato arquivado ainda não aceito.")

        extraction = _latest_extraction(document)
        if extraction is None or extraction.status not in {
            ExtracaoDocumento.Status.COMPLETE,
            ExtracaoDocumento.Status.PARTIAL,
        }:
            raise CommandError("O candidato ainda não possui extração pesquisável.")

        references = [
            reference
            for reference in parse_normative_references(question)
            if not reference.ambiguous and reference.year is not None
        ]
        exact_reference = references[0] if len(references) == 1 else None
        query_plan = classify_normative_query(question)
        requested_facets = _enumerated_topic_facets(question)
        targets = list(query_plan.article_targets)
        article_rows = _article_rows(
            extraction.legal_text,
            page_map=extraction.page_map_json,
        )
        article_numbers = {
            str(row.get("numero") or "").strip().casefold()
            for row in article_rows
        }
        final_article_numbers = []
        for row in article_rows:
            raw_number = str(row.get("numero") or "").strip()
            digits = re.sub(r"\D", "", raw_number)
            if digits and 250 <= int(digits) <= 270:
                final_article_numbers.append(raw_number)
        exact_candidates = list(
            _archive_retrieval_candidates(
                exact_ref=exact_reference,
                explicit_references=[],
                query_tokens=set(),
            )
        ) if exact_reference else []
        sources = retrieve_archive_evidence(question, limit=8)
        identity = _candidate_identity(document)

        self.stdout.write(json.dumps({
            "candidate": {
                "number": identity.get("number"),
                "type": identity.get("type"),
                "year": identity.get("year"),
                "review_status": document.review_status,
                "accepted": document.accepted_extraction_id is not None,
            },
            "extraction": {
                "status": extraction.status,
                "characters": len(extraction.legal_text or ""),
                "page_map_entries": len(extraction.page_map_json or []),
                "article_count": len(article_rows),
                "articles_1_to_3": [
                    {
                        "number": str(row.get("numero") or ""),
                        "page": row.get("page_index") + 1
                        if isinstance(row.get("page_index"), int)
                        else None,
                        "text": re.sub(r"\s+", " ", str(row.get("texto") or ""))[:1200],
                    }
                    for row in article_rows
                    if re.sub(r"\D", "", str(row.get("numero") or "")) in {"1", "2", "3", "26"}
                ],
                "articles_250_to_270": final_article_numbers,
                "requested_articles": targets,
                "requested_articles_parsed": [
                    target for target in targets
                    if any(number.startswith(target) for number in article_numbers)
                ],
            },
            "query": {
                "requested_facets": list(requested_facets),
                "facet_matches": {
                    facet: [
                        str(row.get("numero") or "")
                        for row in article_rows
                        if _facet_match_strength(
                            facet,
                            {"full_text": str(row.get("texto") or "")},
                        )
                    ]
                    for facet in requested_facets
                },
                "article_2_diagnostics": [
                    {
                        "raw_excerpt": str(row.get("texto") or "")[:260],
                        "folded_excerpt": _fold(str(row.get("texto") or ""))[:260],
                        "object_facet_strength": _facet_match_strength(
                            "objeto do Código",
                            {"full_text": str(row.get("texto") or "")},
                        ),
                    }
                    for row in article_rows
                    if re.sub(r"\D", "", str(row.get("numero") or "")) == "2"
                ],
                "kind": query_plan.kind,
                "reference": {
                    "number": exact_reference.number,
                    "type": exact_reference.type_key,
                    "year": exact_reference.year,
                } if exact_reference else None,
                "exact_candidate_count": len(exact_candidates),
                "current_candidate_in_exact_set": any(
                    row.pk == document.pk for row in exact_candidates
                ),
                "retrieved_devices": [source.get("dispositivo_ref") for source in sources],
                "retrieved_evidence": [
                    {
                        "norma": source.get("norma_ref"),
                        "dispositivo": source.get("dispositivo_ref"),
                        "page_index": source.get("page_index"),
                        "page": source.get("page"),
                        "excerpt": re.sub(r"\s+", " ", str(source.get("full_text") or ""))[:1400],
                    }
                    for source in sources
                ],
            },
        }, ensure_ascii=False, sort_keys=True))
