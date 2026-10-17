"""Read-only diagnosis for an exact archive-PDF article lookup in isolated QA."""

from __future__ import annotations

import json
import os
import re
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.llm_engine.ollama_service import OllamaService
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

ALLOWED_SAPL_DOCUMENT_IDS = {UUID("cb810b42-ecea-4cbc-870a-b2581c30df6c")}


def _generation_mode(done: dict) -> str:
    if done.get("generation_attempts"):
        return "ollama_attempted"
    if done.get("source_only"):
        return "source_only_no_llm"
    return "not_generated"


class Command(BaseCommand):
    help = "Diagnóstico somente-leitura da recuperação de um artigo de PDF arquivado no QA."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True, help="UUID público do candidato QA.")
        parser.add_argument("--question", required=True, help="Pergunta exata submetida ao RAG.")
        parser.add_argument(
            "--generate",
            action="store_true",
            help="Executa a geração Ollama real, sem persistir conversa ou conteúdo.",
        )

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

        allowed_source = document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE or (
            document.source_kind == DocumentoNormativo.SourceKind.SAPL
            and document.public_id in ALLOWED_SAPL_DOCUMENT_IDS
        )
        if (
            not allowed_source
            or document.accepted_extraction_id is not None
            or document.review_status not in {
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            }
        ):
            raise CommandError("Diagnóstico permitido somente para candidato QA pendente e allowlisted.")

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

        report = {
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
                "replacement_character_count": (extraction.legal_text or "").count("\ufffd"),
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
                        "citation_label": source.get("citation_label"),
                        "source_kind": source.get("source_kind"),
                        "edition_label": source.get("edition_label"),
                        "source_type": source.get("source_type"),
                        "local_pdf_url": source.get("local_pdf_url"),
                        "pdf_url": source.get("pdf_url"),
                        "page_index": source.get("page_index"),
                        "page": source.get("page"),
                        "excerpt": re.sub(r"\s+", " ", str(source.get("full_text") or ""))[:1400],
                    }
                    for source in sources
                ],
            },
        }

        if options["generate"]:
            from src.processing.qa_archive_rag import stream_archive_qa_answer

            events = list(
                stream_archive_qa_answer(
                    question,
                    k=8,
                    model=settings.OLLAMA_MODEL,
                    temperature=0.2,
                    text_provider=None,
                    ollama=OllamaService(),
                )
            )
            done = next(
                (event for event in reversed(events) if event.get("event") == "done"),
                None,
            )
            source_event = next(
                (event for event in events if event.get("event") == "sources"),
                {},
            )
            if done is None:
                raise CommandError("A geração QA não emitiu evento terminal.")
            attempts = done.get("generation_attempts") or []
            generation_mode = _generation_mode(done)
            report["generation"] = {
                "generation_mode": generation_mode,
                "model": settings.OLLAMA_MODEL if attempts else None,
                "answer": done.get("answer", ""),
                "answer_replacement_character_count": str(done.get("answer") or "").count("\ufffd"),
                "grounded": bool(done.get("grounded")),
                "source_only": bool(done.get("source_only")),
                "reason_code": done.get("reason_code"),
                "timings_ms": done.get("timings_ms") or {},
                "attempts": attempts,
                "stream_chunk_count": sum(
                    event.get("event") == "chunk" for event in events
                ),
                "sources": [
                    {
                        key: source.get(key)
                        for key in (
                            "citation_id",
                            "citation_label",
                            "norma_ref",
                            "dispositivo_ref",
                            "page",
                            "page_index",
                            "source_kind",
                            "edition_label",
                            "source_type",
                            "local_pdf_url",
                            "pdf_url",
                        )
                        if source.get(key) is not None
                    }
                    for source in source_event.get("sources") or []
                ],
                "source_replacement_character_count": sum(
                    str(source.get("full_text") or "").count("\ufffd")
                    for source in source_event.get("sources") or []
                ),
                "answer_persisted": False,
                "chat_created": False,
                "document_review_changed": False,
            }

        # ASCII-escaped JSON preserves Portuguese text across Windows shell/codepage boundaries.
        self.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))
