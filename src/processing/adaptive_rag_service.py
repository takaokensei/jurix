"""Backward-compatible RAGService facade with adaptive retrieval controls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.processing.adaptive_retrieval import (
    AdaptiveRetriever,
    RetrievalOptions,
    attachment_context,
)
from src.processing.graph_retrieval import expand_relation_evidence
from src.processing.normative_query import classify_normative_query
from src.processing.normative_reference import canonical_type, parse_normative_references
from src.processing.rag_context_builder import EvidenceRows
from src.processing.rag_service import RAGService
from src.processing.target_resolver import article_key
from src.processing.temporal_retrieval import (
    retrieve_historical_corpus,
    retrieve_historical_norma,
)
from src.processing.temporal_scope import (
    matches_temporal_scope,
    revoked_dispositivo_ids,
    revoked_norma_ids,
)

NORMA_OVERVIEW_MAX_SOURCES = 48
NORMA_OVERVIEW_ALL_DEVICES_LIMIT = 48
logger = logging.getLogger(__name__)


def _with_graph_trace(rows, trace):
    enriched = EvidenceRows(
        rows,
        reason_code=getattr(rows, "reason_code", None),
        coverage=getattr(rows, "coverage", None),
    )
    enriched.graph_trace = trace
    return enriched


class AdaptiveRAGService(RAGService):
    """Use the existing RAG generation pipeline with a stronger retriever.

    Generation, citation formatting and Ollama streaming remain in the mature
    ``RAGService`` implementation. Only retrieval is overridden here so the
    change is isolated and reversible.
    """

    def _options(self) -> RetrievalOptions:
        value = getattr(self, "_jurix_retrieval_options", None)
        if isinstance(value, RetrievalOptions):
            return value
        return RetrievalOptions(max_sources=12)

    @staticmethod
    def _expand_relation_rows(rows, query_text, options, query_plan):
        """Expand only explicit relation questions and preserve baseline errors."""
        if not rows or not query_plan.relation_intent:
            return rows
        from django.conf import settings

        if not getattr(settings, "RAG_GRAPH_CONTEXT_ENABLED", False):
            return rows
        if options.temporal_scope.as_of is not None:
            # Current Dispositivo text is not admissible evidence for an older
            # version. Keep the date-compatible baseline rather than mixing it.
            trace = {
                "enabled": False,
                "intent": query_plan.relation_intent,
                "discarded": [{"reason": "historical_graph_text_not_projected"}],
            }
            logger.info("Graph retrieval skipped for historical query", extra={"graph_trace": trace})
            return _with_graph_trace(rows, trace)
        expanded, trace = expand_relation_evidence(
            query_text,
            rows,
            relation_intent=query_plan.relation_intent,
            as_of=None,
            max_additional=8,
        )
        logger.info("Normative graph retrieval completed", extra={"graph_trace": trace})
        return _with_graph_trace(
            EvidenceRows(
                expanded,
                reason_code=getattr(rows, "reason_code", None),
                coverage=getattr(rows, "coverage", None),
            ),
            trace,
        )

    def get_relevant_context(self, query_text: str, k: int = 5, max_tokens: int = 2000):
        """Use explicitly attached documents as the authoritative corpus."""
        options = self._options()
        if options.attachment_texts:
            context = attachment_context(options.attachment_texts, max_chars=max_tokens * 4)
            sources = [
                {
                    "text": text[:200],
                    "full_text": text,
                    "norma_ref": "Documento anexado",
                    "similarity_score": 1.0,
                    "distance": 0.0,
                    "attachment": True,
                }
                for text in options.attachment_texts
            ]
            return context, sources
        query_plan = classify_normative_query(query_text)
        if query_plan.is_norma_overview:
            from django.conf import settings

            # Whole-statute questions need a wider evidence window than an
            # article lookup. Keep this explicitly bounded and independent of
            # the normal semantic-search top-k.
            max_chars = max(
                8_000,
                min(
                    48_000,
                    int(getattr(settings, "RAG_NORMA_OVERVIEW_MAX_CONTEXT_CHARS", 24_000)),
                ),
            )
            return super().get_relevant_context(
                query_text,
                k=NORMA_OVERVIEW_MAX_SOURCES,
                max_tokens=max_chars // 4,
            )
        return super().get_relevant_context(query_text, k=k, max_tokens=max_tokens)

    @staticmethod
    def _find_cited_normas(query_text: str) -> list[Any]:
        if not query_text:
            return []
        from src.apps.legislation.models import Norma

        cited_normas = []
        seen_ids = set()
        for reference in parse_normative_references(query_text):
            # A yearless or multi-reference string does not identify one safe
            # target. Never let the first regex match silently choose a norma.
            if reference.ambiguous or reference.year is None:
                continue
            for n in Norma.objects.filter(numero=reference.number, ano=reference.year)[:20]:
                display = getattr(n, "get_tipo_display_name", None)
                actual_type = canonical_type(
                    display() if callable(display) else getattr(n, "tipo", "")
                )
                if actual_type != reference.type_key:
                    continue
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    cited_normas.append(n)
        # Accept the compact number/year form only if exactly one norma has
        # that identifier; ambiguous collisions require an explicit type.
        if not parse_normative_references(query_text):
            import re

            for number, year in re.findall(r"\b(\d{1,6})\s*/\s*((?:19|20)\d{2})\b", query_text):
                matches = list(Norma.objects.filter(numero=number, ano=int(year))[:2])
                if len(matches) == 1 and matches[0].id not in seen_ids:
                    seen_ids.add(matches[0].id)
                    cited_normas.append(matches[0])
        return cited_normas

    @staticmethod
    def _has_unambiguous_versioned_reference(query_text: str) -> bool:
        references = parse_normative_references(query_text or "")
        return (
            len(references) == 1
            and not references[0].ambiguous
            and references[0].year is not None
        )

    def _retrieve_cited_norma_devices(
        self,
        cited_normas: list[Any],
        query_text: str,
        options: RetrievalOptions,
        *,
        norma_overview: bool = False,
    ) -> list[dict[str, Any]]:
        from src.apps.legislation.models import Dispositivo

        results: list[dict[str, Any]] = []
        seen_disp_ids = set()
        retrieval_rows: list[dict[str, Any]] = []
        references = parse_normative_references(query_text)
        explicit_reference = (
            references[0]
            if len(references) == 1 and not references[0].ambiguous and references[0].article
            else None
        )
        for norma in cited_normas:
            all_disps = list(
                Dispositivo.objects.filter(norma_id=norma.id, is_active=True)
                .select_related("norma__documento_base", "dispositivo_pai")
                .order_by("ordem")
            )
            if not all_disps:
                continue

            coverage = None
            if norma_overview:
                chosen_disps, coverage = self._select_norma_overview_devices(all_disps)
                match_kind = (
                    "norma_overview_complete" if coverage["complete"] else "norma_overview_sampled"
                )
                retrieval_rows = []
            elif explicit_reference is not None:
                target_article = article_key(explicit_reference.article)
                article_matches = [
                    d
                    for d in all_disps
                    if d.tipo == "artigo" and article_key(d.numero) == target_article
                ]
                if len(article_matches) != 1:
                    continue
                target_id = article_matches[0].id
                chosen_disps = []
                for d in all_disps:
                    current = d
                    seen_ancestors = set()
                    while current is not None and current.id not in seen_ancestors:
                        if current.id == target_id:
                            chosen_disps.append(d)
                            break
                        seen_ancestors.add(current.id)
                        current = getattr(current, "dispositivo_pai", None)
                match_kind = "explicit_reference"
            else:
                norma_semantic = super().semantic_search(
                    query_text=query_text,
                    k=max(10, min(50, options.max_sources * 3)),
                    norma_id=norma.id,
                    min_similarity=0.0,
                )
                retrieval_rows = norma_semantic
                chosen_disps = [r["dispositivo"] for r in norma_semantic if r.get("dispositivo")]
                if not chosen_disps:
                    retrieval_rows = AdaptiveRetriever(self)._lexical(
                        query_text, max(10, options.max_sources * 3), options, norma_id=norma.id
                    )
                    chosen_disps = [r["dispositivo"] for r in retrieval_rows]
                match_kind = "retrieval"

            for d in chosen_disps:
                if d.id in seen_disp_ids:
                    continue
                seen_disp_ids.add(d.id)
                retrieval_row = (
                    next((row for row in retrieval_rows if row.get("dispositivo") is d), None)
                    if match_kind == "retrieval"
                    else None
                )
                score = (
                    float(retrieval_row.get("similarity_score") or 0.0) if retrieval_row else 0.0
                )
                results.append(
                    {
                        "dispositivo": d,
                        "similarity_score": score,
                        "semantic_score": float(retrieval_row.get("semantic_score") or score)
                        if retrieval_row
                        else 0.0,
                        "lexical_score": float(retrieval_row.get("lexical_score") or 0.0)
                        if retrieval_row
                        else 0.0,
                        "retrieval_score": score,
                        "distance": round(1.0 - score, 4),
                        "match_kind": match_kind,
                        "coverage": coverage,
                        "context": {
                            "norma": {
                                "id": d.norma.id,
                                "tipo": d.norma.tipo,
                                "numero": d.norma.numero,
                                "ano": d.norma.ano,
                                "ementa": d.norma.ementa[:200] if d.norma.ementa else None,
                            },
                            "hierarchy": d.get_caminho_completo(),
                            "parent": str(d.dispositivo_pai) if d.dispositivo_pai else None,
                        },
                        "embedding_model": getattr(d, "embedding_model", None),
                    }
                )
        return results

    @staticmethod
    def _select_norma_overview_devices(dispositivos: list[Any]) -> tuple[list[Any], dict[str, Any]]:
        """Use full coverage for small norms and a distributed sample for large ones."""
        total = len(dispositivos)
        articles = [row for row in dispositivos if getattr(row, "tipo", "") == "artigo"]
        if total <= NORMA_OVERVIEW_ALL_DEVICES_LIMIT:
            selected = dispositivos
        elif articles:
            # Sample article roots evenly across the statute, then use remaining
            # slots for the first substantive child under those roots. This
            # avoids top-k similarity collapsing an overview onto one chapter.
            article_budget = min(32, len(articles), NORMA_OVERVIEW_MAX_SOURCES)
            if article_budget == 1:
                sampled_articles = [articles[0]]
            else:
                indexes = {
                    round(index * (len(articles) - 1) / (article_budget - 1))
                    for index in range(article_budget)
                }
                sampled_articles = [articles[index] for index in sorted(indexes)]

            selected = list(sampled_articles)
            selected_ids = {row.id for row in selected}
            article_ids = {row.id for row in articles}
            rows_by_id = {row.id: row for row in dispositivos}
            children_by_article: dict[int, list[Any]] = {row.id: [] for row in articles}
            for row in dispositivos:
                parent = rows_by_id.get(getattr(row, "dispositivo_pai_id", None))
                seen = set()
                while parent is not None and parent.id not in seen:
                    seen.add(parent.id)
                    if parent.id in article_ids:
                        children_by_article[parent.id].append(row)
                        break
                    parent = rows_by_id.get(getattr(parent, "dispositivo_pai_id", None))

            child_slots = NORMA_OVERVIEW_MAX_SOURCES - len(selected)
            child_candidates = []
            for article in sampled_articles:
                children = children_by_article.get(article.id, [])
                child = next(
                    (
                        row
                        for row in children
                        if row.id not in selected_ids and str(row.texto or "").strip()
                    ),
                    None,
                )
                if child is not None:
                    child_candidates.append(child)
            if child_slots and child_candidates:
                if len(child_candidates) <= child_slots:
                    selected.extend(child_candidates)
                else:
                    indexes = {
                        round(index * (len(child_candidates) - 1) / (child_slots - 1))
                        for index in range(child_slots)
                    } if child_slots > 1 else {0}
                    selected.extend(child_candidates[index] for index in sorted(indexes))

            selected.sort(key=lambda row: (row.ordem, row.id))
        else:
            selected = dispositivos[:NORMA_OVERVIEW_MAX_SOURCES]

        selected_article_ids = {
            row.id if getattr(row, "tipo", "") == "artigo" else None for row in selected
        }
        selected_article_ids.discard(None)
        coverage = {
            "strategy": "whole_norma",
            "total_devices": total,
            "selected_devices": len(selected),
            "total_articles": len(articles),
            "selected_articles": len(selected_article_ids),
            "complete": len(selected) == total,
        }
        return selected, coverage

    @staticmethod
    def _merge_cited_and_general(
        cited_rows: list[dict[str, Any]], general_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not cited_rows:
            return general_rows
        seen_ids = set()
        merged = []
        for r in cited_rows:
            disp = r.get("dispositivo")
            disp_id = getattr(disp, "id", None)
            if disp_id and disp_id not in seen_ids:
                seen_ids.add(disp_id)
                merged.append(r)
        for r in general_rows:
            disp = r.get("dispositivo")
            disp_id = getattr(disp, "id", None)
            if disp_id and disp_id not in seen_ids:
                seen_ids.add(disp_id)
                merged.append(r)
        return merged

    @staticmethod
    def _select_with_citation_priority(
        cited_rows: list[dict[str, Any]],
        general_rows: list[dict[str, Any]],
        *,
        max_sources: int,
        min_similarity: float,
        cited_norma_ids: set[int],
    ) -> list[dict[str, Any]]:
        """Keep an explicitly cited norm ahead of semantic neighbours.

        A query such as ``Lei 8001/2025`` is an instruction about scope, not
        merely another lexical feature.  Applying the generic score selector
        after merging could let unrelated rows with a saturated semantic
        score of ``1.0`` outrank the cited norm.  Select cited rows first and
        only use the general corpus to fill remaining capacity.
        """
        if not cited_rows:
            return AdaptiveRetriever._select(
                general_rows,
                max_sources=max_sources,
                min_similarity=min_similarity,
                cited_norma_ids=cited_norma_ids,
            )

        explicit_rows = [row for row in cited_rows if row.get("match_kind") == "explicit_reference"]
        if explicit_rows:
            return explicit_rows[:max_sources]

        cited_selected = AdaptiveRetriever._select(
            cited_rows,
            max_sources=max_sources,
            min_similarity=min_similarity,
            cited_norma_ids=cited_norma_ids,
        )
        # An explicit norma citation is a scope constraint, not merely a
        # relevance hint. Filling the remaining capacity with generic corpus
        # neighbours makes boilerplate provisions (especially "entra em
        # vigor") appear as if they supported the cited norm. Keep the
        # response evidence bounded to the cited norma; callers can request a
        # broader corpus search without naming a norma when contextual sources
        # are actually desired.
        if cited_selected:
            return cited_selected[:max_sources]

        remaining = max_sources - len(cited_selected)
        general_selected = AdaptiveRetriever._select(
            general_rows,
            max_sources=remaining,
            min_similarity=min_similarity,
            cited_norma_ids=cited_norma_ids,
        )
        seen = {getattr(row.get("dispositivo"), "id", None) for row in cited_selected}
        return (
            cited_selected
            + [
                row
                for row in general_selected
                if getattr(row.get("dispositivo"), "id", None) not in seen
            ][:remaining]
        )

    def semantic_search(
        self, query_text: str, k: int = 10, norma_id=None, min_similarity: float = 0.0
    ):
        options = self._options()
        min_similarity = max(min_similarity, options.min_similarity)
        query_plan = classify_normative_query(query_text)
        parsed_references = parse_normative_references(query_text)
        exact_reference = (
            parsed_references[0]
            if len(parsed_references) == 1
            and not parsed_references[0].ambiguous
            and parsed_references[0].year is not None
            else None
        )
        cited_normas = self._find_cited_normas(query_text) if norma_id is None else []
        norma_overview = query_plan.is_norma_overview and len(cited_normas) == 1
        empty_coverage = {
            "strategy": "whole_norma" if query_plan.is_norma_overview else "explicit_reference",
            "complete": False,
            "total_devices": 0,
            "selected_devices": 0,
        }
        if options.temporal_scope.as_of is not None:
            temporal_normas = cited_normas
            if norma_id is not None:
                from src.apps.legislation.models import Norma

                selected_norma = Norma.objects.filter(pk=norma_id).first()
                temporal_normas = [selected_norma] if selected_norma else []
            if len(temporal_normas) > 1:
                return EvidenceRows(
                    reason_code="ambiguous_historical_norma_scope",
                    coverage={
                        **empty_coverage,
                        "as_of": options.temporal_scope.as_of.isoformat(),
                        "complete": False,
                        "reason": "historical_request_names_multiple_normas",
                    },
                )
            if temporal_normas:
                norma = temporal_normas[0]
                if (
                    options.norma_status != "all"
                    and getattr(norma, "status", None) != options.norma_status
                ):
                    return EvidenceRows(
                        reason_code="historical_norma_outside_scope",
                        coverage={**empty_coverage, "as_of": options.temporal_scope.as_of.isoformat()},
                    )
                if options.year is not None and norma.ano != options.year:
                    return EvidenceRows(
                        reason_code="historical_norma_outside_scope",
                        coverage={**empty_coverage, "as_of": options.temporal_scope.as_of.isoformat()},
                    )
                if options.source_scope != "all":
                    source_url = str(getattr(norma, "sapl_url", "") or "").lower()
                    if source_url and "sapl.natal.rn.leg.br" not in source_url:
                        return EvidenceRows(
                            reason_code="historical_norma_outside_scope",
                            coverage={**empty_coverage, "as_of": options.temporal_scope.as_of.isoformat()},
                        )
                if options.norma_type:
                    display = getattr(norma, "get_tipo_display_name", None)
                    actual_type = canonical_type(
                        display() if callable(display) else getattr(norma, "tipo", "")
                    )
                    if actual_type != canonical_type(options.norma_type):
                        return EvidenceRows(
                            reason_code="historical_norma_outside_scope",
                            coverage={**empty_coverage, "as_of": options.temporal_scope.as_of.isoformat()},
                        )
                overview_selector = self._select_norma_overview_devices if norma_overview else None
                return retrieve_historical_norma(
                    norma,
                    query_text,
                    options.temporal_scope.as_of,
                    max_sources=(
                        NORMA_OVERVIEW_MAX_SOURCES
                        if norma_overview
                        else min(max(1, k), options.max_sources)
                    ),
                    overview_selector=overview_selector,
                    scope=options.temporal_scope,
                )
            if exact_reference:
                return EvidenceRows(
                    reason_code="norm_not_in_corpus",
                    coverage={
                        **empty_coverage,
                        "as_of": options.temporal_scope.as_of.isoformat(),
                    },
                )
            return retrieve_historical_corpus(
                query_text,
                options.temporal_scope.as_of,
                max_sources=min(max(1, k), options.max_sources),
                scope=options.temporal_scope,
                norma_status=options.norma_status,
                source_scope=options.source_scope,
                norma_type=options.norma_type,
                year=options.year,
            )
        if exact_reference and norma_id is None and not cited_normas:
            return EvidenceRows(reason_code="norm_not_in_corpus", coverage=empty_coverage)
        cited_ids = {n.id for n in cited_normas}
        cited_rows = (
            self._retrieve_cited_norma_devices(
                cited_normas, query_text, options, norma_overview=norma_overview
            )
            if cited_normas
            else []
        )
        cited_rows = self._filter_status(cited_rows, options)
        if norma_overview and cited_rows:
            return self._expand_relation_rows(
                cited_rows[:NORMA_OVERVIEW_MAX_SOURCES], query_text, options, query_plan
            )
        if any(row.get("match_kind") == "explicit_reference" for row in cited_rows):
            return self._expand_relation_rows(
                cited_rows[: min(k, options.max_sources)], query_text, options, query_plan
            )
        if exact_reference and cited_normas and (
            query_plan.is_norma_overview or query_plan.reference is not None
        ):
            reason_code = (
                "norm_content_not_in_corpus"
                if norma_overview
                else "requested_device_not_in_corpus"
            )
            return EvidenceRows(reason_code=reason_code, coverage=empty_coverage)

        if norma_id is not None or options.mode == "semantic":
            rows = super().semantic_search(
                query_text=query_text,
                k=max(k, min(50, options.max_sources * 3)),
                norma_id=norma_id,
                min_similarity=min_similarity,
            )
            rows = self._filter_status(rows, options)
            for row in rows:
                row["retrieval_score"] = float(row.get("similarity_score") or 0.0)
                row["semantic_score"] = row["retrieval_score"]
            selected = self._select_with_citation_priority(
                cited_rows,
                rows,
                max_sources=min(k, options.max_sources),
                min_similarity=min_similarity,
                cited_norma_ids=cited_ids,
            )
            return self._expand_relation_rows(selected, query_text, options, query_plan)

        candidate_k = max(k, min(50, options.max_sources * 3))
        if options.mode == "lexical":
            rows = AdaptiveRetriever(self)._lexical(query_text, candidate_k, options)
            selected = self._select_with_citation_priority(
                cited_rows,
                rows,
                max_sources=min(k, options.max_sources),
                min_similarity=min_similarity,
                cited_norma_ids=cited_ids,
            )
            return self._expand_relation_rows(selected, query_text, options, query_plan)

        semantic = super().semantic_search(
            query_text=query_text,
            k=candidate_k,
            norma_id=norma_id,
            min_similarity=min_similarity,
        )
        semantic = self._filter_status(semantic, options)
        for row in semantic:
            row["semantic_score"] = float(row.get("similarity_score") or 0.0)
            row["retrieval_score"] = row["semantic_score"]
        lexical = AdaptiveRetriever(self)._lexical(query_text, candidate_k, options)
        rows = AdaptiveRetriever._merge(semantic, lexical, "hybrid")
        selected = self._select_with_citation_priority(
            cited_rows,
            rows,
            max_sources=min(k, options.max_sources),
            min_similarity=min_similarity,
            cited_norma_ids=cited_ids,
        )
        return self._expand_relation_rows(selected, query_text, options, query_plan)

    @staticmethod
    def _filter_status(rows, options):
        norma_ids = {
            int(getattr(getattr(row.get("dispositivo"), "norma", None), "id", 0) or 0)
            for row in rows
            if row.get("dispositivo")
        }
        revoked_normas = revoked_norma_ids(norma_ids, options.temporal_scope.as_of)
        revoked_devices = revoked_dispositivo_ids(norma_ids, options.temporal_scope.as_of)
        filtered = []
        for row in rows:
            norma = getattr(row.get("dispositivo"), "norma", None)
            if (
                options.norma_status != "all"
                and getattr(norma, "status", None) != options.norma_status
            ):
                continue
            if options.source_scope != "all":
                url = str(getattr(norma, "sapl_url", "") or "").lower()
                if url and "sapl.natal.rn.leg.br" not in url:
                    continue
            dispositivo = row.get("dispositivo")
            if not matches_temporal_scope(norma, options.temporal_scope, revoked_normas):
                continue
            if getattr(dispositivo, "id", None) in revoked_devices:
                continue
            filtered.append(row)
        return filtered

    def answer_question(
        self,
        question: str,
        k: int = 5,
        model=None,
        temperature: float = 0.3,
        options: RetrievalOptions | None = None,
        force_refresh: bool = False,
    ):
        previous = getattr(self, "_jurix_retrieval_options", None)
        self._jurix_retrieval_options = options or RetrievalOptions(max_sources=k)
        try:
            return super().answer_question(
                question=question,
                k=k,
                model=model,
                temperature=temperature,
                force_refresh=(
                    force_refresh
                    or self._has_unambiguous_versioned_reference(question)
                    or self._options().temporal_scope.as_of is not None
                ),
                retrieval_fingerprint=self._options().fingerprint(),
            )
        finally:
            self._jurix_retrieval_options = previous

    def stream_answer_question(
        self,
        question: str,
        k: int = 5,
        model=None,
        temperature: float = 0.3,
        options: RetrievalOptions | None = None,
        text_provider: dict[str, Any] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ):
        previous = getattr(self, "_jurix_retrieval_options", None)
        self._jurix_retrieval_options = options or RetrievalOptions(max_sources=k)
        try:
            yield from super().stream_answer_question(
                question=question,
                k=k,
                model=model,
                temperature=temperature,
                text_provider=text_provider,
                retrieval_fingerprint=self._options().fingerprint(),
                skip_cache=(
                    self._has_unambiguous_versioned_reference(question)
                    or self._options().temporal_scope.as_of is not None
                ),
                should_cancel=should_cancel,
            )
        finally:
            self._jurix_retrieval_options = previous
