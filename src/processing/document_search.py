"""Bounded lexical search over unpromoted local archive documents.

This surface is deliberately separate from normative search: a filename-derived
identity and machine extraction are discovery aids, never reviewed legal facts.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, Value, When

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.normative_reference import canonical_type

ARCHIVE_PAGE_SIZE = 20
MAX_ARCHIVE_QUERY_LENGTH = 200
MAX_QUERY_GROUPS = 10
ARCHIVE_EXCERPT_LENGTH = 360
ARCHIVE_EXCERPT_CONTEXT = 170
_TOKEN_RE = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)
_PAGE_MARKER_RE = re.compile(r"---\s*Página\s+(\d+)\s*---", re.IGNORECASE)
_ARTICLE_QUERY_RE = re.compile(r"\b(?:art(?:igo)?\.?)\s*0*(\d+)", re.IGNORECASE)
_IDENTITY_QUERY_RE = re.compile(
    r"(?P<type>lei\s+(?:complementar|ordinaria|organica|promulgada)|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?|resolucao|portaria|lc)?"
    r"\s*(?:municipal(?:\s+de\s+natal)?|do\s+municipio(?:\s+de\s+natal)?)?"
    r"\s*(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)"
    r"\s*(?:/|de|\s)\s*(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_BARE_NUMBER_QUERY_RE = re.compile(r"\s*(?P<number>\d[\d.]*)\s*")
_SYNONYMS = {
    # Bare singular "resíduo" is polysemous in legal text (e.g. a residual
    # salary amount). Keep waste discovery broad without matching that sense.
    "lixo": ("lixo", "resíduos", "residuos", "resíduo sólido", "residuo solido"),
    "residuo": ("resíduo", "resíduos", "residuo", "residuos", "lixo"),
    "residuos": ("resíduo", "resíduos", "residuo", "residuos", "lixo"),
    "saneamento": ("saneamento", "esgoto", "esgotamento"),
    "esgoto": ("esgoto", "saneamento", "esgotamento"),
    "esgotamento": ("esgotamento", "esgoto", "saneamento"),
}
_STOPWORDS = {
    "para", "como", "sobre", "entre", "uma", "que", "com", "dos", "das", "de", "e", "em", "lei",
    "qual", "quais", "quando", "onde", "preve", "diz", "trata", "artigo",
    "art", "norma", "municipal", "natal",
}
_ACCENT_CLASS = {
    "a": "[aàáâãä]",
    "e": "[eèéêë]",
    "i": "[iìíîï]",
    "o": "[oòóôõö]",
    "u": "[uùúûü]",
    "c": "[cç]",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _accent_tolerant_pattern(term: str) -> str:
    """Build a literal SQL-regex term that matches Portuguese accent variants."""
    folded = _fold(term)
    return "".join(_ACCENT_CLASS.get(char, re.escape(char)) for char in folded)


def _query_groups(query: str) -> tuple[tuple[str, ...], ...]:
    tokens = []
    for raw_token in _TOKEN_RE.findall(query):
        token = _fold(raw_token)
        # NFKD folding turns the ordinal marker in "1º" into a trailing "o".
        # Normalize only numeric ordinals so the text search can match "Art. 1º".
        if re.fullmatch(r"\d+o", token):
            token = token[:-1]
        if token not in tokens:
            tokens.append(token)
    return tuple(
        _SYNONYMS.get(token, (token,))
        for token in tokens
        if token not in _STOPWORDS
    )[:MAX_QUERY_GROUPS]


def _structured_identity(query: str) -> tuple[str, str, int] | None:
    """Recognize an explicit norm number/year before broad lexical matching."""
    match = _IDENTITY_QUERY_RE.search(_fold(query))
    if not match:
        return None
    raw_type = (match.group("type") or "").strip()
    number = re.sub(r"\D", "", match.group("number"))
    return canonical_type(raw_type), number, int(match.group("year"))


def _without_explicit_norm_identity(query: str) -> str:
    """Remove a matched norm's identity so it cannot dominate its excerpt.

    Identity is already resolved structurally for candidate selection. Keeping
    its number/year/type in the snippet query can pull the excerpt toward the
    epigraph, where those tokens are repeated, instead of the requested article.
    Preserve the rest of the user's wording (including article and topic).
    """
    folded_parts: list[str] = []
    original_positions: list[int] = []
    for index, char in enumerate(query):
        folded_char = _fold(char)
        folded_parts.append(folded_char)
        original_positions.extend([index] * len(folded_char))
    folded_query = "".join(folded_parts)
    match = _IDENTITY_QUERY_RE.search(folded_query)
    if not match or match.end() <= match.start():
        return query
    start = original_positions[match.start()]
    end = original_positions[match.end() - 1] + 1
    return f"{query[:start]} {query[end:]}".strip()


def _term_query(terms: tuple[str, ...]) -> Q:
    query = Q()
    for term in terms:
        query |= (
            Q(original_filename__icontains=term)
            | Q(entry_name__icontains=term)
            | Q(source_ref__icontains=term)
            | Q(metadata_json__identity_candidate__type__icontains=term)
            | Q(metadata_json__identity_candidate__number__icontains=term)
            | Q(metadata_json__identity_candidate__year__icontains=term)
            | Q(latest_legal_text__iregex=_accent_tolerant_pattern(term))
        )
    return query


def _full_text_query(groups: tuple[tuple[str, ...], ...]) -> SearchQuery | None:
    """Build an AND query with OR alternatives for the controlled synonyms."""
    combined = None
    for group in groups:
        alternatives = None
        for term in group:
            part = SearchQuery(term, config="portuguese", search_type="plain")
            alternatives = part if alternatives is None else alternatives | part
        if alternatives is not None:
            combined = alternatives if combined is None else combined & alternatives
    return combined


def _group_occurrences(text: str, group: tuple[str, ...]) -> list[int]:
    positions: set[int] = set()
    for term in group:
        pattern = re.compile(_accent_tolerant_pattern(term), re.IGNORECASE)
        positions.update(match.start() for match in pattern.finditer(text))
    return sorted(positions)


def _text_proximity_rank(
    text: str, groups: tuple[tuple[str, ...], ...]
) -> tuple[int, int, int]:
    """Rank matching passages portably when PostgreSQL full-text rank is unavailable."""
    alternative_matches = sum(
        bool(_group_occurrences(text, (alternative,)))
        for group in groups
        for alternative in group
    )
    positions = [
        _group_occurrences(text, group)
        for group in groups
    ]
    entries = sorted(
        (position, group_index)
        for group_index, group_positions in enumerate(positions)
        for position in group_positions
    )
    matched_group_count = len({group_index for _, group_index in entries})
    if not matched_group_count:
        return (alternative_matches, 0, -len(text))
    if matched_group_count < len(groups):
        return (alternative_matches, matched_group_count, -len(text))

    counts: dict[int, int] = {}
    left = 0
    narrowest = len(text)
    for position, group_index in entries:
        counts[group_index] = counts.get(group_index, 0) + 1
        while len(counts) == len(groups):
            narrowest = min(narrowest, position - entries[left][0])
            left_group = entries[left][1]
            counts[left_group] -= 1
            if counts[left_group] == 0:
                del counts[left_group]
            left += 1
    return (alternative_matches, matched_group_count, -narrowest)


def _archive_excerpt(
    text: str,
    groups: tuple[tuple[str, ...], ...],
    *,
    article_number: str | None = None,
) -> dict:
    """Choose a short local context around the densest actual text matches.

    Archive candidates are retained by document-level lexical matching. This
    excerpt makes clear which passage caused discovery instead of always
    showing the PDF's first page, which is often unrelated boilerplate.
    """
    value = str(text or "")
    preview = value[:ARCHIVE_EXCERPT_LENGTH].strip()
    if not value or not groups:
        return {"excerpt": preview, "excerpt_page": None, "excerpt_matched": False}

    occurrences = [_group_occurrences(value, group) for group in groups]
    anchors = sorted({position for group_positions in occurrences for position in group_positions})
    if not anchors:
        return {"excerpt": preview, "excerpt_page": None, "excerpt_matched": False}

    best_anchor = anchors[0]
    best_score = (-1, -1)
    article_matches = []
    if article_number:
        article_pattern = re.compile(
            rf"\bart(?:igo)?\.?\s*0*{re.escape(article_number)}(?!\d)",
            re.IGNORECASE,
        )
        article_matches = list(article_pattern.finditer(value))

    candidate_anchors = [match.start() for match in article_matches] or anchors
    for anchor in candidate_anchors:
        window_start = max(0, anchor - ARCHIVE_EXCERPT_CONTEXT)
        window_end = min(len(value), window_start + ARCHIVE_EXCERPT_LENGTH)
        if article_matches:
            window_start = anchor
            window_end = min(len(value), anchor + ARCHIVE_EXCERPT_LENGTH)
        matched_groups = 0
        matched_occurrences = 0
        for group_positions in occurrences:
            left = bisect_left(group_positions, window_start)
            right = bisect_right(group_positions, window_end)
            if right > left:
                matched_groups += 1
                matched_occurrences += right - left
        score = (matched_groups, matched_occurrences)
        if score > best_score:
            best_score = score
            best_anchor = anchor
            if matched_groups == len(groups) and matched_occurrences >= len(groups):
                break

    start = best_anchor if article_matches else max(0, best_anchor - ARCHIVE_EXCERPT_CONTEXT)
    if start and not article_matches:
        boundary = value.rfind(" ", start, min(len(value), start + 40))
        if boundary >= start:
            start = boundary + 1
    end = min(len(value), start + ARCHIVE_EXCERPT_LENGTH)
    if end < len(value):
        boundary = value.rfind(" ", max(start, end - 40), end)
        if boundary > start:
            end = boundary
    excerpt = value[start:end].strip()
    marker = None
    for page_marker in _PAGE_MARKER_RE.finditer(value, 0, best_anchor + 1):
        marker = page_marker
    return {
        "excerpt": excerpt or preview,
        "excerpt_page": int(marker.group(1)) if marker else None,
        "excerpt_matched": best_score[0] > 0,
    }


def search_archive_documents(
    query: str,
    *,
    page: int | str = 1,
    document_type: str = "",
    year: int | None = None,
    review_status: str = "",
    extraction_status: str = "",
    include_results: bool = True,
):
    """Return one bounded page of archive candidates, with latest text excerpts.

    Searches SQL-side metadata and the latest extraction only; PDF bytes and the
    full document set are never loaded into application memory. Every matching
    candidate is retained in the paginated query, including partial extracts.
    """
    normalized_query = str(query or "").strip()
    if len(normalized_query) > MAX_ARCHIVE_QUERY_LENGTH:
        raise ValueError("A busca de documentos locais aceita até 200 caracteres.")

    latest_extraction = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )
    archive_candidates = DocumentoNormativo.objects.filter(
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        norma__isnull=True,
        review_status__in=(
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        ),
    )
    available_types = sorted(
        {
            value
            for value in archive_candidates.values_list(
                "metadata_json__identity_candidate__type", flat=True
            ).distinct()
            if value
        }
    )
    available_years = sorted(
        {
            int(value)
            for value in archive_candidates.values_list(
                "metadata_json__identity_candidate__year", flat=True
            ).distinct()
            if isinstance(value, int) and 1000 <= value <= 9999
        },
        reverse=True,
    )
    total_candidates = archive_candidates.count()
    candidates = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            norma__isnull=True,
            review_status__in=(
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            ),
        )
        .annotate(
            latest_legal_text=Subquery(latest_extraction.values("legal_text")[:1]),
            latest_extraction_status=Subquery(latest_extraction.values("status")[:1]),
            latest_page_count=Subquery(latest_extraction.values("page_count")[:1]),
        )
    )

    if document_type:
        type_key = canonical_type(document_type)
        candidates = candidates.filter(metadata_json__identity_candidate__type=type_key)
    if year is not None:
        candidates = candidates.filter(metadata_json__identity_candidate__year=year)
    if review_status in {
        DocumentoNormativo.ReviewStatus.PENDING,
        DocumentoNormativo.ReviewStatus.IN_REVIEW,
    }:
        candidates = candidates.filter(review_status=review_status)
    if extraction_status == "none":
        candidates = candidates.filter(latest_extraction_status__isnull=True)
    elif extraction_status in ExtracaoDocumento.Status.values:
        candidates = candidates.filter(latest_extraction_status=extraction_status)

    identity = _structured_identity(normalized_query)
    bare_number = _BARE_NUMBER_QUERY_RE.fullmatch(normalized_query)
    groups = _query_groups(normalized_query)
    article_match = _ARTICLE_QUERY_RE.search(normalized_query)
    requested_article = str(int(article_match.group(1))) if article_match else None
    excerpt_groups = (
        _query_groups(_without_explicit_norm_identity(normalized_query))
        if identity
        else groups
    )
    expanded = any(len(group) > 1 for group in groups)
    if not include_results:
        return {
            "page": None,
            "results": [],
            "count": 0,
            "total_candidates": total_candidates,
            "expanded": expanded,
            "groups": groups,
            "types": available_types,
            "years": available_years,
        }
    if identity:
        type_key, number, identity_year = identity
        # Archive filenames/metadata are inconsistent about zero-padding. Treat
        # 55 and 055 as the same numeric identity for lookup, without changing
        # the candidate's displayed number or relaxing type/year matching.
        canonical_number = number.lstrip("0") or "0"
        number_match = Q(
            metadata_json__identity_candidate__number=canonical_number
        ) | Q(
            metadata_json__identity_candidate__number__regex=(
                rf"^0*{re.escape(canonical_number)}$"
            )
        )
        candidates = candidates.filter(
            number_match,
            metadata_json__identity_candidate__year=identity_year,
        )
        if type_key:
            candidates = candidates.filter(metadata_json__identity_candidate__type=type_key)
        candidates = candidates.order_by("entry_index", "pk")
    elif bare_number:
        # A number-only lookup in a legal archive means a candidate norm
        # number, not an arbitrary occurrence inside extracted prose (for
        # example, an accounting code containing the same digits). The year
        # and type filters remain available to disambiguate repeated numbers.
        canonical_number = re.sub(r"\D", "", bare_number.group("number")).lstrip("0") or "0"
        candidates = candidates.filter(
            Q(metadata_json__identity_candidate__number=canonical_number)
            | Q(
                metadata_json__identity_candidate__number__regex=(
                    rf"^0*{re.escape(canonical_number)}$"
                )
            )
        ).order_by("entry_index", "pk")
    elif groups:
        score = Value(0, output_field=IntegerField())
        all_terms = Q()
        for group in groups:
            term_match = _term_query(group)
            score += Case(
                When(term_match, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
            all_terms &= term_match
        full_text_query = _full_text_query(groups)
        if connection.vendor == "postgresql" and full_text_query is not None:
            candidates = candidates.annotate(
                search_score=score,
                proximity_rank=SearchRank(
                    SearchVector("latest_legal_text", config="portuguese"),
                    full_text_query,
                    normalization=2,
                ),
            ).filter(all_terms)
            # PostgreSQL's positional rank prefers candidates where query terms
            # occur close together, without dropping broad lexical matches.
            candidates = candidates.order_by(
                "-proximity_rank", "-search_score", "entry_index", "pk"
            )
        else:
            # SQLite and other local development backends do not implement
            # PostgreSQL's tsvector syntax. Keep filtering in SQL and use a
            # bounded page-local proximity rank below rather than failing with
            # backend-specific SQL or silently skipping archive results.
            candidates = candidates.annotate(search_score=score).filter(all_terms)
            candidates = candidates.order_by("-search_score", "entry_index", "pk")
    else:
        candidates = candidates.order_by("entry_index", "pk")

    paginator = Paginator(candidates, ARCHIVE_PAGE_SIZE)
    result_page = paginator.get_page(page)
    results = []
    page_documents = list(result_page.object_list)
    if groups and connection.vendor != "postgresql":
        page_documents.sort(
            key=lambda document: _text_proximity_rank(
                str(document.latest_legal_text or ""), groups
            ),
            reverse=True,
        )
    for document in page_documents:
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity = metadata.get("identity_candidate") or {}
        legal_text = document.latest_legal_text or ""
        excerpt = _archive_excerpt(
            legal_text,
            excerpt_groups,
            article_number=requested_article,
        )
        results.append(
            {
                "document": document,
                "identity": identity,
                "identity_status": metadata.get("identity_status", "unresolved"),
                "extraction_status": document.latest_extraction_status or "none",
                "page_count": document.latest_page_count,
                "text": legal_text,
                **excerpt,
                "score": getattr(document, "search_score", 0),
            }
        )
    return {
        "page": result_page,
        "results": results,
        "count": paginator.count,
        "total_candidates": total_candidates,
        "expanded": expanded,
        "groups": groups,
        "types": available_types,
        "years": available_years,
    }
