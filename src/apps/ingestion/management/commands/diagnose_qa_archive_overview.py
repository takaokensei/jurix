"""Run a no-write whole-norm RAG diagnostic against the isolated QA archive."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.llm_engine.ollama_service import OllamaService
from src.processing import qa_archive_rag
from src.processing.partial_overview_quality import (
    has_redundant_content_phrase,
    has_repeated_citation_marker,
)

_CITATION_MARKER_RE = re.compile(r"\[\[(\d{1,6})\]\]")


def _validation_shape_metrics(
    result: dict, sources: list[dict] | None = None, answer: str = ""
) -> dict[str, object]:
    """Keep aggregate grounding shape while discarding all legal/model text."""
    grounding = result.get("grounding") or {}
    claims = grounding.get("claims") or []
    failed_claims = grounding.get("failed_claims") or []
    failed_records = [claim for claim in claims if claim.get("supported") is False]
    sampled_indexes = {
        int(source["citation_index"])
        for source in sources or []
        if source.get("citation_index") is not None and source.get("evidence_text")
    }
    failed_marker_groups = [
        {int(index) for index in _CITATION_MARKER_RE.findall(str(claim.get("claim") or ""))}
        for claim in failed_records
    ]
    closest_rejection_failures = {
        "lexical": 0,
        "numeric": 0,
        "negation": 0,
        "citation": 0,
        "certainty": 0,
        "no_candidate": 0,
    }
    for claim in failed_records:
        rejected_matches = claim.get("rejected_matches") or []
        if not rejected_matches:
            closest_rejection_failures["no_candidate"] += 1
            continue
        closest = max(
            rejected_matches,
            key=lambda match: float(match.get("lexical_overlap") or 0),
        )
        for key, field in (
            ("lexical", "lexical_ok"),
            ("numeric", "numeric_ok"),
            ("negation", "negation_ok"),
            ("citation", "citation_ok"),
            ("certainty", "certainty_ok"),
        ):
            if closest.get(field) is False:
                closest_rejection_failures[key] += 1
    answer_text = str(answer or "")
    citation_indexes = [
        int(index) for index in _CITATION_MARKER_RE.findall(answer_text)
    ]
    sampled_source_count = len(sampled_indexes)
    return {
        "grounded": bool(result.get("grounded")),
        "source_only": bool(result.get("source_only")),
        "score": grounding.get("score"),
        "claim_count": len(claims),
        "failed_claim_count": len(failed_claims),
        "failed_claim_records": len(failed_records),
        "failed_records_without_evidence": sum(
            not claim.get("evidence") for claim in failed_records
        ),
        "failed_records_with_evidence": sum(
            bool(claim.get("evidence")) for claim in failed_records
        ),
        "failed_records_without_citation_marker": sum(
            not markers for markers in failed_marker_groups
        ),
        "failed_records_citing_unsampled_evidence": sum(
            bool(markers) and not markers.issubset(sampled_indexes)
            for markers in failed_marker_groups
        ),
        "failed_records_citing_sampled_evidence_without_match": sum(
            bool(markers) and markers.issubset(sampled_indexes)
            for markers in failed_marker_groups
        ),
        "closest_rejection_failures": closest_rejection_failures,
        "claim_records_missing_support_status": sum(
            "supported" not in claim for claim in claims
        ),
        "candidate_answer_shape": {
            **_answer_shape_metrics(answer_text),
            "distinct_citation_marker_count": len(set(citation_indexes)),
            "repeated_citation_marker_count": len(citation_indexes) - len(set(citation_indexes)),
            "meets_partial_overview_breadth": qa_archive_rag._has_partial_overview_breadth(
                answer_text,
                len(sources or []),
                available_sample_sources=sampled_source_count,
            ),
            "meets_partial_overview_source_alignment": qa_archive_rag._has_partial_overview_breadth(
                answer_text,
                len(sources or []),
                available_sample_sources=sampled_source_count,
                sources=sources,
            ),
            "has_repeated_citation_marker": has_repeated_citation_marker(answer_text),
            "has_redundant_content_phrase": has_redundant_content_phrase(answer_text),
        },
    }


def _answer_shape_metrics(answer: str) -> dict[str, object]:
    """Describe answer structure without retaining its legal or generated text."""
    text = str(answer or "")
    return {
        "character_count": len(text),
        "citation_marker_count": len(_CITATION_MARKER_RE.findall(text)),
        "heading_count": len(re.findall(r"(?m)^\s*#{1,6}\s+", text)),
        "bullet_count": len(re.findall(r"(?m)^\s*[-*]\s+", text)),
        "paragraph_count": len([part for part in re.split(r"\n\s*\n", text) if part.strip()]),
        "has_partial_coverage_note": bool(
            re.search(
                r"(?:A amostra consultada cobre\s+\d+\s+de|A recuperação (?:encontrou|reuniu) evidências em\s+(?:um|\d+)\s+(?:de|dos))\s+\d+\s+artigos",
                text,
                re.IGNORECASE,
            )
        ),
        "has_generic_partial_notice": "A resposta foi limitada ao que as fontes consultadas permitem confirmar." in text,
    }


def _whole_norm_selection_metrics(
    candidates: list[dict], selected: list[dict], *, context_budget_chars: int
) -> dict[str, object]:
    """Report selected/missing article labels and sizes, never legal text."""
    candidate_refs = list(dict.fromkeys(
        str(row.get("dispositivo_ref") or "").strip()
        for row in candidates
        if str(row.get("dispositivo_ref") or "").strip()
    ))
    selected_refs = list(dict.fromkeys(
        str(row.get("dispositivo_ref") or "").strip()
        for row in selected
        if str(row.get("dispositivo_ref") or "").strip()
    ))
    selected_ref_set = set(selected_refs)
    return {
        "candidate_article_count": len(candidate_refs),
        "selected_article_count": len(selected_refs),
        "omitted_article_refs": [ref for ref in candidate_refs if ref not in selected_ref_set],
        "candidate_text_characters": sum(len(str(row.get("full_text") or "")) for row in candidates),
        "selected_text_characters": sum(len(str(row.get("full_text") or "")) for row in selected),
        "context_budget_characters": context_budget_chars,
    }


def _citation_alignment_shapes(answer: str, sources: list[dict]) -> list[dict[str, object]]:
    """Return only device labels and article numbers for alignment debugging."""
    marker_pattern = re.compile(r"\[\[(\d+)\]\]")
    article_pattern = re.compile(r"\b(?:art\.?|artigo)\s*(\d+[a-z]?)\s*[-º°ª]?", re.I)
    boundary_pattern = re.compile(
        r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|"
        r"(?<=\]\])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|[\r\n]+"
    )
    rows = []
    for marker in marker_pattern.finditer(str(answer or "")):
        source_index = int(marker.group(1))
        sentence_start = max(
            (boundary.end() for boundary in boundary_pattern.finditer(answer, 0, marker.start())),
            default=0,
        )
        sentence_end = min(
            (boundary.start() for boundary in boundary_pattern.finditer(answer, marker.end())),
            default=len(answer),
        )
        sentence_text = answer[sentence_start:sentence_end]
        article_mentions = [
            match.group(1).casefold()
            for match in article_pattern.finditer(sentence_text)
        ]
        device_ref = (
            str(sources[source_index - 1].get("dispositivo_ref") or "")
            if 1 <= source_index <= len(sources)
            else ""
        )
        source_article = qa_archive_rag._article_key(device_ref)
        rows.append({
            "citation_index": source_index,
            "source_device_ref": device_ref[:80],
            "source_article_key": source_article,
            "article_mentions_before_marker": article_mentions[-4:],
        })
    return rows


class Command(BaseCommand):
    help = "Measure QA archive overview grounding without saving legal text."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        ):
            raise CommandError("This diagnostic is restricted to the isolated normative QA settings.")

        qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
        output_path = Path(options["output"]).resolve()
        if not output_path.is_relative_to(qa_root) or output_path == qa_root:
            raise CommandError("Diagnostic output must stay inside JURIX_QA_ROOT.")
        if output_path.exists():
            raise CommandError("Refusing to overwrite an existing QA diagnostic.")

        validation_metrics: list[dict[str, object]] = []
        model_stream_chunks: list[str] = []
        quality_gate_checks: list[dict[str, object]] = []
        stop_callback_checks: list[dict[str, object]] = []
        whole_norm_selection_metrics: list[dict[str, object]] = []
        original_generation = qa_archive_rag.stream_grounded_generation
        original_quality_check = qa_archive_rag.has_redundant_content_phrase
        original_whole_norm_sampler = qa_archive_rag._sample_whole_norm_rows
        from src.processing.rag_service import RAGService

        def capture_whole_norm_selection(rows, **kwargs):
            selected, total = original_whole_norm_sampler(rows, **kwargs)
            whole_norm_selection_metrics.append(
                _whole_norm_selection_metrics(
                    rows,
                    selected,
                    context_budget_chars=qa_archive_rag._WHOLE_NORM_CONTEXT_BUDGET_CHARS,
                )
            )
            return selected, total

        original_validate = RAGService._validate_answer

        def capture_validation(prompt, *, validate_attempt, **kwargs):
            last_sources: list[dict] = []

            def validate_with_metrics(service, answer, sources):
                last_sources[:] = sources
                result = original_validate(service, answer, sources)
                validation_metrics.append(
                    _validation_shape_metrics(result, sources, answer)
                )
                return result

            original_stop = kwargs.get("stop_after_validated_prefix")
            if original_stop is not None:
                def stop_with_metrics(answer, validation):
                    stop = bool(original_stop(answer, validation))
                    marker_matches = list(_CITATION_MARKER_RE.finditer(answer))
                    markers = [int(match.group(1)) for match in marker_matches]
                    last_marker_ends: dict[int, int] = {}
                    repeated_marker_gaps = []
                    for match, marker in zip(marker_matches, markers, strict=True):
                        if marker in last_marker_ends:
                            gap = answer[last_marker_ends[marker] : match.start()]
                            repeated_marker_gaps.append({
                                "gap_chars": len(gap),
                                "contains_sentence_boundary": bool(re.search(
                                    r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|[\r\n]+",
                                    gap,
                                )),
                            })
                        last_marker_ends[marker] = match.end()
                    stop_callback_checks.append({
                        "character_count": len(answer),
                        "citation_marker_count": len(markers),
                        "distinct_citation_marker_count": len(set(markers)),
                        "citation_alignment_shapes": _citation_alignment_shapes(answer, last_sources),
                        "repeated_marker_gaps": repeated_marker_gaps,
                        "broad_without_source_alignment": qa_archive_rag._has_partial_overview_breadth(
                            answer,
                            len(last_sources),
                            available_sample_sources=sum(
                                bool(source.get("evidence_text")) for source in last_sources
                            ),
                        ),
                        "source_alignment": qa_archive_rag._has_partial_overview_breadth(
                            answer,
                            len(last_sources),
                            available_sample_sources=sum(
                                bool(source.get("evidence_text")) for source in last_sources
                            ),
                            sources=last_sources,
                        ),
                        "grounded": bool(validation.get("grounded")),
                        "source_only": bool(validation.get("source_only")),
                        "repeated_citation_marker": has_repeated_citation_marker(answer),
                        "redundant_content": original_quality_check(answer),
                        "stop": stop,
                    })
                    return stop

                kwargs["stop_after_validated_prefix"] = stop_with_metrics

            with patch.object(RAGService, "_validate_answer", validate_with_metrics):
                generation = original_generation(
                    prompt,
                    validate_attempt=validate_attempt,
                    **kwargs,
                )
                while True:
                    try:
                        event = next(generation)
                        if event.get("event") == "chunk":
                            model_stream_chunks.append(str(event.get("chunk") or ""))
                        yield event
                    except StopIteration as completed:
                        return completed.value

        def capture_quality_check(answer):
            answer_text = str(answer or "")
            indexes = [
                int(index) for index in _CITATION_MARKER_RE.findall(answer_text)
            ]
            redundant = original_quality_check(answer_text)
            quality_gate_checks.append({
                **_answer_shape_metrics(answer_text),
                "distinct_citation_marker_count": len(set(indexes)),
                "repeated_citation_marker_count": len(indexes) - len(set(indexes)),
                "has_repeated_citation_marker": has_repeated_citation_marker(answer_text),
                "redundant": redundant,
            })
            return redundant

        try:
            with patch.object(
                qa_archive_rag,
                "stream_grounded_generation",
                side_effect=capture_validation,
            ), patch.object(
                qa_archive_rag,
                "has_redundant_content_phrase",
                side_effect=capture_quality_check,
            ), patch.object(
                qa_archive_rag,
                "_sample_whole_norm_rows",
                side_effect=capture_whole_norm_selection,
            ):
                events = list(
                    qa_archive_rag.stream_archive_qa_answer(
                        "O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral "
                        "dos temas identificáveis e informe claramente o que ficou fora da amostra.",
                        k=8,
                        model=settings.OLLAMA_MODEL,
                        temperature=0.2,
                        text_provider=None,
                        ollama=OllamaService(),
                    )
                )
        except Exception as exc:
            # Do not serialize exception messages: providers can include request data.
            raise CommandError(f"QA archive generation failed ({type(exc).__name__}).") from None

        done = next((event for event in reversed(events) if event.get("event") == "done"), None)
        sources = next((event for event in events if event.get("event") == "sources"), {})
        source_rows = sources.get("sources") or []
        coverage = (source_rows[0].get("coverage") or {}) if source_rows else {}
        if done is None:
            raise CommandError("QA archive stream did not emit a terminal event.")
        streamed_chunks = [
            str(event.get("chunk") or "")
            for event in events
            if event.get("event") == "chunk"
        ]
        streamed_answer_shape = _answer_shape_metrics("".join(streamed_chunks))
        model_stream_shape = _answer_shape_metrics("".join(model_stream_chunks))

        report = {
            "dataset": "authentic_historical_archive_qa_unreviewed",
            "query_class": "whole_norm_overview",
            "model": settings.OLLAMA_MODEL,
            "final_reason_code": done.get("reason_code"),
            "final_grounded": bool(done.get("grounded")),
            "final_validation_scope": (done.get("grounding") or {}).get("validation_scope"),
            "final_answer_shape": _answer_shape_metrics(done.get("answer", "")),
            "streamed_chunk_count": len(streamed_chunks),
            "streamed_answer_shape": streamed_answer_shape,
            "model_stream_chunk_count": len(model_stream_chunks),
            "model_stream_answer_shape": model_stream_shape,
            "retrieved_source_count": len(source_rows),
            "whole_norm_selection_metrics": whole_norm_selection_metrics,
            "coverage": {
                key: coverage.get(key)
                for key in (
                    "complete", "selected_articles", "total_articles", "annexes_present"
                )
                if key in coverage
            },
            "generation_attempts": done.get("generation_attempts") or [],
            "candidate_validation_count": len(validation_metrics),
            "candidate_validation_metrics": validation_metrics,
            "quality_gate_check_count": len(quality_gate_checks),
            "quality_gate_checks": quality_gate_checks,
            "stop_callback_checks": stop_callback_checks,
            "answer_text_persisted": False,
            "source_text_persisted": False,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
                output.write("\n")
        except FileExistsError:
            raise CommandError("Refusing to overwrite an existing QA diagnostic.") from None

        self.stdout.write(
            json.dumps(
                {
                    "diagnostic_written": True,
                    "model": report["model"],
                    "reason_code": report["final_reason_code"],
                    "answer_shape": report["final_answer_shape"],
                    "model_stream_answer_shape": report["model_stream_answer_shape"],
                    "model_stream_chunk_count": report["model_stream_chunk_count"],
                    "retrieved_source_count": report["retrieved_source_count"],
                    "coverage": report["coverage"],
                    "candidate_validation_count": report["candidate_validation_count"],
                    "answer_text_persisted": False,
                    "source_text_persisted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
