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
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    FloatField,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
    Window,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, RowNumber

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.normative_reference import canonical_type

ARCHIVE_PAGE_SIZE = 20
MAX_ARCHIVE_QUERY_LENGTH = 200
MAX_QUERY_GROUPS = 10
ARCHIVE_EXCERPT_LENGTH = 360
ARCHIVE_EXCERPT_CONTEXT = 170
ARCHIVE_SEARCH_CONFIG = "jurix_archive_pt_v1"
_TOKEN_RE = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)
_PAGE_MARKER_RE = re.compile(r"---\s*Página\s+(\d+)\s*---", re.IGNORECASE)
_ARTICLE_QUERY_RE = re.compile(r"\b(?:art(?:igo)?\.?)\s*0*(\d+)", re.IGNORECASE)
_ARTICLE_HEADING_RE = re.compile(
    r"(?im)^\s*art(?:igo)?\.?\s*0*\d+(?:\s*[º°ªo])?(?=\s|[-–—]|$)"
)
_REQUESTED_TYPE_RE = re.compile(
    r"\b(?:qual|quais|identifique|encontre|localize|busque|procure)\s+"
    r"(?:(?:e|foi|seria)\s+)?(?:a|as|o|os|uma|um)?\s*"
    r"(?P<type>leis?\s+(?:complementar(?:es)?|ordinaria(?:s)?|organica(?:s)?|promulgada(?:s)?)|"
    r"leis?|decretos?\s+(?:legislativos?|executivos?)|decretos?|"
    r"portarias?|resolucoes?)\b",
    re.IGNORECASE,
)
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
    "lixo": ("lixo", "resíduo sólido", "residuo solido", "resíduos sólidos", "residuos solidos"),
    "residuo": ("resíduo", "resíduos", "residuo", "residuos", "lixo"),
    "residuos": ("resíduo", "resíduos", "residuo", "residuos", "lixo"),
    "saneamento": ("saneamento", "esgoto", "esgotamento"),
    "esgoto": ("esgoto", "saneamento", "esgotamento"),
    "esgotamento": ("esgotamento", "esgoto", "saneamento"),
    "cobranca": (
        "cobrança",
        "recolhimento",
        "recolhimentos",
        "arrecadação",
        "pagamento",
        "pagamentos",
        "contribuição",
    ),
}


class _PrecountedPaginator(Paginator):
    """Paginate an already-counted archive grouping without rerunning its window query."""

    def __init__(self, object_list, per_page, *, count: int):
        super().__init__(object_list, per_page)
        self._known_count = count

    @property
    def count(self):
        return self._known_count


