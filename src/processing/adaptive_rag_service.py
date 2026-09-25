"""Backward-compatible RAGService facade with adaptive retrieval controls."""
from __future__ import annotations

from src.processing.adaptive_retrieval import AdaptiveRetriever, RetrievalOptions, attachment_context
from src.processing.rag_service import RAGService


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
                    'text': text[:200],
                    'full_text': text,
                    'norma_ref': 'Documento anexado',
                    'similarity_score': 1.0,
                    'distance': 0.0,
                    'attachment': True,
                }
                for text in options.attachment_texts
            ]
            return context, sources
        return super().get_relevant_context(query_text, k=k, max_tokens=max_tokens)

    def semantic_search(self, query_text: str, k: int = 10, norma_id=None, min_similarity: float = 0.0):
        options = self._options()
        min_similarity = max(min_similarity, options.min_similarity)
        if norma_id is not None or options.mode == "semantic":
            rows = super().semantic_search(
                query_text=query_text,
                k=max(k, min(50, options.max_sources * 3)),
                norma_id=norma_id,
                min_similarity=min_similarity,
            )
            rows = self._filter_status(rows, options)
            for row in rows:
                row['retrieval_score'] = float(row.get('similarity_score') or 0.0)
                row['semantic_score'] = row['retrieval_score']
            return AdaptiveRetriever._select(rows, max_sources=min(k, options.max_sources), min_similarity=min_similarity)

        candidate_k = max(k, min(50, options.max_sources * 3))
        if options.mode == "lexical":
            rows = AdaptiveRetriever(self)._lexical(query_text, candidate_k, options)
            return AdaptiveRetriever._select(rows, max_sources=min(k, options.max_sources), min_similarity=min_similarity)

        semantic = super().semantic_search(
            query_text=query_text,
            k=candidate_k,
            norma_id=norma_id,
            min_similarity=min_similarity,
        )
        semantic = self._filter_status(semantic, options)
        for row in semantic:
            row['semantic_score'] = float(row.get('similarity_score') or 0.0)
            row['retrieval_score'] = row['semantic_score']
        lexical = AdaptiveRetriever(self)._lexical(query_text, candidate_k, options)
        rows = AdaptiveRetriever._merge(semantic, lexical, "hybrid")
        return AdaptiveRetriever._select(rows, max_sources=min(k, options.max_sources), min_similarity=min_similarity)

    @staticmethod
    def _filter_status(rows, options):
        filtered = []
        for row in rows:
            norma = getattr(row.get("dispositivo"), "norma", None)
            if options.norma_status != "all" and getattr(norma, "status", None) != options.norma_status:
                continue
            if options.source_scope != "all":
                url = str(getattr(norma, "sapl_url", "") or "").lower()
                if url and "sapl.natal.rn.leg.br" not in url:
                    continue
            filtered.append(row)
        return filtered

    def answer_question(
        self,
        question: str,
        k: int = 5,
        model=None,
        options: RetrievalOptions | None = None,
        force_refresh: bool = False,
    ):
        previous = getattr(self, "_jurix_retrieval_options", None)
        self._jurix_retrieval_options = options or RetrievalOptions(max_sources=k)
        try:
            return super().answer_question(
                question=question, k=k, model=model,
                force_refresh=force_refresh,
                retrieval_fingerprint=self._options().fingerprint(),
            )
        finally:
            self._jurix_retrieval_options = previous

    def stream_answer_question(self, question: str, k: int = 5, model=None, options: RetrievalOptions | None = None):
        previous = getattr(self, "_jurix_retrieval_options", None)
        self._jurix_retrieval_options = options or RetrievalOptions(max_sources=k)
        try:
            yield from super().stream_answer_question(
                question=question, k=k, model=model,
                retrieval_fingerprint=self._options().fingerprint(),
            )
        finally:
            self._jurix_retrieval_options = previous
