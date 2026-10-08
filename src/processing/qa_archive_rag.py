"""Retrieval over unreviewed archive PDFs, available only in isolated QA settings."""

from __future__ import annotations

import hashlib
import math
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
from src.processing.partial_overview_quality import has_redundant_content_phrase
from src.processing.rag_answer_pipeline import (
    raise_if_cancelled,
    stream_grounded_generation,
    stream_model_attempt,
)
from src.processing.rag_prompt import build_prompt

_WORD_RE = re.compile(r"[a-z0-9]{2,}")
_NORMATIVE_REFERENCE_SPAN_RE = re.compile(
    r"\b(?:lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica|promulgada))?|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?|"
    r"resolu[çc][ãa]o|portaria|emenda(?:\s+constitucional)?|lc)\s*"
    r"(?:\s+(?:municipal(?:\s+de\s+Natal)?|do\s+munic[ií]pio(?:\s+de\s+Natal)?))?\s*"
    r"(?:n[º°o.]?\s*)?\d[\d.]*"
    r"(?:\s*(?:/|de)\s*(?:19|20)\d{2})?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart(?:igo)?\.?\s*(\d{1,4})\s*[º°ªo]?", re.IGNORECASE)
_APPENDIX_QUERY_RE = re.compile(
    r"\b(?P<label>anexo|adendo|ap[eê]ndice|quadro|tabela)\s+"
    r"(?P<number>[ivxlcdm]+|\d+)\b",
    re.IGNORECASE,
)
_CROSS_REFERENCE_SCAN_RE = re.compile(
    r"\b(?:quais|que)\s+artigos?\b.{0,100}?\b(?:mencionam|menciona|citam|cita|"
    r"fazem\s+refer[eê]ncia|faz\s+refer[eê]ncia|referem-se|refere-se)\b",
    re.IGNORECASE,
)
_ARTICLE_TOPIC_LOOKUP_RE = re.compile(
    r"\b(?:qual|quais)\s+artigos?\b.{0,80}?\b"
    r"(?:trata(?:m)?|menciona(?:m)?|cont[eê]m|aborda(?:m)?|disp[oõ]e(?:m)?)\b"
    r"\s+(?:de|do|da|dos|das|sobre)\s+(?P<topic>[^?.;]+)",
    re.IGNORECASE,
)
_CONTEXTUAL_MULTI_ARTICLE_TOPIC_RE = re.compile(
    r"\b(?:qual|quais)\s+(?:dos|das)\s+(?:dois|duas|tr[eê]s|quatro)\s+"
    r"(?:artigos?|dispositivos?)\b.{0,40}?"
    r"\b(?:trata(?:m)?|menciona(?:m)?|aborda(?:m)?|disp[oõ]e(?:m)?)\b\s+"
    r"(?:de|do|da|dos|das|sobre)\s+(?P<topic>[^?.;]+)",
    re.IGNORECASE,
)
_TOPIC_SCOPED_QUESTION_RE = re.compile(
    r"\b(?:sobre|quanto\s+a|acerca\s+de|em\s+rela[cç][aã]o\s+a|"
    r"no\s+que\s+diz\s+respeito\s+a)\s+"
    r"(?:(?:o|a|os|as)\s+)?[^\W\d_]+",
    re.IGNORECASE,
)
_EXPLICIT_ARTICLE_TOPIC_RE = re.compile(
    r"\bart(?:igo)?\.?\s*\d{1,4}\s*[º°ªo]?(?!\d).{0,80}?\b"
    r"(?:sobre|a\s+respeito\s+de|quanto\s+a)\s+(?P<topic>[^?.;]+)",
    re.IGNORECASE,
)
_ARTICLE_KEY_RE = re.compile(r"(\d{1,4})(?:\s*[ºª°o])?(?:\s*-\s*([A-Za-z]))?", re.IGNORECASE)
_CONTEXTUAL_DEVICE_SCOPE_RE = re.compile(
    r";\s*dispositivo\s+de\s+refer[eê]ncia\s*:\s*art\.", re.IGNORECASE
)
_MULTI_ARTICLE_SYNTHESIS_RE = re.compile(
    r"\b(?:compare|comparar|compara[cç][aã]o|diferen[cç]a|diferencie|"
    r"distinga|contraste|explique|explicar|interprete|analise|resuma|"
    r"sintetize|em\s+linguagem\s+simples)\b",
    re.IGNORECASE,
)
_SALARY_FLOOR_QUERY_RE = re.compile(
    r"\b(?:piso(?:\s+salarial)?|valor\s+m[ií]nimo|vencimento\s+m[ií]nimo)\b",
    re.IGNORECASE,
)
_SALARY_SUBJECT_QUERY_RE = re.compile(
    r"\b(?:sal[aá]rio|vencimento|remunera[cç][aã]o|subs[ií]dio)\b",
    re.IGNORECASE,
)
_SALARY_FLOOR_EVIDENCE_RE = re.compile(
    r"\b(?:piso(?:\s+salarial)?|sal[aá]rio\s+m[ií]nimo|"
    r"vencimento\s+m[ií]nimo|remunera[cç][aã]o\s+m[ií]nima|"
    r"n[aã]o\s+(?:poder[aá]|ser[aá])\s+inferior)\b",
    re.IGNORECASE,
)
_INTERSTICIO_DURATION_QUERY_RE = re.compile(
    r"\b(?:(?:qual|quanto|quantos|quantas|dura[cç][aã]o|prazo)\b.{0,80}?"
    r"\binterst[ií]cio\b|\binterst[ií]cio\b.{0,80}?"
    r"\b(?:qual|quanto|quantos|quantas|dura[cç][aã]o|prazo|m[ií]nimo)\b)",
    re.IGNORECASE,
)
_COUNTED_DURATION_RE = re.compile(
    r"\b(?:\d+(?:[,.]\d+)?|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|"
    r"oito|nove|dez|onze|doze|quinze|vinte|trinta|quarenta|cinquenta|sessenta|"
    r"noventa|cento)\s*(?:\([^)]{1,40}\)\s*)?(?:dia|dias|mes|meses|ano|anos)\b",
    re.IGNORECASE,
)
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
    "principais", "ponto", "pontos", "quais", "sintese", "sintetize", "breve",
    "sustentam", "temas", "visao", "geral", "panorama", "integral", "indique",
    "dispositivos", "lc", "eixo", "eixos", "sao", "contexto", "normativo",
    "explique", "descreva", "detalhe", "informe", "fale", "conte",
    "vincule", "vinculando", "afirmacao", "afirmacoes", "correspondente",
    "correspondentes", "identificavel", "identificaveis",
    "identificado", "identificada", "identificados", "identificadas",
    "tratado", "tratada", "tratados", "tratadas", "abordado", "abordada",
    "abordados", "abordadas", "previsto", "prevista", "previstos", "previstas",
    "objetiva", "objetivo",
    # Normative type words identify the document; they are not topical terms
    # that should exclude every article when the user asks about the whole law.
    "complementar", "decreto", "decretos", "legislativo", "ordinaria",
    "organica", "promulgada", "resolucao", "portaria",
}
_COVERAGE_SCOPE_REQUEST_RE = re.compile(
    r"\b(?:"
    r"(?:e\s+)?(?:informe|indique|diga|esclare[cç]a|especifique|delimite)\s+"
    r"(?:claramente\s+)?(?:o\s+que\s+)?(?:"
    r"(?:ficou|ficaram|foi|foram)\s+(?:de\s+)?fora\s+da\s+(?:amostra|sele[cç][aã]o)|"
    r"se\s+(?:a\s+)?cobertura\s+(?:é|e)\s+parcial|"
    r"(?:a\s+)?(?:cobertura|abrang[eê]ncia)(?:\s+(?:da|do)\s+(?:amostra|sele[cç][aã]o|corpus))?(?:\s+parcial)?|"
    r"se\s+(?:o\s+)?pdf\s+permite\s+identificar\s+"
    r"(?:o\s+)?conte[uú]do\s+completo\s+da\s+norma|"
    r"(?:(?:os?|as?)\s+)?(?:limites?|limita[cç](?:[aã]o|[õo]es?))\s+(?:da|de)\s+(?:amostra|sele[cç][aã]o|corpus|cobertura)|"
    r"o\s+que\s+(?:a\s+)?amostra\s+n[aã]o\s+cobre)"
    r"|(?:informe|indique|diga|esclare[cç]a)\s+quant[oa]s?\s+(?:artigos?|dispositivos?)\s+"
    r"(?:foram|s[aã]o|est[aã]o)\s+identificados?"
    r"|(?:os?|as?)\s+(?:limites?|limita[cç](?:[aã]o|[õo]es?))\s+(?:da|de)\s+cobertura"
    r"|(?:e\s+)?(?:explique|descreva|identifique|aponte|liste|resuma)\s+"
    r"(?:que\s+|quais?\s+(?:s[aã]o\s+)?)"
    r"(?:os?\s+)?(?:principais?\s+)?temas?\s+"
    r"(?:(?:foram|s[aã]o|est[aã]o)\s+)?"
    r"(?:identificados?|relevantes?|centrais?|previstos?|tratados?|abordados?)?"
    r"|(?:e\s+)?deixando\s+claro\s+se\s+(?:a\s+)?"
    r"(?:extra[cç][aã]o|leitura)\s+(?:do\s+)?pdf\s+"
    r"(?:n[aã]o\s+)?(?:permite|permitir|permita)\s+(?:uma?\s+)?"
    r"(?:s[ií]ntese|an[aá]lise|vis[aã]o\s+geral|conclus[aã]o)\s+"
    r"(?:confi[aá]vel|completa|integral)"
    r"|(?:e\s+)?(?:indicando|informando|esclarecendo)\s+"
    r"(?:claramente\s+)?(?:o\s+que\s+)?(?:foi\s+)?(?:efetivamente\s+)?"
    r"(?:coberto|abrangido|recuperado|consultado)"
    r"(?:\s+e\s+o\s+que\s+n[aã]o\s+pode\s+ser\s+confirmado\s+"
    r"(?:pelo\s+)?pdf)?"
    r"|com\s+base\s+(?:no\s+)?pdf"
    r")\b",
    re.IGNORECASE,
)
_WHOLE_NORMAL_FRAMING_RE = re.compile(
    r"\b(?:em\s+linhas\s+gerais|em\s+termos\s+gerais|"
    r"de\s+forma\s+geral|de\s+maneira\s+geral|no\s+geral)\b",
    re.IGNORECASE,
)
_OVERVIEW_SCOPE_QUALIFIER_RE = re.compile(
    r"\b(?:sem\s+(?:inventar|presumir|fingir|afirmar|alegar)\s+"
    r"(?:(?:uma?|a)\s+)?(?:an[aá]lise|s[ií]ntese|cobertura)\s+"
    r"(?:integral|completa|exaustiva|total)|"
    r"s[oó]\s+(?:sintetize|apresente|inclua|use)\s+"
    r"(?:(?:somente|apenas)\s+)?(?:as?\s+)?(?:afirma[cç][õo]es?|conclus[oõ]es?|pontos?)\s+"
    r"(?:que\s+sejam\s+)?apoiad[oa]s?\s+(?:(?:pel[oa]s?|nas?)\s+)?fontes)\b",
    re.IGNORECASE,
)
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
_PARTIAL_OVERVIEW_MIN_CITED_SOURCES = 3
_PARTIAL_OVERVIEW_MAX_SAMPLED_SOURCES = 10
_GENERIC_CLOSING_PROVISION_RE = re.compile(
    r"^(?:(?:(?:esta|este)\s+)?(?:lei(?:\s+complementar)?|decreto)\s+)?"
    r"entra\s+em\s+vigor\s+na\s+data\s+de\s+sua\s+publica[cç][aã]o"
    r"(?:,\s*revogando-se\s+(?:todas\s+)?as\s+disposi[cç][oõ]es\s+em\s+contr[aá]rio)?",
    re.IGNORECASE,
)
_CLOSING_PROVISION_QUERY_RE = re.compile(
    r"\b(?:vig[eê]ncia|vigor|revoga(?:[cç][aã]o|do|da|dos|das)?|"
    r"entra(?:r[aá])?\s+em\s+vigor|publica[cç][aã]o)\b",
    re.IGNORECASE,
)
_PARTIAL_OVERVIEW_REVISION_INSTRUCTION = (
    "\n\nREVISÃO — VISÃO GERAL PARCIAL: a tentativa anterior incluiu uma afirmação sem suporte. "
    "Reescreva usando somente os excertos amostrados. Produza até três frases factuais curtas, "
    "cada uma sobre um dispositivo diferente, com um único marcador [[N]] no fim. "
    "Se houver menos de três excertos, use um por excerto disponível. Agrupe-as em prosa natural, "
    "sem título, lista ou conclusão. Nomeie o artigo na frase; use cada dispositivo e marcador "
    "uma única vez e não misture dispositivos. "
    "Parafraseie minimamente: preserve o verbo e a modalidade do texto, sem inferir obrigação, "
    "permissão, proibição, condição, vigência, efeito ou tema não expresso. Não use negação para "
    "descrever o que a amostra não contém. A cobertura e os anexos serão informados pelo sistema. "
    "Não reescreva em outra frase a criação ou denominação já explicada; cada afirmação seguinte "
    "deve acrescentar um aspecto material distinto e sustentado. Pare após a última afirmação."
)