_STOPWORDS = {
    "para", "como", "sobre", "entre", "uma", "que", "com", "dos", "das", "de", "e", "em", "lei",
    "qual", "quais", "quando", "onde", "preve", "diz", "trata", "tratam", "artigo", "ato", "atos",
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
    # Keep negation attached to its target. PostgreSQL's Portuguese dictionary
    # treats "não" as a stop word, so querying it independently can either
    # erase the search group or match the opposite legal scope.
    folded_query = re.sub(
        r"\bnao\s+([\w]+)",
        lambda match: f"negated_{match.group(1)}",
        _fold(query),
    )
    for raw_token in _TOKEN_RE.findall(folded_query):
        token = _fold(raw_token)
        # NFKD folding turns the ordinal marker in "1º" into a trailing "o".
        # Normalize only numeric ordinals so the text search can match "Art. 1º".
        if re.fullmatch(r"\d+o", token):
            token = token[:-1]
        if token not in tokens:
            tokens.append(token)
    return tuple(
        (
            (f"não {token.removeprefix('negated_')}", f"nao {token.removeprefix('negated_')}")
            if token.startswith("negated_")
            else _SYNONYMS.get(token, (token,))
        )
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


def _requested_archive_types(query: str) -> tuple[str, ...]:
    """Return candidate act kinds to boost when the user explicitly asks for one.

    This is a ranking preference over filename-derived metadata, not a filter or
    a legal classification: uncertain candidates remain visible in the results.
    """
    match = _REQUESTED_TYPE_RE.search(_fold(query))
    if not match:
        return ()
    raw_type = " ".join(match.group("type").split())
    if raw_type.startswith("leis "):
        raw_type = f"lei {raw_type[5:]}"
    elif raw_type == "leis":
        raw_type = "lei"
    if raw_type.startswith("decretos "):
        raw_type = f"decreto {raw_type[9:]}"
    elif raw_type == "decretos":
        raw_type = "decreto"
    elif raw_type == "portarias":
        raw_type = "portaria"
    elif raw_type == "resolucoes":
        raw_type = "resolucao"
    raw_type = raw_type.replace("complementares", "complementar")
    raw_type = raw_type.replace("ordinarias", "ordinaria")
    raw_type = raw_type.replace("organicas", "organica")
    raw_type = raw_type.replace("promulgadas", "promulgada")
    raw_type = raw_type.replace("legislativos", "legislativo")
    raw_type = raw_type.replace("executivos", "executivo")
    type_key = canonical_type(raw_type)
    if type_key == "lei":
        return ("lei", "lei_complementar", "lei_organica", "lei_promulgada")
    if type_key == "decreto":
        return ("decreto", "decreto_legislativo", "decreto_lei")
    return (type_key,)


def _without_requested_type_intent(query: str) -> str:
    """Keep an explicit act-kind request as ranking intent, not a text term."""
    match = _REQUESTED_TYPE_RE.match(str(query or "").strip())
    if not match:
        return query
    return query[match.end() :].lstrip(" \t:,-—")


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
    text_query = Q()
    for term in terms:
        text_query |= Q(latest_legal_text__iregex=_accent_tolerant_pattern(term))
    return _metadata_term_query(terms) | text_query


def _metadata_term_query(terms: tuple[str, ...]) -> Q:
    query = Q()
    for term in terms:
        query |= (
            Q(original_filename__icontains=term)
            | Q(entry_name__icontains=term)
            | Q(source_ref__icontains=term)
            | Q(metadata_json__identity_candidate__type__icontains=term)
            | Q(metadata_json__identity_candidate__number__icontains=term)
            | Q(metadata_json__identity_candidate__year__icontains=term)
        )
    return query


def _full_text_query(groups: tuple[tuple[str, ...], ...]) -> SearchQuery | None:
    """Build an AND query with OR alternatives for the controlled synonyms."""
    combined = None
    for group in groups:
        alternatives = None
        for term in group:
            part = SearchQuery(term, config=ARCHIVE_SEARCH_CONFIG, search_type="plain")
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
        return {
            "excerpt": preview,
            "excerpt_page": None,
            "excerpt_matched": False,
            "excerpt_matched_group_count": 0,
            "excerpt_total_group_count": len(groups),
            "excerpt_match_region": "unknown",
        }

    occurrences = [_group_occurrences(value, group) for group in groups]
    anchors = sorted({position for group_positions in occurrences for position in group_positions})
    if not anchors:
        return {
            "excerpt": preview,
            "excerpt_page": None,
            "excerpt_matched": False,
            "excerpt_matched_group_count": 0,
            "excerpt_total_group_count": len(groups),
            "excerpt_match_region": "unknown",
        }

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
    first_article = _ARTICLE_HEADING_RE.search(value)
    if first_article is None:
        match_region = "unstructured_text"
    else:
        before_groups = sum(
            any(position < first_article.start() for position in group_positions)
            for group_positions in occurrences
        )
        after_groups = sum(
            any(position >= first_article.start() for position in group_positions)
            for group_positions in occurrences
        )
        if after_groups > before_groups:
            match_region = "after_first_article"
        elif before_groups > after_groups:
            match_region = "before_first_article"
        else:
            match_region = "mixed_article_regions"
    return {
        "excerpt": excerpt or preview,
        "excerpt_page": int(marker.group(1)) if marker else None,
        "excerpt_matched": best_score[0] > 0,
        "excerpt_matched_group_count": max(0, best_score[0]),
        "excerpt_total_group_count": len(groups),
        "excerpt_match_region": match_region,
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
            for value in archive_candidates.order_by()
            .values_list("metadata_json__identity_candidate__type", flat=True)
            .distinct()
            if value
        }
    )
    available_years = sorted(
        {
            int(value)
            for value in archive_candidates.order_by()
            .values_list("metadata_json__identity_candidate__year", flat=True)
            .distinct()
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
            latest_extraction_id=Subquery(latest_extraction.values("pk")[:1]),
            latest_legal_text=Subquery(latest_extraction.values("legal_text")[:1]),
            latest_extraction_status=Subquery(latest_extraction.values("status")[:1]),
            latest_page_count=Subquery(latest_extraction.values("page_count")[:1]),
            latest_publication_date_candidate=Subquery(
                latest_extraction.annotate(
                    publication_date_candidate=KeyTextTransform(
                        "data_publicacao",
                        KeyTextTransform("publication", "metadata_candidates_json"),
                    )
                ).values("publication_date_candidate")[:1]
            ),
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
    groups = _query_groups(_without_requested_type_intent(normalized_query))
    requested_types = _requested_archive_types(normalized_query)
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
            "record_count": 0,
            "total_candidates": total_candidates,
            "expanded": expanded,
            "groups": groups,
            "types": available_types,
            "years": available_years,
            "requested_types": requested_types,
            "requested_type_found": None,
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
            negated_phrases = tuple(term for term in group if term.startswith("não "))
            if connection.vendor == "postgresql" and negated_phrases:
                # Do not let the Portuguese full-text stop-word dictionary drop
                # "não" and turn a negative condition into its positive form.
                phrase_match = Q()
                for phrase in negated_phrases:
                    phrase_match |= Q(
                        latest_legal_text__iregex=_accent_tolerant_pattern(phrase)
                    )
                term_match = _metadata_term_query(group) | phrase_match
            elif connection.vendor == "postgresql":
                latest_extraction = (
                    ExtracaoDocumento.objects.filter(
                        documento_id=OuterRef("documento_id")
                    )
                    .order_by("-created_at", "-pk")
                    .values("pk")[:1]
                )
                text_matches = (
                    ExtracaoDocumento.objects.annotate(
                        search_document=SearchVector(
                            "legal_text", config=ARCHIVE_SEARCH_CONFIG
                        )
                    )
                    .filter(search_document=_full_text_query((group,)))
                    .annotate(latest_extraction_id=Subquery(latest_extraction))
                    .filter(pk=F("latest_extraction_id"))
                    .order_by()
                    .values("documento_id")
                )
                term_match = _metadata_term_query(group) | Q(
                    pk__in=Subquery(text_matches)
                )
            else:
                term_match = _term_query(group)
            score += Case(
                When(term_match, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
            all_terms &= term_match
        if requested_types:
            candidates = candidates.annotate(
                requested_type_rank=Case(
                    When(
                        metadata_json__identity_candidate__type__in=requested_types,
                        then=Value(1),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
        type_order = ("-requested_type_rank",) if requested_types else ()
        full_text_query = _full_text_query(groups)
        if connection.vendor == "postgresql" and full_text_query is not None:
            latest_extraction_rank = (
                ExtracaoDocumento.objects.filter(pk=OuterRef("latest_extraction_id"))
                .annotate(
                    _proximity_rank=SearchRank(
                        SearchVector("legal_text", config=ARCHIVE_SEARCH_CONFIG),
                        full_text_query,
                        normalization=2,
                    )
                )
                .values("_proximity_rank")[:1]
            )
            candidates = candidates.annotate(
                search_score=score,
                proximity_rank=Coalesce(
                    Subquery(latest_extraction_rank),
                    Value(0.0, output_field=FloatField()),
                ),
            ).filter(all_terms)
            # PostgreSQL's positional rank prefers candidates where query terms
            # occur close together, without dropping broad lexical matches.
            candidates = candidates.order_by(
                "-proximity_rank", *type_order, "-search_score", "entry_index", "pk"
            )
        else:
            # SQLite and other local development backends do not implement
            # PostgreSQL's tsvector syntax. Keep filtering in SQL and use a
            # bounded page-local proximity rank below rather than failing with
            # backend-specific SQL or silently skipping archive results.
            candidates = candidates.annotate(search_score=score).filter(all_terms)
            candidates = candidates.order_by(
                "-search_score", *type_order, "entry_index", "pk"
            )
    else:
        # The unfiltered archive is a review queue, not a relevance search.
        # Order a candidate publication date first, then use filename-derived
        # identity when no date was extracted. Neither is a reviewed legal fact.
        candidates = candidates.annotate(
            candidate_year_order=Case(
                When(
                    metadata_json__identity_candidate__year__regex=r"^(19|20)\d{2}$",
                    then=Cast(
                        KeyTextTransform(
                            "year", KeyTextTransform("identity_candidate", "metadata_json")
                        ),
                        IntegerField(),
                    ),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
            candidate_number_order=Case(
                When(
                    metadata_json__identity_candidate__number__regex=r"^\d{1,9}$",
                    then=Cast(
                        KeyTextTransform(
                            "number", KeyTextTransform("identity_candidate", "metadata_json")
                        ),
                        IntegerField(),
                    ),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
        ).order_by(
            "-candidate_year_order",
            F("latest_publication_date_candidate").desc(nulls_last=True),
            "-candidate_number_order",
            "entry_index",
            "pk",
        )

    requested_type_found = None
    if len(requested_types) == 1:
        requested_type_found = candidates.filter(
            metadata_json__identity_candidate__type=requested_types[0]
        ).exists()

    matching_candidates = candidates
    candidate_order = matching_candidates.query.order_by or ("pk",)
    archive_hash_partition = Case(
        When(content_sha256="", then=Cast("pk", CharField())),
        default=F("content_sha256"),
        output_field=CharField(),
    )
    candidate_counts = matching_candidates.order_by().aggregate(
        record_count=Count("pk"),
        grouped_count=Count(archive_hash_partition, distinct=True),
    )
    candidate_record_count = candidate_counts["record_count"]
    grouped_candidate_count = candidate_counts["grouped_count"]
    grouped_candidates = matching_candidates.annotate(
        _archive_copy_rank=Window(
            expression=RowNumber(),
            partition_by=[archive_hash_partition],
            order_by=candidate_order,
        ),
        _archive_copy_count=Window(
            expression=Count("pk"),
            partition_by=[archive_hash_partition],
        ),
    ).filter(_archive_copy_rank=1)
    paginator = _PrecountedPaginator(
        grouped_candidates,
        ARCHIVE_PAGE_SIZE,
        count=grouped_candidate_count,
    )
    result_page = paginator.get_page(page)
    results = []
    # Keep the window/pagination SELECT narrow. The queryset above annotates
    # the latest extraction for excerpts and cards; projecting all of those
    # large text/status fields while ranking every hit makes PostgreSQL fetch
    # toasted legal_text values for documents that will never be displayed.
    # First page only stable document IDs, then hydrate exactly those rows.
    page_document_ids = list(result_page.object_list.values_list("pk", flat=True))
    page_documents_by_id = {
        document.pk: document
        for document in candidates.filter(pk__in=page_document_ids).order_by()
    }
    page_documents = [
        page_documents_by_id[document_id]
        for document_id in page_document_ids
        if document_id in page_documents_by_id
    ]
    if groups and connection.vendor != "postgresql":
        page_documents.sort(
            key=lambda document: _text_proximity_rank(
                str(document.latest_legal_text or ""), groups
            ),
            reverse=True,
        )
    duplicate_hashes = {
        document.content_sha256 for document in page_documents if document.content_sha256
    }
    identical_sources_by_hash: dict[str, list[DocumentoNormativo]] = {}
    if duplicate_hashes:
        for copy in archive_candidates.filter(
            content_sha256__in=duplicate_hashes
        ).order_by("content_sha256", "entry_index", "pk"):
            identical_sources_by_hash.setdefault(copy.content_sha256, []).append(copy)

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
                "identity_conflict": metadata.get("identity_conflict") or {},
                "extraction_status": document.latest_extraction_status or "none",
                "page_count": document.latest_page_count,
                "text": legal_text,
                **excerpt,
                "score": getattr(document, "search_score", 0),
                "identical_sources": identical_sources_by_hash.get(
                    document.content_sha256, [document]
                ),
            }
        )
    if groups:
        region_priority = {
            "after_first_article": 2,
            "mixed_article_regions": 1,
            "unstructured_text": 1,
            "unknown": 1,
            "before_first_article": 0,
        }
        # Keep every lexical candidate, but within this fetched page prefer a
        # match in the dispositive body over a match confined to the epigraph
        # or an entity name in the preamble. Within the same region, prefer
        # excerpts covering more query groups. This is only a triage heuristic;
        # it does not classify legal relevance or validity. Python's stable
        # sort preserves the database/proximity order for ties.
        results.sort(
            key=lambda result: (
                region_priority.get(result["excerpt_match_region"], 1),
                result["excerpt_matched_group_count"],
            ),
            reverse=True,
        )
    return {
        "page": result_page,
        "results": results,
        "count": paginator.count,
        "record_count": candidate_record_count,
        "total_candidates": total_candidates,
        "expanded": expanded,
        "groups": groups,
        "types": available_types,
        "years": available_years,
        "requested_types": requested_types,
        "requested_type_found": requested_type_found,
    }
