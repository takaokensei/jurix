"""Adaptive retrieval policy for Jurix RAG.

The old RAG path treated ``k=5`` as a promise to always return five sources.
That is a poor retrieval contract for legal search: a query may have one very
strong match, or twelve genuinely useful matches. This module treats ``k`` as
a *maximum candidate budget* and chooses the final context dynamically.

The module deliberately sits above ``RAGService.semantic_search``. It can
therefore be introduced without duplicating the pgvector SQL and without
breaking the existing fallback path.
"""
from __future__ import annotations

import math
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from django.db.models import Q, Case, When, Value, IntegerField

from src.apps.legislation.models import Dispositivo


_TOKEN_RE = re.compile(r"[\wÀ-ÿ]{3,}", flags=re.UNICODE)
_STOPWORDS = {
    "para", "como", "sobre", "entre", "essa", "este", "esta", "esse", "isso",
    "que", "uma", "por", "dos", "das", "com", "sem", "nos", "nas", "aos", "pelos",
    "pelas", "qual", "quais", "onde", "quando", "quem", "porque", "são", "ser", "tem",
    "mais", "menos", "muito", "muita", "muitas", "muitos", "uma", "um", "e", "ou",
}


@dataclass(frozen=True)
class RetrievalOptions:
    """Validated retrieval settings passed from API/UI to the RAG service."""

    mode: str = "hybrid"
    norma_status: str = "consolidated"
    source_scope: str = "municipal"
    max_sources: int = 12
    min_similarity: float = 0.0
    attachment_texts: tuple[str, ...] = field(default_factory=tuple)

    def fingerprint(self) -> str:
        attachment_digest = hashlib.sha256(
            "\x1f".join(self.attachment_texts).encode("utf-8")
        ).hexdigest()[:16] if self.attachment_texts else "none"
        return (
            f"retrieval=v2;mode={self.mode};status={self.norma_status};scope={self.source_scope};"
            f"max={self.max_sources};min={self.min_similarity:.3f};attachments={attachment_digest}"
        )


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "") if token.lower() not in _STOPWORDS}


def _lexical_score(question_tokens: set[str], text: str) -> float:
    if not question_tokens:
        return 0.0
    document_tokens = _tokens(text)
    overlap = question_tokens & document_tokens
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(question_tokens)
    density = len(overlap) / max(1.0, math.sqrt(len(document_tokens)))
    return max(0.0, min(1.0, (coverage * 0.75) + min(0.25, density)))


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return max(0.0, min(1.0, value))
    return max(0.0, min(1.0, (value - low) / (high - low)))


