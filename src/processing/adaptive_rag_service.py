"""Backward-compatible RAGService facade with adaptive retrieval controls."""

from __future__ import annotations

from typing import Any

from src.processing.adaptive_retrieval import (
    AdaptiveRetriever,
    RetrievalOptions,
    attachment_context,
)
from src.processing.normative_reference import canonical_type, parse_normative_references
from src.processing.rag_service import RAGService
from src.processing.target_resolver import article_key
from src.processing.temporal_scope import (
    matches_temporal_scope,
    revoked_dispositivo_ids,
    revoked_norma_ids,
)


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

    def _retrieve_cited_norma_devices(
        self, cited_normas: list[Any], query_text: str, options: RetrievalOptions
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
                .select_related("norma", "dispositivo_pai")
                .order_by("ordem")
            )
            if not all_disps:
                continue

            if explicit_reference is not None:
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

        cited_normas = self._find_cited_normas(query_text) if norma_id is None else []
        cited_ids = {n.id for n in cited_normas}
        cited_rows = (
            self._retrieve_cited_norma_devices(cited_normas, query_text, options)
            if cited_normas
            else []
        )
        cited_rows = self._filter_status(cited_rows, options)
        if any(row.get("match_kind") == "explicit_reference" for row in cited_rows):
            return cited_rows[: min(k, options.max_sources)]

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
            return self._select_with_citation_priority(
                cited_rows,
                rows,
                max_sources=min(k, options.max_sources),
                min_similarity=min_similarity,
                cited_norma_ids=cited_ids,
            )

        candidate_k = max(k, min(50, options.max_sources * 3))
        if options.mode == "lexical":
            rows = AdaptiveRetriever(self)._lexical(query_text, candidate_k, options)
            return self._select_with_citation_priority(
                cited_rows,
                rows,
                max_sources=min(k, options.max_sources),
                min_similarity=min_similarity,
                cited_norma_ids=cited_ids,
            )

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
        return self._select_with_citation_priority(
            cited_rows,
            rows,
            max_sources=min(k, options.max_sources),
            min_similarity=min_similarity,
            cited_norma_ids=cited_ids,
        )

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
                force_refresh=force_refresh,
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
            )
        finally:
            self._jurix_retrieval_options = previous
