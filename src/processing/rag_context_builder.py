"""Retrieve and format bounded legal context for the RAG prompt."""

from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

from src.processing.normative_query import classify_normative_query

logger = logging.getLogger(__name__)


class EvidenceRows(list):
    """List of retrieved evidence carrying non-source retrieval metadata."""

    def __init__(self, iterable=(), *, reason_code: str | None = None, coverage=None):
        super().__init__(iterable)
        self.reason_code = reason_code
        self.coverage = coverage or {}


def build_relevant_context(
    service: Any, query_text: str, k: int = 5, max_tokens: int = 2000
) -> tuple[str, list[dict[str, Any]]]:
    """Retrieve evidence through ``service`` and build the bounded prompt context."""
    from src.observability.tracing import span

    with span("rag.retrieval", {"rag.k": k, "rag.query_length": len(query_text)}):
        results = service.semantic_search(query_text, k=k)

    if not results:
        return "Nenhum contexto relevante encontrado.", EvidenceRows(
            reason_code=getattr(results, "reason_code", None),
            coverage=getattr(results, "coverage", None),
        )

    context_parts: list[str] = []
    used_results: list[dict[str, Any]] = []
    used_chars = 0
    overview = classify_normative_query(query_text).is_norma_overview
    base_context_limit = int(getattr(settings, "RAG_MAX_CONTEXT_CHARS", max_tokens * 4))
    if overview:
        overview_limit = max(
            8_000,
            min(48_000, int(getattr(settings, "RAG_NORMA_OVERVIEW_MAX_CONTEXT_CHARS", 24_000))),
        )
        max_chars = min(max_tokens * 4, max(base_context_limit, overview_limit))
    else:
        max_chars = min(max_tokens * 4, base_context_limit)
    asks_for_norma_summary = bool(
        re.search(r"\b(?:ementa|assunto|tema)\b", query_text, re.IGNORECASE)
    )
    asks_for_temporal_status = bool(
        re.search(
            r"\b(?:vig[êe]ncia|vig[êe]nte|entra\s+em\s+vigor|publica(?:çc)[ãa]o)\b",
            query_text,
            re.IGNORECASE,
        )
    )

    overview_coverage = next(
        (result.get("coverage") for result in results if result.get("coverage")), None
    )
    scope_note = None
    temporal_example = next(
        (result.get("temporal_version") for result in results if result.get("temporal_version")),
        None,
    )
    temporal_coverage = next(
        (
            result.get("coverage")
            for result in results
            if isinstance(result.get("temporal_version"), dict) and result.get("coverage")
        ),
        None,
    )
    if temporal_example:
        completeness = (
            "cobertura completa dos dispositivos projetados"
            if temporal_coverage and temporal_coverage.get("complete")
            else "cobertura parcial; não infira conteúdo ausente"
        )
        scope_note = (
            f"ESCOPO TEMPORAL OBRIGATÓRIO: responda exclusivamente sobre a redação projetada "
            f"pelo Jurix em {temporal_example.get('as_of')}. Esta projeção não afirma a situação "
            f"jurídica atual nem substitui a fonte oficial; há {completeness}. "
            "Não complete lacunas com o texto consolidado atual."
        )
        context_parts.append(scope_note)
        used_chars += len(scope_note)
    elif overview and overview_coverage:
        if overview_coverage.get("complete"):
            scope_note = (
                "ESCOPO: todos os dispositivos atualmente indexados foram recuperados; o corpus "
                "ainda pode estar incompleto ou desatualizado."
            )
        else:
            scope_note = (
                "ESCOPO: nem todos os dispositivos previstos couberam no contexto; a análise é parcial."
            )
        context_parts.append(scope_note)
        used_chars += len(context_parts[-1])

    for result in results:
        citation_index = len(used_results) + 1
        dispositivo = result["dispositivo"]
        norma = dispositivo.norma
        tipo_getter = getattr(norma, "get_tipo_display_name", None)
        tipo_label = tipo_getter() if callable(tipo_getter) else getattr(norma, "tipo", "Lei")
        if str(tipo_label).isdigit():
            tipo_label = "Lei"

        ementa = getattr(norma, "ementa", "") or ""
        ementa_context = f" | Ementa: {ementa}" if asks_for_norma_summary and ementa else ""
        temporal_context = ""
        source_temporal = result.get("temporal_version")
        if asks_for_temporal_status:
            if isinstance(source_temporal, dict):
                temporal_context = (
                    f" | Situação na projeção de {source_temporal.get('as_of')}: "
                    f"{source_temporal.get('status_note') or source_temporal.get('legal_status')}"
                )
            else:
                publication = getattr(norma, "data_publicacao", None)
                effective = getattr(norma, "data_vigencia", None)
                temporal_context = (
                    f" | Publicação: {publication.isoformat() if publication else 'não informada'}"
                    f" | Vigência registrada: {effective.isoformat() if effective else 'não informada'}"
                )

        coverage = result.get("coverage") or {}
        if overview:
            result["retrieval_strategy"] = "whole_norma"
            result["evidence_scope"] = "complete" if coverage.get("complete") else "sampled"
        result["citation_index"] = citation_index
        temporal_version = source_temporal
        temporal_marker = (
            f" | redação projetada pelo Jurix em {temporal_version.get('as_of')}"
            if isinstance(temporal_version, dict)
            else ""
        )
        header = (
            f"[[{citation_index}]] {tipo_label} nº {norma.numero}/{norma.ano}, "
            f"{dispositivo.get_full_identifier()}{temporal_marker}: "
        )
        full_body = f"{dispositivo.texto}{ementa_context}{temporal_context}"
        graph_relation = result.get("graph_relation")
        if isinstance(graph_relation, dict):
            relation_header = (
                f"\n[RELAÇÃO REVISADA: {graph_relation.get('label')}; "
                f"status temporal: {graph_relation.get('effective_status') or 'não confirmado'}; "
                f"data de publicação: {graph_relation.get('publication_on') or 'não informada'}; "
                f"data de efeito: {graph_relation.get('effective_on') or 'não confirmada'}; "
                f"papel desta evidência: {graph_relation.get('role')}"
            )
            quote = str(graph_relation.get("quote") or "").strip()
            relation_quote = f"; trecho da relação: {quote}" if quote else ""
            full_body += f"{relation_header}{relation_quote}]"
        if isinstance(temporal_version, dict):
            status_note = str(temporal_version.get("status_note") or "").strip()
            if status_note:
                full_body += f"\n[METADADO TEMPORAL — não integra a redação legal: {status_note}]"
        separator = "\n\n" if context_parts else ""
        remaining = max_chars - used_chars - len(separator)
        body_budget = remaining - len(header)
        if body_budget <= 0:
            break
        snippet = full_body[:body_budget]
        if not snippet.strip():
            continue
        part = f"{header}{snippet}"
        context_parts.append(part)
        used_chars += len(separator) + len(part)
        used_results.append(result)
        result["full_text"] = dispositivo.texto
        result["snippet"] = snippet
        result["evidence_text"] = snippet
        result["snippet_truncated"] = len(snippet) < len(full_body)
        result["citation_index"] = citation_index
        result["context_start"] = 0
        result["context_end"] = len(snippet)

    if overview and overview_coverage:
        context_complete = bool(
            overview_coverage.get("complete")
            and len(used_results) == int(overview_coverage.get("selected_devices", 0))
            and not any(result["snippet_truncated"] for result in used_results)
        )
        actual_coverage = {
            **overview_coverage,
            "context_devices": len(used_results),
            "context_articles": sum(
                getattr(result["dispositivo"], "tipo", "") == "artigo"
                for result in used_results
            ),
            "context_truncated_devices": sum(
                result["snippet_truncated"] for result in used_results
            ),
            "context_complete": context_complete,
            "complete": context_complete,
        }
        for result in used_results:
            result["coverage"] = actual_coverage
            result["evidence_scope"] = "complete" if context_complete else "sampled"
        if not context_complete and scope_note and context_parts and context_parts[0] == scope_note:
            context_parts[0] = (
                f"ESCOPO TEMPORAL OBRIGATÓRIO: responda exclusivamente sobre a redação projetada "
                f"pelo Jurix em {temporal_example.get('as_of')}. A cobertura é parcial; não infira "
                "conteúdo ausente nem complete lacunas com o texto consolidado atual."
                if temporal_example
                else "ESCOPO: nem todos os dispositivos previstos couberam no contexto; a análise é parcial."
            )

    formatted_context = "\n\n".join(context_parts)
    total_chars = len(formatted_context)
    logger.info(
        "Generated context of %s characters from %s dispositivos",
        total_chars,
        len(context_parts),
    )
    return formatted_context, used_results