class AdaptiveRetriever:
    """Combine semantic/lexical retrieval and pick a variable number of sources."""

    def __init__(self, rag_service):
        self.rag_service = rag_service

    def retrieve(self, question: str, options: RetrievalOptions) -> list[dict[str, Any]]:
        max_sources = max(1, min(int(options.max_sources), 50))
        candidate_k = max(8, min(50, max_sources * 3))

        semantic = []
        lexical = []
        if options.mode in {"semantic", "hybrid"}:
            semantic = self._semantic(question, candidate_k, options)
        if options.mode in {"lexical", "hybrid"}:
            lexical = self._lexical(question, candidate_k, options)

        merged = self._merge(semantic, lexical, options.mode)
        return self._select(merged, max_sources=max_sources, min_similarity=options.min_similarity)

    @staticmethod
    def _in_scope(norma, options: RetrievalOptions) -> bool:
        if options.source_scope == "all":
            return True
        url = str(getattr(norma, "sapl_url", "") or "").lower()
        # The current Jurix corpus is municipal SAPL. This gate leaves room for
        # future external sources without pretending they are municipal law.
        return "sapl.natal.rn.leg.br" in url or not url

    def _semantic(self, question: str, candidate_k: int, options: RetrievalOptions) -> list[dict[str, Any]]:
        rows = self.rag_service.semantic_search(
            query_text=question,
            k=candidate_k,
            min_similarity=options.min_similarity,
        )
        result = []
        for row in rows:
            dispositivo = row.get("dispositivo")
            norma = getattr(dispositivo, "norma", None)
            if not dispositivo or not norma:
                continue
            if options.norma_status != "all" and getattr(norma, "status", None) != options.norma_status:
                continue
            if not self._in_scope(norma, options):
                continue
            copy = dict(row)
            copy["semantic_score"] = float(row.get("similarity_score") or 0.0)
            copy["lexical_score"] = 0.0
            copy["retrieval_score"] = copy["semantic_score"]
            result.append(copy)
        return result

    def _lexical(self, question: str, candidate_k: int, options: RetrievalOptions, norma_id=None) -> list[dict[str, Any]]:
        tokens = _tokens(question)
        if not tokens:
            return []

        query = Q()
        selected_tokens = sorted(tokens)[:12]
        for token in selected_tokens:
            query |= Q(texto__icontains=token)

        queryset = (
            Dispositivo.objects.select_related("norma", "dispositivo_pai")
            .filter(query)
        )
        if options.norma_status != "all":
            queryset = queryset.filter(norma__status=options.norma_status)
        if norma_id is not None:
            queryset = queryset.filter(norma_id=norma_id)
        if options.source_scope != "all":
            queryset = queryset.filter(
                Q(norma__sapl_url__icontains="sapl.natal.rn.leg.br") | Q(norma__sapl_url="")
            )
        coverage = sum(
            (Case(When(texto__icontains=token, then=Value(1)), default=Value(0),
                  output_field=IntegerField()) for token in selected_tokens), Value(0)
        )
        queryset = queryset.annotate(term_coverage=coverage).order_by(
            "-term_coverage", "id"
        )[:max(100, candidate_k * 8)]

        rows = []
        for dispositivo in queryset:
            norma = dispositivo.norma
            if options.norma_status != "all" and getattr(norma, "status", None) != options.norma_status:
                continue
            if not self._in_scope(norma, options):
                continue
            score = _lexical_score(tokens, dispositivo.texto)
            if score <= 0:
                continue
            rows.append(
                {
                    "dispositivo": dispositivo,
                    "lexical_score": score,
                    "semantic_score": 0.0,
                    "retrieval_score": score,
                    "similarity_score": score,
                    "distance": None,
                    "embedding_model": getattr(dispositivo, "embedding_model", None),
                    "context": {
                        "hierarchy": "",
                        "parent": getattr(getattr(dispositivo, "dispositivo_pai", None), "texto", None),
                    },
                }
            )
        rows.sort(key=lambda item: item["lexical_score"], reverse=True)
        return rows[:candidate_k]

    @staticmethod
    def _merge(semantic: list[dict[str, Any]], lexical: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
        by_id: dict[int, dict[str, Any]] = {}
        for row in semantic + lexical:
            dispositivo = row["dispositivo"]
            key = int(dispositivo.id)
            existing = by_id.get(key)
            if existing is None:
                by_id[key] = dict(row)
                continue
            existing["semantic_score"] = max(existing.get("semantic_score", 0.0), row.get("semantic_score", 0.0))
            existing["lexical_score"] = max(existing.get("lexical_score", 0.0), row.get("lexical_score", 0.0))
            if not existing.get("context") and row.get("context"):
                existing["context"] = row["context"]

        if not by_id:
            return []
        values = list(by_id.values())
        semantic_scores = [float(row.get("semantic_score", 0.0)) for row in values]
        lexical_scores = [float(row.get("lexical_score", 0.0)) for row in values]
        s_low, s_high = min(semantic_scores), max(semantic_scores)
        l_low, l_high = min(lexical_scores), max(lexical_scores)
        for row in values:
            s = _normalize(float(row.get("semantic_score", 0.0)), s_low, s_high)
            l = _normalize(float(row.get("lexical_score", 0.0)), l_low, l_high)
            if mode == "semantic":
                score = float(row.get("semantic_score", 0.0))
            elif mode == "lexical":
                score = float(row.get("lexical_score", 0.0))
            else:
                # Semantic retrieval carries more weight because it is the
                # stronger signal for legal paraphrases; lexical overlap keeps
                # exact article/number queries from disappearing.
                score = (0.72 * s) + (0.28 * l)
            row["retrieval_score"] = score
            row["similarity_score"] = score
        return sorted(values, key=lambda row: row["retrieval_score"], reverse=True)

    @staticmethod
    def _select(rows: Iterable[dict[str, Any]], max_sources: int, min_similarity: float) -> list[dict[str, Any]]:
        ranked = list(rows)
        if not ranked:
            return []

        top = float(ranked[0].get("retrieval_score", 0.0))
        # A source survives when it is close enough to the top result. This
        # deliberately avoids the fixed "always 5 sources" behavior.
        threshold = max(float(min_similarity), top * 0.65, top - 0.10)
        selected: list[dict[str, Any]] = []
        norma_counts: dict[int, int] = {}

        for row in ranked:
            score = float(row.get("retrieval_score", 0.0))
            if score < threshold:
                break
            dispositivo = row["dispositivo"]
            norma_id = int(getattr(dispositivo, "norma_id", 0) or 0)
            if norma_counts.get(norma_id, 0) >= 4:
                continue
            selected.append(row)
            norma_counts[norma_id] = norma_counts.get(norma_id, 0) + 1
            if len(selected) >= max_sources:
                break

        # Preserve a single strong source even when its score is low in an
        # absolute sense. The purpose of min_similarity is to *filter* weak
        # hits, not to manufacture a minimum source count.
        if not selected and ranked and float(ranked[0].get("retrieval_score", 0.0)) >= min_similarity:
            selected.append(ranked[0])
        return selected


def attachment_context(texts: Iterable[str], max_chars: int = 12_000) -> str:
    """Build a bounded context block from temporary user attachments."""
    chunks: list[str] = []
    remaining = max_chars
    for index, text in enumerate(texts, 1):
        if not text or remaining <= 0:
            continue
        clean = str(text).strip()
        if not clean:
            continue
        piece = clean[:remaining]
        chunks.append(f"[DOCUMENTO ANEXADO {index}]\n{piece}")
        remaining -= len(piece)
    return "\n\n".join(chunks)