def _has_partial_overview_breadth(
    answer: str, source_count: int, *, available_sample_sources: int | None = None
) -> bool:
    """Require citations across several retrieved devices for a partial overview."""
    marker_indexes = [
        int(match)
        for match in re.findall(r"\[\[(\d+)\]\]", str(answer or ""))
    ]
    if any(index < 1 or index > source_count for index in marker_indexes):
        return False
    cited_indexes = set(marker_indexes)
    required_sources = min(
        _PARTIAL_OVERVIEW_MIN_CITED_SOURCES,
        available_sample_sources if available_sample_sources is not None else source_count,
    )
    return len(cited_indexes) >= required_sources


def _has_requested_article_coverage(
    answer: str, article_targets: tuple[str, ...], sources: list[dict]
) -> bool:
    """Require every explicitly requested article to appear with its citation."""
    answer = str(answer or "")
    source_indexes = {
        _article_key(str(source.get("dispositivo_ref") or "")): index
        for index, source in enumerate(sources, 1)
        if source.get("citation_id")
    }
    for target in article_targets:
        normalized_target = _article_key(str(target))
        source_index = source_indexes.get(normalized_target)
        if not source_index:
            return False
        article_parts = re.fullmatch(r"(\d+)([a-z]?)", normalized_target)
        if not article_parts:
            return False
        suffix_pattern = (
            rf"\s*(?:[-–]\s*)?{re.escape(article_parts.group(2))}"
            if article_parts.group(2)
            else ""
        )
        article_pattern = re.compile(
            rf"\b(?:art\.?|artigo)\s*{re.escape(article_parts.group(1))}"
            rf"(?:\s*[-º°ª])?{suffix_pattern}\b",
            re.IGNORECASE,
        )
        if not article_pattern.search(answer) or f"[[{source_index}]]" not in answer:
            return False
    return True


def _partial_overview_sample_limit(retrieved_article_count: int) -> int:
    """Scale whole-norm evidence samples with corpus breadth, within a prompt cap."""
    count = max(0, int(retrieved_article_count or 0))
    if count <= 8:
        return count
    return min(
        _PARTIAL_OVERVIEW_MAX_SAMPLED_SOURCES,
        max(5, math.ceil(math.sqrt(count))),
    )


