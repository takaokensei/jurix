"""Retrieval over unreviewed archive PDFs, available only in isolated QA settings."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

from django.conf import settings
from django.urls import reverse

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma
from src.apps.legislation.source_urls import canonical_norma_url
from src.processing.normative_query import classify_normative_query
from src.processing.normative_reference import normalize_number, parse_normative_references
from src.processing.rag_answer_pipeline import (
    raise_if_cancelled,
    run_grounded_generation,
    stream_model_attempt,
)
from src.processing.rag_prompt import build_prompt

_WORD_RE = re.compile(r"[a-z0-9]{2,}")
_ARTICLE_RE = re.compile(r"\bart(?:igo)?\.?\s*(\d{1,4})\s*[º°ªo]?", re.IGNORECASE)
_STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "essa", "esse", "esta", "este", "na", "nas", "no",
    "nos", "o", "os", "ou", "para", "pela", "pelo", "por", "que", "qual",
    "se", "sobre", "um", "uma", "uns", "umas", "art", "artigo", "lei",
    "municipal", "municipais", "municipio", "natal", "sera", "serao",
}
_QUERY_FRAMING = {
    "artigo", "diz", "dispoe", "estabelece", "estabelecem", "faca", "falar",
    "inteira", "mostra", "norma", "preve", "qual", "resuma", "resumo", "trata",
    "artigos", "cada", "centrais", "conteudo", "cobrindo", "indicando",
    "principais", "ponto", "pontos", "quais", "sintese", "sintetize",
    "sustentam", "temas", "visao", "geral", "panorama", "integral", "indique",
    "dispositivos", "lc", "eixo", "eixos", "sao",
    # Normative type words identify the document; they are not topical terms
    # that should exclude every article when the user asks about the whole law.
    "complementar", "decreto", "decretos", "legislativo", "ordinaria",
    "organica", "promulgada", "resolucao", "portaria",
}
_TYPE_LABELS = {
    "lei": "Lei",
    "lei_ordinaria": "Lei Ordinária",
    "lei_complementar": "Lei Complementar",
    "lei_organica": "Lei Orgânica",
    "decreto": "Decreto",
    "decreto_lei": "Decreto-Lei",
    "decreto_legislativo": "Decreto Legislativo",
    "resolucao": "Resolução",
    "portaria": "Portaria",
}
_TYPE_ALIASES = {
    "lei": {"lei", "lei_ordinaria"},
}
_WHOLE_NORM_CONTEXT_BUDGET_CHARS = 24_000
_WHOLE_NORM_MAX_ARTICLES = 20


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _tokens(value: str) -> set[str]:
    return {word for word in _WORD_RE.findall(_fold(value)) if word not in _STOPWORDS}


def _candidate_identity(document: DocumentoNormativo) -> dict:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity = metadata.get("identity_candidate")
    return identity if isinstance(identity, dict) else {}


def _latest_extraction(document: DocumentoNormativo) -> ExtracaoDocumento | None:
    return document.extracoes.order_by("-created_at", "-pk").first()


def _article_rows(text: str) -> list[dict]:
    from src.processing.legal_parser import (
        LegalTextParser,
        find_normative_appendix_start,
        strip_closing_editorial_metadata,
    )

    source = strip_closing_editorial_metadata(LegalTextParser.strip_page_artifacts(text))
    elements = LegalTextParser.parse_legal_text(source)
    appendix_start = find_normative_appendix_start(source)
    division_starts = [
        match.start()
        for pattern in LegalTextParser.DIVISION_PATTERNS.values()
        for match in pattern.finditer(source)
    ]
    articles = [
        row for row in elements
        if row.get("tipo") == "artigo"
        and (appendix_start is None or row["start_pos"] < appendix_start)
    ]
    child_labels = {
        "paragrafo": lambda number: "Parágrafo único" if number == "único" else f"§ {number}",
        "inciso": lambda number: f"Inciso {number}",
        "alinea": lambda number: f"Alínea {number})",
        "item": lambda number: f"Item {number}",
    }
    complete_articles = []
    for index, article in enumerate(articles):
        next_article_start = (
            articles[index + 1]["start_pos"] if index + 1 < len(articles) else float("inf")
        )
        article_end = min(
            next_article_start,
            appendix_start if appendix_start is not None else float("inf"),
            min(
                (start for start in division_starts if start > article["start_pos"]),
                default=float("inf"),
            ),
        )
        article_text = str(article.get("texto") or "").strip()
        if article_end < float("inf"):
            article_text_start = article["start_pos"] + len(str(article.get("full_match") or ""))
            article_text = source[article_text_start:article_end].strip()
        descendants = [
            row for row in elements
            if article["start_pos"] < row["start_pos"] < article_end
            and row.get("tipo") in child_labels
        ]
        parts = [article_text]
        parts.extend(
            f"{child_labels[row['tipo']](str(row.get('numero') or '').strip())} — "
            f"{str(row.get('texto') or '').strip()}"
            for row in descendants
            if str(row.get("texto") or "").strip()
        )
        complete_articles.append({
            **article,
            "texto": "\n".join(part for part in parts if part),
            "annexes_present": appendix_start is not None,
        })
    return complete_articles


def _sample_whole_norm_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Sample a large norm evenly in legal order within the QA context budget."""
    total = len(rows)
    if total <= _WHOLE_NORM_MAX_ARTICLES:
        return rows, total
    average_chars = max(1, sum(len(str(row.get("full_text") or "")) for row in rows) // total)
    budget_count = max(1, _WHOLE_NORM_CONTEXT_BUDGET_CHARS // average_chars)
    sample_size = min(total, _WHOLE_NORM_MAX_ARTICLES, budget_count)
    if sample_size >= total:
        return rows, total
    if sample_size == 1:
        indexes = [total // 2]
    else:
        indexes = [round(index * (total - 1) / (sample_size - 1)) for index in range(sample_size)]
    return [rows[index] for index in indexes], total


def retrieve_archive_evidence(question: str, *, limit: int = 8) -> list[dict]:
    """Return lexically ranked article evidence from the isolated archive only."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False):
        return []

    query_tokens = _tokens(question)
    if not query_tokens:
        return []
    references = [ref for ref in parse_normative_references(question) if not ref.ambiguous]
    exact_ref = references[0] if len(references) == 1 else None
    explicit_years = set(re.findall(r"\b(?:19|20)\d{2}\b", _fold(question)))
    article_match = _ARTICLE_RE.search(question)
    wanted_article = normalize_number(article_match.group(1)) if article_match else None
    topic_tokens = set(query_tokens)
    if exact_ref:
        topic_tokens -= _tokens(f"{exact_ref.number} {exact_ref.year}")
    topic_tokens -= _QUERY_FRAMING
    whole_norm_request = bool(
        exact_ref
        and not wanted_article
        and (
            not topic_tokens
            or classify_normative_query(question).is_norma_overview
        )
    )

    documents = list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            norma__isnull=True,
            review_status__in=(
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            ),
        ).order_by("entry_index", "pk")[:40]
    )
    identity_keys = {
        str((document.metadata_json or {}).get("identity_key"))
        for document in documents
        if isinstance(document.metadata_json, dict)
        and document.metadata_json.get("identity_key")
        and not document.conflicts_json
    }
    sapl_normas_by_identity = {}
    if identity_keys and getattr(settings, "NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED", False):
        sapl_normas_by_identity = {
            norma.identity_key: norma
            for norma in Norma.objects.filter(
                identity_key__in=identity_keys,
                sapl_id__isnull=False,
            ).only("identity_key", "sapl_id", "sapl_url", "pdf_url")
        }
    rows = []
    for document in documents:
        identity = _candidate_identity(document)
        if exact_ref:
            candidate_number = normalize_number(str(identity.get("number") or ""))
            try:
                candidate_year = int(identity.get("year"))
            except (TypeError, ValueError):
                candidate_year = None
            if (
                candidate_number != exact_ref.number
                or candidate_year != exact_ref.year
                or (
                    exact_ref.type_key
                    and identity.get("type") not in _TYPE_ALIASES.get(
                        exact_ref.type_key, {exact_ref.type_key}
                    )
                )
            ):
                continue

        extraction = _latest_extraction(document)
        if extraction is None or extraction.status not in {
            ExtracaoDocumento.Status.COMPLETE,
            ExtracaoDocumento.Status.PARTIAL,
        }:
            continue
        legal_text = extraction.legal_text.strip()
        if len(legal_text) < 80:
            continue
        articles = _article_rows(legal_text)
        if wanted_article:
            articles = [
                row for row in articles
                if normalize_number(str(row.get("numero") or "")) == wanted_article
            ]
            if not articles:
                continue
        if not articles:
            articles = [{"tipo": "texto", "numero": "", "texto": legal_text[:2400]}]

        type_key = str(identity.get("type") or "")
        type_label = _TYPE_LABELS.get(type_key, "Norma importada")
        number = str(identity.get("number") or "?")
        year = str(identity.get("year") or "ano não identificado")
        norma_ref = f"{type_label} nº {number}/{year}"
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity_conflict = bool(document.conflicts_json or not metadata.get("identity_key"))
        matched_norma = (
            sapl_normas_by_identity.get(metadata.get("identity_key"))
            if not identity_conflict else None
        )
        configured_sapl = urlparse(getattr(settings, "SAPL_BASE_URL", ""))
        sapl_url = canonical_norma_url(matched_norma) if matched_norma else None
        if sapl_url:
            sapl_parts = urlparse(sapl_url)
            if (
                sapl_parts.scheme != "https"
                or not configured_sapl.hostname
                or sapl_parts.hostname != configured_sapl.hostname
                or not re.fullmatch(r"/norma/\d+/?", sapl_parts.path)
            ):
                sapl_url = None
        official_pdf_url = str(getattr(matched_norma, "pdf_url", "") or "").strip()
        pdf_parts = urlparse(official_pdf_url) if official_pdf_url else None
        if official_pdf_url and (
            pdf_parts.scheme != "https"
            or not configured_sapl.hostname
            or pdf_parts.hostname != configured_sapl.hostname
            or not pdf_parts.path.startswith("/media/sapl/public/normajuridica/")
        ):
            official_pdf_url = ""

        for article_order, article in enumerate(articles):
            text = str(article.get("texto") or "").strip()
            if len(text) < 30:
                continue
            if explicit_years and not exact_ref:
                candidate_year = str(identity.get("year") or "")
                year_supported = any(
                    year == candidate_year
                    or re.search(rf"(?<!\d){re.escape(year)}(?!\d)", text)
                    for year in explicit_years
                )
                if not year_supported:
                    continue
            overlap = len(query_tokens & _tokens(text)) / max(len(query_tokens), 1)
            topic_overlap = len(topic_tokens & _tokens(text)) / max(len(topic_tokens), 1) if topic_tokens else 0.0
            score = topic_overlap if exact_ref and topic_tokens and not wanted_article else overlap
            if exact_ref and (wanted_article or not topic_tokens):
                score += 1.0
            if wanted_article:
                score += 1.0
            if identity_conflict:
                score *= 0.8
            article_number = str(article.get("numero") or "")
            device_ref = f"Art. {article_number}" if article_number else "Trecho extraído"
            stable_id = hashlib.sha256(
                f"{document.public_id}:{extraction.extraction_sha256}:{article.get('start_pos', 0)}".encode()
            ).hexdigest()[:24]
            rows.append({
                "id": stable_id,
                "source_id": str(document.public_id),
                "citation_id": f"qa:{stable_id}",
                "citation_label": f"{norma_ref}, {device_ref}",
                "norma_ref": norma_ref,
                "dispositivo_ref": device_ref,
                "texto": text,
                "full_text": text,
                "evidence_text": text,
                "similarity_score": min(score, 1.0),
                "_topic_overlap": topic_overlap,
                "contribution": "Trecho da extração do PDF arquivado; transcrição pendente de revisão",
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "retrieval_strategy": "qa_archive_lexical",
                "evidence_scope": "isolated_qa_archive",
                "coverage": {
                    "extraction_status": extraction.status,
                    "identity_conflict": identity_conflict,
                    "annexes_present": article.get("annexes_present", False),
                    "annexes_included_in_article_evidence": False,
                },
                "page_index": article.get("page_index"),
                "_device_order": article.get("start_pos", article_order),
                "local_pdf_url": reverse(
                    "legislation:document_pdf",
                    kwargs={"document_id": document.public_id},
                ),
                "pdf_url": official_pdf_url or None,
                "sapl_url": sapl_url,
                "data_publicacao": None,
                "data_vigencia": None,
            })

    rows.sort(key=lambda item: (item["similarity_score"], item["norma_ref"], item["dispositivo_ref"]), reverse=True)
    if whole_norm_request:
        # A whole-norm request is not constrained by the normal top-k. Small
        # norms return every parsed article; large norms are sampled across the
        # document and explicitly carry incomplete-coverage metadata.
        rows.sort(key=lambda item: (item["norma_ref"], item["source_id"], item["_device_order"]))
        rows, total_articles = _sample_whole_norm_rows(rows)
        selected_articles = len(rows)
        annexes_present = any(row["coverage"].get("annexes_present") for row in rows)
        complete = selected_articles == total_articles and not annexes_present
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "corpus": "acervo histórico local (lote de 40 documentos)",
                "complete": complete,
                "annexes_present": annexes_present,
                "selected_articles": selected_articles,
                "total_articles": total_articles,
            }
    elif exact_ref and not wanted_article:
        if topic_tokens:
            # A question about a topic within a named law should rank only
            # devices that actually overlap the topic; law identity alone must
            # not make every article look like a high-relevance match.
            rows = [row for row in rows if row["_topic_overlap"] >= 0.12]
            rows.sort(key=lambda item: (item["_topic_overlap"], item["dispositivo_ref"]), reverse=True)
        rows = rows[: max(1, min(limit, 12))]
    elif exact_ref and wanted_article:
        rows = rows[: min(limit, 4)]
    else:
        rows = [row for row in rows if row["similarity_score"] >= 0.12][:limit]
    for row in rows:
        row.pop("_topic_overlap", None)
        row.pop("_device_order", None)
    return rows


def stream_archive_qa_answer(
    question: str,
    *,
    k: int,
    model: str,
    temperature: float,
    text_provider: dict | None,
    ollama,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[dict]:
    """Generate a grounded streaming answer from imported QA PDFs."""
    started = time.perf_counter()
    yield {"event": "status", "status": "retrieving"}
    results = retrieve_archive_evidence(question, limit=max(k, 8))
    retrieval_ms = round((time.perf_counter() - started) * 1000)
    if not results:
        answer = "Não encontrei um trecho legível correspondente nos PDFs disponíveis no acervo histórico local. Confira o número da norma e do artigo ou tente outra formulação."
        yield {"event": "status", "status": "insufficient_evidence"}
        yield {"event": "sources", "sources": [], "confidence": None, "reason_code": "qa_archive_no_match", "coverage": {"corpus": "acervo histórico local (lote de 40 documentos)"}}
        yield {"event": "chunk", "chunk": answer, "provisional": False}
        yield {"event": "done", "answer": answer, "sources": [], "grounded": False, "reason_code": "qa_archive_no_match", "grounding": {"grounded": False, "claims": [], "failed_claims": []}, "timings_ms": {"retrieval": retrieval_ms}}
        return

    yield {
        "event": "sources",
        "sources": results,
        "confidence": None,
        "cached": False,
        "retrieval_strategy": "qa_archive_lexical",
        "coverage": {
            **(results[0].get("coverage") or {}),
            "corpus": "acervo histórico local (lote de 40 documentos)",
            "sources_retrieved": len(results),
        },
    }

    # For an explicitly identified article, quote the retrieved PDF text rather
    # than asking a small local model to paraphrase it. This makes the first QA
    # MVP useful even when Ollama's claim validator rejects a semantically sound
    # paraphrase, and it cannot add facts absent from the extracted article.
    exact_references = [ref for ref in parse_normative_references(question) if not ref.ambiguous]
    article_match = _ARTICLE_RE.search(question)
    if len(exact_references) == 1 and article_match and len(results) == 1:
        source = results[0]
        text = str(source.get("full_text") or "").strip()
        if text:
            answer = (
                f'O trecho extraído como **{source["dispositivo_ref"]}** de '
                f'**{source["norma_ref"]}** dispõe: “{text}” [[1]]\n\n'
                "*Transcrição extraída do PDF arquivado; metadados e segmentação ainda estão sob revisão.*"
            )
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": results,
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [{"text": text, "citation_ids": [source["citation_id"]]}],
                    "failed_claims": [],
                    "validation_scope": "verbatim_quote_from_unreviewed_archive_pdf",
                },
                "reason_code": "qa_archive_verbatim_article",
                "source_relevance": source["similarity_score"],
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    context = "\n\n".join(
        f"[[{index}]] {row['norma_ref']}, {row['dispositivo_ref']} — trecho da extração do PDF arquivado; metadados e segmentação sob revisão:\n{row['full_text']}"
        for index, row in enumerate(results, 1)
    )
    coverage = results[0].get("coverage") or {}
    coverage_prompt_note = ""
    coverage_disclosure = ""
    if coverage.get("complete") is False:
        if coverage.get("selected_articles") != coverage.get("total_articles"):
            selected = coverage.get("selected_articles")
            total = coverage.get("total_articles")
            coverage_prompt_note = (
                f"Cobertura parcial: a amostra contém {selected} de {total} artigos identificados. "
            )
            coverage_disclosure = f"A amostra consultada cobre {selected} de {total} artigos identificados. "
        if coverage.get("annexes_present"):
            coverage_prompt_note += (
                "O PDF contém anexos normativos que não foram incluídos na seleção de artigos. "
            )
            coverage_disclosure += (
                "Anexos normativos também foram detectados no PDF e devem ser consultados à parte. "
            )
        coverage_prompt_note += "Não apresente a amostra como análise integral da norma."
        context += "\n\n[ESCOPO DA RECUPERAÇÃO] " + coverage_prompt_note
    prompt = build_prompt(context, question)
    from src.processing.rag_service import RAGService

    validator = RAGService()
    yield {"event": "status", "status": "generating"}
    generation = run_grounded_generation(
        prompt,
        stream_attempt=lambda prompt_text: stream_model_attempt(
            prompt_text,
            ollama=ollama,
            model=model,
            temperature=temperature,
            text_provider=text_provider,
            should_cancel=should_cancel,
        ),
        validate_attempt=lambda answer: validator._validate_answer(answer, results),
        should_cancel=should_cancel,
    )
    raise_if_cancelled(should_cancel)
    grounded = bool(generation["grounding"].get("grounded")) and generation["source_only"]
    if grounded:
        answer = generation["answer"]
        if coverage_disclosure:
            answer += "\n\n" + coverage_disclosure.rstrip()
        grounding_report = generation["grounding"]
        reason_code = None
    else:
        # When a generated synthesis cannot be grounded, return a concise map
        # to the retrieved provisions instead of dumping every PDF excerpt.
        references_by_norma = {}
        for index, source in enumerate(results, 1):
            if not str(source.get("full_text") or "").strip():
                continue
            norma_ref = str(source.get("norma_ref") or "Norma consultada")
            dispositivo_ref = str(source.get("dispositivo_ref") or "trecho")
            references_by_norma.setdefault(norma_ref, []).append(
                f"{dispositivo_ref} [[{index}]]"
            )
        reference_groups = [
            f"**{norma_ref}**: {', '.join(dispositivos)}"
            for norma_ref, dispositivos in references_by_norma.items()
        ]
        selected_articles = coverage.get("selected_articles")
        total_articles = coverage.get("total_articles")
        partial_norm_overview = (
            coverage.get("complete") is False
            and isinstance(selected_articles, int)
            and isinstance(total_articles, int)
            and selected_articles < total_articles
        )
        if partial_norm_overview:
            answer = (
                "Não consegui montar uma síntese confiável a partir da amostra disponível. "
                f"Ela reúne trechos de {selected_articles} dos {total_articles} artigos "
                "identificados na extração. "
            )
            if coverage.get("annexes_present"):
                answer += "O PDF também contém anexos que não entraram nessa seleção. "
            answer += (
                "Abra Fontes Consultadas para conferir os trechos originais ou pergunte "
                "sobre um artigo específico."
            )
        else:
            answer = "Localizei dispositivos que podem ajudar a conferir essa questão: "
            answer += "; ".join(reference_groups) + "."
            answer += (
                " Abra os links para conferir o texto no PDF do acervo histórico local. "
                "Como a extração ainda está em revisão, apresento esses dispositivos como pontos de consulta, "
                "não como uma síntese validada."
            )
            if coverage_disclosure:
                answer += " " + coverage_disclosure.rstrip()
        grounding_report = {
            "grounded": bool(reference_groups),
            "score": 0.0,
            "claims": [
                {
                    "text": f"Dispositivo localizado: {source.get('norma_ref')}, {source.get('dispositivo_ref')}",
                    "citation_ids": [source["citation_id"]],
                }
                for source in results
                if source.get("full_text") and source.get("citation_id")
            ],
            "failed_claims": [],
            "validation_scope": "retrieved_source_index_only_after_synthesis_rejected",
        }
        grounded = bool(reference_groups)
        reason_code = "qa_archive_evidence_only_fallback"
    yield {"event": "status", "status": "grounding" if grounded else "insufficient_evidence"}
    for offset in range(0, len(answer), 72):
        raise_if_cancelled(should_cancel)
        yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
    yield {"event": "status", "status": "finalizing"}
    yield {
        "event": "done",
        "answer": answer,
        "sources": results if grounded else [],
        "grounded": grounded,
        "grounding": grounding_report,
        "reason_code": reason_code,
        "source_relevance": max(row["similarity_score"] for row in results),
        "timings_ms": {"retrieval": retrieval_ms, "generation": sum(attempt["duration_ms"] for attempt in generation["generation_attempts"])},
        "generation_attempts": generation["generation_attempts"],
    }