def _partial_overview_excerpts(
    results: list[dict], *, limit: int = 5, max_chars: int = 220,
    question: str = "",
) -> list[dict]:
    """Choose evenly distributed verbatim excerpts without claiming synthesis."""
    eligible = [
        (index, source)
        for index, source in enumerate(results, 1)
        if source.get("citation_id") and str(source.get("full_text") or "").strip()
    ]
    if not _CLOSING_PROVISION_QUERY_RE.search(question):
        substantive = [
            item
            for item in eligible
            if not _GENERIC_CLOSING_PROVISION_RE.match(
                re.sub(
                    r"^\s*art(?:igo)?\.?\s*\d{1,4}\s*(?:[º°ªo]\s*)?\.?\s*",
                    "",
                    str(item[1].get("full_text") or "").strip(),
                    flags=re.IGNORECASE,
                ).strip()
            )
        ]
        if substantive:
            eligible = substantive
    if len(eligible) <= limit:
        selected = eligible
    else:
        positions = {
            round(position * (len(eligible) - 1) / (limit - 1))
            for position in range(limit)
        }
        selected = [item for position, item in enumerate(eligible) if position in positions]

    excerpts = []
    for citation_index, source in selected:
        text = re.sub(r"\s+", " ", str(source["full_text"])).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        excerpts.append({
            "citation_index": citation_index,
            "citation_id": source["citation_id"],
            "device": str(source.get("dispositivo_ref") or "Dispositivo recuperado"),
            "text": text,
        })
    return excerpts


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _intersticio_duration_not_recovered(question: str, results: list[dict]) -> tuple[int, dict] | None:
    """Find an interstício-only excerpt when the user asks for its duration.

    This is a narrow abstention rule for the unreviewed archive corpus: it
    reports what the retrieved excerpt lacks without asserting that the full
    norm has no duration requirement.
    """
    if not _INTERSTICIO_DURATION_QUERY_RE.search(question):
        return None

    matching_sources = []
    for index, source in enumerate(results, 1):
        text = _fold(str(source.get("full_text") or ""))
        term_matches = list(re.finditer(r"\bintersticio\b", text))
        if not term_matches or not source.get("citation_id"):
            continue
        if any(
            _COUNTED_DURATION_RE.search(text[max(0, match.start() - 120):match.end() + 180])
            for match in term_matches
        ):
            return None
        matching_sources.append((index, source))
    return matching_sources[0] if matching_sources else None


def _tokens(value: str) -> set[str]:
    return {word for word in _WORD_RE.findall(_fold(value)) if word not in _STOPWORDS}


def _is_whole_norm_request(question: str, query_plan=None) -> bool:
    """Share whole-norm intent classification between retrieval and response shaping."""
    parsed_references = parse_normative_references(question)
    references = [reference for reference in parsed_references if not reference.ambiguous]
    exact_ref = references[0] if len(references) == 1 else None
    if exact_ref is None and len(parsed_references) == 1 and query_plan is not None:
        reference = parsed_references[0]
        if reference.year is not None and query_plan.article_targets and query_plan.kind == "provision":
            exact_ref = reference

    wanted_articles = tuple(query_plan.article_targets) if query_plan is not None else ()
    if not wanted_articles:
        wanted_articles = tuple(
            _article_key(match.group(1)) for match in _ARTICLE_RE.finditer(question)
        )
    if not exact_ref or wanted_articles:
        return False

    retrieval_question = _COVERAGE_SCOPE_REQUEST_RE.sub(" ", question)
    retrieval_question = _WHOLE_NORMAL_FRAMING_RE.sub(" ", retrieval_question)
    retrieval_question = _OVERVIEW_SCOPE_QUALIFIER_RE.sub(" ", retrieval_question)
    lexical_question = (
        _NORMATIVE_REFERENCE_SPAN_RE.sub(" ", retrieval_question)
        if len(parsed_references) == 1 and not parsed_references[0].ambiguous
        else retrieval_question
    )
    topic_tokens = _tokens(lexical_question) - _QUERY_FRAMING
    return not topic_tokens


def _candidate_identity(document: DocumentoNormativo) -> dict:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity = metadata.get("identity_candidate")
    return identity if isinstance(identity, dict) else {}


def _latest_extraction(document: DocumentoNormativo) -> ExtracaoDocumento | None:
    return document.extracoes.order_by("-created_at", "-pk").first()


def _article_key(value: str) -> str:
    match = _ARTICLE_KEY_RE.search(str(value or ""))
    return f"{int(match.group(1))}{(match.group(2) or '').lower()}" if match else ""


def _archive_device_label(device: str, norma: str) -> str:
    """Render a device citation with the correct Portuguese article for its norm."""
    references = parse_normative_references(norma)
    if not references:
        return f"**{device}** da norma **{norma}**"

    type_key = references[0].type_key
    preposition = "do" if type_key in {"decreto", "decreto_lei", "decreto_legislativo"} else "da"
    return f"**{device}** {preposition} **{norma}**"


def _article_topic_label(question: str) -> str | None:
    """Return the user-facing topic phrase for explicit article lookup asks."""
    question = str(question or "")
    match = (
        _CONTEXTUAL_MULTI_ARTICLE_TOPIC_RE.search(question)
        or _ARTICLE_TOPIC_LOOKUP_RE.search(question)
        or _EXPLICIT_ARTICLE_TOPIC_RE.search(question)
    )
    if not match:
        return None
    topic = re.sub(r"\s*\(contexto normativo:.*\)\s*$", "", match.group("topic"), flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip(" \t,.;:")
    return topic or None


def _article_topic_phrase(question: str) -> str | None:
    """Return the normalized topic phrase for exact-text evidence matching."""
    topic = _article_topic_label(question)
    if not topic:
        return None
    tokens = [
        token
        for token in _WORD_RE.findall(_fold(topic))
        if token not in _STOPWORDS and token not in _QUERY_FRAMING and not token.isdigit()
    ]
    return " ".join(tokens) or None


def _supports_article_topic(question: str, text: str) -> bool:
    """Require lexical evidence for a topic explicitly tied to an article."""
    topic = _article_topic_phrase(question)
    if not topic:
        return True
    topic_tokens = _tokens(topic)
    if not topic_tokens:
        return True
    evidence_tokens = _tokens(text)
    matched = sum(
        any(
            topic_token == evidence_token
            or (
                min(len(topic_token), len(evidence_token)) >= 6
                and topic_token[:6] == evidence_token[:6]
            )
            for evidence_token in evidence_tokens
        )
        for topic_token in topic_tokens
    )
    return matched / len(topic_tokens) >= 0.5


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
    complete_articles = []
    for index, article in enumerate(articles):
        next_article_start = articles[index + 1]["start_pos"] if index + 1 < len(articles) else len(source)
        article_end = min(
            next_article_start,
            appendix_start if appendix_start is not None else len(source),
            min(
                (start for start in division_starts if start > article["start_pos"]),
                default=len(source),
            ),
        )
        article_text_start = article["start_pos"] + len(str(article.get("full_match") or ""))
        # Slice the original extraction once. It already contains paragraphs,
        # incisos and alíneas; appending parsed descendants duplicates them.
        article_text = source[article_text_start:article_end].strip()
        complete_articles.append({
            **article,
            "texto": article_text,
            "annexes_present": appendix_start is not None,
        })
    return complete_articles


def _sample_whole_norm_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Keep every article that fits; otherwise sample evenly within the QA budget."""
    total = len(rows)
    if not total:
        return rows, total

    text_lengths = [len(str(row.get("full_text") or "")) for row in rows]
    total_chars = sum(text_lengths)
    if total_chars <= _WHOLE_NORM_CONTEXT_BUDGET_CHARS:
        return rows, total

    average_chars = max(1, total_chars // total)
    budget_count = max(1, _WHOLE_NORM_CONTEXT_BUDGET_CHARS // average_chars)
    sample_size = min(total, budget_count)
    while sample_size:
        if sample_size == 1:
            indexes = [total // 2]
        else:
            indexes = [
                round(index * (total - 1) / (sample_size - 1))
                for index in range(sample_size)
            ]
        # The average-size estimate can miss uneven articles. Reduce the
        # evenly-spaced sample until its actual evidence text fits the budget.
        if sum(text_lengths[index] for index in indexes) <= _WHOLE_NORM_CONTEXT_BUDGET_CHARS:
            return [rows[index] for index in indexes], total
        sample_size -= 1

    # One article may itself exceed the soft aggregate budget; preserve that
    # single source rather than silently dropping all evidence for the norm.
    return [rows[total // 2]], total


def retrieve_archive_evidence(question: str, *, limit: int = 8) -> list[dict]:
    """Return lexically ranked article evidence from the isolated archive only."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False):
        return []

    # A request to disclose uncovered sample scope is metadata about breadth,
    # not a topical constraint on which provisions to retrieve.
    retrieval_question = _COVERAGE_SCOPE_REQUEST_RE.sub(" ", question)
    # These idioms signal breadth rather than a substantive topic. Remove the
    # complete phrase so its leftover tokens do not force topical top-k.
    retrieval_question = _WHOLE_NORMAL_FRAMING_RE.sub(" ", retrieval_question)
    retrieval_question = _OVERVIEW_SCOPE_QUALIFIER_RE.sub(" ", retrieval_question)
    parsed_references = parse_normative_references(question)
    query_plan = classify_normative_query(question)
    appendix_match = _APPENDIX_QUERY_RE.search(question)
    requested_appendix = None
    if appendix_match:
        requested_appendix = (
            appendix_match.group("label").capitalize(),
            appendix_match.group("number").upper(),
        )
    # Exclude the matched legal identity as a unit before lexical ranking.
    # Otherwise formatted numbers (e.g. 7.795/2005) leave fragments such as
    # "7" and "795" behind after subtracting normalized number 7795, making a
    # whole-norm request look like a topical query and suppressing coverage.
    lexical_question = (
        _NORMATIVE_REFERENCE_SPAN_RE.sub(" ", retrieval_question)
        if len(parsed_references) == 1 and not parsed_references[0].ambiguous
        else retrieval_question
    )
    query_tokens = _tokens(lexical_question)
    if not query_tokens:
        if not (len(parsed_references) == 1 and query_plan.is_norma_overview):
            return []
    article_topic_phrase = _article_topic_phrase(question)
    references = [ref for ref in parsed_references if not ref.ambiguous]
    exact_ref = references[0] if len(references) == 1 else None
    if requested_appendix and exact_ref is None:
        # Never answer an underspecified appendix follow-up from whichever
        # document happens to rank first; conversation context must resolve it.
        return []
    explicit_multi_references = [
        ref for ref in parsed_references
        if ref.year is not None and ref.number
    ] if len(parsed_references) > 1 else []
    asks_salary_floor = bool(
        _SALARY_FLOOR_QUERY_RE.search(question)
        and _SALARY_SUBJECT_QUERY_RE.search(question)
    )
    if (
        exact_ref is None
        and len(parsed_references) == 1
        and parsed_references[0].year is not None
        and query_plan.article_targets
        and query_plan.kind == "provision"
    ):
        exact_ref = parsed_references[0]
    explicit_years = set(re.findall(r"\b(?:19|20)\d{2}\b", _fold(question)))
    wanted_articles = query_plan.article_targets
    if not wanted_articles:
        wanted_articles = tuple(
            _article_key(match.group(1)) for match in _ARTICLE_RE.finditer(question)
        )
    wanted_articles = tuple(dict.fromkeys(target for target in wanted_articles if target))
    topic_tokens = set(query_tokens)
    topic_tokens -= _QUERY_FRAMING
    topical_sequence = [
        token
        for token in _WORD_RE.findall(_fold(lexical_question))
        if token not in _STOPWORDS
        and token not in _QUERY_FRAMING
        and not (exact_ref and token.isdigit())
    ]
    topical_phrases = tuple(
        " ".join(topical_sequence[index : index + 2])
        for index in range(max(0, len(topical_sequence) - 1))
    )
    # Explicit law identity alone does not mean the user asked for a whole-law
    # overview: broad lead-ins such as "explique" can precede a specific topic
    # ("Explique o piso ... na LC ..."). Overview retrieval is reserved for
    # queries whose normalized tokens contain no topic after framing is removed.
    whole_norm_request = _is_whole_norm_request(question, query_plan)

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
        elif explicit_multi_references:
            candidate_number = normalize_number(str(identity.get("number") or ""))
            try:
                candidate_year = int(identity.get("year"))
            except (TypeError, ValueError):
                candidate_year = None
            candidate_type = str(identity.get("type") or "")
            matches_explicit_reference = any(
                candidate_number == reference.number
                and candidate_year == reference.year
                and (
                    not reference.type_key
                    or candidate_type in _TYPE_ALIASES.get(
                        reference.type_key, {reference.type_key}
                    )
                )
                for reference in explicit_multi_references
            )
            if not matches_explicit_reference:
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
        if requested_appendix:
            from src.processing.legal_parser import (
                LegalTextParser,
                extract_normative_appendices,
                strip_closing_editorial_metadata,
            )

            appendix_text = strip_closing_editorial_metadata(
                LegalTextParser.strip_page_artifacts(legal_text)
            )
            appendices = extract_normative_appendices(appendix_text)
            articles = [
                {
                    "tipo": "anexo",
                    "numero": appendix["label"],
                    "texto": appendix["text"],
                    "start_pos": appendix["start"],
                    "annexes_present": True,
                    "is_appendix": True,
                }
                for appendix in appendices
                if tuple(appendix["label"].split(maxsplit=1)) == requested_appendix
            ]
            if not articles:
                continue
        else:
            articles = _article_rows(legal_text)
        if wanted_articles and not requested_appendix:
            requested_articles = set(wanted_articles)
            articles = [
                row for row in articles
                if _article_key(str(row.get("numero") or "")) in requested_articles
            ]
            if not articles:
                continue
        if not articles and not requested_appendix:
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
            folded_text = _fold(text)
            topic_phrase_match = any(phrase in folded_text for phrase in topical_phrases)
            if article_topic_phrase:
                topic_phrase_match = article_topic_phrase in folded_text
            score = topic_overlap if exact_ref and topic_tokens and not wanted_articles else overlap
            if exact_ref and (wanted_articles or not topic_tokens):
                score += 1.0
            if wanted_articles:
                score += 1.0
            if identity_conflict:
                score *= 0.8
            article_number = str(article.get("numero") or "")
            device_ref = (
                article_number
                if article.get("is_appendix")
                else f"Art. {article_number}" if article_number else "Trecho extraído"
            )
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
                "_topic_phrase_match": topic_phrase_match,
                "contribution": "Trecho da extração do PDF arquivado; transcrição pendente de revisão",
                "source_type": "Acervo histórico local — extração pendente de revisão",
                "retrieval_strategy": "qa_archive_lexical",
                "evidence_scope": "isolated_qa_archive",
                "coverage": {
                    "extraction_status": extraction.status,
                    "identity_conflict": identity_conflict,
                    "annexes_present": article.get("annexes_present", False),
                    "annexes_included_in_article_evidence": False,
                    "evidence_kind": "normative_appendix" if article.get("is_appendix") else "article",
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
    if requested_appendix:
        rows.sort(key=lambda item: (item["norma_ref"], item["_device_order"]))
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "requested_appendix": row["dispositivo_ref"],
                "complete": True,
            }
    elif whole_norm_request:
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
    elif exact_ref and not wanted_articles:
        if topic_tokens:
            # A question about a topic within a named law should rank only
            # devices that actually overlap the topic; law identity alone must
            # not make every article look like a high-relevance match.
            phrase_matches = [row for row in rows if row["_topic_phrase_match"]]
            rows = phrase_matches or [row for row in rows if row["_topic_overlap"] >= 0.12]
            if asks_salary_floor:
                explicit_floor_rows = [
                    row for row in rows
                    if _SALARY_FLOOR_EVIDENCE_RE.search(str(row.get("full_text") or ""))
                ]
                # A topical hit on "vencimento básico" alone is not enough to
                # answer a question about its floor. When the source states an
                # explicit minimum rule, prefer only those devices; otherwise
                # preserve ordinary retrieval and let grounding abstain if needed.
                if explicit_floor_rows:
                    rows = explicit_floor_rows
            rows.sort(key=lambda item: (item["_topic_overlap"], item["dispositivo_ref"]), reverse=True)
        rows = rows[: max(1, min(limit, 12))]
    elif exact_ref and wanted_articles:
        requested = set(wanted_articles)
        rows = [
            row for row in rows
            if _article_key(row.get("dispositivo_ref", "")) in requested
        ]
        if article_topic_phrase:
            rows = [
                row for row in rows
                if _supports_article_topic(question, row.get("full_text", ""))
            ]
        article_order = {article: index for index, article in enumerate(wanted_articles)}
        rows.sort(
            key=lambda row: article_order.get(
                _article_key(row.get("dispositivo_ref", "")), len(article_order)
            )
        )
        found = {_article_key(row.get("dispositivo_ref", "")) for row in rows}
        missing = [article for article in wanted_articles if article not in found]
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "requested_articles": list(wanted_articles),
                "missing_articles": missing,
                "complete": not missing,
            }
        rows = rows[: min(limit, max(len(wanted_articles), 1))]
    elif explicit_multi_references and wanted_articles:
        requested = set(wanted_articles)
        rows = [
            row for row in rows
            if _article_key(row.get("dispositivo_ref", "")) in requested
        ]
        rows.sort(key=lambda row: (row["norma_ref"], row["dispositivo_ref"]))
        rows = rows[: min(limit, max(len(explicit_multi_references), 1) * len(requested))]
    else:
        rows = [row for row in rows if row["similarity_score"] >= 0.12][:limit]
    for row in rows:
        row.pop("_topic_overlap", None)
        row.pop("_topic_phrase_match", None)
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
    temporal_scope_requested: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[dict]:
    """Generate a grounded streaming answer from imported QA PDFs."""
    started = time.perf_counter()
    yield {"event": "status", "status": "retrieving"}
    if temporal_scope_requested:
        answer = (
            "Não encontrei evidências históricas suficientes para responder sobre essa data. "
            "A redação atual não será apresentada como se fosse a redação histórica."
        )
        reason_code = "historical_evidence_unavailable"
        yield {"event": "status", "status": "insufficient_evidence"}
        yield {
            "event": "sources",
            "sources": [],
            "confidence": None,
            "reason_code": reason_code,
            "coverage": {
                "corpus": "acervo histórico local (lote de 40 documentos)",
                "temporal_scope_available": False,
            },
        }
        yield {"event": "chunk", "chunk": answer, "provisional": False}
        yield {
            "event": "done",
            "answer": answer,
            "sources": [],
            "grounded": False,
            "reason_code": reason_code,
            "grounding": {"grounded": False, "claims": [], "failed_claims": []},
            "timings_ms": {"retrieval": round((time.perf_counter() - started) * 1000)},
        }
        return

    results = retrieve_archive_evidence(question, limit=max(k, 8))
    query_plan = classify_normative_query(question)
    if query_plan.article_targets and _article_topic_phrase(question):
        results = [
            source for source in results
            if _supports_article_topic(question, source.get("full_text", ""))
        ]
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

    # The isolated PDF archive is an original-text corpus, not an audited
    # amendment chain. A provision excerpt can establish its wording, but it
    # cannot establish whether later acts amended or revoked it. Avoid falling
    # through to the single-article transcription path for relation questions.
    if query_plan.relation_intent in {"modification", "mixed"}:
        source = next(
            (
                item for item in results
                if item.get("citation_id") and item.get("full_text")
            ),
            None,
        )
        if source:
            citation_index = next(
                index for index, item in enumerate(results, 1) if item is source
            )
            norm = str(source.get("norma_ref") or "norma consultada")
            device = str(source.get("dispositivo_ref") or "dispositivo localizado")
            text = str(source.get("full_text") or "").strip()
            answer = (
                f'O PDF arquivado registra a redação de origem de **{norm}, {device}**: '
                f'“{text}” [[{citation_index}]].\n\n'
                "Esse lote contém extrações de PDFs, mas não uma cadeia de alterações e "
                "revogações vinculada e revisada. Portanto, ele não permite confirmar se "
                "o dispositivo foi alterado ou revogado depois, nem concluir que continua "
                "vigente. Confira a linha do tempo normativa e os atos oficiais antes de "
                "usar essa redação em uma fundamentação."
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
                    "claims": [{
                        "text": f"Transcrição da redação de origem de {norm}, {device}",
                        "citation_ids": [source["citation_id"]],
                    }],
                    "failed_claims": [],
                    "validation_scope": "archive_original_text_only_no_audited_amendment_chain",
                },
                "reason_code": "qa_archive_relation_history_unavailable",
                "source_relevance": max(
                    (float(item.get("similarity_score") or 0) for item in results),
                    default=0.0,
                ),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    intersticio_gap = _intersticio_duration_not_recovered(question, results)
    if intersticio_gap:
        citation_index, source = intersticio_gap
        norma_ref = str(source.get("norma_ref") or "norma consultada")
        dispositivo_ref = str(source.get("dispositivo_ref") or "dispositivo recuperado")
        answer = (
            f"O trecho recuperado de **{norma_ref}, {dispositivo_ref}** menciona o respeito "
            "ao interstício mínimo, mas não informa sua duração. Como a extração do PDF está "
            "em revisão, esse resultado não permite concluir se outro dispositivo define o prazo. "
            f"[[{citation_index}]]"
        )
        yield {"event": "status", "status": "grounding"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": [source],
            "grounded": True,
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": [{
                    "text": (
                        f"O excerto de {dispositivo_ref} menciona interstício mínimo, "
                        "mas não informa a duração no trecho recuperado."
                    ),
                    "citation_ids": [source["citation_id"]],
                }],
                "failed_claims": [],
                "validation_scope": "requested_intersticio_duration_in_retrieved_unreviewed_excerpt",
            },
            "reason_code": "qa_archive_requested_detail_not_in_retrieved_evidence",
            "source_relevance": float(source.get("similarity_score") or 0),
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    # A cross-reference inventory is a retrieval task, not a free-form
    # synthesis task. Report only provisions whose extracted text contains the
    # exact referenced norm; a semantically similar article cannot support a
    # different article number in the answer.
    cross_reference_question = bool(_CROSS_REFERENCE_SCAN_RE.search(question))
    if cross_reference_question:
        def reference_identity(reference):
            normalized_number = normalize_number(reference.number).lstrip("0") or "0"
            return reference.type_key, normalized_number, reference.year

        source_norm_identities = {
            reference_identity(reference)
            for source in results
            for reference in parse_normative_references(str(source.get("norma_ref") or ""))
        }
        query_references = [
            reference
            for reference in parse_normative_references(question)
            if reference.year is not None
        ]
        # In the supported question form, the first explicit norm is the one
        # whose articles are being scanned and subsequent norms are targets.
        # Fall back to retrieved-source identity only when the question names
        # a single norm.
        target_references = (
            [
                reference
                for reference in query_references[1:]
                if reference_identity(reference) != reference_identity(query_references[0])
            ]
            if len(query_references) > 1
            else [
                reference
                for reference in query_references
                if reference_identity(reference) not in source_norm_identities
            ]
        )
        matched_sources = []
        if target_references:
            target_identities = {reference_identity(reference) for reference in target_references}
            for source in results:
                text_references = {
                    reference_identity(reference)
                    for reference in parse_normative_references(str(source.get("full_text") or ""))
                    if reference.year is not None
                }
                if source.get("citation_id") and text_references & target_identities:
                    matched_sources.append(source)

        if target_references:
            result_indexes = {
                source["citation_id"]: index
                for index, source in enumerate(results, 1)
            }
            target_label = next(
                (
                    str(source.get("norma_ref") or "norma consultada")
                    for source in results
                ),
                "norma consultada",
            )
            if matched_sources:
                lines = [
                    f"Nos trechos legíveis recuperados de **{target_label}**, "
                    "identifiquei referência expressa à norma indicada nestes dispositivos:"
                ]
                for source in matched_sources:
                    index = result_indexes[source["citation_id"]]
                    # The renderer resolves the marker to the full legal
                    # citation label (norm + article); avoid repeating the
                    # article label immediately before that hyperlink.
                    lines.append(f"- [[{index}]]")
                lines.append(
                    "A lista se limita aos trechos recuperados e legíveis; ela não confirma "
                    "que os demais dispositivos da norma não contenham outras referências. "
                    "A extração do PDF do acervo ainda está sob revisão."
                )
                scan_grounded = True
                scan_reason = "qa_archive_cross_reference_scan"
            else:
                lines = [
                    f"Não identifiquei referência literal à norma indicada nos trechos "
                    f"legíveis recuperados de **{target_label}**. Isso não permite concluir "
                    "que os demais dispositivos da norma não façam essa referência, pois "
                    "a extração do PDF do acervo ainda está sob revisão."
                ]
                scan_grounded = False
                scan_reason = "qa_archive_cross_reference_not_found"
            answer = "\n\n".join(lines)
            yield {
                "event": "status",
                "status": "grounding" if scan_grounded else "insufficient_evidence",
            }
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": matched_sources,
                "grounded": scan_grounded,
                "grounding": {
                    "grounded": scan_grounded,
                    "score": 1.0 if scan_grounded else 0.0,
                    "claims": [
                        {
                            "text": f"Referência normativa literal no {source.get('dispositivo_ref')}",
                            "citation_ids": [source["citation_id"]],
                        }
                        for source in matched_sources
                    ],
                    "failed_claims": [] if scan_grounded else [answer],
                    "validation_scope": "literal_normative_cross_reference_in_retrieved_archive_text",
                },
                "reason_code": scan_reason,
                "source_relevance": max(
                    (float(source.get("similarity_score") or 0) for source in matched_sources),
                    default=0.0,
                ),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    contextual_device_scope = bool(_CONTEXTUAL_DEVICE_SCOPE_RE.search(question))
    if contextual_device_scope and len(results) == 1 and results[0].get("citation_id"):
        source = results[0]
        device = str(source.get("dispositivo_ref") or "dispositivo citado")
        norm = str(source.get("norma_ref") or "norma consultada")
        text = str(source.get("full_text") or "").strip()
        if not text:
            # A device label alone is not evidence for a legal explanation.
            # Fall through to the normal grounded-generation/abstention path.
            contextual_device_scope = False
        else:
            answer = (
                f"No PDF arquivado, {_archive_device_label(device, norm)} estabelece: "
                f'“{text}” [[1]]\n\n'
                "*Transcrição automática; metadados e segmentação ainda estão sob revisão. "
                "Confira o PDF original antes de usar.*"
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
                "reason_code": "qa_archive_contextual_device_verbatim",
                "source_relevance": float(source.get("similarity_score") or 0),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    # For an explicitly identified article, quote the retrieved PDF text rather
    # than asking a small local model to paraphrase it. This makes the first QA
    # MVP useful even when Ollama's claim validator rejects a semantically sound
    # paraphrase, and it cannot add facts absent from the extracted article.
    exact_references = [ref for ref in parse_normative_references(question) if not ref.ambiguous]
    query_plan = classify_normative_query(question)
    article_targets = tuple(query_plan.article_targets)
    requires_article_coverage = (
        len(exact_references) == 1
        and len(article_targets) > 1
        and bool(_MULTI_ARTICLE_SYNTHESIS_RE.search(question))
    )
    if (
        len(exact_references) == 1
        and len(article_targets) > 1
        and not _MULTI_ARTICLE_SYNTHESIS_RE.search(question)
    ):
        by_article = {
            _article_key(source.get("dispositivo_ref", "")): source
            for source in results
            if _article_key(source.get("dispositivo_ref", ""))
        }
        ordered_sources = [by_article.get(article) for article in article_targets]
        complete_comparison = (
            all(ordered_sources)
            and len({str(source.get("norma_ref") or "") for source in ordered_sources}) == 1
            and all(
                source.get("full_text") and source.get("citation_id")
                for source in ordered_sources
            )
            and all(
                (source.get("coverage") or {}).get("complete", True)
                for source in ordered_sources
            )
        )
        if complete_comparison:
            source_indexes = {
                source["citation_id"]: index
                for index, source in enumerate(results, 1)
            }
            norm_label = ordered_sources[0]["norma_ref"]
            lines = [f"Nos trechos recuperados de **{norm_label}**, os dispositivos solicitados dizem:"]
            for source in ordered_sources:
                citation = source_indexes[source["citation_id"]]
                lines.append(
                    f"- **{source['dispositivo_ref']}**: “{str(source['full_text']).strip()}” [[{citation}]]"
                )
            lines.append(
                "*Transcrição dos PDFs do acervo local; extração e segmentação ainda pendentes de revisão.*"
            )
            answer = "\n\n".join(lines)
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
                    "claims": [
                        {
                            "text": f"Transcrição de {source['dispositivo_ref']} da extração do PDF",
                            "citation_ids": [source["citation_id"]],
                        }
                        for source in ordered_sources
                    ],
                    "failed_claims": [],
                    "validation_scope": "verbatim_quotes_from_unreviewed_archive_pdf",
                },
                "reason_code": "qa_archive_explicit_article_transcription",
                "source_relevance": min(
                    float(source.get("similarity_score") or 0) for source in ordered_sources
                ),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    article_match = _ARTICLE_RE.search(question)
    if (
        len(exact_references) == 1
        and article_match
        and len(results) == 1
        and not contextual_device_scope
    ):
        source = results[0]
        text = str(source.get("full_text") or "").strip()
        if text:
            answer = (
                f'No PDF arquivado, '
                f'{_archive_device_label(source["dispositivo_ref"], source["norma_ref"])} '
                f'estabelece: '
                f'“{text}” [[1]]\n\n'
                "*Transcrição automática; metadados e segmentação ainda estão sob revisão. "
                "Confira o PDF original antes de usar.*"
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

    article_topic_phrase = _article_topic_phrase(question)
    if len(exact_references) == 1 and article_topic_phrase and results:
        article_topic_label = _article_topic_label(question) or article_topic_phrase
        exact_phrase_sources = [
            source
            for source in results
            if article_topic_phrase in _fold(str(source.get("full_text") or ""))
            and source.get("citation_id")
        ]
        if exact_phrase_sources and len(
            {str(source.get("norma_ref") or "") for source in exact_phrase_sources}
        ) == 1:
            source_indexes = {
                source["citation_id"]: index
                for index, source in enumerate(results, 1)
            }
            norma_ref = str(exact_phrase_sources[0].get("norma_ref") or "norma consultada")
            article_refs = "\n".join(
                f"- [[{source_indexes[source['citation_id']]}]]"
                for source in exact_phrase_sources
            )
            answer = (
                f'A expressão consultada **“{article_topic_label}”** aparece nos seguintes '
                f'trechos de **{norma_ref}**:\n\n{article_refs}\n\n'
                "Esta busca localiza a expressão na transcrição do PDF; confira os trechos "
                "originais antes de interpretar ou aplicar a norma. A extração ainda está sob revisão."
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
                    "claims": [
                        {
                            "text": f'Expressão literal “{article_topic_phrase}” encontrada em {source["dispositivo_ref"]}',
                            "citation_ids": [source["citation_id"]],
                        }
                        for source in exact_phrase_sources
                    ],
                    "failed_claims": [],
                    "validation_scope": "exact_phrase_occurrence_in_unreviewed_archive_extraction",
                },
                "reason_code": "qa_archive_exact_phrase_lookup",
                "source_relevance": min(
                    float(source.get("similarity_score") or 0) for source in exact_phrase_sources
                ),
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
            coverage_disclosure = (
                f"A amostra consultada cobre {selected} de {total} artigos identificados. "
                "Esta resposta é parcial e não representa uma análise integral da norma. "
            )
        if coverage.get("annexes_present"):
            if (
                coverage.get("selected_articles") == coverage.get("total_articles")
                and isinstance(coverage.get("total_articles"), int)
            ):
                article_count = coverage["total_articles"]
                coverage_prompt_note += (
                    f"Todos os {article_count} artigos identificados foram selecionados, "
                    "mas os anexos normativos detectados não foram incluídos. "
                )
                coverage_disclosure = (
                    f"Os {article_count} artigos identificados foram recuperados, mas os anexos "
                    "normativos detectados ficaram fora desta resposta. Portanto, a visão geral "
                    "é parcial e não cobre a norma integralmente. "
                )
            coverage_prompt_note += (
                "O PDF contém anexos normativos que não foram incluídos na seleção de artigos. "
            )
            if coverage.get("selected_articles") != coverage.get("total_articles"):
                coverage_disclosure += (
                    "Anexos normativos também foram detectados no PDF e devem ser consultados à parte. "
                )
        coverage_prompt_note += "Não apresente a amostra como análise integral da norma."
        context += "\n\n[ESCOPO DA RECUPERAÇÃO] " + coverage_prompt_note
    selected_articles = coverage.get("selected_articles")
    total_articles = coverage.get("total_articles")
    validation_results = results
    # Keep response shaping identical to retrieval: a broad classifier label
    # must not turn a topical answer into a whole-norm overview when substantive
    # topic terms correctly narrowed the recovered evidence.
    whole_norm_overview = _is_whole_norm_request(question, query_plan)
    partial_norm_overview = (
        whole_norm_overview
        and coverage.get("complete") is False
        and isinstance(selected_articles, int)
        and isinstance(total_articles, int)
        # A norm may contain every parsed article while still being incomplete
        # because annexes were detected but excluded from article evidence.
        # Keep those requests on the whole-norm path instead of treating them
        # as an ordinary topically retrieved answer.
        and (
            selected_articles < total_articles
            or coverage.get("annexes_present") is True
        )
    )
    if partial_norm_overview:
        # A 24k-character context containing dozens of complete provisions
        # overwhelms small local models and encourages narrow, rejected drafts.
        # Give generation a deterministic, distributed evidence sample while
        # keeping the full retrieval set for source cards and validation.
        prompt_excerpts = _partial_overview_excerpts(
            results,
            limit=_partial_overview_sample_limit(len(results)),
            max_chars=1200,
            question=question,
        )
        if prompt_excerpts:
            excerpt_by_index = {
                excerpt["citation_index"]: excerpt for excerpt in prompt_excerpts
            }
            context = "\n\n".join(
                f"[[{excerpt['citation_index']}]] "
                f"{results[excerpt['citation_index'] - 1].get('norma_ref') or 'Norma consultada'}, "
                f"{excerpt['device']} — excerto da extração do PDF, ainda sob revisão:\n"
                f"{excerpt['text']}"
                for excerpt in prompt_excerpts
            )
            # Preserve citation numbering but prevent the validator from using
            # hidden, unsampled provisions to justify a model claim. The full
            # retrieval set remains available to the source drawer and final SSE.
            validation_results = []
            for index, source in enumerate(results, 1):
                excerpt = excerpt_by_index.get(index)
                validation_results.append({
                    **source,
                    "citation_index": index,
                    "evidence_text": excerpt["text"] if excerpt else "",
                })
            sampled_count = len(prompt_excerpts)
            recovered_count = len(results)
            sample_note = (
                f"A geração recebeu {sampled_count} excertos distribuídos entre "
                f"{recovered_count} dispositivos recuperados; os demais dispositivos "
                "recuperados não foram resumidos nesta resposta."
            )
            if coverage_prompt_note:
                context += "\n\n[ESCOPO DA RECUPERAÇÃO] " + coverage_prompt_note
            context += "\n\n[ESCOPO DA AMOSTRAGEM] " + sample_note
            coverage_disclosure += (
                f" Para esta síntese, a geração recebeu uma amostra de {sampled_count} "
                f"excertos entre {recovered_count} dispositivos recuperados. A resposta "
                "cita apenas os excertos que sustentam as afirmações apresentadas; os "
                "demais dispositivos não foram resumidos."
            )
    # Article-specific answers stay buffered until exact target coverage is
    # confirmed. Partial norm overviews instead release a prefix as soon as it
    # is both grounded and broad enough; this preserves safe progressive SSE.
    hold_generated_chunks = requires_article_coverage
    generation_temperature = 0.0 if partial_norm_overview else temperature
    generation_question = question
    if whole_norm_overview:
        # Coverage counts and archive limitations are attached deterministically
        # below. Keeping those meta-instructions in the model question conflicts
        # with the overview contract, which explicitly delegates coverage notes
        # to the system.
        generation_question = _COVERAGE_SCOPE_REQUEST_RE.sub(" ", generation_question)
        generation_question = _OVERVIEW_SCOPE_QUALIFIER_RE.sub(" ", generation_question)
        generation_question = re.sub(r"\s+", " ", generation_question).strip(" \t,;:")
    prompt = build_prompt(context, generation_question)
    if whole_norm_overview:
        prompt += (
            "\n\nINSTRUÇÃO ESPECÍFICA — VISÃO GERAL DA NORMA:\n"
            "- Escreva até três frases factuais curtas, cada uma apoiada por um excerto diferente "
            "e terminada por um único marcador [[N]]. Se houver menos de três excertos, use cada "
            "excerto disponível uma vez.\n"
            "- Agrupe as frases em um ou dois parágrafos naturais; não use heading, lista, conclusão "
            "ou frase introdutória. Nomeie o artigo correspondente em cada frase e não combine "
            "dispositivos nem atribua a um artigo conteúdo de outro; use cada artigo e marcador "
            "uma única vez.\n"
            "- Faça paráfrase mínima, preserve o verbo operativo e a modalidade do excerto. Não "
            "infira obrigação, permissão, proibição, condição, vigência, efeito ou informação não "
            "expressa. Use somente os excertos amostrados; não descreva o que ficou fora da amostra.\n"
            "- Não repita tema ou denominação: se uma frase já explicou o objeto da norma ou de um "
            "plano/programa, não reescreva a mesma instituição em outra frase com verbo sinônimo "
            "(por exemplo, ‘institui’, ‘cria’ ou ‘estabelece’). Cada frase seguinte deve acrescentar "
            "um aspecto material distinto que esteja expresso em outro dispositivo.\n"
            "- Pare após a terceira afirmação sustentada, ou antes "
            "se houver menos de três excertos. A cobertura "
            "e os anexos serão explicados pelo sistema."
        )
        if partial_norm_overview:
            required_sample_citations = min(
                _PARTIAL_OVERVIEW_MIN_CITED_SOURCES, len(prompt_excerpts)
            )
            prompt += (
                "\n- Há evidências para "
                f"{required_sample_citations} frases: escreva exatamente {required_sample_citations}, "
                "com um artigo e um marcador distinto por frase. O sistema acrescentará a nota de "
                "cobertura parcial; não tente completá-la nem extrapole para os dispositivos fora "
                "da amostra."
            )
    from src.processing.rag_service import RAGService

    validator = RAGService()
    yield {"event": "status", "status": "generating"}
    generation_events = stream_grounded_generation(
        prompt,
        stream_attempt=lambda prompt_text: stream_model_attempt(
            prompt_text,
            ollama=ollama,
            model=model,
            temperature=generation_temperature,
            text_provider=text_provider,
            should_cancel=should_cancel,
        ),
        validate_attempt=lambda answer: validator._validate_answer(answer, validation_results),
        should_cancel=should_cancel,
        retry_after_partial_rejection=partial_norm_overview,
        should_retry_after_partial=(
            lambda answer, validation: not (
                validation.get("grounded")
                and validation.get("source_only")
                and _has_partial_overview_breadth(
                    answer,
                    len(results),
                    available_sample_sources=len(prompt_excerpts),
                )
                and not has_redundant_content_phrase(answer)
            )
            if partial_norm_overview
            else None
        ),
        include_partial_notice=not partial_norm_overview,
        revision_instruction=(
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION
            if partial_norm_overview
            else None
        ) or None,
    )
    streamed_answer = ""
    public_streamed_answer = ""
    public_stream_stopped = False
    while True:
        try:
            generation_event = next(generation_events)
        except StopIteration as completed:
            generation = completed.value
            break
        if generation_event.get("event") == "chunk":
            streamed_answer += generation_event.get("chunk", "")
            if partial_norm_overview:
                # The generation pipeline emits only complete, individually
                # grounded sentences. Keep early sentences private until the
                # overview spans enough distinct sampled devices and passes a
                # conservative repetition check; then stream each safe delta.
                candidate = streamed_answer
                if not public_streamed_answer:
                    if (
                        _has_partial_overview_breadth(
                            candidate,
                            len(results),
                            available_sample_sources=len(prompt_excerpts),
                        )
                        and not has_redundant_content_phrase(candidate)
                    ):
                        public_streamed_answer = candidate
                        yield {
                            "event": "chunk",
                            "chunk": public_streamed_answer,
                            "provisional": False,
                        }
                elif (
                    candidate.startswith(public_streamed_answer)
                    and not has_redundant_content_phrase(candidate)
                ):
                    delta = candidate[len(public_streamed_answer):]
                    if delta:
                        public_streamed_answer = candidate
                        yield {
                            "event": "chunk",
                            "chunk": delta,
                            "provisional": False,
                        }
                else:
                    # Never retract already displayed text. Freeze at the last
                    # clean grounded prefix and disclose the scope below.
                    public_stream_stopped = True
            elif not hold_generated_chunks:
                yield generation_event
    raise_if_cancelled(should_cancel)
    generation_grounding = generation["grounding"]
    grounded = bool(generation_grounding.get("grounded")) and generation["source_only"]
    generation_answer = str(
        generation.get("validated_prefix")
        if partial_norm_overview and generation.get("partial")
        else generation.get("answer", "")
    )
    if (
        partial_norm_overview
        and not generation.get("partial")
        and grounded
        and has_redundant_content_phrase(generation_answer)
    ):
        # If the model repeats a phrase only later in generation, retain the
        # already released broad prefix instead of replacing it with fallback.
        if public_streamed_answer:
            generation_answer = public_streamed_answer
            public_stream_stopped = True
        else:
            grounded = False
    if partial_norm_overview and generation.get("partial"):
        prefix_candidates = list(generation.get("validated_prefix_candidates") or [])
        if (
            generation_answer
            and grounded
            and not any(item.get("answer") == generation_answer for item in prefix_candidates)
        ):
            prefix_candidates.append({
                "answer": generation_answer,
                "grounding": generation_grounding,
                "source_only": generation["source_only"],
            })
        eligible_prefixes = [
            item
            for item in prefix_candidates
            if item.get("source_only")
            and bool((item.get("grounding") or {}).get("grounded"))
            and not has_redundant_content_phrase(str(item.get("answer") or ""))
            and _has_partial_overview_breadth(
                str(item.get("answer") or ""),
                len(results),
                available_sample_sources=len(prompt_excerpts),
            )
        ]
        if eligible_prefixes:
            chosen_prefix = max(
                eligible_prefixes,
                key=lambda item: (
                    len({
                        int(index)
                        for index in re.findall(
                            r"\[\[(\d+)\]\]", str(item.get("answer") or "")
                        )
                    }),
                    len(str(item.get("answer") or "")),
                ),
            )
            generation_answer = str(chosen_prefix["answer"])
            generation_grounding = chosen_prefix["grounding"]
            grounded = True
        else:
            grounded = False
    if (
        grounded
        and partial_norm_overview
        and not _has_partial_overview_breadth(
            generation_answer,
            len(results),
            available_sample_sources=len(prompt_excerpts),
        )
    ):
        grounded = False
    if partial_norm_overview and public_streamed_answer:
        # The visible answer is immutable once streamed. If a later candidate
        # was rejected by a breadth/style gate, finalize exactly that prefix.
        if public_stream_stopped:
            generation_answer = public_streamed_answer
            grounded = True
            reason_code = "generation_partial_after_grounded_prefix"
        elif not generation_answer.startswith(public_streamed_answer):
            generation_answer = public_streamed_answer
            grounded = True
            reason_code = "generation_partial_after_grounded_prefix"
    if (
        grounded
        and requires_article_coverage
        and not _has_requested_article_coverage(
            generation_answer, article_targets, results
        )
    ):
        grounded = False
        if hold_generated_chunks:
            # The incomplete candidate was buffered, never emitted. The
            # evidence-map fallback is now the only answer sent to the user.
            streamed_answer = ""
    if grounded:
        answer = generation_answer
        if coverage_disclosure:
            answer += "\n\n" + coverage_disclosure.rstrip()
        grounding_report = dict(generation_grounding)
        if partial_norm_overview:
            grounding_report["validation_scope"] = (
                "grounded_generated_claims_against_sampled_excerpts_from_unreviewed_archive_pdf"
            )
        reason_code = (
            "generation_partial_after_grounded_prefix"
            if generation.get("partial") or public_stream_stopped
            else None
        )
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
        comparison_fallback = False
        evidence_map_fallback = False
        if partial_norm_overview:
            answer_parts = [
                coverage_disclosure.rstrip()
                or (
                    f"A amostra consultada reúne trechos de {selected_articles} dos "
                    f"{total_articles} artigos identificados na extração."
                )
            ]
            if coverage.get("annexes_present") and not coverage_disclosure:
                answer_parts.append("O PDF também contém anexos que não entraram nessa seleção.")
            answer_parts.append(
                "Para não extrapolar o conteúdo recuperado, seguem trechos literais e abreviados "
                "de diferentes partes da norma; cada referência abre o dispositivo correspondente:"
            )
            excerpts = _partial_overview_excerpts(
                results,
                limit=_partial_overview_sample_limit(len(results)),
                question=question,
            )
            answer_parts.extend(
                f"- “{excerpt['text']}” "
                f"[[{excerpt['citation_index']}]]"
                for excerpt in excerpts
            )
            answer_parts.append(
                "A extração automática e a segmentação ainda estão sob revisão. Confira o PDF "
                "original antes de usar; as fontes completas também estão em Fontes Consultadas."
            )
            answer = "\n\n".join(answer_parts)
            grounding_report = {
                "grounded": bool(excerpts),
                "score": 1.0 if excerpts else 0.0,
                "claims": [
                    {
                        "text": excerpt["text"],
                        "citation_ids": [excerpt["citation_id"]],
                    }
                    for excerpt in excerpts
                ],
                "failed_claims": [],
                "validation_scope": "verbatim_sampled_excerpts_from_unreviewed_archive_pdf",
            }
            grounded = bool(excerpts)
            reason_code = "qa_archive_partial_overview_evidence_map"
        elif (
            len(exact_references) == 1
            and len(article_targets) > 1
            and _MULTI_ARTICLE_SYNTHESIS_RE.search(question)
        ):
            sources_by_article = {
                _article_key(str(source.get("dispositivo_ref") or "")): source
                for source in results
                if source.get("citation_id") and str(source.get("full_text") or "").strip()
            }
            requested_sources = [
                sources_by_article.get(article) for article in article_targets
            ]
            same_complete_norm = (
                all(requested_sources)
                and len({str(source.get("norma_ref") or "") for source in requested_sources}) == 1
                and all((source.get("coverage") or {}).get("complete", True) for source in requested_sources)
            )
            if same_complete_norm:
                source_indexes = {
                    source["citation_id"]: index
                    for index, source in enumerate(results, 1)
                }
                answer_lines = ["Nos trechos recuperados, os dispositivos indicados estabelecem:"]
                for source in requested_sources:
                    citation = source_indexes[source["citation_id"]]
                    quote = str(source["full_text"]).strip()
                    article_ref = source.get("dispositivo_ref") or "Dispositivo"
                    answer_lines.append(
                        f"- **{article_ref}**: “{quote}” [[{citation}]]"
                    )
                answer_lines.append(
                    "A comparação fica limitada a essas transcrições: elas não mostram "
                    "referência expressa de um dispositivo ao outro. A extração ainda "
                    "está sob revisão; confira o PDF original antes de aplicar a norma."
                )
                answer = "\n\n".join(answer_lines)
                grounding_report = {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": f"Transcrição de {source['dispositivo_ref']} da extração arquivada",
                            "citation_ids": [source["citation_id"]],
                        }
                        for source in requested_sources
                    ],
                    "failed_claims": [],
                    "validation_scope": "explicit_article_comparison_verbatim_fallback",
                }
                grounded = True
                reason_code = "qa_archive_comparison_evidence_fallback"
                comparison_fallback = True
            else:
                answer = "Localizei dispositivos que podem ajudar a conferir essa questão: "
                answer += "; ".join(reference_groups) + "."
                answer += (
                    " Abra os links para conferir o texto no PDF do acervo histórico local. "
                    "Como a extração ainda está em revisão, apresento esses dispositivos como pontos de consulta, "
                    "não como uma síntese validada."
                )
                grounding_report = {
                    "grounded": bool(reference_groups),
                    "score": 0.0,
                    "claims": [
                        {"text": f"Dispositivo localizado: {source.get('norma_ref')}, {source.get('dispositivo_ref')}", "citation_ids": [source["citation_id"]]}
                        for source in results if source.get("full_text") and source.get("citation_id")
                    ],
                    "failed_claims": [],
                    "validation_scope": "retrieved_source_index_only_after_synthesis_rejected",
                }
                grounded = bool(reference_groups)
                reason_code = "qa_archive_evidence_only_fallback"
        else:
            excerpts = _partial_overview_excerpts(
                results, limit=3, question=question
            )
            if excerpts:
                answer_parts = [
                    "No PDF do acervo, estes são os trechos relacionados à pergunta que podem ser conferidos:"
                ]
                answer_parts.extend(
                    f"- **{excerpt['device']}**: “{excerpt['text']}” "
                    f"[[{excerpt['citation_index']}]]"
                    for excerpt in excerpts
                )
                answer_parts.append(
                    "*Transcrição automática do acervo local; extração e segmentação ainda "
                    "estão sob revisão. Confira o PDF original antes de usar.*"
                )
                if coverage_disclosure:
                    answer_parts.append(coverage_disclosure.rstrip())
                answer = "\n\n".join(answer_parts)
                grounding_report = {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": excerpt["text"],
                            "citation_ids": [excerpt["citation_id"]],
                        }
                        for excerpt in excerpts
                    ],
                    "failed_claims": [],
                    "validation_scope": "verbatim_sampled_excerpts_from_unreviewed_archive_pdf",
                }
                grounded = True
                reason_code = "qa_archive_evidence_map_fallback"
                evidence_map_fallback = True
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
        if not comparison_fallback and not partial_norm_overview and not evidence_map_fallback:
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
    if partial_norm_overview:
        streamed_answer = public_streamed_answer if grounded else ""
    elif not answer.startswith(streamed_answer):
        answer = streamed_answer or answer
    for offset in range(0, len(answer[len(streamed_answer) :]), 72):
        raise_if_cancelled(should_cancel)
        yield {
            "event": "chunk",
            "chunk": answer[len(streamed_answer) + offset : len(streamed_answer) + offset + 72],
            "provisional": False,
        }
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
