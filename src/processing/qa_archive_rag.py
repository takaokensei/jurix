"""Retrieval over unreviewed archive PDFs, available only in isolated QA settings."""

from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, Value, When
from django.urls import reverse

from src.apps.legislation.document_models import (
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.models import Norma
from src.apps.legislation.source_urls import canonical_norma_url, canonical_sapl_url
from src.processing.coordinated_article_references import (
    parse_coordinated_article_norm_pairs,
)
from src.processing.document_metadata import compare_identity_to_epigraph, parse_initial_epigraphs
from src.processing.normative_query import classify_normative_query, requested_edition_scope
from src.processing.normative_reference import (
    canonical_type,
    normalize_number,
    parse_normative_references,
)
from src.processing.partial_overview_quality import (
    has_redundant_content_phrase,
    has_repeated_citation_marker,
)
from src.processing.rag_answer_pipeline import (
    insufficient_evidence_events,
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
_PLURAL_ARTICLE_GROUP_RE = re.compile(
    r"\bart(?:s|igo(?:s)?)?\.?\s*(?P<articles>\d{1,4}\s*[º°ªo]?"
    r"(?:\s*,\s*(?:inciso\s+)?[ivxlcdm]+)?"
    r"(?:\s*(?:,\s*(?:e\s+|ou\s+)?|;\s*(?:e\s+|ou\s+)?|\be\s+|\bou\s+)"
    r"\s*(?:inciso\s+[ivxlcdm]+\s*,\s*)?"
    r"(?:art(?:igo)?\.?\s*)?\d{1,4}\s*[º°ªo]?)+)",
    re.IGNORECASE,
)
_APPENDIX_QUERY_RE = re.compile(
    r"\b(?P<label>anexo|adendo|ap[eê]ndice|quadro|tabela)\s+" r"(?P<number>[ivxlcdm]+|\d+)\b",
    re.IGNORECASE,
)
_CROSS_REFERENCE_SCAN_RE = re.compile(
    r"(?:\b(?:(?:quais|que)\s+(?:artigos?|dispositivos?)|"
    r"(?:todos|todas)\s+(?:os|as)\s+(?:artigos?|dispositivos?))\b.{0,120}?"
    r"\b(?:mencionam|menciona|citam|cita|"
    r"fazem\s+(?:(?:essa|esta|a)\s+)?(?:refer[eê]ncia|remiss[aã]o)|"
    r"faz\s+(?:(?:essa|esta|a)\s+)?(?:refer[eê]ncia|remiss[aã]o)|"
    r"remetem|remete|referenciam|referencia|referem-se|refere-se)\b|"
    r"\b(?:lei|lc)\b.{0,100}?\b(?:mencionam|menciona|citam|cita|"
    r"faz(?:em)?\s+(?:(?:essa|esta|a)\s+)?(?:refer[eê]ncia|remiss[aã]o)|"
    r"remetem|remete|referenciam|referencia|referem-se|refere-se)\b.{0,100}?\b(?:lei|lc)\b)",
    re.IGNORECASE,
)
_ARTICLE_TOPIC_LOOKUP_RE = re.compile(
    r"\b(?:qual|quais)\s+artigos?\b.{0,80}?\b"
    r"(?:trata(?:m)?|menciona(?:m)?|cont[eê]m|aborda(?:m)?|disp[oõ]e(?:m)?)\b"
    r"\s+(?:de|do|da|dos|das|sobre)\s+(?P<topic>[^?.;]+)",
    re.IGNORECASE,
)
_EFFECTIVE_DATE_ARTICLE_QUERY_RE = re.compile(
    r"(?:"
    r"\b(?:qual|quais)\s+(?:o\s+)?(?:artigos?|dispositivos?)\b.{0,100}?\b"
    r"(?:define(?:m)?|estabelece(?:m)?|fixa(?:m)?|determina(?:m)?|"
    r"informa(?:m)?|prev[eê]m?|disp[oõ]e(?:m)?(?:\s+sobre)?)\b.{0,80}?\b"
    r"(?:data\s+de\s+entrada\s+em\s+vigor|entrada\s+em\s+vigor|"
    r"vig[eê]ncia|quando\s+(?:esta\s+)?(?:lei|norma)\s+entra\s+em\s+vigor)\b"
    r"|"
    r"\b(?:quando|em\s+que\s+data|qual\s+(?:e|é)\s+a\s+data)\b.{0,100}?"
    r"(?:(?:a|esta|a\s+presente)\s+)?(?:lei(?:\s+complementar)?|norma)?\s*"
    r"(?:entra(?:r[aá]?)?\s+em\s+vigor|entrou\s+em\s+vigor|"
    r"passa(?:r)?\s+a\s+vigorar|passou\s+a\s+vigorar|"
    r"começou\s+a\s+vigorar|vigora)"
    r")",
    re.IGNORECASE,
)
_EFFECTIVE_DATE_OPERATIVE_RE = re.compile(
    r"\b(?:esta|a\s+presente)\s+(?:lei(?:\s+complementar)?|norma)\s+"
    r"(?:entra(?:r[aá]?)?\s+em\s+vigor|passa\s+a\s+vigorar)\b",
    re.IGNORECASE,
)
_HISTORICAL_WORDING_QUERY_RE = re.compile(
    r"\b(?:qual|que)\s+reda[cç][aã]o\b.{0,120}?"
    r"\b(?:vigente|em\s+vigor)\b.{0,40}?\b(?:em\s+)?(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_EXPLICIT_TEXT_COMPARISON_QUERY_RE = re.compile(
    r"\b(?:compare|comparar|comparem|diferen[cç]a(?:s)?\s+entre|" r"confronte|coteje)\b",
    re.IGNORECASE,
)
_EXPLICIT_AMENDMENT_QUERY_RE = re.compile(
    r"\b(?:acrescent(?:a|am|ou|aram)|adicion(?:a|am|ou|aram)|inclu(?:i|em|iu|íram)|"
    r"inser(?:e|em|iu|iram)|alter(?:a|am|ou|aram)|modific(?:a|am|ou|aram)|"
    r"substitu(?:i|em|iu|íram)|d[aá]\s+nova\s+reda[cç][aã]o)\b",
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
_NORM_IDENTITY_TOPIC_RE = re.compile(
    r"\b(?:qual|que)\s+norma\b.{0,100}?\b"
    r"(?:institui|instituiu|cria|criou|estabelece|estabeleceu)\s+"
    r"(?P<topic>.+?)(?=\s+e\s+(?:o\s+que|qual|como|onde)\b|"
    r"\s+art(?:igo)?\.?\s*\d|[?.;]|$)",
    re.IGNORECASE,
)
_ARTICLE_KEY_RE = re.compile(r"(\d{1,4})(?:\s*[ºª°o])?(?:\s*-\s*([A-Za-z]))?", re.IGNORECASE)
_CONTEXTUAL_DEVICE_SCOPE_RE = re.compile(
    r";\s*dispositivo\s+de\s+refer[eê]ncia\s*:\s*art\.", re.IGNORECASE
)
_ARTICLE_SCOPE_LIMITS_REQUEST_RE = re.compile(
    r"\b(?:alcance|aplicabilidade|limites?|o\s+que\s+(?:esse\s+trecho\s+)?"
    r"(?:eu\s+)?n[aã]o\s+(?:posso|permite|autoriza)\s+concluir|"
    r"o\s+que\s+(?:ainda\s+)?n[aã]o\s+(?:[eé]|se\s+pode)\s+concluir|"
    r"dados\s+do\s+processo|caso\s+concreto|obra\s+espec[ií]fica)\b",
    re.IGNORECASE,
)
_CASE_RECORD_SUFFICIENCY_REQUEST_RE = re.compile(
    r"\b(?:documenta[cç][aã]o|documentos?|pe[cç]as?|autos?)\b"
    r"[\s\S]{0,100}\b(?:suficiente|complet[oa]s?|adequad[oa]s?|bastam?|"
    r"juntad[oa]s?|anexad[oa]s?|apresentad[oa]s?|pendentes?|faltam?)\b|"
    r"\b(?:suficiente|complet[oa]s?|adequad[oa]s?)\b[\s\S]{0,100}"
    r"\b(?:documenta[cç][aã]o|documentos?|pe[cç]as?|autos?)\b|"
    r"\bquais\s+(?:documentos?|pe[cç]as?)\b[\s\S]{0,100}"
    r"\b(?:juntad[oa]s?|anexad[oa]s?|apresentad[oa]s?|faltam|pendentes?)\b",
    re.IGNORECASE,
)
_LEGISLATIVE_MATTER_QUERY_RE = re.compile(
    r"\b(?:plc|projeto\s+de\s+lei(?:\s+complementar)?|"
    r"emenda\s+(?:supressiva|modificativa|aditiva)|"
    r"proposi[cç][aã]o|mat[eé]ria\s+legislativa)\b",
    re.IGNORECASE,
)
_PROPOSED_WORDING_REQUEST_RE = re.compile(
    r"\b(?:red[aã]ç[aã]o|texto|conte[uú]do)\b.{0,60}\b(?:propost[oa]|projeto)\b|"
    r"\bproposta\s+de\s+(?:nova\s+)?(?:red[aã]ç[aã]o|texto)\b",
    re.IGNORECASE,
)
_PROCESS_TRANSITION_EVIDENCE_RE = re.compile(
    r"\bprocessos?\b.{0,160}\bprotocolad[oa]s?\b.{0,160}\bentrada\s+em\s+vigor\b"
    r".{0,160}\bsem\s+despacho\s+decis[oó]rio\b.{0,240}\bmanifesta[cç][aã]o\s+formal\b",
    re.IGNORECASE | re.DOTALL,
)
_PROTOCOL_DATE_EVIDENCE_RE = re.compile(
    r"\blegisla[cç][oõ]es?\s+vigentes?\s+na\s+data\s+do\s+protocolo\b",
    re.IGNORECASE,
)
_PROCESS_TRANSITION_SCOPE_REQUEST_RE = re.compile(
    r"\b(?:regra\s+de\s+transi[cç][aã]o|"
    r"transi[cç][aã]o\b.{0,80}\b(?:art(?:igo)?\.?\s*\d+|regra)\b|"
    r"manifesta[cç][aã]o\s+formal|op[cç][aã]o\s+formal)\b|"
    r"\bpedidos?\s+de\s+licenciamento\b.{0,120}\bprotocolad[oa]s?\b"
    r".{0,120}\b(?:antes|at[eé])\b.{0,80}\b(?:entrada\s+em\s+vigor|vig[eê]ncia)\b|"
    r"\bpedidos?\s+de\s+licenciamento\b.{0,100}\bprotocolad[oa]s?\b"
    r".{0,120}\bentrada\s+em\s+vigor\b.{0,120}\bsem\s+despacho\s+decis[oó]rio\b|"
    r"\bprocessos?\b.{0,100}\bprotocolad[oa]s?\b.{0,120}\bentrada\s+em\s+vigor\b"
    r".{0,120}\bsem\s+despacho\s+decis[oó]rio\b|"
    r"\bdespacho\s+decis[oó]rio\b.{0,100}\b(?:automaticamente|lei\s+nova|"
    r"regime\s+(?:aplic[aá]vel|jur[ií]dico))\b|"
    r"\b(?:automaticamente|lei\s+nova|regime\s+(?:aplic[aá]vel|jur[ií]dico))\b"
    r".{0,100}\bdespacho\s+decis[oó]rio\b|"
    r"\bprocessos?\b.{0,24}\bde\s+licenciamento\b.{0,120}\b"
    r"(?:protocolad[oa]s?|sem\s+despacho|despacho\s+decis[oó]rio|"
    r"entrada\s+em\s+vigor|vig[eê]ncia)\b",
    re.IGNORECASE,
)
_REPEAL_TRANSITION_RELATION_RE = re.compile(
    r"(?=.*\btransi[cç][aã]o\b)(?=.*\brevog)"
    r"(?=.*\b(?:relaciona(?:m)?|rela[cç][aã]o|articula(?:m)?|articula[cç][aã]o)\b).+",
    re.IGNORECASE | re.DOTALL,
)
_AUTO_NEW_LAW_AFTER_DECISION_QUERY_RE = re.compile(
    r"\bdespacho\s+decis[oó]rio\b.{0,100}\b(?:automaticamente|lei\s+nova|"
    r"regime\s+(?:aplic[aá]vel|jur[ií]dico))\b|"
    r"\b(?:automaticamente|lei\s+nova|regime\s+(?:aplic[aá]vel|jur[ií]dico))\b"
    r".{0,100}\bdespacho\s+decis[oó]rio\b",
    re.IGNORECASE,
)
_NORMATIVE_CHANGE_INVENTORY_QUERY_RE = re.compile(
    r"\b(?:o\s+que|quais?\s+(?:dispositivos?|normas?|artigos?)|liste|identifique)\b"
    r".{0,120}\b(?:alterad[oa]s?|revogad[oa]s?|modificad[oa]s?|alterou|revogou|modificou)\b"
    r".{0,100}\b(?:pela|por|promovid[oa]s?\s+por)\b|"
    r"\b(?:o\s+que|quais?)\b.{0,80}\b(?:a\s+lei|esta\s+lei|a\s+norma|esta\s+norma)\b"
    r".{0,60}\b(?:alterou|revogou|modificou)\b",
    # Article-targeted follow-ups such as "quais alterações posteriores do Art. 21".
    # Keep the exact act/year requirement in _is_normative_change_inventory_request.
    re.IGNORECASE,
)
_NORMATIVE_CHANGE_HISTORY_QUERY_RE = re.compile(
    r"\bquais?\s+(?:as\s+)?(?:altera[cç][oõ]es?|revoga[cç][oõ]es?|modifica[cç][oõ]es?)"
    r"\s+(?:posteriores?|subsequentes?)\b",
    re.IGNORECASE,
)
_DIRECT_NORMATIVE_HISTORY_REQUEST_RE = re.compile(
    r"\b(?:se\s+(?:houve|ocorreram|ocorreu|existem?)|"
    r"(?:foi|foram|est[aá]|est[aã]o)\s+(?:alterad[oa]s?|revogad[oa]s?|modificad[oa]s?)|"
    r"(?:sofreu|sofreram)\s+(?:alterad[oa]s?|revogad[oa]s?|modificad[oa]s?|"
    r"altera[cç][ãa]o|revoga[cç][ãa]o|modifica[cç][ãa]o|"
    r"altera[cç][õo]es|revoga[cç][õo]es|modifica[cç][õo]es)|"
    r"(?:alterou|revogou|modificou|quais?\s+altera[cç][oõ]es?\s+posteriores?)|"
    r"(?:recebeu|ganhou|teve|passou\s+a\s+ter)\s+(?:uma\s+)?nova\s+red[aã][cç][aã]o|"
    r"nova\s+red[aã][cç][aã]o.{0,80}\b(?:ato|artigo|dispositivo|posterior)\b|"
    r"ainda\s+vigora|continua\s+vigente|permanece\s+vigente)\b",
    re.IGNORECASE,
)
_RELATION_SCOPE_QUALIFIER_RE = re.compile(
    r"\b(?:separe|distinga|diferencie|esclare[cç]a|indique)\b"
    r".{0,120}\b(?:vig[eê]ncia|vigente|red[aã]c[aã]o\s+(?:atual|arquivada)|"
    r"altera[cç][oõ]es?\s+posteriores?)\b",
    re.IGNORECASE,
)
_NORMATIVE_CHANGE_EVIDENCE_RE = re.compile(
    r"\b(?:passam?\s+a\s+vigorar|d[êe]-se\s+nova\s+red[aã]c[aã]o|"
    r"(?:fica[m]?\s+)?(?:revogad[oa]s?|alterad[oa]s?|acrescid[oa]s?|"
    r"revog(?:a|am|ou|aram|ar|ando)|alter(?:a|am|ou|aram|ar|ando)|"
    r"modific(?:a|am|ou|aram|ar|ando)|suprim(?:e|em|iu|iram|ir)|"
    r"acrescent(?:a|am|ou|aram|ar)|adiciona(?:m)?)|"
    r"revogam-se|alteram-se)\b",
    re.IGNORECASE,
)
_AMENDMENT_OPERATIVE_CLAUSE_RE = re.compile(
    r"\b(?:passa[m]?\s+a\s+vigorar|d[êe]-se\s+nova\s+reda[cç][aã]o|"
    r"fica[m]?\s+(?:acrescid[oa]s?|inclu[ií]d[oa]s?|alterad[oa]s?)|"
    r"(?:acrescent(?:a|am|ou|aram)|adiciona(?:m)?|inclu[ií](?:ram)?|"
    r"substitu[ií](?:ram)?|modific(?:a|am|ou|aram)))\b",
    re.IGNORECASE,
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
    "a",
    "ao",
    "aos",
    "as",
    "com",
    "como",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "entre",
    "essa",
    "esse",
    "esta",
    "este",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelo",
    "por",
    "que",
    "qual",
    "se",
    "sobre",
    "um",
    "uma",
    "uns",
    "umas",
    "art",
    "artigo",
    "lei",
    "municipal",
    "municipais",
    "municipio",
    "natal",
    "sera",
    "serao",
}
_QUERY_FRAMING = {
    "artigo",
    "diz",
    "dispoe",
    "estabelece",
    "estabelecem",
    "faca",
    "falar",
    "inteira",
    "mostra",
    "norma",
    "preve",
    "qual",
    "resuma",
    "resumo",
    "trata",
    "artigos",
    "cada",
    "centrais",
    "conteudo",
    "cobrindo",
    "indicando",
    "principais",
    "ponto",
    "pontos",
    "quais",
    "sintese",
    "sintetize",
    "breve",
    "sustentam",
    "temas",
    "visao",
    "geral",
    "panorama",
    "integral",
    "indique",
    "dispositivos",
    "lc",
    "eixo",
    "eixos",
    "sao",
    "contexto",
    "normativo",
    "explique",
    "descreva",
    "detalhe",
    "informe",
    "fale",
    "conte",
    "vincule",
    "vinculando",
    "afirmacao",
    "afirmacoes",
    "correspondente",
    "correspondentes",
    "identificavel",
    "identificaveis",
    "identificado",
    "identificada",
    "identificados",
    "identificadas",
    "encontrado",
    "encontrados",
    "encontrada",
    "encontradas",
    "tratado",
    "tratada",
    "tratados",
    "tratadas",
    "abordado",
    "abordada",
    "abordados",
    "abordadas",
    "previsto",
    "prevista",
    "previstos",
    "previstas",
    "objetiva",
    "objetivo",
    # Normative type words identify the document; they are not topical terms
    # that should exclude every article when the user asks about the whole law.
    "complementar",
    "decreto",
    "decretos",
    "legislativo",
    "ordinaria",
    "organica",
    "promulgada",
    "resolucao",
    "portaria",
}
_EVIDENCE_REQUEST_FRAMING = {
    "apenas",
    "aparecem",
    "cite",
    "citem",
    "concluir",
    "especifica",
    "especifico",
    "recuperado",
    "recuperados",
    "recuperada",
    "recuperadas",
    "responde",
    "sustenta",
    "sustentam",
}
_ARCHIVE_RETRIEVAL_FRAMING = {
    # Generic question wording otherwise floods the SQL shortlist before
    # expensive parsing of the extracted PDFs.
    "acervo",
    "apenas",
    "ato",
    "atos",
    "concluir",
    "consta",
    "constam",
    "disponivel",
    "ele",
    "ela",
    "nao",
    "permite",
    "permitem",
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
    r"(?:foram|s[aã]o|est[aã]o)\s+(?:identificados?|recuperados?|selecionados?|inclu[ií]dos?)"
    r"(?:\s+e\s+se\s+(?:os?\s+)?anexos?\s+(?:foram|s[aã]o|est[aã]o)\s+"
    r"(?:considerados?|inclu[ií]dos?|recuperados?))?"
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
_DIRECT_WHOLE_NORM_SUMMARY_RE = re.compile(
    r"\b(?:s[ií]ntese|resumo|panorama|vis[aã]o\s+geral)"
    r"(?:\s+(?:curta|breve|executiva|geral))?\s+(?:da|do)\s+"
    r"(?:lei(?:\s+complementar|\s+org[aâ]nica)?|lc|norma|decreto)\b",
    re.IGNORECASE,
)
_WHOLE_NORM_THEMES_SUMMARY_RE = re.compile(
    r"\b(?:fa[cç]a\s+)?(?:uma\s+)?(?:s[ií]ntese|resumo|panorama)\s+"
    r"(?:dos?\s+)?principais?\s+temas?\s+"
    r"(?:e\s+(?:(?:dos?|de)\s+)?dispositivos?\s+)?"
    r"(?:encontrados?|identificados?)?\s+(?:na|da)\s+"
    r"(?:lei(?:\s+complementar|\s+org[aâ]nica)?|lc|norma|decreto)\b",
    re.IGNORECASE,
)
_OVERVIEW_SCOPE_QUALIFIER_RE = re.compile(
    r"\b(?:sem\s+(?:inventar|presumir|fingir|afirmar|alegar)\s+"
    r"(?:(?:uma?|a)\s+)?(?:an[aá]lise|s[ií]ntese|cobertura)\s+"
    r"(?:integral|completa|exaustiva|total)|"
    r"s[oó]\s+(?:sintetize|apresente|inclua|use)\s+"
    r"(?:(?:somente|apenas)\s+)?(?:as?\s+)?(?:afirma[cç][õo]es?|conclus[oõ]es?|pontos?)\s+"
    r"(?:que\s+sejam\s+)?apoiad[oa]s?\s+(?:(?:pel[oa]s?|nas?)\s+)?fontes|"
    r"n[aã]o\s+trate\s+a\s+extra[cç][aã]o\s+(?:local\s+)?como\s+"
    r"texto\s+(?:jur[ií]dico\s+)?(?:revisado|validado|conferido)|"
    r"(?:informe|indique|diga)\s+expressamente\s+se\s+a\s+recupera[cç][aã]o\s+"
    r"cobre\s+a\s+norma\s+inteira\s+ou\s+apenas\s+parte\s+dela)\b",
    re.IGNORECASE,
)
_TYPE_LABELS = {
    "lei": "Lei",
    "lei_ordinaria": "Lei Ordinária",
    "lei_complementar": "Lei Complementar",
    "lei_organica": "Lei Orgânica",
    "lei_promulgada": "Lei Promulgada",
    "decreto": "Decreto",
    "decreto_lei": "Decreto-Lei",
    "decreto_legislativo": "Decreto Legislativo",
    "resolucao": "Resolução",
    "portaria": "Portaria",
}
_TYPE_ALIASES = {
    "lei": {"lei", "lei_ordinaria"},
}
# Keep the entire set of parsed articles for ordinary medium-sized acts (the
# QA corpus includes a 39-article law totaling ~29k characters). Generation
# still receives a smaller, distributed excerpt sample for local-model safety.
# Truly large acts remain bounded and advertise partial article coverage.
_WHOLE_NORM_CONTEXT_BUDGET_CHARS = 32_000
_PARTIAL_OVERVIEW_MIN_CITED_SOURCES = 3
_PARTIAL_OVERVIEW_MAX_SAMPLED_SOURCES = 10
# Parsing a lexical shortlist is CPU-heavy (every candidate is segmented into
# legal devices before article-level ranking). Keep topical queries bounded;
# explicit references and named-norm lookups use their own targeted paths.
_ARCHIVE_LEXICAL_CANDIDATE_LIMIT = 60
_ARCHIVE_EXPLICIT_TITLE_CANDIDATE_LIMIT = 40
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
    answer: str,
    source_count: int,
    *,
    available_sample_sources: int | None = None,
    sources: list[dict] | None = None,
) -> bool:
    """Require broad, source-resolved citations; reject visible wrong labels."""
    answer = str(answer or "")
    marker_matches = list(re.finditer(r"\[\[(\d+)\]\]", answer))
    marker_indexes = [int(match.group(1)) for match in marker_matches]
    if any(index < 1 or index > source_count for index in marker_indexes):
        return False
    cited_indexes = set(marker_indexes)
    required_sources = min(
        _PARTIAL_OVERVIEW_MIN_CITED_SOURCES,
        available_sample_sources if available_sample_sources is not None else source_count,
    )
    if len(cited_indexes) < required_sources:
        return False

    if sources is None:
        return True

    # Citation markers are already resolved through the ordered structured
    # source list. If prose also names an article, reject a mismatch; do not
    # require the model to repeat the article number when the linked citation
    # itself carries that metadata.
    sentence_boundary = (
        r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|" r"(?<=\]\])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|[\r\n]+"
    )
    sentence_spans = []
    sentence_start = 0
    for boundary in re.finditer(sentence_boundary, answer):
        sentence_spans.append(
            (sentence_start, boundary.start(), answer[sentence_start : boundary.start()])
        )
        sentence_start = boundary.end()
    sentence_spans.append((sentence_start, len(answer), answer[sentence_start:]))

    for match in marker_matches:
        source_index = int(match.group(1))
        if source_index > len(sources):
            return False
        device_key = _article_key(str(sources[source_index - 1].get("dispositivo_ref") or ""))
        article_parts = re.fullmatch(r"(\d+)([a-z]?)", device_key)
        if not article_parts:
            return False
        article_pattern = re.compile(
            r"\b(?:art\.?|artigo)\s*(\d+)(?:\s*[-º°ª])?" r"(?:\s*[-–]\s*([a-z]))?",
            re.IGNORECASE,
        )
        sentence = next(
            (text for start, end, text in sentence_spans if start <= match.start() <= end),
            "",
        )
        visible_articles = {
            f"{int(match.group(1))}{(match.group(2) or '').casefold()}"
            for match in article_pattern.finditer(sentence)
        }
        if visible_articles and device_key not in visible_articles:
            return False
    return True


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
            rf"\s*(?:[-–]\s*)?{re.escape(article_parts.group(2))}" if article_parts.group(2) else ""
        )
        article_pattern = re.compile(
            rf"\b(?:art\.?|artigo)\s*{re.escape(article_parts.group(1))}"
            rf"(?:\s*[-º°ª])?{suffix_pattern}\b",
            re.IGNORECASE,
        )
        if not article_pattern.search(answer) or f"[[{source_index}]]" not in answer:
            return False
    return True


def _requested_articles_without_coverage(
    answer: str, article_targets: tuple[str, ...], sources: list[dict]
) -> tuple[str, ...]:
    """Return requested devices not represented by a cited answer claim."""
    return tuple(
        target
        for target in article_targets
        if not _has_requested_article_coverage(answer, (target,), sources)
    )


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
    results: list[dict],
    *,
    limit: int = 5,
    max_chars: int = 220,
    question: str = "",
    topical_only: bool = False,
) -> list[dict]:
    """Choose verbatim excerpts for a norm overview or a topical evidence map."""
    eligible = [
        (index, source)
        for index, source in enumerate(results, 1)
        if source.get("citation_id") and str(source.get("full_text") or "").strip()
    ]
    if topical_only:
        # A failed topical synthesis must not fall back to a representative
        # sample of unrelated documents. Anchor the evidence map on the most
        # specific query term that actually occurs in recovered device text.
        # Whole-norm overviews deliberately keep their separate, distributed
        # sampling behavior.
        topical_tokens = (
            _tokens(_NORMATIVE_REFERENCE_SPAN_RE.sub(" ", str(question or "")))
            - _QUERY_FRAMING
            - _EVIDENCE_REQUEST_FRAMING
        )
        topical_tokens = {token for token in topical_tokens if len(token) >= 5}
        if not topical_tokens:
            return []
        evidence_tokens = {
            index: _tokens(str(source.get("full_text") or "")) for index, source in eligible
        }
        most_specific_length = max(map(len, topical_tokens))
        anchors = {token for token in topical_tokens if len(token) >= most_specific_length - 1}
        topic_anchors = anchors
        eligible = [item for item in eligible if evidence_tokens[item[0]] & anchors]
    else:
        topic_anchors = set()

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
    if topical_only:
        # Keep a failed topical synthesis concise even when many archived
        # decrees repeat the same payment rule. Every recovered source remains
        # available in Fontes Consultadas; the answer body samples only the
        # requested number of evidence excerpts.
        selected = eligible[:limit]
    elif len(eligible) <= limit:
        selected = eligible
    else:
        positions = {
            round(position * (len(eligible) - 1) / (limit - 1)) for position in range(limit)
        }
        selected = [item for position, item in enumerate(eligible) if position in positions]

    excerpts = []
    for citation_index, source in selected:
        text = re.sub(r"\s+", " ", str(source["full_text"])).strip()
        if topical_only and topic_anchors:
            anchor_match = next(
                (
                    match
                    for match in re.finditer(r"[^\W\d_]+", text, flags=re.UNICODE)
                    if _fold(match.group()) in topic_anchors
                ),
                None,
            )
            if anchor_match and len(text) > max_chars:
                start = max(0, anchor_match.start() - max_chars // 3)
                end = min(len(text), start + max_chars)
                if start:
                    start = text.find(" ", start)
                    start = start + 1 if start >= 0 else 0
                if end < len(text):
                    boundary = text.rfind(" ", start, end)
                    if boundary > start:
                        end = boundary
                text = ("…" if start else "") + text[start:end].strip()
                if end < len(str(source["full_text"]).strip()):
                    text += "…"
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        excerpts.append(
            {
                "citation_index": citation_index,
                "citation_id": source["citation_id"],
                "device": str(source.get("dispositivo_ref") or "Dispositivo recuperado"),
                "text": text,
            }
        )
    return excerpts


def _partial_overview_evidence_narrative(excerpts: list[dict]) -> list[str]:
    """Present fallback evidence as a concise list without editorial claims."""
    return [f"- “{excerpt['text']}” " f"[[{excerpt['citation_index']}]]" for excerpt in excerpts]


def _partial_overview_limits_disclosure(question: str) -> str | None:
    """State the boundary between statutory excerpts and case-specific proof."""
    if not _ARTICLE_SCOPE_LIMITS_REQUEST_RE.search(str(question or "")):
        return None
    return (
        "Esses excertos não trazem os fatos dos autos nem confirmam a redação oficial "
        "aplicável na data relevante. Portanto, não permitem concluir a situação de uma "
        "obra ou processo concreto nem se alguma providência cabe ao caso; confira os autos, "
        "a publicação oficial e o histórico de alterações."
    )


def _partial_overview_triage_checklist(question: str) -> str | None:
    """Answer an explicit request for practical cautions without attributing them to law."""
    normalized_question = str(question or "")
    asks_for_cautions = re.search(
        r"\b(?:cautelas?|cuidados?|pontos\s+de\s+aten[cç][aã]o)\b",
        normalized_question,
        re.IGNORECASE,
    )
    asks_before_application = re.search(
        r"\b(?:antes\s+de\s+(?:aplicar|usar|invocar)|"
        r"aplicar\s+.{0,50}\b(?:processo|autos|caso)|"
        r"processo\s+concreto|autos\s+concretos)\b",
        normalized_question,
        re.IGNORECASE,
    )
    if not asks_for_cautions or not asks_before_application:
        return None
    return (
        "Como roteiro geral de triagem — não como requisitos atribuídos a esta lei — "
        "confira três pontos antes de aplicar os excertos:\n\n"
        "1. **Texto e vigência:** coteje o PDF com a publicação oficial e verifique alterações, "
        "revogações e a redação aplicável na data relevante.\n"
        "2. **Fatos e estágio dos autos:** confirme datas, pedidos, documentos, decisões e "
        "demais fatos do processo; eles não foram fornecidos nem são demonstrados por estes excertos.\n"
        "3. **Contexto normativo:** confira dispositivos relacionados, regras transitórias e "
        "anexos no texto integral antes de formular uma conclusão para o caso."
    )


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _relation_candidate_dedupe_key(source: dict) -> tuple[str, ...]:
    """Identify literal duplicate relation evidence without merging editions."""
    relation = source.get("relation_candidate") or {}
    target = relation.get("target_identity") or {}
    edition = str(source.get("edition_label") or "").strip()
    return (
        _fold(str(source.get("norma_ref") or source.get("citation_label") or "")),
        _fold(str(source.get("dispositivo_ref") or "")),
        str(relation.get("action") or source.get("relation_action_candidate") or "").casefold(),
        _fold(str(target.get("type") or "")),
        normalize_number(str(target.get("number") or "")).lstrip("0"),
        str(target.get("year") or ""),
        _fold(str(target.get("structural_type") or "")),
        normalize_number(str(target.get("structural_number") or "")).lstrip("0"),
        normalize_number(str(target.get("structural_article_number") or "")).lstrip("0"),
        _fold(str(source.get("action_quote") or "")),
        _fold(str(source.get("target_text") or "")),
        _fold(str(source.get("evidence_text") or source.get("full_text") or source.get("texto") or "")),
        _fold(edition),
    )


def _dedupe_relation_candidate_sources(sources: list[dict]) -> list[dict]:
    """Prefer SAPL for identical clauses; retain text or edition differences."""
    unique: list[dict] = []
    indexes: dict[tuple[str, ...], int] = {}
    for source in sources:
        key = _relation_candidate_dedupe_key(source)
        existing_index = indexes.get(key)
        if existing_index is None:
            indexes[key] = len(unique)
            unique.append(source)
            continue
        existing = unique[existing_index]
        if (
            str(source.get("source_kind") or "").casefold() == "sapl"
            and str(existing.get("source_kind") or "").casefold() != "sapl"
        ):
            unique[existing_index] = source
    return unique


def _intersticio_duration_not_recovered(
    question: str, results: list[dict]
) -> tuple[int, dict] | None:
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
            _COUNTED_DURATION_RE.search(text[max(0, match.start() - 120) : match.end() + 180])
            for match in term_matches
        ):
            return None
        matching_sources.append((index, source))
    return matching_sources[0] if matching_sources else None


def _tokens(value: str) -> set[str]:
    return {word for word in _WORD_RE.findall(_fold(value)) if word not in _STOPWORDS}


def _archive_search_tokens(query_tokens: set[str]) -> set[str]:
    """Drop generic question wording from the costly archive-PDF shortlist."""
    focused = set(query_tokens) - _QUERY_FRAMING - _EVIDENCE_REQUEST_FRAMING
    focused -= _ARCHIVE_RETRIEVAL_FRAMING
    return focused or set(query_tokens)


def _strong_topic_phrase_rows(question: str, rows: list[dict]) -> list[dict]:
    """Keep only evidence matching a distinctive 3+ term phrase in the query.

    This prevents a few shared words such as ``servidor`` or ``saúde`` from
    pulling unrelated provisions into a focused question when the archive has
    an exact multi-word subject match (for example, a named allowance).
    """
    sequence = [
        token
        for token in _WORD_RE.findall(_fold(question))
        if token not in _STOPWORDS
        and token not in _QUERY_FRAMING
        and token not in _EVIDENCE_REQUEST_FRAMING
    ]
    if len(sequence) < 3 or not rows:
        return []

    def contains_ordered_phrase(text: str, phrase: tuple[str, ...]) -> bool:
        tokens = _WORD_RE.findall(_fold(text))
        next_positions = {index for index, token in enumerate(tokens) if token == phrase[0]}
        for word in phrase[1:]:
            next_positions = {
                candidate
                for position in next_positions
                for candidate in range(position + 1, min(position + 4, len(tokens)))
                if tokens[candidate] == word
            }
            if not next_positions:
                return False
        return bool(next_positions)

    for width in range(min(5, len(sequence)), 2, -1):
        matching = [
            row
            for row in rows
            if any(
                contains_ordered_phrase(
                    str(row.get("full_text") or row.get("evidence_text") or ""),
                    tuple(sequence[start : start + width]),
                )
                for start in range(len(sequence) - width + 1)
            )
        ]
        if matching:
            return matching
    return []


def _whole_norm_topic_tokens(question: str) -> set[str]:
    """Extract substantive scope words from a whole-norm request qualifier."""
    topical_question = _NORMATIVE_REFERENCE_SPAN_RE.sub(" ", str(question or ""))
    topical_question = _COVERAGE_SCOPE_REQUEST_RE.sub(" ", topical_question)
    topical_question = _DIRECT_WHOLE_NORM_SUMMARY_RE.sub(" ", topical_question)
    topical_question = _WHOLE_NORM_THEMES_SUMMARY_RE.sub(" ", topical_question)
    topical_question = _OVERVIEW_SCOPE_QUALIFIER_RE.sub(" ", topical_question)
    topical_question = _WHOLE_NORMAL_FRAMING_RE.sub(" ", topical_question)
    task_framing = {
        "assunto",
        "assuntos",
        "auto",
        "autos",
        "conclusao",
        "concluir",
        "conferir",
        "curta",
        "dispositivo",
        "dispositivos",
        "geral",
        "inicial",
        "oficial",
        "pdf",
        "nao",
        "posso",
        "processo",
        "publicacao",
        "relevante",
        "relevantes",
        "sem",
        "sintese",
        "triagem",
        "antes",
        "aplicar",
        "aplique",
        "cautela",
        "cautelas",
        "deve",
        "devem",
        "excertos",
        "observar",
        "procurador",
        "tres",
        "organiza",
        "organizam",
        "regula",
        "regulam",
        "disciplina",
        "disciplinam",
        "estrutura",
        "estruturam",
        "etapa",
        "etapas",
        "fase",
        "fases",
        "preve",
        "orientar",
        "teria",
        "teriam",
        "documento",
        "documentos",
        "fato",
        "fatos",
        "concreto",
        "caso",
        "eu",
        "diga",
        "pertinente",
        "pertinentes",
    }
    return _tokens(topical_question) - _QUERY_FRAMING - _EVIDENCE_REQUEST_FRAMING - task_framing


def _is_whole_norm_request(question: str, query_plan=None) -> bool:
    """Share whole-norm intent classification between retrieval and response shaping."""
    if (
        query_plan is not None
        and query_plan.explicit_target_overview
        and query_plan.reference is not None
    ):
        return True
    parsed_references = parse_normative_references(question)
    references = [reference for reference in parsed_references if not reference.ambiguous]
    exact_ref = references[0] if len(references) == 1 else None
    if exact_ref is None and len(parsed_references) == 1 and query_plan is not None:
        reference = parsed_references[0]
        if (
            reference.year is not None
            and query_plan.article_targets
            and query_plan.kind == "provision"
        ):
            exact_ref = reference

    wanted_articles = tuple(query_plan.article_targets) if query_plan is not None else ()
    if not wanted_articles:
        wanted_articles = tuple(
            _article_key(match.group(1)) for match in _ARTICLE_RE.finditer(question)
        )
    if not exact_ref or wanted_articles:
        return False
    # An explicit request for a summary of the named enactment remains a
    # whole-norm query when the user adds a practical purpose or asks what
    # requires checking in the case file.
    if _DIRECT_WHOLE_NORM_SUMMARY_RE.search(question) or _WHOLE_NORM_THEMES_SUMMARY_RE.search(
        question
    ):
        return True
    if query_plan is not None and query_plan.broad_topical_scope:
        return True

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


def _coverage_scope_disclosure(coverage: dict) -> str:
    """Describe parser coverage without presenting it as legal validation."""
    selected = coverage.get("selected_articles")
    total = coverage.get("total_articles")
    annexes_present = coverage.get("annexes_present")
    if not isinstance(selected, int) or not isinstance(total, int):
        return (
            "Os metadados desta extração não permitem quantificar com segurança os artigos "
            "recuperados nem confirmar se os anexos foram considerados. Confira o PDF original."
        )

    if selected == total:
        disclosure = f"A extração identificou {total} artigos, e a busca recuperou todos. "
    else:
        disclosure = (
            f"A busca recuperou evidências em {selected} de {total} artigos identificados; "
            "a cobertura é parcial. "
        )

    if annexes_present is True:
        disclosure += (
            "O parser detectou anexos normativos, mas eles não foram incluídos nesta seleção. "
        )
    elif annexes_present is False:
        disclosure += "O parser não detectou anexos normativos; confira também essa indicação no PDF original. "
    else:
        disclosure += "Os metadados não informam se há anexos normativos. "
    return disclosure + "Esses dados descrevem a extração automática, ainda pendente de revisão."


def _is_normative_change_inventory_request(question: str, query_plan=None) -> bool:
    """Detect an explicit request to list actions performed by one named norm."""
    if query_plan is None:
        query_plan = classify_normative_query(question)
    if not _NORMATIVE_CHANGE_INVENTORY_QUERY_RE.search(question):
        return False
    references = [
        reference
        for reference in parse_normative_references(question)
        if not reference.ambiguous and reference.year is not None
    ]
    return len(references) == 1


def _is_normative_change_history_request(question: str, query_plan=None) -> bool:
    """Detect a request for later acts affecting a specifically cited provision."""
    if query_plan is None:
        query_plan = classify_normative_query(question)
    if not _NORMATIVE_CHANGE_HISTORY_QUERY_RE.search(question) or not query_plan.article_targets:
        return False
    references = [
        reference
        for reference in parse_normative_references(question)
        if not reference.ambiguous and reference.year is not None
    ]
    return len(references) == 1


def _candidate_identity(document: DocumentoNormativo) -> dict:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity = metadata.get("identity_candidate")
    return identity if isinstance(identity, dict) else {}


def _candidate_edition_label(document: DocumentoNormativo) -> str:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    edition = metadata.get("edition_candidate")
    if not isinstance(edition, dict):
        return ""
    if edition.get("kind") == "official_consolidated_text":
        year = edition.get("declared_value_year")
        if isinstance(year, int):
            return f"Consolidação municipal · exercício {year} · revisão pendente"
    if document.source_kind == DocumentoNormativo.SourceKind.SAPL:
        return "PDF oficial SAPL · revisão pendente"
    return ""


def _requested_archive_edition_scope(question: str, references) -> tuple[tuple | None, int | None]:
    """Resolve an explicitly named consolidation year to its nearby legal act.

    The exercise year identifies a document edition, not the enactment year of
    the law. Bind it to the closest explicit legal reference in the question;
    never apply it to every cited norm in a comparison.
    """
    return requested_edition_scope(question, references)


def _candidate_official_pdf_url(document: DocumentoNormativo) -> str | None:
    """Expose only staged PDF URLs on the two verified Natal government hosts."""
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    provenance = metadata.get("source_provenance")
    provenance_url = provenance.get("official_url") if isinstance(provenance, dict) else None
    raw_url = str(getattr(document, "official_url", None) or provenance_url or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not parsed.path.lower().endswith(".pdf")
    ):
        return None
    if parsed.hostname == "sapl.natal.rn.leg.br" and parsed.path.startswith(
        "/media/sapl/public/normajuridica/"
    ):
        return raw_url
    if parsed.hostname in {"natal.rn.gov.br", "www.natal.rn.gov.br"} and parsed.path.startswith(
        "/sefin/legislacao/lei/"
    ):
        return raw_url
    return None


def _archive_relation_candidate_sources(
    reference,
    article_targets: tuple[str, ...],
    *,
    source_reference=None,
) -> list[dict]:
    """Return exact, unreviewed PDF relation evidence without asserting legal effect."""
    if (
        reference is None
        or not reference.type_key
        or not reference.number
        or reference.year is None
        or (not article_targets and source_reference is None)
    ):
        return []

    # Resolve through the app registry at request time. The stream endpoint
    # imports this helper from inside its response iterator; a direct import
    # from the cohesive model module can race its initialization in that path.
    from django.apps import apps

    EventoNormativoCandidato = apps.get_model("legislation", "EventoNormativoCandidato")

    target_number = normalize_number(reference.number).lstrip("0") or "0"
    number_pattern = "^0*" + r"\.?".join(re.escape(digit) for digit in target_number) + "$"
    year_query = Q(target_reference_json__year_candidate=str(reference.year)) | Q(
        target_reference_json__year_candidate=reference.year
    )
    number_query = Q(target_reference_json__number_candidate__regex=number_pattern)
    candidates = (
        EventoNormativoCandidato.objects.filter(
            action__in={"REVOGA", "ALTERA", "SUBSTITUI"},
        )
        .filter(year_query & number_query)
        .select_related("extracao__documento", "extracao__documento__norma")
        .prefetch_related("revisoes")
        .order_by("extracao__documento_id", "source_structural_key", "pk")[:500]
    )

    display_types = {
        "lei": "Lei",
        "lei_complementar": "Lei Complementar",
        "lei_organica": "Lei Orgânica",
        "lei_promulgada": "Lei Promulgada",
        "decreto": "Decreto",
        "decreto_legislativo": "Decreto Legislativo",
        "decreto_lei": "Decreto-Lei",
        "resolucao": "Resolução",
        "portaria": "Portaria",
    }
    rows = []
    for candidate in candidates:
        target = candidate.target_reference_json or {}
        candidate_number = normalize_number(str(target.get("number_candidate") or ""))
        if (candidate_number.lstrip("0") or "0") != target_number:
            continue
        try:
            candidate_year = int(target.get("year_candidate"))
        except (TypeError, ValueError):
            continue
        if candidate_year != reference.year:
            continue
        target_type = canonical_type(str(target.get("type_candidate") or ""))
        if target_type != reference.type_key:
            continue

        structural_type = _fold(str(target.get("structural_type") or ""))
        structural_number = normalize_number(str(target.get("structural_number") or ""))
        structural_article_number = normalize_number(
            str(target.get("structural_article_number") or "")
        )
        if article_targets and structural_article_number:
            if structural_article_number.lstrip("0") not in {
                article.lstrip("0") for article in article_targets
            }:
                continue
        elif article_targets and "art" in structural_type and structural_number:
            if structural_number.lstrip("0") not in {
                article.lstrip("0") for article in article_targets
            }:
                continue

        document = candidate.extracao.documento
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity = _candidate_identity(document)
        if (
            document.source_kind
            not in {DocumentoNormativo.SourceKind.ARCHIVE, DocumentoNormativo.SourceKind.SAPL}
            or metadata.get("synthetic") is True
            or not identity
            or (
                document.norma_id
                and (document.norma.identity_json or {}).get("synthetic_fixture") is True
            )
        ):
            continue
        try:
            source_year = int(identity.get("year"))
        except (TypeError, ValueError):
            continue
        source_type = canonical_type(str(identity.get("type") or ""))
        source_number = normalize_number(str(identity.get("number") or ""))
        if source_year <= reference.year or not source_number or source_type not in display_types:
            continue
        if source_reference is not None:
            expected_source_number = normalize_number(str(source_reference.number))
            expected_source_year = int(source_reference.year)
            if (
                source_type != source_reference.type_key
                or (source_number.lstrip("0") or "0")
                != (expected_source_number.lstrip("0") or "0")
                or source_year != expected_source_year
            ):
                continue

        reviews = list(candidate.revisoes.all())
        latest_review = max(reviews, key=lambda row: (row.created_at, row.pk), default=None)
        if latest_review and latest_review.decision == "reject":
            continue

        source_title_number = source_number
        first_group_length = len(source_title_number) % 3 or 3
        source_title_number = ".".join(
            [
                source_title_number[:first_group_length],
                *(
                    source_title_number[index : index + 3]
                    for index in range(first_group_length, len(source_title_number), 3)
                ),
            ]
        )
        source_norma_ref = f"{display_types[source_type]} nº {source_title_number}/{source_year}"
        evidence = candidate.evidence_json if isinstance(candidate.evidence_json, dict) else {}
        action_device = str(evidence.get("action_device") or "").strip()
        article_match = re.search(r"\b(?:artigo|art\.?)[\sº°ª]*([\d.]+)", action_device, re.I)
        if article_match:
            source_device = f"Art. {article_match.group(1)}"
        else:
            source_device = action_device or candidate.source_device_label
        item_device = str(candidate.source_device_label or "").strip()
        item_match = re.fullmatch(r"inciso\s+([ivxlcdm]+)", item_device, re.I)
        if item_match:
            item_device = f"inciso {item_match.group(1).upper()}"
        if item_device and _fold(item_device) != _fold(source_device):
            source_device = f"{source_device}, {item_device}"
        item_quote = str(evidence.get("item_quote") or candidate.target_text or "").strip()
        if not item_quote:
            continue

        official_url = str(document.official_url or "").strip()
        parsed_url = urlparse(official_url)
        allowed_hosts = {
            DocumentoNormativo.SourceKind.SAPL: {"sapl.natal.rn.leg.br"},
            DocumentoNormativo.SourceKind.ARCHIVE: {"sapl.natal.rn.leg.br", "www2.natal.rn.gov.br"},
        }
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname not in allowed_hosts[document.source_kind]
            or parsed_url.username
            or parsed_url.password
        ):
            official_url = ""

        source_id = f"relation-candidate:{candidate.fingerprint}"
        rows.append(
            {
                "id": source_id,
                "source_id": str(document.public_id),
                "document_id": str(document.public_id),
                "document_sha256": document.content_sha256,
                "citation_id": source_id,
                "citation_label": f"{source_norma_ref}, {source_device}",
                "source_kind": document.source_kind,
                "source_type": "PDF oficial — relação textual candidata, extração não revisada",
                "edition_label": str(
                    metadata.get("edition_label")
                    or metadata.get("edition")
                    or metadata.get("version_label")
                    or ""
                ).strip(),
                "norma_ref": source_norma_ref,
                "dispositivo_ref": source_device,
                "texto": item_quote,
                "full_text": item_quote,
                "evidence_text": item_quote,
                "action_quote": evidence.get("action_quote") or candidate.action_quote,
                "target_text": evidence.get("target_quote") or candidate.target_text,
                "relation_action_candidate": candidate.action,
                "relation_candidate": {
                    "fingerprint": candidate.fingerprint,
                    "action": candidate.action,
                    "target_identity": {
                        "type": target_type,
                        "number": candidate_number,
                        "year": candidate_year,
                        "structural_type": target.get("structural_type"),
                        "structural_number": target.get("structural_number"),
                        "structural_article_number": target.get("structural_article_number"),
                    },
                    "source_extraction_sha256": candidate.extracao.extraction_sha256,
                    "status": (
                        "extraction_confirmed_legal_effect_unreviewed"
                        if latest_review and latest_review.decision == "confirm"
                        else "candidate_unreviewed"
                    ),
                },
                "relation_review_status": (
                    "extraction_confirmed"
                    if latest_review and latest_review.decision == "confirm"
                    else "candidate_unreviewed"
                ),
                "contribution": (
                    "Indício literal no PDF; a relação e seus efeitos jurídicos não foram validados"
                ),
                "evidence_scope": "unreviewed_document_relation_candidate",
                "coverage": {
                    "review_status": "confirmed_extraction"
                    if latest_review and latest_review.decision == "confirm"
                    else "pending_extraction_review",
                    "legal_effect_reviewed": False,
                    "source_extraction_sha256": candidate.extracao.extraction_sha256,
                },
                "page": evidence.get("action_page") or evidence.get("target_page"),
                "pdf_url": official_url or None,
                "local_pdf_url": reverse(
                    "legislation:document_pdf", kwargs={"document_id": document.public_id}
                ),
                "similarity_score": 1.0,
            }
        )
    return rows


def _target_normative_device_sources(
    reference,
    article_targets: tuple[str, ...],
    *,
    structural_type: str = "",
    structural_number: str = "",
) -> list[dict]:
    """Retrieve the prior text of the target device from its identified QA PDF.

    This deliberately reads only an exact SAPL identity candidate and emits a
    source marked pending review. It does not promote that document or infer
    the legal effect/currentness of the relation.
    """
    if (
        reference is None
        or not reference.type_key
        or not reference.number
        or reference.year is None
        or not article_targets
    ):
        return []

    display_types = {
        "lei": "Lei",
        "lei_complementar": "Lei Complementar",
        "lei_organica": "Lei Orgânica",
        "lei_promulgada": "Lei Promulgada",
        "decreto": "Decreto",
        "decreto_legislativo": "Decreto Legislativo",
        "decreto_lei": "Decreto-Lei",
        "resolucao": "Resolução",
        "portaria": "Portaria",
    }
    # `_archive_identity_query` returns a compound Q; apply it separately so
    # alternate JSON number formats remain supported.
    documents = (
        DocumentoNormativo.objects.filter(
            source_kind__in={
                DocumentoNormativo.SourceKind.SAPL,
                DocumentoNormativo.SourceKind.ARCHIVE,
            },
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .filter(_archive_identity_query(reference))
        .order_by("pk")[:20]
    )
    rows = []
    wanted_articles = {normalize_number(value).lstrip("0") or "0" for value in article_targets}
    for document in documents:
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        if document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE:
            provenance = metadata.get("source_provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            if (
                document.norma_id is not None
                or metadata.get("identity_status") != "candidate"
                or metadata.get("rag_eligible") is not False
                or provenance.get("kind") != "municipal_official_repository"
                or provenance.get("official_url")
                != "https://www.natal.rn.gov.br/storage/app/media/semurb/legislacao/leis/"
                "5-lei-promulgada-275-2009-regulamenta-as-calcadas-no-municipio.pdf"
            ):
                continue
        identity = _candidate_identity(document)
        try:
            identity_year = int(identity.get("year"))
        except (TypeError, ValueError):
            continue
        if (
            metadata.get("synthetic") is True
            or canonical_type(str(identity.get("type") or "")) != reference.type_key
            or (normalize_number(str(identity.get("number") or "")).lstrip("0") or "0")
            != (normalize_number(reference.number).lstrip("0") or "0")
            or identity_year != reference.year
        ):
            continue
        extraction = document.extracoes.order_by("-created_at", "-pk").first()
        if (
            extraction is None
            or extraction.status != ExtracaoDocumento.Status.COMPLETE
            or not extraction.legal_text
        ):
            continue
        for article in _article_rows(extraction.legal_text, page_map=extraction.page_map_json):
            article_key = normalize_number(str(article.get("numero") or "")).lstrip("0") or "0"
            if article_key not in wanted_articles:
                continue
            excerpt = str(article.get("texto") or "").strip()
            resolved_device = f"Art. {article.get('numero')}"
            if structural_type == "paragrafo" and structural_number:
                paragraph_matches = list(
                    re.finditer(
                        r"(?:§\s*(?P<number>\d+\s*[º°ª]?|único)|" r"parágrafo\s+(?P<unique>único))",
                        excerpt,
                        re.IGNORECASE,
                    )
                )
                wanted_paragraph = normalize_number(structural_number)
                selected = next(
                    (
                        index
                        for index, match in enumerate(paragraph_matches)
                        if (
                            normalize_number(match.group("number") or "") == wanted_paragraph
                            if match.group("number")
                            else structural_number.casefold() in {"único", "unico"}
                        )
                    ),
                    None,
                )
                if selected is None:
                    continue
                start = paragraph_matches[selected].start()
                end = (
                    paragraph_matches[selected + 1].start()
                    if selected + 1 < len(paragraph_matches)
                    else len(excerpt)
                )
                excerpt = excerpt[start:end].strip()
                resolved_device += f", § {structural_number}"
            if not excerpt:
                continue
            source_number = normalize_number(str(identity.get("number") or ""))
            source_title_number = source_number
            first_group_length = len(source_title_number) % 3 or 3
            source_title_number = ".".join(
                [
                    source_title_number[:first_group_length],
                    *(
                        source_title_number[index : index + 3]
                        for index in range(first_group_length, len(source_title_number), 3)
                    ),
                ]
            )
            norm_label = (
                f"{display_types[reference.type_key]} nº {source_title_number}/{reference.year}"
            )
            official_url = str(document.official_url or "").strip()
            parsed_url = urlparse(official_url)
            allowed_sapl_url = (
                parsed_url.scheme == "https"
                and parsed_url.hostname == "sapl.natal.rn.leg.br"
                and parsed_url.path.startswith("/media/sapl/public/normajuridica/")
            )
            allowed_lp275_url = (
                parsed_url.scheme == "https"
                and parsed_url.hostname == "www.natal.rn.gov.br"
                and parsed_url.path
                == "/storage/app/media/semurb/legislacao/leis/"
                "5-lei-promulgada-275-2009-regulamenta-as-calcadas-no-municipio.pdf"
            )
            if (
                not (allowed_sapl_url or allowed_lp275_url)
                or parsed_url.username
                or parsed_url.password
            ):
                official_url = ""
            page_index = _page_index_for_excerpt(article, excerpt, extraction.page_map_json)
            if official_url and isinstance(page_index, int):
                official_url = f"{official_url}#page={page_index + 1}"
            source_id = (
                f"target-device:{document.public_id}:{extraction.extraction_sha256}:"
                f"{article_key}:{structural_type}:{normalize_number(structural_number)}"
            )
            rows.append(
                {
                    "id": source_id,
                    "source_id": str(document.public_id),
                    "document_id": str(document.public_id),
                    "document_sha256": document.content_sha256,
                    "citation_id": source_id,
                    "citation_label": f"{norm_label}, {resolved_device}",
                    "source_kind": getattr(
                        document,
                        "source_kind",
                        DocumentoNormativo.SourceKind.ARCHIVE,
                    ),
                    "source_type": "PDF oficial — extração local pendente de revisão",
                    "norma_ref": norm_label,
                    "dispositivo_ref": resolved_device,
                    "texto": excerpt,
                    "full_text": excerpt,
                    "evidence_text": excerpt,
                    "evidence_scope": "unreviewed_target_device_extraction",
                    "relation_review_status": "candidate_unreviewed",
                    "contribution": "Texto anterior localizado no PDF; extração local ainda pendente de revisão",
                    "coverage": {
                        "review_status": "pending_extraction_review",
                        "legal_effect_reviewed": False,
                        "source_extraction_sha256": extraction.extraction_sha256,
                    },
                    # The source payload is consumed by the browser as a
                    # one-based PDF page number (and its JS deep-link builder
                    # replaces any existing fragment with this value).
                    "page": page_index + 1 if isinstance(page_index, int) else None,
                    "pdf_url": official_url or None,
                    "local_pdf_url": reverse(
                        "legislation:document_pdf", kwargs={"document_id": document.public_id}
                    ),
                    "similarity_score": 1.0,
                }
            )
    return rows


def _requested_archive_norm_title(question: str) -> str | None:
    """Resolve a small set of explicit archive titles without guessing a number."""
    folded = _fold(str(question or ""))
    if re.search(r"\bcodigo\s+de\s+obras\b", folded):
        return "codigo de obras"
    return None


def _latest_extraction(document: DocumentoNormativo) -> ExtracaoDocumento | None:
    if hasattr(document, "latest_extraction_status"):
        if not document.latest_extraction_status:
            return None
        return SimpleNamespace(
            status=document.latest_extraction_status,
            legal_text=document.latest_legal_text or "",
            extraction_sha256=document.latest_extraction_sha256 or "",
            metadata_candidates_json=getattr(document, "latest_metadata_candidates", {}) or {},
            page_map_json=getattr(document, "latest_page_map", []) or [],
        )
    return document.extracoes.order_by("-created_at", "-pk").first()


def _archive_identity_query(reference, *, include_year: bool = True) -> Q:
    """Build a SQL-side identity predicate, tolerating zero-padded numbers."""
    number = str(reference.number or "").lstrip("0") or "0"
    query = (
        Q(metadata_json__identity_candidate__number=number)
        | Q(metadata_json__identity_candidate__number__regex=rf"^0*{re.escape(number)}$")
    )
    if include_year:
        query &= Q(metadata_json__identity_candidate__year=reference.year)
    if reference.type_key:
        aliases = _TYPE_ALIASES.get(reference.type_key, {reference.type_key})
        type_query = Q()
        for alias in aliases:
            type_query |= Q(metadata_json__identity_candidate__type=alias)
        query &= type_query
    return query


def _reference_identity(reference) -> tuple[str, str, int | None]:
    number = normalize_number(reference.number).lstrip("0") or "0"
    return reference.type_key, number, reference.year


def _archive_source_norm_identity(source: dict) -> tuple[str, str, int | None] | None:
    references = parse_normative_references(str(source.get("norma_ref") or ""))
    if len(references) != 1 or references[0].year is None:
        return None
    return _reference_identity(references[0])


def _archive_source_article(source: dict) -> str:
    return _article_key(str(source.get("dispositivo_ref") or ""))


def _archive_source_version_rank(source: dict) -> tuple[int, int]:
    """Rank repeated article occurrences by their explicit amendment notes."""
    text = _fold(str(source.get("full_text") or ""))
    years = [
        int(year)
        for year in re.findall(
            r"\((?:redacao dada|incluido|incluida|acrescentado|acrescentada|alterado|alterada)"
            r"[^)]{0,180}\b((?:19|20)\d{2})\b",
            text,
        )
    ]
    return (max(years, default=0), len(years))


def _archive_replacement_excerpt(source_text: str, article_number: str) -> tuple[str, bool] | None:
    """Extract explicit wording inside a quoted replacement, tracking omissions.

    Some municipal acts use long dot/ellipsis runs to omit unchanged paragraphs,
    then reproduce only a changed paragraph. Stop at the next quoted article
    and return substantive provision fragments rather than treating the first
    omission marker as the end of the amendment.
    """
    opening = re.search(
        rf"[\"“«]\s*(Art\.?\s*{re.escape(str(article_number))}" r"\s*[ºª°]?(?:\s*[-–—.]\s*)?)",
        str(source_text or ""),
        flags=re.IGNORECASE,
    )
    if opening is None:
        return None
    tail = str(source_text)[opening.end() :]
    next_quoted_article = re.search(
        r"[“\"«]\s*Art\.?\s*\d+(?:-[A-Z])?[ºª°]?\b", tail, re.IGNORECASE
    )
    closing_quote = re.search(r"[”»\"]", tail)
    boundaries = [
        match.start() for match in (next_quoted_article, closing_quote) if match
    ]
    omission_re = re.compile(r"\.{6,}[\uFFFD…]*|…{2,}")
    if not boundaries:
        # Some extracted SAPL PDFs omit the closing quotation mark at the end
        # of an expressly truncated replacement. The omission marker is a
        # reliable boundary for the available text; do not discard the entire
        # comparison merely because OCR lost that final glyph.
        omission = omission_re.search(tail)
        if omission is None:
            return None
        end = omission.end()
    else:
        end = min(boundaries)
    block = tail[:end]
    omitted_tail = bool(omission_re.search(block))
    fragments = []
    for index, fragment in enumerate(omission_re.split(block)):
        fragment = re.sub(r"\s+", " ", fragment).strip(" \t\r\n:;,.–—-")
        if len(fragment) < 12:
            continue
        if index == 0 or re.search(
            r"(?:§\s*\d|par[aá]grafo\s+(?:[uú]nico|\d)|\b[IVX]+\s*[-–—.]\s*)",
            fragment,
            re.I,
        ):
            fragments.append(fragment)
    excerpt = " … ".join(fragments) if fragments else re.sub(r"\s+", " ", block).strip()
    if not excerpt:
        return None
    return excerpt, omitted_tail


def _archive_explicit_textual_amendment_comparison(
    question: str,
    results: list[dict],
    article_norm_pairs: tuple[tuple[tuple[str, str, int | None], str], ...],
) -> tuple[str, list[dict], list[dict], dict] | None:
    """Summarize only an explicit amendment passage paired with its prior text."""
    if not _EXPLICIT_TEXT_COMPARISON_QUERY_RE.search(question or ""):
        return None

    requested = {(identity, _article_key(article)) for identity, article in article_norm_pairs}
    source_indexes = {
        str(source.get("citation_id") or ""): index
        for index, source in enumerate(results, 1)
        if source.get("citation_id")
    }
    if not source_indexes:
        return None
    query_references = [
        reference
        for reference in parse_normative_references(question)
        if not reference.ambiguous
    ]
    _edition_identity, consolidation_year_value = _requested_archive_edition_scope(
        question, query_references
    )
    consolidation_year = str(consolidation_year_value) if consolidation_year_value else None

    for amendment in results:
        amendment_identity = _archive_source_norm_identity(amendment)
        if not amendment_identity:
            continue
        amendment_article = _archive_source_article(amendment)
        if (amendment_identity, amendment_article) not in requested:
            continue
        amendment_text = str(amendment.get("full_text") or "")
        if not re.search(
            r"\bpassam?\s+a\s+vigorar\s+com\s+as?\s+seguintes\s+reda[cç][oõ]es?",
            amendment_text,
            re.I,
        ):
            continue
        cited_targets = {
            _reference_identity(reference)
            for reference in parse_normative_references(amendment_text)
            if reference.year is not None
        }
        if len(cited_targets) != 1:
            continue
        target_identity = next(iter(cited_targets))
        for target_article in sorted(
            article for identity, article in requested if identity == target_identity
        ):
            prior_sources = [
                source
                for source in results
                if _archive_source_norm_identity(source) == target_identity
                and _archive_source_article(source) == target_article
                and source.get("citation_id") in source_indexes
            ]
            if len(prior_sources) > 1 and consolidation_year:
                requested_edition = [
                    source
                    for source in prior_sources
                    if re.search(
                        rf"\b(?:exerc[ií]cio\s+)?{re.escape(consolidation_year)}\b",
                        str(source.get("edition_label") or ""),
                        re.IGNORECASE,
                    )
                ]
                if len(requested_edition) == 1:
                    prior_sources = requested_edition
            if len(prior_sources) > 1:
                ranked_prior = sorted(
                    prior_sources,
                    key=_archive_source_version_rank,
                    reverse=True,
                )
                if (
                    _archive_source_version_rank(ranked_prior[0])
                    > _archive_source_version_rank(ranked_prior[1])
                ):
                    prior_sources = [ranked_prior[0]]
            replacement = _archive_replacement_excerpt(amendment_text, target_article)
            if len(prior_sources) != 1 or replacement is None:
                continue
            prior = prior_sources[0]
            prior_reference = str(
                prior.get("citation_label") or prior.get("norma_ref") or "norma-alvo"
            )
            prior_reference = re.sub(r"\s*,\s*Art\.?\s*\d+.*$", "", prior_reference, flags=re.I)
            prior_text = re.sub(r"\s+", " ", str(prior.get("full_text") or "")).strip()
            prior_text = re.sub(
                rf"^Art\.?\s*{re.escape(target_article)}\s*[ºª°]?\s*[.–—-]?\s*",
                "",
                prior_text,
                flags=re.IGNORECASE,
            )
            new_text, omitted_tail = replacement
            article_display = f"Art. {target_article}"
            normalized_prior = unicodedata.normalize("NFKC", prior_text).casefold()
            normalized_new = unicodedata.normalize("NFKC", new_text).casefold()
            changes = []
            if "a primeiro" in normalized_prior and "em primeiro" in normalized_new:
                changes.append(
                    "ajusta a formulação da data-base de “a primeiro” para “em primeiro”"
                )
            if re.search(r"constru[ií]d[oa]s?\s+durante", prior_text, re.I) and re.search(
                r"constru[ií]d[oa]s?\s+ou\s+ampliad[oa]s?", new_text, re.I
            ):
                changes.append(
                    "passa a mencionar também prédios ampliados e a parte ampliada da construção"
                )
            if re.search(
                r"certid[aã]o\s+de\s+conclus[aã]o\s+de\s+obra", new_text, re.I
            ) and not re.search(r"certid[aã]o\s+de\s+conclus[aã]o\s+de\s+obra", prior_text, re.I):
                changes.append(
                    "inclui a emissão da Certidão de Conclusão de Obra entre os marcos textualmente citados"
                )
            if re.search(r"par[aá]grafo\s+[uú]nico", new_text, re.I) and not re.search(
                r"par[aá]grafo\s+[uú]nico", prior_text, re.I
            ):
                changes.append(
                    "acrescenta regra para caracterizar a ocupação de condomínios verticais"
                )
            if not changes:
                if new_text:
                    section_match = re.match(
                        r"(?:§\s*\d+[ºª°]?|par[aá]grafo\s+[uú]nico)",
                        new_text,
                        re.I,
                    )
                    label = section_match.group(0) if section_match else "trecho alterado"
                    section_number_match = (
                        re.search(r"\d+", label)
                        if section_match and label.lstrip().startswith("§")
                        else None
                    )
                    old_clause_match = (
                        re.search(
                            rf"§\s*{section_number_match.group(0)}[ºª°]?.{{0,320}}?(?=(?:§\s*\d|$))",
                            prior_text,
                            re.IGNORECASE,
                        )
                        if section_number_match
                        else None
                    )
                    old_clause = (
                        re.sub(r"\s+", " ", old_clause_match.group(0)).strip()
                        if old_clause_match
                        else ""
                    )
                    if old_clause and re.search(r"vetad[oa]", old_clause, re.I):
                        changes.append(
                            f"na edição anterior, o {label} do {article_display} aparece como "
                            f"“{old_clause}”; "
                            f"o trecho do ato modificador traz “{new_text}”"
                        )
                    else:
                        changes.append(f"o trecho do ato modificador reproduz “{new_text}”")

            # This specialized answer and its sources drawer are deliberately
            # scoped to the selected prior edition and the amending passage.
            # General retrieval may also contain unrelated acts that mention
            # the same target law; they are not evidence for this comparison.
            prior_index = 1
            amendment_index = 2
            prior_label = str(prior.get("edition_label") or "consolidação anterior").strip()
            prior_label = re.sub(r"\s*·\s*revis[aã]o pendente\s*$", "", prior_label, flags=re.I)
            amendment_label = str(
                amendment.get("citation_label") or amendment.get("norma_ref") or "ato modificador"
            )
            amendment_label = re.sub(r"\s*,\s*Art\.?\s*\d+.*$", "", amendment_label, flags=re.I)
            lines = [
                f"Na {prior_label}, o {article_display} de **{prior_reference}** traz a redação anterior [[{prior_index}]].",
                f"A redação transcrita no {amendment.get('dispositivo_ref') or 'dispositivo'} de **{amendment_label}** difere textualmente [[{amendment_index}]]:",
            ]
            lines.extend(
                f"- {change}. [[{prior_index}]] [[{amendment_index}]]"
                for change in changes
            )
            caveat = (
                "A extração da alteração termina com reticências e não reproduz toda a continuação do artigo. "
                if omitted_tail
                else ""
            )
            lines.append(
                f"{caveat}As extrações permanecem pendentes de revisão; este cotejo textual não confirma vigência, "
                "eficácia nem a redação aplicável a um processo concreto."
            )
            claims = [
                {
                    "text": f"O texto anterior de {prior_reference}, {article_display}, consta na fonte citada.",
                    "citation_ids": [str(prior["citation_id"])],
                },
                {
                    "text": "As diferenças textuais listadas constam na redação transcrita pelo ato modificador.",
                    "citation_ids": [str(amendment["citation_id"])],
                },
            ]
            return (
                "\n\n".join(lines),
                [prior, amendment],
                claims,
                {
                    "coverage_status": "textual_comparison_only",
                    "temporal_scope_available": False,
                    "omitted_continuation": omitted_tail,
                    "compared_article": target_article,
                },
            )
    return None


def _cross_reference_scan_scope(question: str):
    """Resolve the first named norm as the source and later distinct norms as targets."""
    if not _CROSS_REFERENCE_SCAN_RE.search(question or ""):
        return None
    references = [
        reference
        for reference in parse_normative_references(question)
        if reference.year is not None and reference.number
    ]
    unique = []
    seen = set()
    for reference in references:
        identity = _reference_identity(reference)
        if identity not in seen:
            seen.add(identity)
            unique.append(reference)
    if len(unique) < 2:
        return None
    return unique[0], tuple(unique[1:])


def _article_reference_mentions(question: str) -> tuple[tuple[int, str], ...]:
    """Return article-number mentions, including explicit plural article lists."""
    raw = question or ""
    mentions = [
        (match.start(), _article_key(match.group(1))) for match in _ARTICLE_RE.finditer(raw)
    ]
    for group in _PLURAL_ARTICLE_GROUP_RE.finditer(raw):
        article_list = group.group("articles")
        mentions.extend(
            (
                group.start("articles") + number.start(),
                _article_key(number.group(0)),
            )
            for number in re.finditer(r"\d{1,4}", article_list)
        )
    return tuple(sorted(set(mentions)))


def _has_ambiguous_multi_norm_article_scope(question: str) -> bool:
    """Fail closed when article numbers cannot be paired to multiple named norms."""
    query_plan = classify_normative_query(question)
    if len(query_plan.article_targets) <= 1 or _cross_reference_scan_scope(question):
        return False
    paired_targets = _explicit_article_norm_pairs(question)
    mentions = _article_reference_mentions(question)
    if len(paired_targets) == len(mentions) and mentions:
        identities_by_article: dict[str, set[tuple[str, str, int | None]]] = {}
        for identity, article in paired_targets:
            identities_by_article.setdefault(article, set()).add(identity)
        if all(len(identities_by_article.get(article, set())) == 1 for _start, article in mentions):
            return False
    identities = {
        _reference_identity(reference)
        for reference in parse_normative_references(question)
        if reference.year is not None and reference.number
    }
    return len(identities) > 1


def _ambiguous_article_scope_clarification(question: str) -> str:
    """Ask for only the missing article-to-norm mapping, without guessing it."""
    type_labels = {
        "lei": "Lei",
        "lei_complementar": "Lei Complementar",
        "lei_organica": "Lei Orgânica",
        "lei_promulgada": "Lei Promulgada",
        "decreto": "Decreto",
        "decreto_legislativo": "Decreto Legislativo",
        "decreto_lei": "Decreto-Lei",
        "resolucao": "Resolução",
        "portaria": "Portaria",
        "emenda": "Emenda",
        "emenda_constitucional": "Emenda Constitucional",
    }
    references = []
    for reference in parse_normative_references(question):
        if reference.year is None or not reference.number:
            continue
        identity = _reference_identity(reference)
        if identity in {item[0] for item in references}:
            continue
        digits = normalize_number(reference.number).lstrip("0") or "0"
        first_group = len(digits) % 3 or 3
        formatted_number = ".".join(
            [digits[:first_group], *(digits[index:index + 3] for index in range(first_group, len(digits), 3))]
        )
        label = type_labels.get(reference.type_key, "Norma")
        references.append((identity, f"{label} nº {formatted_number}/{reference.year}"))

    article_labels = list(dict.fromkeys(
        f"Art. {article}º" for _start, article in _article_reference_mentions(question)
    ))
    if references and article_labels:
        norm_list = ", ".join(label for _identity, label in references[:6])
        article_list = ", ".join(article_labels[:12])
        return (
            "Identifiquei estas normas na sua pergunta: "
            f"{norm_list}. Também identifiquei {article_list}, mas a frase não deixa claro "
            "qual artigo pertence a qual norma. Para eu não atribuir o texto à lei errada, "
            "confirme somente essa associação — por exemplo: ‘Art. 1º da primeira norma; "
            "Art. 2º da segunda’. Essa confirmação trata apenas da associação e não determina "
            "a redação vigente; para isso, confira o texto consolidado e o histórico oficial "
            "de alterações."
        )
    return (
        "Não consegui associar com segurança cada artigo à norma correspondente nesta pergunta, "
        "que menciona mais de uma norma. Para evitar atribuir um dispositivo à lei errada, "
        "informe cada referência completa (artigo, tipo, número e ano) ou consulte um dispositivo "
        "por vez. Esta busca não determina a redação vigente hoje; confira o texto consolidado "
        "e o histórico oficial de alterações."
    )


def _explicit_article_norm_pairs(
    question: str,
) -> tuple[tuple[tuple[str, str, int | None], str], ...]:
    """Pair articles with a nearby norm or a narrowly scoped follow-up reference.

    Direct forms such as "Art. 21 da LC X" remain preferred. A phrase like
    "A LC Y menciona o Art. 21 da LC X? Considere também os Arts. 260 e 262"
    scopes the follow-up articles to the last named norm (Y), but only for the
    sentence introduced by an explicit continuation cue. Other unqualified
    articles across sentence boundaries remain ambiguous.
    """
    raw = question or ""
    article_matches = _article_reference_mentions(raw)
    norm_matches = list(_NORMATIVE_REFERENCE_SPAN_RE.finditer(raw))
    pairs_by_start = {}
    grouped_mentions: set[int] = set()
    for start, identity, article_key in parse_coordinated_article_norm_pairs(raw):
        pairs_by_start[start] = (identity, article_key)
        grouped_mentions.add(start)

    for group in _PLURAL_ARTICLE_GROUP_RE.finditer(raw):
        following = next((match for match in norm_matches if match.start() >= group.end()), None)
        following_gap = raw[group.end() : following.start()] if following else ""
        if (
            following
            and len(following_gap) <= 24
            and re.fullmatch(r"\s*(?:da|do|de)?\s*", following_gap, re.IGNORECASE)
        ):
            reference_match = following
        else:
            preceding = next(
                (match for match in reversed(norm_matches) if match.end() <= group.start()),
                None,
            )
            preceding_gap = raw[preceding.end() : group.start()] if preceding else ""
            if (
                preceding is None
                or len(preceding_gap) > 100
                or re.search(r"[;!?]|\.(?!\s*\d)", preceding_gap)
                or re.search(r"\b(?:entre|versus|comparar|compare)\b", preceding_gap, re.IGNORECASE)
            ):
                continue
            reference_match = preceding
        reference = next(
            (
                item
                for item in parse_normative_references(reference_match.group(0))
                if item.year is not None and item.number
            ),
            None,
        )
        if reference is None:
            continue
        identity = _reference_identity(reference)
        for start, article_key in article_matches:
            if group.start("articles") <= start < group.end("articles"):
                grouped_mentions.add(start)
                pairs_by_start[start] = (identity, article_key)

    for article_start, article_key in article_matches:
        if article_start in grouped_mentions:
            continue
        preceding = next(
            (match for match in reversed(norm_matches) if match.end() <= article_start),
            None,
        )
        if preceding is not None:
            preceding_gap = raw[preceding.end() : article_start]
            # Also accept the common citation order “Lei X, Art. Y”. Keep this
            # deliberately narrow: only whitespace and a comma may separate
            # the explicit norm identity from the article, so nearby laws in
            # comparative or multi-norm questions are never guessed together.
            if len(preceding_gap) <= 24 and re.fullmatch(r"\s*,?\s*", preceding_gap):
                reference = next(
                    (
                        item
                        for item in parse_normative_references(preceding.group(0))
                        if item.year is not None and item.number
                    ),
                    None,
                )
                if reference is not None:
                    pairs_by_start[article_start] = (
                        _reference_identity(reference),
                        article_key,
                    )
                    continue
        following = next(
            (match for match in norm_matches if match.start() >= article_start),
            None,
        )
        if following is None or following.start() - article_start > 100:
            continue
        between = raw[article_start : following.start()]
        intervening_articles = [
            (start, key)
            for start, key in article_matches
            if article_start < start < following.start()
        ]
        if re.search(r"[;!?]|\.(?!\s*\d)", between):
            continue
        if intervening_articles:
            if (
                len(intervening_articles) != 1
                or not re.search(
                    r"\b(?:e|ou)\s*(?:o|a)?\s*$",
                    between[: intervening_articles[0][0] - article_start],
                    re.IGNORECASE,
                )
                or not re.search(r"\b(?:da|do|de)\s*$", between, re.IGNORECASE)
            ):
                continue
        if not re.search(r"\b(?:da|do|de)\s*$", between, re.IGNORECASE):
            continue
        references = parse_normative_references(following.group(0))
        reference = next(
            (item for item in references if item.year is not None and item.number),
            None,
        )
        if reference is None:
            continue
        pairs_by_start[article_start] = (
            _reference_identity(reference),
            article_key,
        )

    # A follow-up often repeats an article number without repeating its law
    # identity ("Art. 21 ... A LC 258 mentions it? ... does Art. 21 still
    # apply?"). Inherit only a single earlier explicit identity for that same
    # article number; if the same number was paired with multiple laws, keep
    # the later mention unresolved.
    for article_start, article_key in article_matches:
        if article_start in pairs_by_start:
            continue
        prior_identities = {
            pairs_by_start[prior_start][0]
            for prior_start, prior_key in article_matches
            if prior_start < article_start
            and prior_start in pairs_by_start
            and prior_key == article_key
        }
        if len(prior_identities) == 1:
            pairs_by_start[article_start] = (
                next(iter(prior_identities)),
                article_key,
            )

    continuation_re = re.compile(
        r"\b(?:considere(?:m)?\s+(?:tamb[eé]m|ainda)|inclua(?:m)?\s+(?:tamb[eé]m|ainda))\b",
        re.IGNORECASE,
    )
    for continuation in continuation_re.finditer(raw):
        tail = raw[continuation.end() :]
        sentence_end = re.search(r"[?!]|\.(?=\s+[A-ZÀ-ÖØ-Þ])", tail)
        segment_end = continuation.end() + sentence_end.start() if sentence_end else len(raw)
        preceding_norms = [match for match in norm_matches if match.end() <= continuation.start()]
        if not preceding_norms:
            continue
        fallback_reference = next(
            (
                item
                for item in parse_normative_references(preceding_norms[-1].group(0))
                if item.year is not None and item.number
            ),
            None,
        )
        if fallback_reference is None:
            continue

        for article_start, article_key in article_matches:
            if not continuation.end() <= article_start < segment_end:
                continue
            if article_start in pairs_by_start:
                continue
            local_preceding_norms = [
                match
                for match in norm_matches
                if continuation.end() <= match.start() < article_start
            ]
            reference = fallback_reference
            if local_preceding_norms:
                reference = next(
                    (
                        item
                        for item in parse_normative_references(local_preceding_norms[-1].group(0))
                        if item.year is not None and item.number
                    ),
                    None,
                )
            if reference is not None:
                pairs_by_start[article_start] = (
                    _reference_identity(reference),
                    article_key,
                )

    # In relational questions such as "Art. 260 da LC X ... se articula com a
    # regra de transição do Art. 262", a norm cited inside the repeal clause
    # (LC Y) is the object of the repeal, not the owner of the final article.
    # Inherit the immediately prior explicit article's norm only for this
    # narrow transition-relation construction and only when it is unambiguous.
    for article_start, article_key in article_matches:
        if article_start in pairs_by_start:
            continue
        prefix = raw[:article_start]
        if not re.search(
            r"\bse\s+articula\s+com\b.{0,180}\bregra\s+de\s+transi[cç][aã]o\s+do\s*$",
            prefix,
            re.IGNORECASE | re.DOTALL,
        ):
            continue
        prior_identities = {
            pairs_by_start[prior_start][0]
            for prior_start, _prior_article in article_matches
            if prior_start < article_start and prior_start in pairs_by_start
        }
        if len(prior_identities) == 1:
            pairs_by_start[article_start] = (next(iter(prior_identities)), article_key)

    return tuple(
        pairs_by_start[start] for start, _article in article_matches if start in pairs_by_start
    )


def _explicit_amendment_article_scope(question: str):
    """Resolve the named amendment act separately from its target provision.

    Example: “Que parágrafos a LC A acrescenta ao Art. 34 da LC B?” names
    the amendment source (A) and pairs the sole article mention with target B.
    This is intentionally narrow: one target article, one other named act, and
    an explicit amendment verb are required.
    """
    if not _EXPLICIT_AMENDMENT_QUERY_RE.search(question or ""):
        return None
    mentions = _article_reference_mentions(question)
    pairs = tuple(dict.fromkeys(_explicit_article_norm_pairs(question)))
    if len(mentions) != 1 or len(pairs) != 1:
        return None
    target_identity, target_article = pairs[0]
    references = {
        _reference_identity(reference)
        for reference in parse_normative_references(question)
        if reference.type_key and reference.year is not None and reference.number
    }
    source_identities = references - {target_identity}
    if len(source_identities) != 1:
        return None
    return next(iter(source_identities)), target_identity, target_article


def _text_mentions_norm_identity(text: str, identity: tuple[str, str, int | None]) -> bool:
    """Match a norm identity when a PDF spells its date instead of ``/year``.

    Legal acts commonly cite an older norm as “Lei Complementar n. 55, de 27
    de janeiro de 2004”. The general reference parser intentionally does not
    guess that the date belongs to a preceding citation; this narrow helper is
    used only after the question has supplied an exact target identity.
    """
    type_key, raw_number, year = identity
    label = _TYPE_LABELS.get(type_key)
    number = normalize_number(str(raw_number)).lstrip("0") or "0"
    if not label or not number or year is None:
        return False
    normalized = re.sub(r"\s+", " ", _fold(text))
    label_pattern = r"\s+".join(re.escape(part) for part in _fold(label).split())
    number_pattern = re.escape(number)
    reference = re.compile(
        rf"\b{label_pattern}\s*(?:n[.oº°]*\s*)?0*{number_pattern}\b"
        rf"(?P<tail>.{{0,100}}?)(?:/\s*{year}\b|\bde\b.{{0,90}}?\b{year}\b)",
        re.IGNORECASE,
    )
    return bool(reference.search(normalized))


def _archive_explicit_amendment_synthesis(question: str, sources: list[dict]):
    """Quote substantively extracted paragraphs from an explicit amendment clause."""
    scope = _explicit_amendment_article_scope(question)
    if not scope:
        return None
    source_identity, target_identity, target_article = scope
    for source in sources:
        if _archive_source_norm_identity(source) != source_identity:
            continue
        if not _AMENDMENT_OPERATIVE_CLAUSE_RE.search(str(source.get("full_text") or "")):
            continue
        text = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
        if not _text_mentions_norm_identity(text, target_identity):
            continue
        mentioned_articles = {article for _position, article in _article_reference_mentions(text)}
        if target_article not in mentioned_articles:
            continue
        operative = re.search(
            r"\b(?:acrescid[oa]s?|inclu[ií]d[oa]s?|alterad[oa]s?|"
            r"passa[m]?\s+a\s+vigorar)\b.{0,100}?\b(?:seguintes|par[aá]grafos|reda[cç][aã]o)",
            text,
            re.IGNORECASE,
        )
        if not operative:
            continue
        paragraph_tail = text[operative.end() :]
        markers = list(re.finditer(r"§{1,2}\s*(\d+)\s*[ºª°]?", paragraph_tail))
        additions = []
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(paragraph_tail)
            body = paragraph_tail[marker.end() : end].strip(" \t\r\n-–—:;,.\"'“”")
            body = re.sub(r"\s+", " ", body).strip()
            if len(re.findall(r"[a-z]{3,}", _fold(body))) < 3:
                continue
            additions.append((int(marker.group(1)), body))
        if not additions:
            continue

        commencement = next(
            (
                candidate
                for candidate in sources
                if candidate is not source
                and _archive_source_norm_identity(candidate) == source_identity
                and _EFFECTIVE_DATE_OPERATIVE_RE.search(
                    str(candidate.get("full_text") or "")
                )
            ),
            None,
        )
        selected_sources = [source, *([commencement] if commencement else [])]
        source_index = 1
        norm_label = str(source.get("norma_ref") or "a norma alteradora")
        device_label = str(source.get("dispositivo_ref") or "dispositivo do ato alterador")
        target_label = _TYPE_LABELS.get(target_identity[0], "Norma")
        target_ref = f"{target_label} nº {target_identity[1]}/{target_identity[2]}"
        answer = (
            f"A extração do **{norm_label}, {device_label}** afirma que o **Art. {target_article} "
            f"da {target_ref}** passa a incluir os seguintes parágrafos: [[{source_index}]]"
        )
        answer += "\n\n" + "\n\n".join(
            f"- **§ {number}º:** “{body}” [[{source_index}]]" for number, body in additions
        )
        if commencement:
            answer += (
                "\n\nO **Art. 3º da LC nº 173/2017** dispõe sobre a entrada em vigor na data da "
                "publicação [[2]]. Ainda assim, as extrações locais estão pendentes de revisão e "
                "não confirmam, por si sós, a vigência atual nem alterações posteriores. Confira o PDF oficial."
            )
        else:
            answer += (
                "\n\nNão localizei a cláusula de vigência nesta recuperação. As extrações locais estão "
                "pendentes de revisão e não confirmam, por si sós, a vigência atual nem alterações "
                "posteriores. Confira o PDF oficial."
            )
        claim = {
            "text": "A extração do ato alterador contém os parágrafos transcritos acima.",
            "citation_ids": [str(source.get("citation_id") or "")],
        }
        claims = [claim]
        if commencement:
            claims.append(
                {
                    "text": "O Art. 3º da extração prevê entrada em vigor na data da publicação.",
                    "citation_ids": [str(commencement.get("citation_id") or "")],
                }
            )
        return answer, selected_sources, claims, {
            "coverage_status": "explicit_amendment_text_extracted_pending_review",
            "legal_effect_reviewed": False,
            "temporal_scope_available": False,
            "added_paragraph_numbers": [number for number, _body in additions],
        }
    return None


def _matching_archive_article_sources(
    article_norm_pairs: tuple[tuple[tuple[str, str, int | None], str], ...],
    sources: list[dict],
) -> list[dict]:
    """Keep archive excerpts only when both the explicit norm and article match."""
    requested = set(article_norm_pairs)
    if not requested:
        return []
    matched = []
    seen_citations = set()
    for source in sources:
        article = _article_key(str(source.get("dispositivo_ref") or ""))
        if not article:
            continue
        source_identities = {
            _reference_identity(reference)
            for reference in parse_normative_references(str(source.get("norma_ref") or ""))
            if reference.year is not None and reference.number
        }
        if not any((identity, article) in requested for identity in source_identities):
            continue
        citation_id = str(source.get("citation_id") or "")
        if not citation_id or citation_id in seen_citations:
            continue
        seen_citations.add(citation_id)
        matched.append(source)
    return matched


def _missing_explicit_article_norm_pairs(question: str, sources: list[dict]) -> tuple[str, ...]:
    """List only confidently paired requested provisions absent from retrieved evidence."""
    article_mentions = _article_reference_mentions(question)
    requested = tuple(dict.fromkeys(_explicit_article_norm_pairs(question)))
    if not requested or len(requested) != len(article_mentions):
        # If the wording did not resolve every article to exactly one norm,
        # do not manufacture a missing-reference diagnosis from an ambiguous scope.
        return ()

    matched = {
        (identity, _article_key(str(source.get("dispositivo_ref") or "")))
        for source in _matching_archive_article_sources(requested, sources)
        for identity in {
            _reference_identity(reference)
            for reference in parse_normative_references(str(source.get("norma_ref") or ""))
            if reference.year is not None and reference.number
        }
    }
    missing = []
    for identity, article in requested:
        if (identity, article) in matched:
            continue
        type_key, number, year = identity
        label = _TYPE_LABELS.get(type_key, "Norma")
        normalized_number = normalize_number(number).lstrip("0") or "0"
        first_group = len(normalized_number) % 3 or 3
        formatted_number = ".".join(
            [normalized_number[:first_group]]
            + [
                normalized_number[index:index + 3]
                for index in range(first_group, len(normalized_number), 3)
            ]
        )
        norm = f"{label} nº {formatted_number}/{year}"
        preposition = (
            "do"
            if type_key in {"decreto", "decreto_lei", "decreto_legislativo"}
            else "da"
        )
        missing.append(f"Art. {article} {preposition} {norm}")
    return tuple(missing)


def _related_matter_search_limit(status: str | None, *, article_scope: bool = True) -> str:
    if status == "searched":
        if not article_scope:
            return (
                "A busca pública do SAPL por ementa e identidade da norma foi concluída, mas "
                "não encontrou matéria com menção explícita à lei. A pesquisa não prova a "
                "completude do cadastro nem substitui o histórico oficial; não conclua que "
                "inexistem alterações posteriores."
            )
        return (
            "A pesquisa pública do SAPL por ementa foi concluída, mas não encontrou matéria "
            "com associação explícita a este artigo. Como essa consulta não prova a completude "
            "do cadastro nem substitui o histórico oficial, não conclua que inexiste proposição "
            "ou alteração posterior."
        )
    if status == "unavailable":
        return (
            "Não foi possível concluir a consulta complementar ao SAPL. Portanto, esta resposta "
            "não verifica se há proposição posterior; a indisponibilidade não significa que ela "
            "inexista."
        )
    if status == "partial":
        return (
            "A consulta complementar ao SAPL foi interrompida durante a validação de resultados. "
            "As matérias encontradas são apenas candidatas e a busca não permite concluir que a "
            "lista esteja completa."
        )
    if status == "disabled":
        return (
            "A consulta complementar ao SAPL está desativada nesta instância; esta resposta não "
            "verifica proposições posteriores nem permite concluir que elas inexistam."
        )
    return ""


def _multi_norm_synthesis_instruction(question: str) -> str:
    """Add a concise relational style contract only for explicitly paired norms."""
    pairs = _explicit_article_norm_pairs(question)
    if len(pairs) < 2 or len({identity for identity, _article in pairs}) < 2:
        return ""
    return (
        "\n\nINSTRUÇÃO ESPECÍFICA — ARTIGOS DE MAIS DE UMA NORMA:\n"
        "- Responda primeiro à relação perguntada em prosa natural, em até dois parágrafos; "
        "não escreva um parágrafo separado para cada fonte nem repita aberturas como ‘No PDF local’.\n"
        "- Sintetize os dispositivos em vez de transcrever artigos inteiros; preserve modalidade, "
        "condições e exceções. Cite cada afirmação logo após o dispositivo que a sustenta.\n"
        "- Distinga texto de edição anterior, alteração/revogação posterior e regra de transição. "
        "Não trate a redação de um PDF consolidado antigo como prova de vigência atual.\n"
        "- Se faltarem fatos do processo ou cobertura temporal, diga objetivamente o que os textos "
        "permitem afirmar e o que continua inconclusivo; não transforme isso em parecer sobre o caso."
    )


def _same_norm_article_synthesis_instruction(question: str) -> str:
    """Keep answers about several devices of one norm concise and correctly attributed."""
    pairs = _explicit_article_norm_pairs(question)
    identities = {identity for identity, _article in pairs}
    articles = {article for _identity, article in pairs}
    if len(identities) != 1 or len(articles) < 2:
        return ""
    return (
        "\n\nINSTRUÇÃO ESPECÍFICA — MAIS DE UM ARTIGO DA MESMA NORMA:\n"
        "- Responda diretamente em até dois parágrafos, salvo se o usuário pedir outro formato. "
        "Não crie um bloco nem uma conclusão repetida para cada artigo.\n"
        "- Compare ou conecte os dispositivos somente no limite do que o texto demonstra; "
        "não invente relação causal. Mantenha cada afirmação junto da citação do artigo que a sustenta.\n"
        "- Sintetize regras próximas sem omitir condições, exceções ou modalidade. Se um dispositivo "
        "não tiver evidência suficiente, delimite essa parte sem atribuí-la ao outro artigo."
    )


def _text_mentions_normative_identity(text: str, identity: tuple[str, str, int | None]) -> bool:
    """Match an explicit norm citation whose year may be written as a full date."""
    wanted_number = normalize_number(identity[1]).lstrip("0") or "0"
    for match in _NORMATIVE_REFERENCE_SPAN_RE.finditer(text or ""):
        reference = next(iter(parse_normative_references(match.group(0))), None)
        if reference is None:
            continue
        actual_number = normalize_number(reference.number).lstrip("0") or "0"
        if reference.type_key != identity[0] or actual_number != wanted_number:
            continue
        if reference.year == identity[2]:
            return True
        if reference.year is None and identity[2] is not None:
            nearby_date = (text or "")[match.end() : match.end() + 48]
            if re.search(rf"\b{identity[2]}\b", nearby_date):
                return True
    return False


def _archive_transition_synthesis(
    question: str, results: list[dict]
) -> tuple[str, list[dict]] | None:
    """Synthesize a narrowly evidenced repeal/transition chain from archive PDFs.

    This is deliberately limited to explicitly paired articles where the newer
    norm's retrieved text both names a repealed norm and states a protocol-date
    transition rule. It may state the conditional consequence of facts explicitly
    supplied in a hypothetical question, but never adjudicates a real case.
    """
    pairs = _explicit_article_norm_pairs(question)
    if len(pairs) < 3 or len(pairs) != len(_article_reference_mentions(question)):
        return None
    if len({identity for identity, _article in pairs}) < 2:
        return None

    indexed_sources = []
    for index, source in enumerate(results, 1):
        text = str(source.get("full_text") or "").strip()
        citation_id = str(source.get("citation_id") or "")
        if not text or not citation_id:
            continue
        norm_identity = next(
            (
                _reference_identity(reference)
                for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                if reference.year is not None
            ),
            None,
        )
        if norm_identity is None:
            continue
        indexed_sources.append(
            (
                index,
                source,
                norm_identity,
                _article_key(str(source.get("dispositivo_ref") or "")),
                text,
            )
        )

    requested_pairs = set(pairs)
    transitions = []
    for entry in indexed_sources:
        _index, _source, identity, article, text = entry
        if (identity, article) not in requested_pairs:
            continue
        folded = _fold(text)
        if all(
            marker in folded
            for marker in (
                "protocolad",
                "entrada em vigor",
                "sem despacho decisorio",
                "legislacao em vigor",
                "manifestacao formal",
            )
        ):
            transitions.append(entry)

    for transition in transitions:
        transition_index, transition_source, newer_identity, transition_article, _text = transition
        for older_identity, older_article in pairs:
            if older_identity == newer_identity:
                continue
            old_source = next(
                (
                    entry
                    for entry in indexed_sources
                    if entry[2] == older_identity and entry[3] == older_article
                ),
                None,
            )
            if old_source is None:
                continue
            repeal = next(
                (
                    entry
                    for entry in indexed_sources
                    if entry[2] == newer_identity
                    and "revog" in _fold(entry[4])
                    and _text_mentions_normative_identity(entry[4], older_identity)
                ),
                None,
            )
            if repeal is None:
                continue

            repeal_index, repeal_source, _identity, repeal_article, _repeal_text = repeal
            old_index, old_source_record, _identity, _article, _old_text = old_source
            commencement = next(
                (
                    entry
                    for entry in indexed_sources
                    if entry[2] == newer_identity and _EFFECTIVE_DATE_OPERATIVE_RE.search(entry[4])
                ),
                None,
            )
            repeal_norm = str(repeal_source.get("norma_ref") or "a norma posterior")
            transition_norm = str(transition_source.get("norma_ref") or repeal_norm)
            old_norm = str(old_source_record.get("norma_ref") or "a norma anterior")
            commencement_note = ""
            if commencement is not None:
                official_commencement = next(
                    (
                        entry
                        for entry in indexed_sources
                        if entry[2] == newer_identity
                        and entry[3] == commencement[3]
                        and entry[1].get("source_kind") == "official_gazette_extraction"
                        and entry[1].get("data_publicacao")
                    ),
                    None,
                )
                vacatio_rule = next(
                    (
                        entry
                        for entry in indexed_sources
                        if entry[1].get("evidence_scope") == "official_vacatio_counting_rule"
                    ),
                    None,
                )
                effective_date = None
                if official_commencement and vacatio_rule:
                    try:
                        publication_date = date.fromisoformat(
                            str(official_commencement[1]["data_publicacao"])
                        )
                        effective_date = _vacatio_effective_date(
                            official_commencement[4], publication_date
                        )
                    except (KeyError, TypeError, ValueError):
                        effective_date = None
                if effective_date and official_commencement and vacatio_rule:
                    commencement_note = (
                        " A cláusula de vigência consta também na extração automatizada, ainda "
                        "não revisada, do Diário Oficial, que registra publicação em "
                        f"{publication_date.strftime('%d/%m/%Y')} "
                        f"[[{official_commencement[0]}]]. Aplicando a regra de contagem da "
                        f"LC nº 95/1998 [[{vacatio_rule[0]}]], o termo de 90 dias aponta "
                        f"para {effective_date.strftime('%d/%m/%Y')}; confira a edição oficial "
                        "e a contagem antes de usar essa data no processo."
                    )
                else:
                    commencement_note = (
                        " A mesma lei também estabelece uma regra de entrada em vigor "
                        f"[[{commencement[0]}]]; "
                        "a data concreta depende da publicação oficial."
                    )
            explicit_pending_case = all(
                marker in _fold(question)
                for marker in (
                    "processo",
                    "protocolado antes da entrada em vigor",
                    "sem despacho decisorio",
                )
            )
            if explicit_pending_case:
                answer = (
                    f"O texto recuperado da **{repeal_norm}** lista expressamente a "
                    f"**{old_norm}** entre os atos revogados [[{repeal_index}]]. Para o cenário "
                    "descrito, porém, a regra de transição determina que processos protocolados antes da "
                    "entrada em vigor da lei nova e ainda sem despacho decisório sejam apreciados "
                    "integralmente pela legislação vigente na data do protocolo, salvo manifestação "
                    f"formal do interessado pela análise integral conforme a lei nova [[{transition_index}]]. "
                    f"Assim, a disciplina da **{old_norm}** pode ser considerada nesse regime "
                    "transitório se integrava a legislação vigente na data do protocolo e não houve "
                    f"essa opção formal.{commencement_note}\n\n"
                    f"A extração ainda pendente de revisão da **{old_norm}** trata do licenciamento "
                    f"de obras e de prazos de análise [[{old_index}]]. "
                    "Antes de aplicar ou citar essa redação, confira o texto oficial e o histórico "
                    "do dispositivo na data relevante. Esta síntese não valida os fatos de um processo real."
                )
            else:
                answer = (
                    f"O texto recuperado da **{repeal_norm}** inclui "
                    f"a **{old_norm}** entre os atos revogados [[{repeal_index}]]. "
                    "A mesma lei prevê tratamento pela legislação "
                    f"da época do protocolo para processos protocolados até sua entrada em vigor e "
                    f"ainda sem despacho decisório, ressalvada a manifestação formal pela análise "
                    f"integral conforme a lei nova [[{transition_index}]].\n\n"
                    f"A extração pendente de revisão da **{old_norm}** trata do licenciamento de obras "
                    f"e dos prazos de análise [[{old_index}]]. Isso não basta "
                    "para afirmar que esse artigo rege o processo concreto: é preciso conferir a data "
                    "de entrada em vigor da lei nova, a data do protocolo, a existência de despacho, "
                    "eventual manifestação formal e o histórico oficial posterior da norma antiga. "
                    f"{commencement_note}"
                    "Os PDFs do acervo são pontos de conferência, não uma validação jurídica do caso."
                )
            claims = [
                {
                    "text": f"A extração da {repeal_norm}, {repeal_source.get('dispositivo_ref')}, lista a {old_norm} entre os atos revogados.",
                    "citation_ids": [str(repeal_source["citation_id"])],
                },
                {
                    "text": f"A extração da {transition_norm}, Art. {transition_article}, prevê regra transitória para processos protocolados antes da entrada em vigor e sem despacho decisório, com exceção por manifestação formal.",
                    "citation_ids": [str(transition_source["citation_id"])],
                },
                {
                    "text": f"A extração pendente da {old_norm}, Art. {older_article}, trata do licenciamento de obras e de prazos de análise.",
                    "citation_ids": [str(old_source_record["citation_id"])],
                },
            ]
            if commencement is not None:
                claims.append(
                    {
                        "text": "A norma posterior contém cláusula operativa de entrada em vigor.",
                        "citation_ids": [str(commencement[1]["citation_id"])],
                    }
                )
                if effective_date and official_commencement and vacatio_rule:
                    claims.append(
                        {
                            "text": (
                                "A edição oficial do Diário Oficial identifica a publicação e a "
                                "cláusula de vigência; a data calculada aplica a regra geral de "
                                "contagem da LC 95/1998 e requer conferência humana."
                            ),
                            "citation_ids": [
                                str(official_commencement[1]["citation_id"]),
                                str(vacatio_rule[1]["citation_id"]),
                            ],
                        }
                    )
            return answer, claims
    return None


def _archive_explicit_repeal_scope_synthesis(
    question: str, results: list[dict]
) -> tuple[str, list[dict]] | None:
    """Describe the literal scope of targets named in one retrieved repeal clause.

    This deliberately distinguishes a bare act citation from an explicit
    article citation without deciding whether the legal effect is total or
    partial. The PDF extraction and target identities remain unreviewed.
    """
    if not re.search(r"\brevog", question, re.IGNORECASE):
        return None
    references = [
        reference
        for reference in parse_normative_references(question)
        if not reference.ambiguous and reference.year is not None and reference.number
    ]
    query_plan = classify_normative_query(question)
    if len(references) != 1 or len(query_plan.article_targets) != 1:
        return None

    query_reference = references[0]
    query_identity = _reference_identity(query_reference)
    target_article = query_plan.article_targets[0]
    source_indexes = {
        str(source.get("citation_id") or ""): index
        for index, source in enumerate(results, 1)
        if source.get("citation_id")
    }
    matching_sources = []
    for source in results:
        if _article_key(str(source.get("dispositivo_ref") or "")) != target_article:
            continue
        source_identity = next(
            (
                _reference_identity(reference)
                for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                if reference.year is not None and reference.number
            ),
            None,
        )
        text = str(source.get("full_text") or "").strip()
        if (
            source_identity == query_identity
            and source.get("citation_id")
            and _NORMATIVE_CHANGE_EVIDENCE_RE.search(text)
            and re.search(r"\brevog", text, re.IGNORECASE)
        ):
            matching_sources.append(source)
    if len(matching_sources) != 1:
        return None

    source = matching_sources[0]
    citation_id = str(source["citation_id"])
    citation_index = source_indexes[citation_id]
    text = str(source.get("full_text") or "")
    act_targets: list[str] = []
    article_targets: list[str] = []
    seen: set[tuple[str, str | None]] = set()
    for match in _NORMATIVE_REFERENCE_SPAN_RE.finditer(text):
        cited_references = [
            reference
            for reference in parse_normative_references(match.group(0))
            if reference.number
        ]
        if len(cited_references) != 1:
            continue
        cited = cited_references[0]
        if cited.type_key == query_reference.type_key and (
            normalize_number(cited.number).lstrip("0") or "0"
        ) == (normalize_number(query_reference.number).lstrip("0") or "0"):
            continue

        prefix = text[max(0, match.start() - 48) : match.start()]
        article_match = re.search(
            r"\bart(?:igo)?s?\.?\s*(\d{1,4}\s*[º°ªo]?)\s+(?:da|do|de)\s*$",
            prefix,
            re.IGNORECASE,
        )
        article = f"Art. {article_match.group(1).strip()}" if article_match else None
        label = str(match.group(0)).strip()
        if cited.year is None:
            written_date = re.match(
                r"\s+de\s+\d{1,2}\s+de\s+[a-zç]+\s+de\s+((?:19|20)\d{2})\b",
                text[match.end() :],
                re.IGNORECASE,
            )
            if written_date:
                label = f"{label}/{written_date.group(1)}"
        key = (str(_reference_identity(cited)), article)
        if key in seen:
            continue
        seen.add(key)
        if article:
            article_targets.append(f"{article} da {label}")
        else:
            act_targets.append(label)

    if not act_targets and not article_targets:
        return None

    device = str(source.get("dispositivo_ref") or f"Art. {target_article}")
    norma = str(source.get("norma_ref") or "norma consultada")
    sections = [f"Na extração local do **{device} da {norma}**, a cláusula de revogação menciona:"]
    if act_targets:
        items = "; ".join(f"**{target}**" for target in act_targets)
        sections.append(
            f"atos sem artigo individual especificado no trecho recuperado: {items} [[{citation_index}]]."
        )
    if article_targets:
        items = "; ".join(f"**{target}**" for target in article_targets)
        sections.append(
            f"dispositivo(s) com artigo expressamente delimitado: {items} [[{citation_index}]]."
        )
    if act_targets and article_targets:
        sections.append(
            "No alcance literal da cláusula, os itens que citam a lei sem indicar artigo "
            "dirigem a revogação ao ato sem limitar o texto a um dispositivo específico; "
            "o item que menciona artigo delimita expressamente o alvo àquele dispositivo. "
            "Isso descreve o que a redação enuncia, não confirma a eficácia jurídica da "
            "revogação, alterações posteriores ou vigência atual de cada norma. A extração "
            "do PDF ainda requer revisão; confira a página original e o histórico oficial."
        )
    else:
        sections.append(
            "Essa separação descreve apenas como os alvos aparecem no texto extraído; não "
            "confirma alterações posteriores nem a vigência atual. A extração do PDF segue "
            "pendente de revisão; confira a página original e o histórico oficial antes de usar."
        )
    claims = (
        [
            {
                "text": "O trecho extraído lista atos sem artigo individual especificado.",
                "citation_ids": [citation_id],
            }
            for _ in act_targets
        ]
        + [
            {
                "text": f"O trecho extraído delimita expressamente {target}.",
                "citation_ids": [citation_id],
            }
            for target in article_targets
        ]
        + (
            [
                {
                    "text": (
                        "A cláusula cita alguns atos sem artigo individualizado e delimita "
                        "outro alvo a um artigo específico; essa é a extensão literal do texto, "
                        "não uma confirmação de eficácia ou vigência atual."
                    ),
                    "citation_ids": [citation_id],
                }
            ]
            if act_targets and article_targets
            else []
        )
    )
    return "\n\n".join(sections), claims


def _archive_explicit_transition_pair_synthesis(
    question: str, results: list[dict]
) -> tuple[str, list[dict]] | None:
    """Summarize an explicitly requested protocol rule and its transition clause.

    Only runs when the question names both provisions in one norm, one retrieved
    excerpt states the protocol-date rule, and another states the pending-case
    conditions and formal opt-in. This is a source-bound summary, not a ruling
    on an individual proceeding or on the legal validity of the extraction.
    """
    if not _PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question):
        return None

    pairs = _explicit_article_norm_pairs(question)
    mentions = _article_reference_mentions(question)
    repeal_relation = bool(_REPEAL_TRANSITION_RELATION_RE.search(question))
    if not pairs and mentions:
        norm_references = [
            reference
            for reference in parse_normative_references(question)
            if not reference.ambiguous and reference.year is not None and reference.number
        ]
        norm_identities = {_reference_identity(reference) for reference in norm_references}
        if len(norm_identities) == 1:
            identity = next(iter(norm_identities))
            pairs = tuple(
                (identity, _article_key(article))
                for _position, article in mentions
                if _article_key(article)
            )
    if not pairs or len(pairs) != len(mentions) or (len(pairs) < 2 and not repeal_relation):
        return None
    identities = {identity for identity, _article in pairs}
    if len(identities) != 1:
        return None
    requested_pairs = set(pairs)

    indexed_sources = []
    for index, source in enumerate(results, 1):
        citation_id = str(source.get("citation_id") or "")
        text = str(source.get("full_text") or "").strip()
        if not citation_id or not text:
            continue
        norm_identity = next(
            (
                _reference_identity(reference)
                for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                if reference.year is not None
            ),
            None,
        )
        pair = (norm_identity, _article_key(str(source.get("dispositivo_ref") or "")))
        if pair in requested_pairs or (repeal_relation and norm_identity in identities):
            indexed_sources.append((index, source, pair, text))

    protocol_rule = next(
        (entry for entry in indexed_sources if _PROTOCOL_DATE_EVIDENCE_RE.search(entry[3])),
        None,
    )
    transition_rule = next(
        (entry for entry in indexed_sources if _PROCESS_TRANSITION_EVIDENCE_RE.search(entry[3])),
        None,
    )
    if transition_rule is None:
        return None

    # Narrowly support the observed PGM question that relates a repeal clause
    # to the same act's transition article. The older act is the object of the
    # repeal, not the owner of Art. 262. Require the exact relational wording,
    # a repeal cue, and an explicit reference from the Art. 260 source to a
    # different act that is also named by the user.
    repeal_rule = None
    if repeal_relation:
        question_identities = {
            _reference_identity(reference)
            for reference in parse_normative_references(question)
            if reference.year is not None and reference.number
        }

        def named_repealed_norms(text: str, owning_identity) -> list[str]:
            matches = []
            for match in _NORMATIVE_REFERENCE_SPAN_RE.finditer(text):
                parsed_candidates = parse_normative_references(match.group(0))
                nearby_date = text[match.end() : match.end() + 72]
                matched_targets = {
                    target
                    for reference in parsed_candidates
                    if reference.number
                    for target in question_identities
                    if target[0] == reference.type_key
                    and target[1] == (normalize_number(reference.number).lstrip("0") or "0")
                    and target != owning_identity
                    and (
                        reference.year == target[2]
                        or (
                            reference.year is None
                            and target[2] is not None
                            and re.search(
                                rf"\bde\s+\d{{1,2}}\s+de\s+[a-zç]+\s+de\s+{target[2]}\b",
                                nearby_date,
                                re.IGNORECASE,
                            )
                        )
                    )
                }
                type_labels = {
                    "lei_complementar": "Lei Complementar",
                    "lei": "Lei",
                    "lei_organica": "Lei Orgânica",
                    "decreto": "Decreto",
                    "decreto_lei": "Decreto-Lei",
                    "decreto_legislativo": "Decreto Legislativo",
                    "resolucao": "Resolução",
                    "portaria": "Portaria",
                }
                matches.extend(
                    f"{type_labels.get(target[0], 'Norma')} nº {target[1]}/{target[2]}"
                    for target in sorted(matched_targets)
                    if target[2] is not None
                )
            return matches

        repeal_rule = next(
            (
                entry
                for entry in indexed_sources
                if re.search(r"\brevog", entry[3], re.IGNORECASE)
                and named_repealed_norms(entry[3], entry[2][0])
            ),
            None,
        )

    if repeal_relation and repeal_rule is None:
        # A user may ask about a clause's relationship to a general repeal
        # without naming one of the repealed acts. In that case, explain only
        # the two extracted texts; do not invent a target or claim legal effect.
        generic_repeal = next(
            (
                entry
                for entry in indexed_sources
                if re.search(r"\brevog", entry[3], re.IGNORECASE)
                and _NORMATIVE_CHANGE_EVIDENCE_RE.search(entry[3])
            ),
            None,
        )
        if generic_repeal is not None:
            repeal_index, repeal_source, _pair, repeal_text = generic_repeal
            transition_index, transition_source, _pair, transition_text = transition_rule
            repeal_label = str(repeal_source.get("dispositivo_ref") or "dispositivo de revogação")
            transition_label = str(
                transition_source.get("dispositivo_ref") or "dispositivo de transição"
            )
            norm_label = str(repeal_source.get("norma_ref") or "a norma consultada")
            repeal_excerpt = re.sub(r"\s+", " ", repeal_text).strip()
            transition_excerpt = re.sub(r"\s+", " ", transition_text).strip()
            answer = (
                f"Na extração local, o **{repeal_label} da {norm_label}** contém a cláusula: "
                f"“{repeal_excerpt}” [[{repeal_index}]]. O **{transition_label}** prevê: "
                f"“{transition_excerpt}” [[{transition_index}]]. Os trechos tratam de matérias "
                "relacionadas, mas a cláusula de revogação, isoladamente, não demonstra que a "
                "regra transitória deixe de incidir nos processos que atendam às suas condições. "
                "Também não é possível identificar aqui todo o alcance da revogação nem decidir "
                "o regime de um processo concreto."
            )
            claims = [
                {
                    "text": f"Transcrição da cláusula de revogação do {repeal_label}.",
                    "citation_ids": [str(repeal_source["citation_id"])],
                },
                {
                    "text": f"Transcrição da regra de transição do {transition_label}.",
                    "citation_ids": [str(transition_source["citation_id"])],
                },
            ]
            commencement = next(
                (
                    entry
                    for entry in indexed_sources
                    if _EFFECTIVE_DATE_OPERATIVE_RE.search(entry[3])
                ),
                None,
            )
            if commencement is not None:
                commencement_index, commencement_source, _pair, _text = commencement
                commencement_label = str(
                    commencement_source.get("dispositivo_ref") or "dispositivo de vigência"
                )
                answer += (
                    f" A entrada em vigor também deve ser conferida no **{commencement_label}** "
                    f"[[{commencement_index}]]."
                )
                claims.append(
                    {
                        "text": f"A norma contém regra de entrada em vigor no {commencement_label}.",
                        "citation_ids": [str(commencement_source["citation_id"])],
                    }
                )
            answer += (
                " A extração dos PDFs locais ainda está pendente de revisão. Para a triagem, "
                "confira a publicação oficial, a data de protocolo, a existência de despacho "
                "decisório e eventual manifestação formal do interessado; os trechos, sozinhos, "
                "não comprovam esses fatos nem determinam o resultado do caso."
            )
            return answer, claims

    if protocol_rule is not None and protocol_rule[2] != transition_rule[2]:
        first_rule, second_rule = protocol_rule, transition_rule
    elif repeal_rule is not None and repeal_rule[2] != transition_rule[2]:
        first_rule, second_rule = repeal_rule, transition_rule
    else:
        return None

    first_index, first_source, _first_pair, first_text = first_rule
    second_index, second_source, _second_pair, second_text = second_rule
    if repeal_rule is first_rule:
        repeal_label = str(first_source.get("dispositivo_ref") or "dispositivo de revogação")
        transition_label = str(second_source.get("dispositivo_ref") or "dispositivo de transição")
        norm_label = str(first_source.get("norma_ref") or "a norma consultada")
        repealed_norms = named_repealed_norms(first_text, first_rule[2][0])
        if not repealed_norms:
            return None
        old_norm_label = repealed_norms[0]
        answer = (
            f"Na extração do PDF, o **{repeal_label} da {norm_label}** inclui "
            f"**{old_norm_label}** entre as normas revogadas [[{first_index}]]. "
            f"Já o **{transition_label}** contém uma regra transitória para processos "
            "de licenciamento protocolados até a entrada em vigor da lei e ainda sem "
            "despacho decisório, com ressalva para manifestação formal pela análise "
            f"nos termos da lei nova [[{second_index}]].\n\n"
            "Para a triagem, confirme nos autos: se o caso é de licenciamento abrangido "
            "pelo dispositivo; a data oficial de entrada em vigor; a data do protocolo; "
            "se já havia despacho decisório; e se existe manifestação formal do interessado. "
            "Esses trechos não determinam, por si sós, o regime aplicável ao processo. "
            "A extração dos PDFs locais está pendente de revisão; confira a publicação e o "
            "histórico oficiais antes de usar esta leitura."
        )
        claims = [
            {
                "text": f"O {repeal_label} da {norm_label} inclui {old_norm_label} entre as normas revogadas no texto extraído.",
                "citation_ids": [str(first_source["citation_id"])],
            },
            {
                "text": f"O {transition_label} descreve condições transitórias para processos de licenciamento, incluindo protocolo, despacho decisório e manifestação formal.",
                "citation_ids": [str(second_source["citation_id"])],
            },
            {
                "text": "A aplicação a um processo concreto depende de fatos dos autos e da conferência das fontes oficiais.",
                "citation_ids": [
                    str(first_source["citation_id"]),
                    str(second_source["citation_id"]),
                ],
            },
        ]
        return answer, claims

    protocol_index, protocol_source, _protocol_pair, _protocol_text = first_rule
    transition_index, transition_source, _transition_pair, _transition_text = second_rule
    norm_label = str(protocol_source.get("norma_ref") or "a norma consultada")
    protocol_article = str(protocol_source.get("dispositivo_ref") or "dispositivo")
    transition_article = str(transition_source.get("dispositivo_ref") or "dispositivo")
    answer = (
        f"Os trechos são complementares: o **{protocol_article}** da **{norm_label}** "
        f"estabelece como referência a legislação vigente na data do protocolo [[{protocol_index}]]. "
        f"Para processos protocolados até a entrada em vigor da lei e ainda sem despacho "
        f"decisório, o **{transition_article}** prevê análise integral conforme a legislação "
        f"da época do protocolo, ressalvada manifestação formal do interessado pela análise "
        f"integral nos termos da lei nova [[{transition_index}]].\n\n"
        "Na triagem, confira a data oficial de entrada em vigor, a data do protocolo, se já havia "
        "despacho decisório e se existe essa manifestação formal. A extração dos PDFs locais "
        "ainda está pendente de revisão; ela não verifica os fatos dos autos nem confirma, "
        "sozinha, a redação oficial aplicável ao caso concreto."
    )
    claims = [
        {
            "text": f"O {protocol_article} da {norm_label} vincula a análise à legislação vigente na data do protocolo.",
            "citation_ids": [str(protocol_source["citation_id"])],
        },
        {
            "text": f"O {transition_article} prevê regra para processo protocolado até a entrada em vigor e sem despacho decisório, ressalvada manifestação formal pela lei nova.",
            "citation_ids": [str(transition_source["citation_id"])],
        },
        {
            "text": "A aplicação a um processo concreto depende de fatos e conferência da redação oficial.",
            "citation_ids": [
                str(protocol_source["citation_id"]),
                str(transition_source["citation_id"]),
            ],
        },
    ]
    return answer, claims


def _archive_transition_commencement_synthesis(
    question: str, results: list[dict]
) -> tuple[str, list[dict]] | None:
    """Synthesize same-act transition, repeal (when asked), and commencement evidence."""
    if not _PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question):
        return None
    if _article_reference_mentions(question):
        return None

    references = [
        reference
        for reference in parse_normative_references(question)
        if not reference.ambiguous and reference.year is not None and reference.number
    ]
    if references:
        identities = {_reference_identity(reference) for reference in references}
        if len(identities) != 1:
            return None
        identity = next(iter(identities))
    else:
        # A uniquely resolved title (currently “Código de Obras”) is an
        # adequate norm scope. Never synthesize across multiple candidate acts.
        if not _requested_archive_norm_title(question):
            return None
        identities = {
            _reference_identity(reference)
            for source in results
            for reference in parse_normative_references(str(source.get("norma_ref") or ""))
            if not reference.ambiguous and reference.year is not None and reference.number
        }
        if len(identities) != 1:
            return None
        identity = next(iter(identities))

    indexed_sources = []
    for index, source in enumerate(results, 1):
        citation_id = str(source.get("citation_id") or "")
        text = str(source.get("full_text") or "").strip()
        source_identity = next(
            (
                _reference_identity(reference)
                for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                if reference.year is not None and reference.number
            ),
            None,
        )
        if citation_id and text and source_identity == identity:
            indexed_sources.append((index, source, text))

    transition = next(
        (entry for entry in indexed_sources if _PROCESS_TRANSITION_EVIDENCE_RE.search(entry[2])),
        None,
    )
    commencement = next(
        (entry for entry in indexed_sources if _EFFECTIVE_DATE_OPERATIVE_RE.search(entry[2])),
        None,
    )
    if transition is None or commencement is None or transition[0] == commencement[0]:
        return None

    asks_about_repeal = bool(re.search(r"\brevog", question, re.IGNORECASE))
    repeal_candidates = [
        entry
        for entry in indexed_sources
        if asks_about_repeal
        and re.search(r"\brevog", entry[2], re.IGNORECASE)
        and _NORMATIVE_CHANGE_EVIDENCE_RE.search(entry[2])
    ]
    # Prefer the article that actually names the acts over a neighboring
    # commencement article whose tail says only “revogadas as disposições em
    # contrário”. If no specific target is extracted, retain the generic
    # clause as a candidate but keep the legal-effect warning below.
    repeal = next(
        (entry for entry in repeal_candidates if _NORMATIVE_REFERENCE_SPAN_RE.search(entry[2])),
        repeal_candidates[0] if repeal_candidates else None,
    )
    if asks_about_repeal and repeal is None:
        return None

    transition_index, transition_source, _transition_text = transition
    commencement_index, commencement_source, _commencement_text = commencement
    norm_label = str(transition_source.get("norma_ref") or "a norma consultada")
    transition_article = str(transition_source.get("dispositivo_ref") or "dispositivo transitório")
    commencement_article = str(
        commencement_source.get("dispositivo_ref") or "dispositivo de vigência"
    )
    answer = ""
    claims = []
    if repeal is not None:
        repeal_index, repeal_source, repeal_text = repeal
        repeal_article = str(repeal_source.get("dispositivo_ref") or "dispositivo de revogação")
        repeal_excerpt = re.sub(r"\s+", " ", repeal_text).strip()
        answer += (
            f"A extração local da **{norm_label}** também contém uma cláusula de revogação expressa "
            f"no **{repeal_article}**: “{repeal_excerpt}” [[{repeal_index}]]. "
            "Ela deve ser conferida no PDF para identificar exatamente os atos abrangidos; a transcrição, "
            "sozinha, não confirma os efeitos jurídicos sobre cada norma. "
        )
        claims.append(
            {
                "text": f"A extração do {repeal_article} contém cláusula de revogação expressa.",
                "citation_ids": [str(repeal_source["citation_id"])],
            }
        )
    commencement_excerpt = re.sub(r"\s+", " ", _commencement_text).strip()
    answer += (
        f"Para processos de licenciamento protocolados até a entrada em vigor da **{norm_label}** "
        f"e ainda sem despacho decisório, o **{transition_article}** prevê análise segundo a "
        "legislação vigente na data do protocolo, salvo manifestação formal do interessado pela "
        f"análise integral conforme a lei nova [[{transition_index}]]. O marco de vigência está no "
        f"**{commencement_article}**: “{commencement_excerpt}” "
        f"[[{commencement_index}]].\n\n"
        "Na triagem, confira nos autos a data do protocolo, a publicação oficial e o cálculo da "
        "entrada em vigor, a existência de despacho decisório e eventual manifestação formal. "
        "Também é preciso localizar a redação oficial vigente na data do protocolo e verificar "
        "alterações posteriores. A extração do PDF local ainda está pendente de revisão e não "
        "permite concluir qual regime se aplica ao processo concreto."
    )
    claims.extend(
        [
            {
                "text": f"{transition_article} da {norm_label} contém a regra transitória descrita.",
                "citation_ids": [str(transition_source["citation_id"])],
            },
            {
                "text": f"{commencement_article} da {norm_label} contém a cláusula de entrada em vigor transcrita.",
                "citation_ids": [str(commencement_source["citation_id"])],
            },
        ]
    )
    return answer, claims


def _archive_retrieval_candidates(
    *, exact_ref, explicit_references, query_tokens, required_title: str | None = None
):
    """Shortlist eligible unreviewed legal PDFs in SQL and annotate latest extraction.

    Explicit normative references are resolved across the entire archive before
    any application-side parsing. Broad topical questions use a bounded,
    database-ranked lexical shortlist so corpus size does not become a Python
    scan or an N+1 query over every document.
    """
    latest = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )
    source_kinds = [DocumentoNormativo.SourceKind.ARCHIVE]
    # Public SAPL PDFs may be tested as pending evidence in the isolated QA
    # profile. Never expose unreviewed SAPL documents to a non-QA assistant.
    if getattr(settings, "JURIX_BUILD_PROFILE", "") == "qa":
        source_kinds.append(DocumentoNormativo.SourceKind.SAPL)
    candidates = DocumentoNormativo.objects.filter(
        source_kind__in=tuple(source_kinds),
        norma__isnull=True,
        review_status__in=(
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        ),
    ).annotate(
        latest_legal_text=Subquery(latest.values("legal_text")[:1]),
        latest_extraction_status=Subquery(latest.values("status")[:1]),
        latest_extraction_sha256=Subquery(latest.values("extraction_sha256")[:1]),
        latest_metadata_candidates=Subquery(latest.values("metadata_candidates_json")[:1]),
        latest_page_map=Subquery(latest.values("page_map_json")[:1]),
    )

    if required_title == "codigo de obras":
        # Resolve the named code by its title before parsing a broad lexical
        # shortlist. The opening provisions are checked again after extraction;
        # the phrase filter prevents unrelated accessibility laws from
        # dominating and bounds CPU work on a large archive.
        title_query = Q()
        for phrase in ("Código de Obras", "Codigo de Obras"):
            title_query |= (
                Q(latest_legal_text__icontains=phrase)
                | Q(original_filename__icontains=phrase)
                | Q(entry_name__icontains=phrase)
                | Q(source_ref__icontains=phrase)
            )
        title_candidates = candidates.filter(title_query)
        if title_candidates.exists():
            return title_candidates.order_by("entry_index", "pk")[
                :_ARCHIVE_EXPLICIT_TITLE_CANDIDATE_LIMIT
            ]

        # If extraction/filename metadata omits the exact title phrase, retain
        # a small, relevance-ranked fallback and abstain when it is insufficient.
        for token_variants in (("código", "codigo"), ("obras",)):
            token_query = Q()
            for token in token_variants:
                token_query |= (
                    Q(latest_legal_text__icontains=token)
                    | Q(original_filename__icontains=token)
                    | Q(entry_name__icontains=token)
                    | Q(source_ref__icontains=token)
                )
            candidates = candidates.filter(token_query)

    if exact_ref:
        # The year embedded in archive filenames is only a discovery hint.
        # Include same-number/type candidates from other filename years so a
        # complete PDF epigraph can resolve a mislabeled archive entry. The
        # application-side check below still requires an exact type/number/year
        # match before the text can answer a year-specific query.
        candidates = candidates.filter(_archive_identity_query(exact_ref, include_year=False))
        return candidates.order_by("entry_index", "pk")
    if explicit_references:
        identity_query = Q()
        for reference in explicit_references:
            identity_query |= _archive_identity_query(reference)
        return candidates.filter(identity_query).order_by("entry_index", "pk")

    terms = sorted(query_tokens)
    if not terms:
        return candidates.none()
    lexical_query = Q()
    relevance = Value(0, output_field=IntegerField())
    for term in terms:
        term_query = (
            Q(latest_legal_text__icontains=term)
            | Q(original_filename__icontains=term)
            | Q(entry_name__icontains=term)
            | Q(source_ref__icontains=term)
        )
        lexical_query |= term_query
        relevance += Case(
            When(term_query, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    candidate_limit = (
        _ARCHIVE_EXPLICIT_TITLE_CANDIDATE_LIMIT
        if required_title == "codigo de obras"
        else _ARCHIVE_LEXICAL_CANDIDATE_LIMIT
    )
    return (
        candidates.filter(lexical_query)
        .annotate(archive_relevance=relevance)
        .order_by("-archive_relevance", "entry_index", "pk")[:candidate_limit]
    )


def _article_key(value: str) -> str:
    match = _ARTICLE_KEY_RE.search(str(value or ""))
    return f"{int(match.group(1))}{(match.group(2) or '').lower()}" if match else ""


def _archive_requested_paragraphs(question: str, article: str, article_text: str):
    """Narrow a retrieved article to an explicitly requested paragraph range."""
    scope = re.search(
        r"§{1,2}\s*(?P<start>\d+)\s*[º°ª]?"
        r"(?:\s*(?:a|até|[-–—])\s*§{0,2}\s*(?P<end>\d+)\s*[º°ª]?)?"
        r"\s*(?:do|de)\s*Art\.?\s*(?P<article>\d+)",
        str(question or ""),
        re.IGNORECASE,
    )
    if scope is None or _article_key(scope.group("article")) != _article_key(article):
        return None

    start_number = int(scope.group("start"))
    end_number = int(scope.group("end") or start_number)
    if end_number < start_number or end_number - start_number > 20:
        return None

    paragraph_matches = list(
        re.finditer(r"§\s*(?P<number>\d+)\s*[º°ª]?", str(article_text or ""))
    )
    selected = []
    for index, match in enumerate(paragraph_matches):
        number = int(match.group("number"))
        if not start_number <= number <= end_number:
            continue
        segment_end = (
            paragraph_matches[index + 1].start()
            if index + 1 < len(paragraph_matches)
            else len(article_text)
        )
        excerpt = re.sub(r"\s+", " ", article_text[match.start() : segment_end]).strip()
        if excerpt:
            selected.append((number, excerpt))

    if not selected:
        return None
    expected_numbers = list(range(start_number, end_number + 1))
    if [number for number, _excerpt in selected] != expected_numbers:
        return None
    label = (
        f"§ {start_number}º"
        if start_number == end_number
        else f"§§ {start_number}º–{end_number}º"
    )
    return label, " ".join(excerpt for _number, excerpt in selected)


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
    instruction_before_topic = question[match.start() : match.start("topic")]
    if re.search(
        r"\b(?:n[aã]o\s+(?:conclua|afirme|presuma|determine)|sem\s+concluir)\b",
        instruction_before_topic,
        re.IGNORECASE,
    ):
        # A caution such as “cite os dispositivos e não conclua sobre vigência”
        # is answer-scope guidance, not a topic that should filter out the
        # explicitly requested articles.
        return None
    topic = re.sub(r"\s*\(contexto normativo:.*\)\s*$", "", match.group("topic"), flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip(" \t,.;:")
    return topic or None


def _article_topic_phrase(question: str) -> str | None:
    """Return the normalized topic phrase for exact-text evidence matching."""
    # Questions about the evidentiary limits of an explicitly cited article are
    # still article-level lookups. Do not reinterpret the application scenario
    # (for example, "regularidade de uma obra") as a topic that filters out the
    # very article the user asked us to assess.
    if _ARTICLE_SCOPE_LIMITS_REQUEST_RE.search(str(question or "")):
        return None
    topic = _article_topic_label(question)
    if not topic:
        return None
    tokens = [
        token
        for token in _WORD_RE.findall(_fold(topic))
        if token not in _STOPWORDS and token not in _QUERY_FRAMING and not token.isdigit()
    ]
    return " ".join(tokens) or None


def _enumerated_topic_facets(question: str) -> tuple[str, ...]:
    """Extract a short, explicit topic list so retrieval can cover each item."""
    text = str(question or "")
    match = re.search(r"[—–:]\s*(?P<topics>[^?]+)", text)
    natural_list = False
    if match and re.search(
        r"\b(?:aspectos?|temas?|t[oó]picos?|eixos|pontos?|itens?)\b",
        text[: match.start()],
        re.IGNORECASE,
    ):
        # A colon introducing the purpose of a question is not a topic-list
        # delimiter. Require an explicit heading before it, such as "aspectos — ...".
        topic_text = match.group("topics").split(".", 1)[0]
    else:
        # Also recognize natural questions that ask which provisions "tratam
        # de X, de Y e de Z". This keeps the explicit list boundary narrow and
        # avoids interpreting an ordinary whole-norm summary as multi-facet.
        natural_match = re.search(
            r"\b(?:tratam|trata|disp[oõ]em|disciplina[m]?|regula[m]?|"
            r"estabelece[m]?|prev[eê]em)\s+(?:sobre\s+|(?:de|do|da|dos|das)\s+)?"
            r"(?P<topics>[^?;]+)",
            text,
            re.IGNORECASE,
        )
        if not natural_match:
            return ()
        topic_text = natural_match.group("topics").split(".", 1)[0]
        natural_list = True
    facets = tuple(
        re.sub(
            r"\s+", " ", re.sub(r"^(?:de|do|da|dos|das)\s+", "", item, flags=re.IGNORECASE)
        ).strip(" \t,;:.-")
        for item in re.split(
            r"\s*,\s*|\s+e\s+(?=(?:de|do|da|dos|das)\s+)" if natural_list else r"\s*,\s*|\s+e\s+",
            topic_text,
            flags=re.IGNORECASE,
        )
    )
    facets = tuple(
        facet
        for facet in facets
        if facet and len(_tokens(facet) - _STOPWORDS - _QUERY_FRAMING) <= 4
    )
    return facets if 3 <= len(facets) <= 6 else ()


def _requested_topic_facets(question: str) -> tuple[str, ...]:
    """Combine explicit topic lists with paired legal questions that need coverage."""
    facets = list(_enumerated_topic_facets(question))
    folded = _fold(question)
    if re.search(
        r"\b(?:elegibilidade|requisitos?\s+(?:para|de)\s+(?:concess[aã]o|percep[cç][aã]o))\b",
        folded,
    ):
        facets.append("elegibilidade")
    elif re.search(r"\b(?:gratifica[cç][aã]o|gvisa)\b", folded) and re.search(
        r"\b(?:experi[eê]ncia\s+m[ií]nima|especializa[cç][aã]o|dedica[cç][aã]o\s+exclusiva)\b",
        folded,
    ):
        # Users often ask about the actual qualification conditions without
        # using the abstract word "elegibilidade". Route those questions to
        # the same precise provision excerpt rather than a generic article hit.
        facets.append("elegibilidade")
    if re.search(r"\b(?:acumula[cç][aã]o|acumular|percep[cç][aã]o\s+em\s+conjunto)\b", folded):
        facets.append("acumulação")
    if re.search(
        r"\b(?:acessibilidade|acess[ií]vel|acess[ií]veis|mobilidade\s+reduzida|"
        r"pessoas?\s+com\s+defici[eê]ncia|rampas?)\b",
        folded,
    ):
        facets.append("acessibilidade")
    return tuple(dict.fromkeys(facets))


def _facet_tokens(facet: str) -> set[str]:
    return _tokens(facet) - _STOPWORDS - _QUERY_FRAMING


_FACET_TERM_ALIASES = {
    "acessibilidade": (
        "acessibilidade|9",
        "acessível|6",
        "acessíveis|6",
        "pessoas com deficiência|7",
        "mobilidade reduzida|7",
        "rota acessível|7",
        "rampas|5",
        "sanitário acessível|7",
        "adaptação para pessoas com deficiência|7",
    ),
    "elegibilidade": (
        "gratificação de vigilância sanitária|9",
        "experiência mínima",
        "especialização",
        "dedicação exclusiva",
    ),
    "acumulacao": (
        "vedada a percepção|8",
        "percepção em conjunto|8",
        "qualquer outra gratificação específica|7",
        "gratificação específica da saúde|7",
    ),
    "ingresso": (
        "ingresso",
        "concurso público",
        "investidura",
        "provimento de cargo efetivo",
        "nomeação",
    ),
    "jornada": (
        "jornada semanal|6",
        "carga horária semanal de trabalho|7",
        "carga horária|5",
        "horas semanais|5",
        "horas por semana|5",
        "40 horas|3",
        "jornada|2",
    ),
    "remuneracao": (
        "remuneração",
        "padrões de vencimento",
        "vencimento básico",
        "salário",
        "tabela remuneratória",
        "padrão remuneratório",
    ),
    "desenvolvimento funcional": (
        "desenvolvimento funcional",
        "progressão funcional",
        "promoção funcional",
        "desenvolvimento dos servidores",
        "progressão",
        "promoção",
    ),
}


def _facet_match_strength(facet: str, source: dict) -> int:
    # PDF extraction often inserts line breaks inside a sentence, so matching
    # expressions for a multi-word legal concept must operate on normalized
    # whitespace rather than treating each visual line as a separate phrase.
    text = _fold(re.sub(r"\s+", " ", str(source.get("full_text") or source.get("texto") or "")))
    normalized_facet = _fold(facet)
    if normalized_facet == "objeto do codigo":
        # "Código" elsewhere in an article (e.g. Código Civil) is not evidence
        # about the object of the municipal code. Require a local semantic
        # construction connecting the object/purpose to this Code, including
        # the code's explicitly titled objectives-and-principles provisions.
        object_of_code = re.search(
            r"\b(?:este|o) codigo\b.{0,100}\b(?:tem por objeto|tem como objetivo|"
            r"tem por finalidade|objetiva|estabelece como objetivo|objetivos e principios)\b|"
            r"\b(?:objeto|finalidade|objetivo|objetivos|principios)\b.{0,60}"
            r"\b(?:deste|do) codigo\b|"
            r"\b(?:objetivos|principios)\b.{0,100}\bcodigo\b|"
            r"\bcodigo\b.{0,100}\b(?:objetivos|principios)\b",
            text,
        )
        return 6 if object_of_code else 0
    aliases = tuple(_fold(term) for term in _FACET_TERM_ALIASES.get(normalized_facet, ()))
    direct_strength = 4 if len(_facet_tokens(facet)) > 1 else 2
    strength = direct_strength if normalized_facet in text else 0
    for alias in aliases:
        phrase, _, raw_weight = alias.partition("|")
        weight = int(raw_weight) if raw_weight.isdigit() else 5
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text):
            strength = max(strength, weight)
    if strength:
        return strength
    wanted = _facet_tokens(facet)
    present = _tokens(text)
    if not wanted:
        return 0
    matched = sum(
        any(
            token == candidate
            or (min(len(token), len(candidate)) >= 6 and token[:6] == candidate[:6])
            for candidate in present
        )
        for token in wanted
    )
    # A one-token overlap is not enough for a compound legal topic: a generic
    # occurrence of "Código" must not stand in for its object, and "processo"
    # alone must not establish the transition rule for old cases without a
    # decision. Keep single-word topics usable; require at least two terms for
    # multi-word facets (and two thirds for longer phrases).
    required_matches = 1 if len(wanted) == 1 else max(2, (2 * len(wanted) + 2) // 3)
    return 1 if matched >= required_matches else 0


def _facet_excerpt(facet: str, source: dict, *, max_chars: int = 420) -> str:
    """Return a local quote around the exact facet term/alias, not article start."""
    text = re.sub(r"\s+", " ", str(source.get("full_text") or source.get("texto") or "")).strip()
    normalized_facet = _fold(facet)
    if normalized_facet == "elegibilidade":
        eligibility = re.search(
            r"\bII\s*[–—-]\s*Gratifica[cç][aã]o\s+de\s+Vigil[aâ]ncia\s+Sanit[aá]ria\b"
            r".*?(?=\s*,\s*(?:estabelecida|fixada)\s+em\b)",
            text,
            re.IGNORECASE,
        )
        if eligibility:
            return eligibility.group(0).strip(" ,;:")
    if normalized_facet == "acumulacao":
        accumulation = re.search(
            r"§\s*1[º°o]?\s*[-–.]?\s*É\s+vedada\s+a\s+percep[cç][aã]o\b[^.]*\.",
            text,
            re.IGNORECASE,
        )
        if accumulation:
            return accumulation.group(0).strip()
    if len(text) <= max_chars:
        return text
    folded = _fold(text)
    needles = [normalized_facet]
    needles.extend(
        _fold(item.partition("|")[0]) for item in _FACET_TERM_ALIASES.get(normalized_facet, ())
    )
    positions = [folded.find(needle) for needle in needles if needle and folded.find(needle) >= 0]
    if not positions:
        for token in sorted(_facet_tokens(facet), key=len, reverse=True):
            position = folded.find(token)
            if position >= 0:
                positions.append(position)
                break
    start = max(0, min(positions, default=0) - max_chars // 3)
    end = min(len(text), start + max_chars)
    if start:
        boundary = text.find(" ", start)
        start = boundary + 1 if boundary >= 0 else start
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        if boundary > start:
            end = boundary
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _source_matches_facet(facet: str, source: dict) -> bool:
    return _facet_match_strength(facet, source) > 0


def _select_facet_sources(rows: list[dict], facets: tuple[str, ...], limit: int) -> list[dict]:
    """Reserve one best-ranked provision per requested facet before filling top-k."""
    ranked = sorted(
        rows,
        key=lambda row: (
            float(row.get("similarity_score") or 0),
            str(row.get("dispositivo_ref") or ""),
        ),
        reverse=True,
    )
    selected = []
    selected_ids = set()
    for facet in facets:
        candidates = [
            row
            for row in ranked
            if row.get("citation_id")
            and row.get("citation_id") not in selected_ids
            and _source_matches_facet(facet, row)
        ]
        candidate = None
        if candidates:
            candidate = max(
                candidates,
                key=lambda row: (
                    _facet_match_strength(facet, row),
                    float(row.get("similarity_score") or 0),
                ),
            )
        if candidate is not None:
            selected.append(candidate)
            selected_ids.add(candidate.get("citation_id"))
    for row in ranked:
        if row.get("citation_id") in selected_ids:
            continue
        if len(selected) >= max(limit, len(selected)):
            break
        selected.append(row)
    return selected


def _has_cited_facet_coverage(answer: str, results: list[dict], facets: tuple[str, ...]) -> bool:
    """Require requested facets and material eligibility criteria to be cited."""
    if not facets:
        return True

    def answer_covers_facet(facet: str, source: dict) -> bool:
        if _fold(facet) != "elegibilidade":
            return True
        source_excerpt = _fold(_facet_excerpt(facet, source))
        answer_text = _fold(answer)
        # A generic paraphrase such as "experiência mínima" can omit the
        # operative threshold or an alternative qualification. In the
        # reviewed-archive workflow, require the answer to carry each material
        # condition actually present in the cited clause; otherwise the caller
        # replaces the draft with the verbatim facet evidence map.
        for condition in ("experiencia minima", "especializacao", "dedicacao exclusiva"):
            if condition in source_excerpt and condition not in answer_text:
                return False
        duration = re.search(
            r"experiencia minima.{0,50}?\b(\d+)\s*(?:\([^)]*\)\s*)?anos?\b",
            source_excerpt,
        )
        if duration and not re.search(
            rf"\b{re.escape(duration.group(1))}\s*.{{0,18}}?\banos?\b", answer_text
        ):
            return False
        workload = re.search(r"\b(\d+)\s*(?:\([^)]*\)\s*)?horas?\b", source_excerpt)
        if workload and not re.search(
            rf"\b{re.escape(workload.group(1))}\s*.{{0,18}}?\bhoras?\b", answer_text
        ):
            return False
        return True

    for index, source in enumerate(results, 1):
        if f"[[{index}]]" not in answer:
            continue
        if all(
            _source_matches_facet(facet, source) and answer_covers_facet(facet, source)
            for facet in facets
        ):
            return True
    for facet in facets:
        if not any(
            f"[[{index}]]" in answer
            and _source_matches_facet(facet, source)
            and answer_covers_facet(facet, source)
            for index, source in enumerate(results, 1)
        ):
            return False
    return True


def _facet_evidence_map(
    facets: tuple[str, ...], results: list[dict], *, history_requested: bool = False
) -> tuple[str, list[dict]]:
    """Build a concise, cited prose synthesis after a narrow model draft."""
    sentences = []
    claims = []
    for facet in facets:
        matches = [
            (index, source)
            for index, source in enumerate(results, 1)
            if source.get("citation_id") and _source_matches_facet(facet, source)
        ]
        match = max(
            matches,
            key=lambda item: (
                _facet_match_strength(facet, item[1]),
                float(item[1].get("similarity_score") or 0),
            ),
            default=None,
        )
        if match is None:
            sentences.append(
                f"Quanto a {facet}, não localizei evidência direta nos trechos recuperados."
            )
            continue
        index, source = match
        excerpt = _facet_excerpt(facet, source)
        sentences.append(f"Quanto a {facet}, o trecho recuperado dispõe: “{excerpt}” [[{index}]].")
        claims.append({"text": excerpt, "citation_ids": [source["citation_id"]]})
    limits = (
        "Esta é uma triagem da extração de PDFs arquivados, ainda pendente de revisão; "
        "ela não confirma a redação vigente, os fatos dos autos nem o enquadramento de "
        "uma obra concreta, e não substitui a conferência do documento original."
    )
    if history_requested:
        limits += (
            " O acervo consultado não fornece uma cadeia de alterações e revogações "
            "vinculada e revisada; portanto, não confirma quais mudanças posteriores "
            "atingiram esses dispositivos."
        )
    return " ".join([" ".join(sentences), limits]), claims


def _norm_identity_topic_tokens(question: str) -> set[str]:
    """Extract the object of an explicit "which norm institutes X" subquestion."""
    match = _NORM_IDENTITY_TOPIC_RE.search(str(question or ""))
    if not match:
        return set()
    return _tokens(match.group("topic")) - _QUERY_FRAMING


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


def _article_rows(text: str, *, page_map: list[dict] | None = None) -> list[dict]:
    from src.processing.legal_parser import (
        _PAGE_HEADER_LINE_RE,
        _PAGE_SEPARATOR_RE,
        LegalTextParser,
        find_normative_appendix_start,
        strip_closing_editorial_metadata,
    )

    # Keep every character offset aligned with ExtracaoDocumento.legal_text so
    # source spans can be resolved against its immutable page_map_json. Mask
    # page artifacts instead of deleting them (strip_page_artifacts shifts all
    # offsets after each separator/header).
    chars = list(text or "")
    original = "".join(chars)
    for pattern in (_PAGE_SEPARATOR_RE, _PAGE_HEADER_LINE_RE):
        for match in pattern.finditer(original):
            for position in range(match.start(), match.end()):
                if chars[position] not in "\r\n":
                    # A non-whitespace sentinel keeps the parser's leading
                    # ``\s*`` from swallowing a page marker/header and moving
                    # an article's start offset onto the previous page.
                    chars[position] = "\x00"
    source = strip_closing_editorial_metadata("".join(chars))

    def page_index_at(offset: int) -> int | None:
        for span in page_map or []:
            start, end, page = span.get("start"), span.get("end"), span.get("page")
            if (
                isinstance(start, int)
                and isinstance(end, int)
                and start <= offset < end
                and isinstance(page, int)
                and page > 0
            ):
                return page - 1
        return None

    elements = LegalTextParser.parse_legal_text(source, preserve_offsets=True)
    appendix_start = find_normative_appendix_start(source)
    division_starts = [
        match.start()
        for pattern in LegalTextParser.DIVISION_PATTERNS.values()
        for match in pattern.finditer(source)
    ]
    articles = [
        row
        for row in elements
        if row.get("tipo") == "artigo"
        and (appendix_start is None or row["start_pos"] < appendix_start)
    ]
    complete_articles = []
    for index, article in enumerate(articles):
        next_article_start = (
            articles[index + 1]["start_pos"] if index + 1 < len(articles) else len(source)
        )
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
        raw_body = source[article_text_start:article_end].replace("\x00", " ")
        leading_whitespace = len(raw_body) - len(raw_body.lstrip())
        article_text = raw_body.strip()
        complete_articles.append(
            {
                **article,
                "texto": article_text,
                "text_start_pos": article_text_start + leading_whitespace,
                "end_pos": article_end,
                "page_index": page_index_at(article["start_pos"]),
                "annexes_present": appendix_start is not None,
            }
        )
    return complete_articles


def _page_index_for_excerpt(article: dict, excerpt: str, page_map: list[dict] | None) -> int | None:
    """Resolve the page containing most of an excerpt within a parsed article."""
    body_start = article.get("text_start_pos")
    body = str(article.get("texto") or "")
    words = str(excerpt or "").split()
    if not isinstance(body_start, int) or not body or not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), body, re.IGNORECASE)
    if not match:
        return None
    excerpt_start = body_start + match.start()
    excerpt_end = body_start + match.end()
    overlaps = []
    for span in page_map or []:
        start, end, page = span.get("start"), span.get("end"), span.get("page")
        if not (
            isinstance(start, int) and isinstance(end, int) and isinstance(page, int) and page > 0
        ):
            continue
        overlap = max(0, min(excerpt_end, end) - max(excerpt_start, start))
        if overlap:
            overlaps.append((overlap, page - 1))
    return max(overlaps, key=lambda item: item[0])[1] if overlaps else None


def _sample_whole_norm_rows(
    rows: list[dict], *, topic_tokens: set[str] | None = None,
    budget_chars: int = _WHOLE_NORM_CONTEXT_BUDGET_CHARS,
) -> tuple[list[dict], int]:
    """Keep every article that fits; otherwise sample by scope or across the norm."""
    total = len(rows)
    if not total:
        return rows, total

    text_lengths = [len(str(row.get("full_text") or "")) for row in rows]
    total_chars = sum(text_lengths)
    if total_chars <= budget_chars:
        return rows, total

    if topic_tokens:
        # A practical-purpose qualifier changes which provisions are useful
        # for triage. Do not replace that scope with an evenly spaced sample
        # of unrelated articles merely because the user also named the whole
        # enactment. Keep only articles with literal topic overlap and rank
        # them by overlap before applying the same context budget.
        ranked = []
        for index, row in enumerate(rows):
            evidence_tokens = _tokens(str(row.get("full_text") or ""))
            overlap = topic_tokens & evidence_tokens
            if not overlap:
                continue
            ranked.append(
                (
                    len(overlap) / len(topic_tokens),
                    float(row.get("similarity_score") or 0),
                    index,
                    row,
                )
            )
        if not ranked:
            return [], total
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = []
        selected_chars = 0
        for _overlap_score, _retrieval_score, _index, row in ranked:
            row_chars = len(str(row.get("full_text") or ""))
            if selected_chars + row_chars <= budget_chars:
                selected.append(row)
                selected_chars += row_chars
        selected_ids = {id(row) for row in selected}
        return [row for row in rows if id(row) in selected_ids], total

    average_chars = max(1, total_chars // total)
    budget_count = max(1, budget_chars // average_chars)
    sample_size = min(total, budget_count)
    while sample_size:
        if sample_size == 1:
            indexes = [total // 2]
        else:
            indexes = [
                round(index * (total - 1) / (sample_size - 1)) for index in range(sample_size)
            ]
        # The average-size estimate can miss uneven articles. Reduce the
        # evenly-spaced sample until its actual evidence text fits the budget.
        if sum(text_lengths[index] for index in indexes) <= budget_chars:
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
    effective_date_question = bool(_EFFECTIVE_DATE_ARTICLE_QUERY_RE.search(question))
    explicit_norm_references = [
        reference for reference in parsed_references if reference.year is not None
    ]
    explicit_norm_identities = {reference.identity for reference in explicit_norm_references}
    explicit_amendment_scope = _explicit_amendment_article_scope(question)
    one_exact_norm_reference = (
        bool(parsed_references)
        and len(explicit_norm_references) == len(parsed_references)
        and len(explicit_norm_identities) == 1
    )
    single_norm_reference = explicit_norm_references[0] if one_exact_norm_reference else None
    change_inventory_request = _is_normative_change_inventory_request(question, query_plan)
    explicit_article_norm_pairs = _explicit_article_norm_pairs(question)
    paired_article_scope = (
        len(explicit_article_norm_pairs) == len(_article_reference_mentions(question))
        and (
            len(explicit_article_norm_pairs) > 1
            or explicit_amendment_scope is not None
        )
        and not _cross_reference_scan_scope(question)
    )
    article_targets_by_identity: dict[tuple[str, str, int | None], set[str]] = {}
    for identity_key, article_key in explicit_article_norm_pairs:
        article_targets_by_identity.setdefault(identity_key, set()).add(article_key)
    cross_reference_scope = _cross_reference_scan_scope(question)
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
        if cross_reference_scope or one_exact_norm_reference
        else retrieval_question
    )
    # A citation inventory must scan the explicitly named source norm, not
    # rank its articles by question boilerplate such as “prova que alterou”.
    query_tokens = (
        set() if cross_reference_scope or effective_date_question else _tokens(lexical_question)
    )
    if not query_tokens:
        if not (
            cross_reference_scope
            or (one_exact_norm_reference and query_plan.is_norma_overview)
            or query_plan.explicit_target_overview
            or change_inventory_request
            or (effective_date_question and one_exact_norm_reference)
        ):
            return []
    article_topic_phrase = _article_topic_phrase(question)
    requested_facets = _requested_topic_facets(question)
    requested_norm_title = _requested_archive_norm_title(question)
    references = [ref for ref in parsed_references if not ref.ambiguous]
    requested_edition_identity, requested_edition_year = _requested_archive_edition_scope(
        question, references
    )
    exact_ref = (
        single_norm_reference
        if one_exact_norm_reference
        else (references[0] if len(references) == 1 else None)
    )
    if query_plan.explicit_target_overview and query_plan.reference is not None:
        exact_ref = query_plan.reference
        # The paired act/article is context for the request; do not let its
        # number or change wording rank only one article of the target norm.
        query_tokens = set()
    if cross_reference_scope:
        exact_ref = cross_reference_scope[0]
    transition_scope_question = bool(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question))
    if requested_appendix and exact_ref is None:
        # Never answer an underspecified appendix follow-up from whichever
        # document happens to rank first; conversation context must resolve it.
        return []
    explicit_multi_references = (
        [ref for ref in parsed_references if ref.year is not None and ref.number]
        if len(explicit_norm_identities) > 1 and not cross_reference_scope
        else []
    )
    asks_salary_floor = bool(
        _SALARY_FLOOR_QUERY_RE.search(question) and _SALARY_SUBJECT_QUERY_RE.search(question)
    )
    if (
        exact_ref is None
        and one_exact_norm_reference
        and query_plan.article_targets
        and query_plan.kind == "provision"
    ):
        exact_ref = single_norm_reference
    explicit_years = set(re.findall(r"\b(?:19|20)\d{2}\b", _fold(question)))
    wanted_articles = (
        ()
        if cross_reference_scope or query_plan.explicit_target_overview
        else query_plan.article_targets
    )
    if (
        not wanted_articles
        and not cross_reference_scope
        and not query_plan.explicit_target_overview
    ):
        wanted_articles = tuple(
            _article_key(match.group(1)) for match in _ARTICLE_RE.finditer(question)
        )
    wanted_articles = tuple(dict.fromkeys(target for target in wanted_articles if target))
    if _has_ambiguous_multi_norm_article_scope(question) and not query_plan.explicit_target_overview:
        # Article numbers belong to a specific norm. Until sentence-level
        # parsing can reliably pair each article mention with its norm, do not
        # allow one norm's Art. 21 to satisfy a request about another norm's
        # Art. 21 merely because both identities occur in the same question.
        return []
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
    identity_topic_tokens = _norm_identity_topic_tokens(question) if wanted_articles else set()
    # Explicit law identity alone does not mean the user asked for a whole-law
    # overview: broad lead-ins such as "explique" can precede a specific topic
    # ("Explique o piso ... na LC ..."). Overview retrieval is reserved for
    # queries whose normalized tokens contain no topic after framing is removed.
    whole_norm_request = _is_whole_norm_request(question, query_plan)
    archive_query_tokens = _archive_search_tokens(topic_tokens or query_tokens)
    archive_query_tokens |= {
        token
        for facet in requested_facets
        for alias in _FACET_TERM_ALIASES.get(_fold(facet), ())
        for token in _tokens(alias.partition("|")[0])
    }

    documents = list(
        _archive_retrieval_candidates(
            exact_ref=exact_ref,
            explicit_references=explicit_multi_references,
            query_tokens=archive_query_tokens,
            required_title=(requested_norm_title if not explicit_norm_references else None),
        )
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
        candidate_identity = (
            str(identity.get("type") or ""),
            normalize_number(str(identity.get("number") or "")).lstrip("0") or "0",
            int(identity.get("year")) if str(identity.get("year") or "").isdigit() else None,
        )
        if (
            requested_edition_identity
            and requested_edition_year
            and candidate_identity == requested_edition_identity
        ):
            metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
            edition = metadata.get("edition_candidate")
            edition_year = (
                edition.get("declared_value_year") if isinstance(edition, dict) else None
            )
            if (
                not isinstance(edition, dict)
                or edition.get("kind") != "official_consolidated_text"
                or str(edition_year) != str(requested_edition_year)
            ):
                continue
        document_article_targets = (
            article_targets_by_identity.get(candidate_identity, set())
            if paired_article_scope
            else set(wanted_articles)
        )
        is_amendment_source = bool(
            explicit_amendment_scope
            and candidate_identity == explicit_amendment_scope[0]
        )
        if paired_article_scope and not document_article_targets and not is_amendment_source:
            continue
        if exact_ref:
            candidate_number = normalize_number(str(identity.get("number") or ""))
            if (
                candidate_number != exact_ref.number
                or (
                    exact_ref.type_key
                    and identity.get("type")
                    not in _TYPE_ALIASES.get(exact_ref.type_key, {exact_ref.type_key})
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
                    or candidate_type in _TYPE_ALIASES.get(reference.type_key, {reference.type_key})
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
        # Re-read the bounded PDF heading from the extraction text. Stored
        # candidate metadata may predate a parser fix or have been produced by
        # a line-broken text layer; the source PDF text remains the observation
        # used for a safe exact-reference match.
        fresh_epigraph = parse_initial_epigraphs(
            re.split(r"(?m)^--- Página \d+ ---\s*$", legal_text), max_pages=3
        )
        extraction_metadata = getattr(extraction, "metadata_candidates_json", {}) or {}
        stored_epigraph = (
            extraction_metadata.get("epigraph", {})
            if isinstance(extraction_metadata, dict)
            else {}
        )
        epigraph_candidate = {
            "status": fresh_epigraph.status,
            "candidates": [
                {
                    "type_key": candidate.type_key,
                    "number": candidate.number,
                    "year": candidate.year,
                    "act_date": candidate.act_date,
                }
                for candidate in fresh_epigraph.candidates
            ],
        }
        if not epigraph_candidate["candidates"] and isinstance(stored_epigraph, dict):
            epigraph_candidate = stored_epigraph
        identity_epigraph_check = compare_identity_to_epigraph(identity, epigraph_candidate)
        epigraph_identity = identity_epigraph_check.get("epigraph_identity", {})
        epigraph_matches_exact = bool(
            exact_ref
            and epigraph_identity.get("type")
            in _TYPE_ALIASES.get(exact_ref.type_key, {exact_ref.type_key})
            and epigraph_identity.get("number") == exact_ref.number
            and str(epigraph_identity.get("year") or "") == str(exact_ref.year)
        )
        filename_identity_matches_exact = bool(
            exact_ref
            and candidate_identity[1] == exact_ref.number
            and candidate_identity[2] == exact_ref.year
            and candidate_identity[0]
            in _TYPE_ALIASES.get(exact_ref.type_key, {exact_ref.type_key})
        )
        if identity_epigraph_check["status"] == "conflict" and not epigraph_matches_exact:
            # Keep fail-closed behavior when the observed act contradicts both
            # the archive-derived identity and the requested citation.
            continue
        if exact_ref and not (filename_identity_matches_exact or epigraph_matches_exact):
            continue
        effective_identity = identity
        if epigraph_matches_exact and not filename_identity_matches_exact:
            # The exact epigraph resolves a filename-year conflict for this
            # query only. The candidate remains pending; no database identity,
            # SAPL association, or legal-effect status is changed.
            effective_identity = {
                **identity,
                "type": epigraph_identity["type"],
                "number": epigraph_identity["number"],
                "year": int(epigraph_identity["year"]),
            }
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
            articles = _article_rows(
                legal_text,
                page_map=getattr(extraction, "page_map_json", None),
            )
        if requested_norm_title and not explicit_norm_references:
            opening_text = _fold(
                " ".join(
                    str(article.get("texto") or "")
                    for article in articles
                    if _article_key(str(article.get("numero") or "")) in {"1", "2", "3"}
                )
            )
            if "codigo de obras" not in opening_text:
                continue
            first_article_text = next(
                (
                    _fold(str(article.get("texto") or ""))
                    for article in articles
                    if _article_key(str(article.get("numero") or "")) == "1"
                ),
                "",
            )
            title_edition_candidate = bool(
                first_article_text
                and not re.search(
                    r"^(?:fica(?:m)?\s+)?(?:(?:esta|a presente)\s+)?"
                    r"(?:lei(?:\s+complementar)?\s+)?"
                    r"(?:altera(?:do|da|dos|das)?|acrescenta(?:do|da|dos|das)?|"
                    r"revoga(?:do|da|dos|das)?|modifica(?:do|da|dos|das)?|"
                    r"da nova redacao)\b",
                    first_article_text,
                )
            )
        else:
            title_edition_candidate = False
        if change_inventory_request and not requested_appendix and not wanted_articles:
            articles = [
                article
                for article in articles
                if _NORMATIVE_CHANGE_EVIDENCE_RE.search(str(article.get("texto") or ""))
            ]
            if not articles:
                continue
        if cross_reference_scope and not requested_appendix:
            target_identities = {
                _reference_identity(reference) for reference in cross_reference_scope[1]
            }
            articles = [
                article
                for article in articles
                if target_identities
                & {
                    _reference_identity(reference)
                    for reference in parse_normative_references(str(article.get("texto") or ""))
                    if reference.year is not None
                }
            ]
        if document_article_targets and not requested_appendix:
            all_articles = articles
            requested_articles = set(document_article_targets)
            target_articles = [
                row
                for row in all_articles
                if _article_key(str(row.get("numero") or "")) in requested_articles
            ]
            if transition_scope_question and (
                paired_article_scope or exact_ref or requested_norm_title
            ):
                has_transition_clause = any(
                    _PROCESS_TRANSITION_EVIDENCE_RE.search(str(article.get("texto") or ""))
                    for article in all_articles
                )
                if has_transition_clause:
                    target_articles.extend(
                        article
                        for article in all_articles
                        if _EFFECTIVE_DATE_OPERATIVE_RE.search(str(article.get("texto") or ""))
                    )
            if transition_scope_question and re.search(r"\brevog", question, re.IGNORECASE):
                target_articles.extend(
                    article
                    for article in all_articles
                    if _NORMATIVE_CHANGE_EVIDENCE_RE.search(str(article.get("texto") or ""))
                    and _NORMATIVE_REFERENCE_SPAN_RE.search(str(article.get("texto") or ""))
                )
            if not target_articles:
                continue
            identity_support = []
            if identity_topic_tokens:
                identity_matches = []
                for article in all_articles:
                    article_tokens = _tokens(str(article.get("texto") or ""))
                    overlap = len(identity_topic_tokens & article_tokens) / len(
                        identity_topic_tokens
                    )
                    if overlap >= 0.55:
                        identity_matches.append((overlap, article))
                # A compound query asks for both a norm's identity and a named
                # provision. Require an excerpt that actually supports the
                # norm-identification clause; otherwise the article number or
                # salary vocabulary alone can select an unrelated act.
                if not identity_matches:
                    continue
                identity_matches.sort(key=lambda item: item[0], reverse=True)
                identity_support = [
                    {**article, "_identity_support": True}
                    for _score, article in identity_matches[:2]
                    if _article_key(str(article.get("numero") or "")) not in requested_articles
                ]
            articles = target_articles + identity_support
        if not articles and not requested_appendix:
            articles = [{"tipo": "texto", "numero": "", "texto": legal_text[:2400]}]

        identity = effective_identity
        type_key = str(identity.get("type") or "")
        type_label = _TYPE_LABELS.get(type_key, "Norma importada")
        number = str(identity.get("number") or "?")
        year = str(identity.get("year") or "ano não identificado")
        norma_ref = f"{type_label} nº {number}/{year}"
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        edition_label = _candidate_edition_label(document)
        identity_conflict = bool(
            document.conflicts_json
            or not metadata.get("identity_key")
            or identity_epigraph_check["status"] == "conflict"
        )
        matched_norma = (
            sapl_normas_by_identity.get(metadata.get("identity_key"))
            if not identity_conflict
            else None
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
                    year == candidate_year or re.search(rf"(?<!\d){re.escape(year)}(?!\d)", text)
                    for year in explicit_years
                )
                if not year_supported:
                    continue
            overlap = len(query_tokens & _tokens(text)) / max(len(query_tokens), 1)
            topic_overlap = (
                len(topic_tokens & _tokens(text)) / max(len(topic_tokens), 1)
                if topic_tokens
                else 0.0
            )
            folded_text = _fold(text)
            topic_phrase_match = any(phrase in folded_text for phrase in topical_phrases)
            if article_topic_phrase:
                topic_phrase_match = article_topic_phrase in folded_text
            score = topic_overlap if exact_ref and topic_tokens and not wanted_articles else overlap
            if exact_ref and (wanted_articles or not topic_tokens):
                score += 1.0
            if document_article_targets:
                score += 1.0
            if identity_conflict:
                score *= 0.8
            article_number = str(article.get("numero") or "")
            device_ref = (
                article_number
                if article.get("is_appendix")
                else f"Art. {article_number}"
                if article_number
                else "Trecho extraído"
            )
            stable_id = hashlib.sha256(
                f"{document.public_id}:{extraction.extraction_sha256}:{article.get('start_pos', 0)}".encode()
            ).hexdigest()[:24]
            source_page_index = article.get("page_index")
            if requested_facets and not article.get("is_appendix"):
                page_map = getattr(extraction, "page_map_json", None)
                for facet in requested_facets:
                    facet_excerpt = _facet_excerpt(facet, {"full_text": text})
                    excerpt_page_index = _page_index_for_excerpt(article, facet_excerpt, page_map)
                    if excerpt_page_index is not None:
                        source_page_index = excerpt_page_index
                        break
            rows.append(
                {
                    "id": stable_id,
                    "source_id": str(document.public_id),
                    "document_id": str(document.public_id),
                    "document_sha256": getattr(document, "content_sha256", None),
                    "citation_id": f"qa:{stable_id}",
                    "citation_label": f"{norma_ref}, {device_ref}",
                    "source_kind": getattr(
                        document,
                        "source_kind",
                        DocumentoNormativo.SourceKind.ARCHIVE,
                    ),
                    "norma_ref": norma_ref,
                    "edition_label": edition_label,
                    "dispositivo_ref": device_ref,
                    "texto": text,
                    "full_text": text,
                    "evidence_text": text,
                    "similarity_score": min(score, 1.0),
                    "_topic_overlap": topic_overlap,
                    "_topic_phrase_match": topic_phrase_match,
                    "_identity_support": article.get("_identity_support", False),
                    "_title_edition_candidate": title_edition_candidate,
                    "_identity_year": identity.get("year"),
                    "contribution": (
                        f"{edition_label}. Trecho de extração pendente de revisão."
                        if edition_label
                        else "Trecho de extração PDF pendente de revisão"
                    ),
                    "source_type": edition_label
                    or "Acervo histórico local — extração pendente de revisão",
                    "retrieval_strategy": "qa_archive_lexical",
                    "evidence_scope": "isolated_qa_archive",
                    "coverage": {
                        "extraction_status": extraction.status,
                        "identity_conflict": identity_conflict,
                        "epigraph_identity_status": identity_epigraph_check["status"],
                        "annexes_present": article.get("annexes_present", False),
                        "annexes_included_in_article_evidence": False,
                        "evidence_kind": "normative_appendix"
                        if article.get("is_appendix")
                        else "article",
                    },
                    "page_index": source_page_index,
                    "page": source_page_index + 1 if isinstance(source_page_index, int) else None,
                    "span": {
                        "start": article.get("start_pos"),
                        "end": article.get("end_pos"),
                        "text_start": article.get("text_start_pos"),
                    }
                    if isinstance(article.get("start_pos"), int)
                    and isinstance(article.get("end_pos"), int)
                    else None,
                    "span_basis": "offset-preserving-legal-extraction",
                    "_page_map": getattr(extraction, "page_map_json", None) or [],
                    "_device_order": article.get("start_pos", article_order),
                    "local_pdf_url": reverse(
                        "legislation:document_pdf",
                        kwargs={"document_id": document.public_id},
                    ),
                    "pdf_url": official_pdf_url or _candidate_official_pdf_url(document),
                    "sapl_url": sapl_url,
                    "data_publicacao": None,
                    "data_vigencia": None,
                }
            )

    # For a request to explain every explicitly named provision, the topic is
    # useful for ranking but must not hide a requested article. Keep topic
    # filtering for choice questions such as "qual dos dois dispositivos...".
    preserve_explicit_article_targets = (
        paired_article_scope and not _CONTEXTUAL_MULTI_ARTICLE_TOPIC_RE.search(question)
    )
    if wanted_articles and article_topic_phrase and not preserve_explicit_article_targets:
        # An article number is not a topic: when a question asks about a
        # provision *and* names its subject, apply that subject constraint
        # before returning candidates. Otherwise unrelated norms with the same
        # article number can leak into the early source event/top-k set.
        rows = [
            row
            for row in rows
            if row.get("_identity_support")
            or _supports_article_topic(question, row.get("full_text", ""))
        ]

    if exact_ref and _EFFECTIVE_DATE_ARTICLE_QUERY_RE.search(question):
        # A follow-up asking which provision sets the effective date needs the
        # operative commencement clause, not provisions that merely mention
        # "the date of entry into force" as a condition (for example, a
        # transitional rule). Abstain if no operative clause is present.
        rows = [
            row
            for row in rows
            if _EFFECTIVE_DATE_OPERATIVE_RE.search(str(row.get("full_text") or ""))
        ]

    if requested_norm_title and not explicit_norm_references:
        # A title may occur in historical acts that were later replaced, as
        # well as in amendment acts that merely cite the code. Resolve an
        # unnumbered title query only to a uniquely newest archive candidate
        # whose opening provisions identify that code and whose Art. 1º is not
        # an amendment clause. This is retrieval
        # ranking only: the archive remains pending review and this does not
        # establish legal validity or current force.
        title_origins = [
            row
            for row in rows
            if row.get("_title_edition_candidate") and isinstance(row.get("_identity_year"), int)
        ]
        if not title_origins:
            rows = []
        else:
            newest_year = max(row["_identity_year"] for row in title_origins)
            newest_origin_ids = {
                row["source_id"] for row in title_origins if row["_identity_year"] == newest_year
            }
            rows = (
                [row for row in rows if row["source_id"] in newest_origin_ids]
                if len(newest_origin_ids) == 1
                else []
            )

    if (exact_ref or requested_norm_title) and transition_scope_question:
        # Resolve a title-only query to one archive edition before filtering
        # to transition/repeal/commencement clauses; otherwise the opening
        # article that identifies the title is removed before edition
        # disambiguation. This remains retrieval only and does not establish
        # legal effect.
        requested_protocol_articles = set(wanted_articles)
        asks_about_repeal = bool(re.search(r"\brevog", question, re.IGNORECASE))
        rows = [
            row
            for row in rows
            if _PROCESS_TRANSITION_EVIDENCE_RE.search(str(row.get("full_text") or ""))
            or _EFFECTIVE_DATE_OPERATIVE_RE.search(str(row.get("full_text") or ""))
            or (
                asks_about_repeal
                and re.search(r"\brevog", str(row.get("full_text") or ""), re.IGNORECASE)
                and _NORMATIVE_CHANGE_EVIDENCE_RE.search(str(row.get("full_text") or ""))
            )
            or (
                preserve_explicit_article_targets
                and _article_key(str(row.get("dispositivo_ref") or ""))
                in requested_protocol_articles
                and _PROTOCOL_DATE_EVIDENCE_RE.search(str(row.get("full_text") or ""))
            )
        ]

    # Identical PDFs may coexist in the archive (for example, one filename
    # with a mistaken year and another with the correct year). Avoid spending
    # the evidence budget on duplicate text for the same legal device; keep the
    # candidate whose recorded identity agrees with its epigraph when possible.
    deduplicated_rows = {}
    for row in rows:
        duplicate_key = (
            row["norma_ref"],
            row["dispositivo_ref"],
            re.sub(r"\s+", " ", _fold(str(row.get("full_text") or ""))).strip(),
        )
        previous = deduplicated_rows.get(duplicate_key)
        if previous is None or (
            previous["coverage"].get("identity_conflict")
            and not row["coverage"].get("identity_conflict")
        ):
            deduplicated_rows[duplicate_key] = row
    rows = list(deduplicated_rows.values())

    rows.sort(
        key=lambda item: (item["similarity_score"], item["norma_ref"], item["dispositivo_ref"]),
        reverse=True,
    )
    if cross_reference_scope:
        # Only literal article-level mentions of the requested target are
        # returned, and source order is preserved. This avoids lexical top-k
        # losing a valid reference because legal citations dominate the query.
        rows.sort(key=lambda item: (item["norma_ref"], item["source_id"], item["_device_order"]))
        rows = rows[: min(max(limit, 32), 100)]
    elif requested_appendix:
        rows.sort(key=lambda item: (item["norma_ref"], item["_device_order"]))
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "requested_appendix": row["dispositivo_ref"],
                "complete": True,
            }
    elif whole_norm_request:
        # A whole-norm request is not constrained by the normal top-k. Small
        # norms return every parsed article. A substantive case/topic qualifier
        # ranks matching provisions within the same context budget; an unscoped
        # overview remains evenly sampled. Both paths disclose incomplete coverage.
        rows.sort(key=lambda item: (item["norma_ref"], item["source_id"], item["_device_order"]))
        topic_tokens = (
            set()
            if query_plan.explicit_target_overview
            else _whole_norm_topic_tokens(question)
        )
        rows, total_articles = _sample_whole_norm_rows(
            rows,
            topic_tokens=topic_tokens,
        )
        selected_articles = len(rows)
        annexes_present = any(row["coverage"].get("annexes_present") for row in rows)
        complete = selected_articles == total_articles and not annexes_present
        selection_strategy = "topic_ranked" if topic_tokens else "distributed"
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "corpus": "acervo histórico local pesquisável",
                "complete": complete,
                "selection_strategy": selection_strategy,
                "annexes_present": annexes_present,
                "selected_articles": selected_articles,
                "total_articles": total_articles,
            }
    elif change_inventory_request:
        # Inventory only clauses that expressly perform a normative action.
        # This avoids lexical top-k dropping a repeal clause when the same act
        # also contains an amendment clause. It does not establish legal effect.
        rows.sort(key=lambda item: (item["norma_ref"], item["source_id"], item["_device_order"]))
        rows, total_change_devices = _sample_whole_norm_rows(rows)
        selected_change_devices = len(rows)
        for row in rows:
            complete_inventory = selected_change_devices == total_change_devices and not row[
                "coverage"
            ].get("annexes_present")
            row["coverage"] = {
                **row["coverage"],
                "inventory_scope": "normative_changes",
                "inventory_selected": selected_change_devices,
                "inventory_total": total_change_devices,
                "inventory_complete": complete_inventory,
                "complete": complete_inventory,
            }
    elif (exact_ref or (requested_norm_title and transition_scope_question)) and not wanted_articles:
        if transition_scope_question:
            # The prior filter already selected only qualifying transition
            # evidence. Do not re-rank it away using generic lexical overlap.
            rows = rows[: max(1, min(limit, 12))]
        elif topic_tokens:
            # A question about a topic within a named law should rank only
            # devices that actually overlap the topic; law identity alone must
            # not make every article look like a high-relevance match.
            phrase_matches = [row for row in rows if row["_topic_phrase_match"]]
            topical_rows = phrase_matches or [row for row in rows if row["_topic_overlap"] >= 0.12]
            if requested_facets:
                facet_rows = [
                    row
                    for row in rows
                    if any(_source_matches_facet(facet, row) for facet in requested_facets)
                ]
                topical_rows = list(
                    {row["citation_id"]: row for row in [*topical_rows, *facet_rows]}.values()
                )
            rows = topical_rows
            if asks_salary_floor:
                explicit_floor_rows = [
                    row
                    for row in rows
                    if _SALARY_FLOOR_EVIDENCE_RE.search(str(row.get("full_text") or ""))
                ]
                # A topical hit on "vencimento básico" alone is not enough to
                # answer a question about its floor. When the source states an
                # explicit minimum rule, prefer only those devices; otherwise
                # preserve ordinary retrieval and let grounding abstain if needed.
                if explicit_floor_rows:
                    rows = explicit_floor_rows
            rows = (
                _select_facet_sources(
                    rows,
                    requested_facets,
                    max(1, min(limit, 12)),
                )
                if requested_facets
                else rows
            )
            rows.sort(
                key=lambda item: (item["_topic_overlap"], item["dispositivo_ref"]), reverse=True
            )
        rows = rows[: max(1, min(max(limit, len(requested_facets)), 12))]
    elif exact_ref and wanted_articles:
        requested = set(wanted_articles)
        rows = [
            row
            for row in rows
            if _article_key(row.get("dispositivo_ref", "")) in requested
            or (
                transition_scope_question
                and (
                    _PROCESS_TRANSITION_EVIDENCE_RE.search(str(row.get("full_text") or ""))
                    or _EFFECTIVE_DATE_OPERATIVE_RE.search(str(row.get("full_text") or ""))
                    or (
                        re.search(r"\brevog", question, re.IGNORECASE)
                        and re.search(r"\brevog", str(row.get("full_text") or ""), re.IGNORECASE)
                        and _NORMATIVE_CHANGE_EVIDENCE_RE.search(
                            str(row.get("full_text") or "")
                        )
                        and _NORMATIVE_REFERENCE_SPAN_RE.search(
                            str(row.get("full_text") or "")
                        )
                    )
                )
            )
        ]
        if article_topic_phrase and not preserve_explicit_article_targets:
            rows = [
                row for row in rows if _supports_article_topic(question, row.get("full_text", ""))
            ]
        article_order = {article: index for index, article in enumerate(wanted_articles)}
        rows.sort(
            key=lambda row: article_order.get(
                _article_key(row.get("dispositivo_ref", "")), len(article_order)
            )
        )
        if transition_scope_question:
            rows.sort(key=lambda row: (row.get("_device_order", 0), row.get("dispositivo_ref", "")))
        found = {_article_key(row.get("dispositivo_ref", "")) for row in rows}
        missing = [article for article in wanted_articles if article not in found]
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "requested_articles": list(wanted_articles),
                "missing_articles": missing,
                "complete": not missing,
            }
        if transition_scope_question:
            # A transition/repeal question needs the requested provision plus
            # the same act's operative commencement and repeal clauses. The
            # generic top-k must not silently discard those evidence roles.
            rows = rows[: min(max(limit, len(rows), 3), 32)]
        else:
            rows = rows[: min(limit, max(len(wanted_articles), 1))]
    elif paired_article_scope:
        if explicit_amendment_scope:
            source_identity, target_identity, target_article = explicit_amendment_scope
            amendment_rows = []
            for row in rows:
                row_identity = _archive_source_norm_identity(row)
                article = _archive_source_article(row)
                role = None
                if row_identity == target_identity and article == target_article:
                    role = "target_provision"
                elif row_identity == source_identity:
                    text = str(row.get("full_text") or "")
                    text_identities = {
                        _reference_identity(reference)
                        for reference in parse_normative_references(text)
                        if reference.year is not None and reference.number
                    }
                    if _text_mentions_norm_identity(text, target_identity):
                        text_identities.add(target_identity)
                    text_articles = {
                        article_key for _position, article_key in _article_reference_mentions(text)
                    }
                    if (
                        target_identity in text_identities
                        and target_article in text_articles
                        and _AMENDMENT_OPERATIVE_CLAUSE_RE.search(text)
                    ):
                        role = "amendment_clause"
                    elif _EFFECTIVE_DATE_OPERATIVE_RE.search(text):
                        role = "amendment_commencement"
                if role:
                    row["coverage"] = {
                        **row["coverage"],
                        "explicit_amendment_scope": True,
                        "amendment_evidence_role": role,
                        "legal_effect_reviewed": False,
                    }
                    amendment_rows.append(row)
            roles = {
                row["coverage"].get("amendment_evidence_role") for row in amendment_rows
            }
            complete_amendment_pair = {
                "target_provision",
                "amendment_clause",
            }.issubset(roles)
            for row in amendment_rows:
                row["coverage"]["complete"] = complete_amendment_pair
            rows = amendment_rows
            rows.sort(
                key=lambda item: (
                    0
                    if item["coverage"].get("amendment_evidence_role") == "amendment_clause"
                    else 1
                    if item["coverage"].get("amendment_evidence_role") == "target_provision"
                    else 2,
                    item["norma_ref"],
                    item["dispositivo_ref"],
                )
            )
        else:
            rows.sort(key=lambda item: (item["norma_ref"], item["dispositivo_ref"]))
            candidate_rows = rows
            rows = rows[: min(max(limit, len(explicit_article_norm_pairs)), 32)]
        if transition_scope_question and not explicit_amendment_scope:
            transition_rows = [
                row
                for row in candidate_rows
                if _PROCESS_TRANSITION_EVIDENCE_RE.search(str(row.get("full_text") or ""))
            ]
            transition_identities = {
                _reference_identity(reference)
                for row in transition_rows
                for reference in parse_normative_references(str(row.get("norma_ref") or ""))
                if reference.year is not None and reference.number
            }
            commencement_rows = []
            for row in candidate_rows:
                identity = next(
                    (
                        _reference_identity(reference)
                        for reference in parse_normative_references(str(row.get("norma_ref") or ""))
                        if reference.year is not None and reference.number
                    ),
                    None,
                )
                if identity in transition_identities and _EFFECTIVE_DATE_OPERATIVE_RE.search(
                    str(row.get("full_text") or "")
                ):
                    commencement_rows.append(row)
            rows = list(
                {str(row.get("citation_id")): row for row in [*rows, *commencement_rows]}.values()
            )
        found_pairs = {
            (
                _reference_identity(reference),
                _article_key(str(row.get("dispositivo_ref") or "")),
            )
            for row in rows
            for reference in parse_normative_references(str(row.get("norma_ref") or ""))
            if reference.year is not None
        }
        missing_pairs = [
            {"normative_identity": list(identity), "article": article}
            for identity, article in explicit_article_norm_pairs
            if (identity, article) not in found_pairs
        ]
        for row in rows:
            row["coverage"] = {
                **row["coverage"],
                "requested_article_norm_pairs": [
                    {"normative_identity": list(identity), "article": article}
                    for identity, article in explicit_article_norm_pairs
                ],
                "missing_article_norm_pairs": missing_pairs,
                "complete": row["coverage"].get("complete", True) and not missing_pairs,
            }
    elif explicit_multi_references and wanted_articles:
        requested = set(wanted_articles)
        rows = [row for row in rows if _article_key(row.get("dispositivo_ref", "")) in requested]
        rows.sort(key=lambda row: (row["norma_ref"], row["dispositivo_ref"]))
        rows = rows[: min(limit, max(len(explicit_multi_references), 1) * len(requested))]
    else:
        if requested_facets:
            # A topic-specific request must not return generic articles merely
            # because one incidental word overlaps. Synonym expansion above
            # broadens candidate discovery; this evidence gate keeps only
            # provisions that actually support at least one requested facet.
            facet_rows = [
                row
                for row in rows
                if any(_source_matches_facet(facet, row) for facet in requested_facets)
            ]
            rows = (
                _select_facet_sources(
                    facet_rows,
                    requested_facets,
                    max(1, min(limit, 12)),
                )
                if facet_rows
                else []
            )
        else:
            focused_rows = [] if wanted_articles else _strong_topic_phrase_rows(question, rows)
            if focused_rows:
                rows = focused_rows[:limit]
            else:
                rows = [row for row in rows if row["similarity_score"] >= 0.12][:limit]
    for row in rows:
        row.pop("_topic_overlap", None)
        row.pop("_topic_phrase_match", None)
        row.pop("_device_order", None)
        row.pop("_identity_support", None)
        row.pop("_title_edition_candidate", None)
        row.pop("_identity_year", None)
    return rows


def _metadata_only_sapl_norma_source(reference) -> dict | None:
    """Resolve one explicit catalog-only norma without treating metadata as law text."""
    if (
        reference is None
        or reference.ambiguous
        or not reference.type_key
        or not reference.number
        or reference.year is None
    ):
        return None

    digits = normalize_number(reference.number)
    if not digits:
        return None
    first_group_length = len(digits) % 3 or 3
    grouped_number = ".".join(
        [
            digits[:first_group_length],
            *(digits[index : index + 3] for index in range(first_group_length, len(digits), 3)),
        ]
    )
    candidates = list(
        Norma.objects.filter(
            ano=reference.year,
            numero__in={reference.number, digits, grouped_number},
            status=Norma.Status.PENDING,
            sapl_id__isnull=False,
            sapl_metadata__has_key="_jurix_source_hash",
            pdf_path="",
            texto_original="",
            texto_consolidado="",
        ).order_by("pk")[:50]
    )
    matches = [
        norma
        for norma in candidates
        if canonical_type(norma.get_tipo_display_name()) == reference.type_key
        and (normalize_number(norma.numero).lstrip("0") or "0") == (digits.lstrip("0") or "0")
    ]
    if len(matches) != 1:
        return None

    norma = matches[0]
    sapl_url = canonical_sapl_url(sapl_id=norma.sapl_id)
    if not sapl_url:
        return None
    sapl_metadata = norma.sapl_metadata if isinstance(norma.sapl_metadata, dict) else {}
    raw_publication_date = sapl_metadata.get("data_publicacao")
    publication_date = None
    if isinstance(raw_publication_date, date):
        publication_date = raw_publication_date.isoformat()
    elif isinstance(raw_publication_date, str):
        candidate_date = raw_publication_date.strip()
        try:
            publication_date = date.fromisoformat(candidate_date[:10]).isoformat()
        except ValueError:
            try:
                publication_date = datetime.strptime(candidate_date, "%d/%m/%Y").date().isoformat()
            except ValueError:
                publication_date = None
    display_type = norma.get_tipo_display_name()
    norma_ref = f"{display_type} nº {norma.numero}/{norma.ano}"
    return {
        "citation_id": f"sapl:norma-catalog:{norma.sapl_id}",
        "citation_index": 1,
        "citation_label": f"{norma_ref} — cadastro no SAPL",
        "norma_ref": norma_ref,
        "source_kind": "sapl_normative_catalog",
        "source_type": "Cadastro oficial SAPL — somente metadados, sem texto legal integrado",
        "contribution": "Identifica o ato; não comprova conteúdo, vigência ou histórico de alterações",
        "evidence_scope": "official_normative_catalog_metadata",
        "sapl_url": sapl_url,
        "data_publicacao": publication_date,
        "metadata_only": True,
        "similarity_score": 0,
    }


def _official_sapl_publication_source(reference) -> dict | None:
    """Return publication-date metadata for one unambiguous SAPL act identity."""
    if (
        reference is None
        or reference.ambiguous
        or not reference.type_key
        or not reference.number
        or reference.year is None
    ):
        return None

    digits = normalize_number(reference.number)
    candidates = list(
        Norma.objects.filter(ano=reference.year, sapl_id__isnull=False)
        .order_by("pk")[:500]
    )
    matches = [
        norma
        for norma in candidates
        if not (norma.identity_json or {}).get("synthetic_fixture")
        and canonical_type(norma.get_tipo_display_name()) == reference.type_key
        and (normalize_number(norma.numero).lstrip("0") or "0")
        == (digits.lstrip("0") or "0")
        and canonical_sapl_url(sapl_id=norma.sapl_id)
    ]
    if len(matches) != 1:
        return None

    norma = matches[0]
    metadata = norma.sapl_metadata if isinstance(norma.sapl_metadata, dict) else {}
    raw_date = norma.data_publicacao or metadata.get("data_publicacao")
    publication_date = None
    if isinstance(raw_date, datetime):
        publication_date = raw_date.date()
    elif isinstance(raw_date, date):
        publication_date = raw_date
    elif isinstance(raw_date, str):
        try:
            publication_date = date.fromisoformat(raw_date.strip()[:10])
        except ValueError:
            try:
                publication_date = datetime.strptime(raw_date.strip(), "%d/%m/%Y").date()
            except ValueError:
                publication_date = None
    if publication_date is None:
        return None

    display_type = norma.get_tipo_display_name()
    norma_ref = f"{display_type} nº {norma.numero}/{norma.ano}"
    vehicle = str(metadata.get("veiculo_publicacao") or "").strip()
    vehicle_note = f" Veículo registrado: {vehicle}." if vehicle else ""
    return {
        "citation_id": f"sapl:publication-metadata:{norma.sapl_id}",
        "citation_label": f"{norma_ref} — data de publicação no SAPL",
        "norma_ref": norma_ref,
        "dispositivo_ref": "Metadado de publicação",
        "source_kind": "sapl_publication_metadata",
        "source_type": "Cadastro normativo oficial SAPL — metadado, sem texto legal",
        "evidence_scope": "official_publication_metadata",
        "contribution": "O cadastro registra a data; confira a edição do Diário Oficial.",
        "full_text": (
            f"O cadastro oficial do SAPL registra publicação em "
            f"{publication_date.strftime('%d/%m/%Y')}.{vehicle_note}"
        ),
        "data_publicacao": publication_date.isoformat(),
        "source_url": canonical_sapl_url(sapl_id=norma.sapl_id),
        "sapl_url": canonical_sapl_url(sapl_id=norma.sapl_id),
        "metadata_only": True,
        "similarity_score": 0,
    }


def _vacatio_effective_date(commencement_text: str, publication_date: date) -> date | None:
    """Calculate the day after an explicitly stated whole-day publication vacatio."""
    if not _EFFECTIVE_DATE_OPERATIVE_RE.search(commencement_text):
        return None
    match = re.search(
        r"\b(?P<days>\d{1,4})\s*(?:\(\s*[a-zçãõ]+\s*\))?\s*dias?\s+"
        r"ap[oó]s\s+(?:a\s+data\s+de\s+)?(?:sua\s+)?publica[cç][aã]o\b",
        commencement_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        days = int(match.group("days"))
    except (TypeError, ValueError):
        return None
    if days < 1:
        return None
    return publication_date + timedelta(days=days)


def _vacatio_counting_rule_source() -> dict:
    return {
        "citation_id": "official:lc95-art8-paragraph1",
        "citation_label": "Lei Complementar nº 95/1998, Art. 8º, § 1º",
        "norma_ref": "Lei Complementar nº 95/1998",
        "dispositivo_ref": "Art. 8º, § 1º",
        "source_kind": "official_general_legislation",
        "source_type": "Legislação federal oficial — critério de contagem de vacatio legis",
        "evidence_scope": "official_vacatio_counting_rule",
        "contribution": "Expõe o critério de contagem usado no cálculo derivado.",
        "full_text": (
            "A contagem inclui a data da publicação e o último dia do prazo; a lei entra em "
            "vigor no dia seguinte à consumação integral."
        ),
        "source_url": "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp95.htm",
        "metadata_only": False,
        "similarity_score": 0,
    }


def _archive_transition_publication_sources(question: str, results: list[dict]) -> list[dict]:
    """Resolve publication/effectiveness evidence for a fully matched transition chain.

    This intentionally adds sources only when the deterministic transition
    synthesis already has the repeal, transition, and prior-device evidence.
    The SAPL date is used only to locate the official DOM issue; the DOM's exact
    commencement article must independently match before a date is calculated.
    """
    if _archive_transition_synthesis(question, results) is None:
        return []

    commencement_sources = [
        source
        for source in results
        if source.get("source_kind") == "archive"
        and source.get("citation_id")
        and _EFFECTIVE_DATE_OPERATIVE_RE.search(str(source.get("full_text") or ""))
        and re.search(
            r"\b\d{1,4}\s*(?:\(\s*[a-zçãõ]+\s*\))?\s*dias?\s+ap[oó]s\s+(?:a\s+data\s+de\s+)?(?:sua\s+)?publica[cç][aã]o\b",
            str(source.get("full_text") or ""),
            re.IGNORECASE,
        )
    ]
    if len(commencement_sources) != 1:
        return []

    commencement = commencement_sources[0]
    reference_matches = [
        reference
        for reference in parse_normative_references(
            str(commencement.get("norma_ref") or commencement.get("citation_label") or "")
        )
        if reference.year is not None and reference.number and not reference.ambiguous
    ]
    if len(reference_matches) != 1:
        return []

    publication_source = _official_sapl_publication_source(reference_matches[0])
    if not publication_source:
        return []
    publication_date = publication_source.get("data_publicacao")
    if not publication_date:
        return []

    act_identity = _reference_identity(reference_matches[0])
    explicit_targets = {
        (identity, _article_key(article))
        for identity, article in _explicit_article_norm_pairs(question)
    }
    article_targets = [
        str(source.get("dispositivo_ref") or "")
        for source in results
        if source.get("source_kind") == "archive"
        and source.get("citation_id")
        and _archive_source_norm_identity(source) == act_identity
        and (act_identity, _article_key(str(source.get("dispositivo_ref") or "")))
        in explicit_targets
    ]
    article_targets.append(str(commencement.get("dispositivo_ref") or ""))
    article_targets = list(dict.fromkeys(article_targets))
    if len(article_targets) > 8:
        return []
    gazette_sources = _official_dom_articles_sources(
        reference_matches[0], article_targets, str(publication_date)
    )
    if len(gazette_sources) != len(article_targets):
        return []

    gazette_by_article = {
        _article_key(source.get("dispositivo_ref")): source for source in gazette_sources
    }
    commencement_article_key = _article_key(str(commencement.get("dispositivo_ref") or ""))
    gazette_commencement = gazette_by_article.get(commencement_article_key)
    if (
        gazette_commencement is None
        or gazette_commencement.get("data_publicacao") != str(publication_date)
        or not _EFFECTIVE_DATE_OPERATIVE_RE.search(str(gazette_commencement.get("full_text") or ""))
    ):
        return []

    try:
        published = date.fromisoformat(str(publication_date)[:10])
    except ValueError:
        return []
    effective_date = _vacatio_effective_date(str(gazette_commencement["full_text"]), published)
    if not effective_date:
        return []

    existing_ids = {str(source.get("citation_id") or "") for source in results}
    additions = [*gazette_sources, _vacatio_counting_rule_source()]
    return [
        source
        for source in additions
        if source.get("citation_id") and str(source["citation_id"]) not in existing_ids
    ]


def _official_dom_articles_sources(
    reference, article_targets: list[str], publication_date: str | None
) -> list[dict]:
    """Fetch exact articles from one official DOM issue in a single download.

    It resolves the issue from the SAPL record's publication date, verifies the
    act heading inside the official gazette PDF, and returns only requested
    articles. Any ambiguity, unavailable date, or parse failure returns no source.
    """
    if (
        reference is None
        or reference.ambiguous
        or not reference.type_key
        or not reference.number
        or reference.year is None
        or not article_targets
        or not publication_date
    ):
        return []
    try:
        published = date.fromisoformat(str(publication_date)[:10])
        if published.year != reference.year:
            return []
        from src.clients.dom_natal.client import DomNatalClient
        from src.processing.gazette_act_candidates import find_gazette_act_candidates
        from src.processing.legal_parser import LegalTextParser

        client = DomNatalClient(timeout=(3.0, 8.0))
        try:
            editions = client.list_editions(month=published.month, year=published.year)
            same_day = [edition for edition in editions if edition.publication_date == published]
            if not same_day:
                return []
            import pymupdf

            exact_act_matches = []
            for edition in same_day:
                downloaded = client.download_edition(edition)
                pdf = pymupdf.open(stream=downloaded.content, filetype="pdf")
                try:
                    if not 1 <= len(pdf) <= 500:
                        return []
                    pages = [pdf.load_page(index).get_text() for index in range(len(pdf))]
                finally:
                    pdf.close()
                segmented = find_gazette_act_candidates(pages, max_pages=500)
                matching_acts = [
                    act
                    for act in segmented.candidates
                    if act.type_key_candidate == reference.type_key
                    and (normalize_number(act.number_candidate or "").lstrip("0") or "0")
                    == (normalize_number(reference.number).lstrip("0") or "0")
                    and act.year_candidate == reference.year
                ]
                if segmented.truncated:
                    return []
                exact_act_matches.extend((edition, act, pages) for act in matching_acts)
        finally:
            client.session.close()
        if len(exact_act_matches) != 1:
            return []

        selected_edition, act, pages = exact_act_matches[0]
        act_parts = []
        page_offsets = []
        offset = 0
        for span in act.spans:
            if act_parts:
                act_parts.append("\f")
                offset += 1
            page_text = pages[span.page - 1]
            part = page_text[span.start_offset : span.end_offset]
            page_offsets.append((span.page, offset, offset + len(part)))
            act_parts.append(part)
            offset += len(part)
        act_text = "".join(act_parts)
        extracted_articles = LegalTextParser.extract_articles(act_text)
        requested_articles = []
        for article_target in dict.fromkeys(article_targets):
            wanted_key = _article_key(article_target)
            matching_articles = [
                article
                for article in extracted_articles
                if _article_key(article.get("numero")) == wanted_key
            ]
            if len(matching_articles) != 1:
                return []
            requested_articles.append(matching_articles[0])
        display_types = {
            "lei": "Lei Ordinária",
            "lei_complementar": "Lei Complementar",
            "lei_organica": "Lei Orgânica",
            "lei_promulgada": "Lei Promulgada",
            "decreto": "Decreto",
            "decreto_lei": "Decreto-Lei",
            "decreto_legislativo": "Decreto Legislativo",
            "resolucao": "Resolução",
            "portaria": "Portaria",
        }
        display_number_digits = normalize_number(reference.number)
        first_group_length = len(display_number_digits) % 3 or 3
        display_number = ".".join(
            [
                display_number_digits[:first_group_length],
                *(
                    display_number_digits[index : index + 3]
                    for index in range(first_group_length, len(display_number_digits), 3)
                ),
            ]
        )
        norm_ref = (
            f"{display_types.get(reference.type_key, 'Norma')} nº {display_number}/{reference.year}"
        )
        sources = []
        for article in requested_articles:
            article_text = f"Art. {article['numero']} {article['texto']}".strip()
            article_page = next(
                (page for page, start, end in page_offsets if start <= article["start_pos"] < end),
                act.heading_page,
            )
            citation_id = (
                "dom:"
                + hashlib.sha256(
                    f"{selected_edition.identity}:{act.heading_start_offset}:{article['start_pos']}".encode()
                ).hexdigest()[:24]
            )
            sources.append({
                "citation_id": citation_id,
                "citation_label": f"{norm_ref}, Art. {article['numero']}",
                "norma_ref": norm_ref,
                "dispositivo_ref": f"Art. {article['numero']}",
                "full_text": article_text,
                "text": article_text[:200] + ("..." if len(article_text) > 200 else ""),
                "evidence_text": article_text,
                "similarity_score": 1.0,
                "contribution": "Texto localizado na edição oficial do Diário Oficial do Município; extração automatizada, confira o PDF.",
                "source_type": "Diário Oficial de Natal — extração automatizada não revisada",
                "source_kind": "official_gazette_extraction",
                "retrieval_strategy": "exact_publication_day_and_act_identity",
                "evidence_scope": "official_gazette_unreviewed_extraction",
                "pdf_url": selected_edition.official_url,
                "page": article_page,
                "data_publicacao": published.isoformat(),
                "temporal_status": "data_indeterminada",
                "coverage": {
                    "extraction_status": "automated_unreviewed",
                    "act_identity_match": True,
                    "annexes_included_in_article_evidence": False,
                },
            })
        return sources
    except Exception:
        # Network, PDF, or parser failures must preserve the existing safe abstention.
        return []


def _official_dom_article_source(reference, article_target: str, publication_date: str | None):
    """Fetch one exact article from its official DOM issue, without persisting it."""
    sources = _official_dom_articles_sources(reference, [article_target], publication_date)
    return sources[0] if len(sources) == 1 else None


def _supplement_missing_explicit_official_articles(
    question: str, results: list[dict]
) -> list[dict]:
    """Recover only explicitly paired, missing article references from the official DOM.

    This is a narrow fallback for amendment/repeal questions where local RAG
    returned some evidence but omitted a specifically named device. SAPL must
    resolve one exact act identity and its publication date, and the DOM parser
    must match that act/article in the corresponding official issue. The
    returned text remains an unreviewed extraction; it does not establish legal
    effect, currentness, or completeness of a normative chain.
    """
    pairs = _explicit_article_norm_pairs(question)
    if len(pairs) < 3 or len({identity for identity, _article in pairs}) < 2:
        return []

    references_by_identity: dict[tuple[str, str, int | None], object] = {}
    for match in _NORMATIVE_REFERENCE_SPAN_RE.finditer(question or ""):
        reference = next(
            (
                item
                for item in parse_normative_references(match.group(0))
                if item.year is not None and item.number and not item.ambiguous
            ),
            None,
        )
        if reference is not None:
            references_by_identity.setdefault(_reference_identity(reference), reference)

    existing = {
        (_archive_source_norm_identity(source), _archive_source_article(source))
        for source in results
        if source.get("citation_id")
    }
    additions = []
    seen = set(existing)
    for identity, article in pairs:
        key = (identity, _article_key(article))
        if key in seen:
            continue
        reference = references_by_identity.get(identity)
        if reference is None:
            continue
        publication_source = _official_sapl_publication_source(reference)
        publication_date = (
            publication_source.get("data_publicacao") if publication_source else None
        )
        if not publication_date:
            continue
        source = _official_dom_article_source(reference, article, str(publication_date))
        if not source or _archive_source_norm_identity(source) != identity:
            continue
        if _archive_source_article(source) != key[1] or not source.get("citation_id"):
            continue
        additions.append(source)
        seen.add(key)
    return additions


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
                "corpus": "acervo histórico local pesquisável",
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

    from src.processing.sapl_matter_lookup import (
        lookup_explicit_matter_sources,
        lookup_related_matter_result,
        parse_explicit_matter_references,
    )

    explicit_proposal_text_request = bool(
        parse_explicit_matter_references(question) and _PROPOSED_WORDING_REQUEST_RE.search(question)
    )
    matter_sources = (
        lookup_explicit_matter_sources(question) if explicit_proposal_text_request else []
    )
    if explicit_proposal_text_request and not matter_sources:
        answer = (
            "Não foi possível confirmar a redação proposta em uma fonte oficial verificável. "
            "Confira o número e o ano na ficha da matéria no SAPL, especialmente o anexo "
            "‘Texto Original’. Sem esse documento, não vou inferir o conteúdo nem tratar a "
            "proposta como lei vigente."
        )
        retrieval_ms = round((time.perf_counter() - started) * 1000)
        yield from insufficient_evidence_events(
            answer=answer,
            reason_code="explicit_matter_source_unavailable",
            coverage={
                "scope": "explicit_legislative_matter",
                "source_lookup_enabled": bool(
                    getattr(settings, "SAPL_MATTER_LOOKUP_ENABLED", False)
                ),
                "unrelated_archive_search_skipped": True,
            },
            retrieval_ms=retrieval_ms,
            total_before_done_ms=lambda: round((time.perf_counter() - started) * 1000),
        )
        return

    # A request for a bill's proposed wording is scoped to that exact public
    # matter. Searching and parsing unrelated archive PDFs first can take minutes
    # and cannot supply the bill's original text.
    results = (
        []
        if explicit_proposal_text_request
        else retrieve_archive_evidence(question, limit=max(k, 8))
    )
    retrieval_ms = round((time.perf_counter() - started) * 1000)
    query_plan = classify_normative_query(question)
    explicit_transition_chain = (
        len(_explicit_article_norm_pairs(question)) >= 3
        and len({identity for identity, _article in _explicit_article_norm_pairs(question)}) >= 2
        and bool(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question))
    )
    if query_plan.relation_intent in {"modification", "mixed"} or explicit_transition_chain:
        results.extend(_supplement_missing_explicit_official_articles(question, results))
    if not explicit_proposal_text_request:
        matter_sources = lookup_explicit_matter_sources(question)
    supplemental_matter_sources = []
    related_matter_lookup_used = False
    related_matter_status = None
    exact_article_lookup = (
        query_plan.relation_intent is None
        and query_plan.kind == "provision"
        and len(query_plan.article_targets) == 1
        and query_plan.reference is not None
        and query_plan.reference.year is not None
        and not query_plan.reference.ambiguous
    )
    explicit_legislative_matter_query = bool(_LEGISLATIVE_MATTER_QUERY_RE.search(question))
    if (
        not matter_sources
        and explicit_legislative_matter_query
        and (query_plan.relation_intent in {"modification", "mixed"} or exact_article_lookup)
    ):
        related_lookup = lookup_related_matter_result(
            question, include_exact_article=exact_article_lookup
        )
        matter_sources = list(related_lookup.sources)
        related_matter_status = related_lookup.status
        related_matter_lookup_used = True
    if matter_sources and exact_article_lookup and related_matter_lookup_used:
        # A proposal that mentions the same article is useful version-check
        # context, but must not replace an answer to the article's substance.
        # Keep it as a separately cited supplement while the local provision
        # remains the evidence used for the legal explanation.
        supplemental_matter_sources = matter_sources
        matter_sources = []
        if related_matter_status == "searched":
            # The completed SAPL search did return candidates; the generic
            # empty-result disclosure would otherwise contradict the sources.
            related_matter_status = None
    if matter_sources:
        # This deterministic path reports only the official matter record.
        # It deliberately does not treat a proposal's ementa/status as law.
        article_norm_pairs = _explicit_article_norm_pairs(question)
        archive_sources = _matching_archive_article_sources(article_norm_pairs, results)
        public_matter_sources = [
            {key: value for key, value in source.items() if not key.startswith("_")}
            for source in matter_sources
        ]
        original_document_sources = [
            source["_original_document"]
            for source in matter_sources
            if isinstance(source.get("_original_document"), dict)
        ]
        display_sources = [
            *archive_sources,
            *public_matter_sources,
            *original_document_sources,
        ]
        original_document_indexes = {
            str(source.get("citation_id")): len(archive_sources)
            + len(public_matter_sources)
            + index
            + 1
            for index, source in enumerate(original_document_sources)
        }
        if query_plan.relation_intent in {"modification", "mixed"} and query_plan.article_targets:
            lines = [
                "Com as evidências disponíveis, não foi possível confirmar se o dispositivo "
                "consultado foi alterado ou revogado. A extração do PDF local ainda está "
                "pendente de revisão, e os registros do SAPL são matérias legislativas que, "
                "por si, não comprovam promulgação ou vigência de uma alteração.",
                "Encontrei estes registros oficiais relacionados no SAPL:",
            ]
        elif query_plan.relation_intent in {"modification", "mixed"}:
            lines = [
                "A busca por ementas do SAPL encontrou registros que mencionam a norma. "
                "Essa pesquisa não é um inventário exaustivo: atos que não mencionem a lei "
                "na ementa podem não aparecer, e a associação não comprova que produziram "
                "alteração normativa.",
                "Registros oficiais localizados no SAPL:",
            ]
        else:
            lines = ["Encontrei registros oficiais das matérias no SAPL:"]
        claims = []
        for index, source in enumerate(archive_sources, start=1):
            label = source.get("citation_label") or (
                f'{source.get("norma_ref", "Norma")}, {source.get("dispositivo_ref", "dispositivo")}'
            )
            excerpt = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
            lines.append(
                f"No PDF local pendente de revisão, {label}, o trecho extraído diz: “{excerpt}” [[{index}]]."
            )
            lines.append(
                "Essa transcrição ainda requer revisão humana e não confirma a redação oficial vigente."
            )
            claims.append(
                {
                    "claim": f"O PDF local pendente contém o trecho extraído de {label}.",
                    "supported": True,
                    "citation_indexes": [index],
                }
            )

        next_index = len(archive_sources) + 1
        for matter_offset, (raw_source, source) in enumerate(
            zip(matter_sources, public_matter_sources, strict=True)
        ):
            index = next_index + matter_offset
            title = source["citation_label"]
            ementa = source["full_text"]
            if source.get("source_kind") == "sapl_matter_original_pdf":
                proposed_text = re.sub(r"\s+", " ", str(ementa or "")).strip()
                lines.append(
                    f"O PDF oficial do texto original do projeto apresenta, como proposta, "
                    f"“{proposed_text}” [[{index}]]. Esse trecho não comprova aprovação, "
                    "promulgação, vigência ou efeito jurídico."
                )
                claims.append(
                    {
                        "claim": f"O texto proposto consta no PDF oficial: {title}.",
                        "supported": bool(proposed_text),
                        "citation_indexes": [index],
                    }
                )
                continue
            status = source["status_label"]
            result = source.get("matter_result")
            publication_date = source.get("data_publicacao")
            matter_summary = f"**{title}**: {ementa} [[{index}]]. Situação no SAPL: {status}."
            relation_label = str(source.get("relation_label") or "").strip()
            if relation_label:
                matter_summary = f"A ementa da matéria menciona {relation_label}: {matter_summary}"
            updated_at = str(
                source.get("matter_updated_at_label") or source.get("matter_updated_at") or ""
            ).strip()
            if updated_at:
                matter_summary += (
                    f" Última atualização do cadastro informada pelo SAPL: {updated_at}."
                )
            consulted_at_label = str(source.get("consulted_at_label") or "").strip()
            if consulted_at_label:
                matter_summary += (
                    f" Consulta feita ao SAPL em {consulted_at_label} (horário local); "
                    "isso não é a data de atualização do cadastro."
                )
            if result:
                matter_summary += f" Resultado registrado: {result}."
            if publication_date:
                matter_summary += f" Data de publicação registrada: {publication_date}."
            if not result and not publication_date:
                matter_summary += " Resultado e data de publicação não informados no cadastro."
            lines.append(matter_summary)
            if _PROPOSED_WORDING_REQUEST_RE.search(question):
                original_document = raw_source.get("_original_document")
                if original_document and original_document.get("full_text"):
                    document_index = original_document_indexes.get(
                        str(original_document.get("citation_id"))
                    )
                    proposed_wording = re.sub(
                        r"\s+", " ", str(original_document["full_text"])
                    ).strip()
                    lines.append(
                        "O documento Texto Original anexado à proposição apresenta a redação "
                        f"proposta: “{proposed_wording}” [[{document_index}]]. "
                        "Esse texto é uma proposta legislativa, não uma norma promulgada nem "
                        "prova de vigência."
                    )
                    claims.append(
                        {
                            "claim": "O texto proposto consta no documento original da matéria SAPL.",
                            "supported": True,
                            "citation_indexes": [document_index],
                        }
                    )
                else:
                    lines.append(
                        "A consulta SAPL usada aqui retornou a ementa e metadados, mas não o texto "
                        "integral do projeto. Portanto, não é possível confirmar a redação proposta "
                        "do dispositivo com esta evidência; confira eventual documento anexado na "
                        "ficha oficial antes de citar o texto."
                    )
            claims.append(
                {
                    "claim": f"Registro SAPL localizado para {title}; situação: {status}.",
                    "supported": True,
                    "citation_indexes": [index],
                }
            )
        if article_norm_pairs and not archive_sources:
            requested_labels = ", ".join(
                f"Art. {article} da norma mencionada" for _identity, article in article_norm_pairs
            )
            lines.append(
                f"Esta busca não recuperou um excerto local associado com segurança a {requested_labels}; "
                "isso não prova que o dispositivo inexista nem que esteja revogado."
            )
        lines.append(
            "Esses dados descrevem uma matéria legislativa e seu cadastro no SAPL; "
            "não demonstram, por si, aprovação, promulgação, vigência ou validade de uma norma."
        )
        answer = "\n\n".join(lines)
        yield {
            "event": "sources",
            "sources": display_sources,
            "confidence": None,
            "cached": False,
            "retrieval_strategy": "sapl_explicit_matter_reference_with_archive_article_match",
            "coverage": {
                "corpus": "registros SAPL e PDFs do acervo QA",
                "sources_retrieved": len(display_sources),
                "matched_archive_articles": len(archive_sources),
                "requested_article_norm_pairs": len(article_norm_pairs),
            },
        }
        yield {"event": "status", "status": "grounding"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": display_sources,
            "grounded": True,
            "source_only": True,
            "reason_code": "sapl_explicit_matter_reference_with_archive_article_match",
            "grounding": {"grounded": True, "claims": claims, "failed_claims": []},
            "coverage": {
                "coverage_status": "explicit_archive_article_matches_and_sapl_matter_records"
                if archive_sources
                else "sapl_matter_records_only",
                "temporal_scope_available": False,
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        yield {"event": "status", "status": "completed"}
        return
    query_plan = classify_normative_query(question)
    if (
        query_plan.article_targets
        and _article_topic_phrase(question)
        and not (
            len(_explicit_article_norm_pairs(question))
            == len(_article_reference_mentions(question))
            and len(_explicit_article_norm_pairs(question)) > 1
            and not _cross_reference_scan_scope(question)
            and not _CONTEXTUAL_MULTI_ARTICLE_TOPIC_RE.search(question)
        )
    ):
        results = [
            source
            for source in results
            if _supports_article_topic(question, source.get("full_text", ""))
        ]
    relation_candidate_sources = []
    explicit_references = [
        reference
        for reference in parse_normative_references(question)
        if reference.year is not None and reference.number and reference.type_key
    ]
    explicit_act_pair_relation = bool(
        getattr(settings, "JURIX_BUILD_PROFILE", "") == "qa"
        and query_plan.relation_intent in {"modification", "mixed"}
        and not query_plan.article_targets
        and len(explicit_references) == 2
    )
    if (
        getattr(settings, "JURIX_BUILD_PROFILE", "") == "qa"
        and query_plan.relation_intent in {"modification", "mixed"}
        and explicit_references
    ):
        if query_plan.article_targets:
            for reference in explicit_references:
                relation_candidate_sources.extend(
                    _archive_relation_candidate_sources(reference, query_plan.article_targets)
                )
        elif explicit_act_pair_relation:
            source_reference, target_reference = explicit_references
            relation_candidate_sources.extend(
                _archive_relation_candidate_sources(
                    target_reference,
                    (),
                    source_reference=source_reference,
                )
            )
            relation_candidate_sources.extend(
                _archive_relation_candidate_sources(
                    source_reference,
                    (),
                    source_reference=target_reference,
                )
            )
        relation_candidate_sources = _dedupe_relation_candidate_sources(
            relation_candidate_sources
        )
        original_device_sources = []
        for source in relation_candidate_sources:
            relation = source.get("relation_candidate") or {}
            target = relation.get("target_identity") or {}
            article_number = target.get("structural_article_number")
            if not article_number:
                article_number = (
                    target.get("structural_number")
                    if target.get("structural_type") == "artigo"
                    else None
                )
            try:
                target_year = int(target.get("year"))
            except (TypeError, ValueError):
                continue
            if not article_number:
                continue
            target_reference = SimpleNamespace(
                type_key=str(target.get("type") or ""),
                number=str(target.get("number") or ""),
                year=target_year,
                ambiguous=False,
            )
            original_device_sources.extend(
                _target_normative_device_sources(
                    target_reference,
                    (str(article_number),),
                    structural_type=str(target.get("structural_type") or ""),
                    structural_number=str(target.get("structural_number") or ""),
                )
            )
        relation_candidate_sources.extend(original_device_sources)
    if explicit_act_pair_relation and relation_candidate_sources:
        def source_matches_pair(source):
            coverage = source.get("coverage") or {}
            if coverage.get("identity_conflict") is True:
                return False
            epigraph_status = coverage.get("epigraph_identity_status")
            if epigraph_status and epigraph_status != "match":
                return False
            for reference in explicit_references:
                for source_reference in parse_normative_references(
                    str(source.get("norma_ref") or source.get("citation_label") or "")
                ):
                    if (
                        source_reference.type_key == reference.type_key
                        and normalize_number(source_reference.number).lstrip("0")
                        == normalize_number(reference.number).lstrip("0")
                        and source_reference.year == reference.year
                    ):
                        return True
            return False

        temporal_context_requested = bool(
            re.search(
                r"\b(?:transi[cç][aã]o|vig[eê]ncia|vigente|entrada\s+em\s+vigor|"
                r"data\s+de\s+efic[aá]cia|prazo\s+de\s+vac[aâ]ncia)\b",
                question,
                re.IGNORECASE,
            )
        )
        candidate_source_reference = None
        explicit_pair_identities = {
            _reference_identity(reference)
            for reference in explicit_references
            if reference.year is not None
        }

        def source_supports_pair_scope(source):
            text = str(source.get("full_text") or "")
            if not text or not source_matches_pair(source):
                return False
            is_transition = bool(_PROCESS_TRANSITION_EVIDENCE_RE.search(text))
            is_commencement = bool(
                re.search(
                    r"\b(?:entra\s+em\s+vigor|vig[eê]ncia|noventa\s+dias|"
                    r"\d+\s*\(\s*noventa\s*\))\b",
                    text,
                    re.IGNORECASE,
                )
            )
            has_relation_verb = bool(
                re.search(
                    r"\b(?:ficam?\s+revogad[oa]s?|revogad[oa]s?|alterad[oa]s?|"
                    r"d[aá]\s+nova\s+reda[cç][aã]o|passa\s+a\s+vigorar)\b",
                    text,
                    re.IGNORECASE,
                )
            )
            names_other_act_in_pair = any(
                _reference_identity(reference) in explicit_pair_identities
                and _reference_identity(reference)
                != next(
                    (
                        _reference_identity(source_reference)
                        for source_reference in parse_normative_references(
                            str(source.get("norma_ref") or source.get("citation_label") or "")
                        )
                        if source_reference.year is not None
                    ),
                    None,
                )
                for reference in parse_normative_references(text)
                if reference.year is not None
            )
            return is_transition or is_commencement or (
                has_relation_verb and names_other_act_in_pair
            )

        pair_sources = [
            source
            for source in results
            if source_matches_pair(source)
            and (
                not temporal_context_requested
                or source_supports_pair_scope(source)
            )
        ][:6]
        if temporal_context_requested:
            # A relation question often needs the enactment's own transition
            # and commencement clauses as well as the repeal candidate. Do a
            # second, identity-constrained archive search instead of letting
            # the original lexical top-k silently define that scope.
            candidate_source_reference = next(
                (
                    reference
                    for candidate in relation_candidate_sources
                    for reference in parse_normative_references(
                        str(candidate.get("norma_ref") or "")
                    )
                    if reference.year is not None and not reference.ambiguous
                ),
                None,
            )
            if candidate_source_reference is not None:
                source_label = next(
                    (
                        str(candidate.get("norma_ref"))
                        for candidate in relation_candidate_sources
                        if candidate.get("norma_ref")
                    ),
                    "a norma identificada na pista de relação",
                )
                targeted_questions = (
                    f"Quais dispositivos da {source_label} tratam da transição de processos "
                    "sem despacho decisório?",
                    f"Qual dispositivo da {source_label} determina quando esta Lei Complementar "
                    "entra em vigor e qual é o prazo contado da publicação?",
                )
                for targeted_question in targeted_questions:
                    for source in retrieve_archive_evidence(targeted_question, limit=12):
                        if not source.get("citation_id") or not source.get("full_text"):
                            continue
                        if not source_matches_pair(source):
                            continue
                        text = str(source.get("full_text") or "")
                        relevant_transition = bool(_PROCESS_TRANSITION_EVIDENCE_RE.search(text))
                        relevant_commencement = bool(
                            re.search(
                                r"\b(?:entra\s+em\s+vigor|vig[eê]ncia|noventa\s+dias|"
                                r"\d+\s*\(\s*noventa\s*\))\b",
                                text,
                                re.IGNORECASE,
                            )
                        )
                        if not (relevant_transition or relevant_commencement):
                            continue
                        if not any(
                            existing.get("citation_id") == source.get("citation_id")
                            for existing in pair_sources
                        ):
                            pair_sources.append(source)
            # When the question describes a works/construction licensing case,
            # retrieve the operative historical provision from the explicitly
            # named target act. Generic semantic top-k tends to return its
            # definitions article instead. Keep this expansion narrow: exact
            # act identity, matching epigraph, and text that actually connects
            # a work/service starting to municipal licensing or a permit.
            work_licensing_case = bool(
                re.search(r"\blicenciamento\b", question, re.IGNORECASE)
                and re.search(r"\b(?:obras?|edifica[cç][õo]es?)\b", question, re.IGNORECASE)
            )
            target_identity_data = next(
                (
                    (candidate.get("relation_candidate") or {}).get("target_identity") or {}
                    for candidate in relation_candidate_sources
                    if (candidate.get("relation_candidate") or {}).get("target_identity")
                ),
                {},
            )
            target_type = str(target_identity_data.get("type") or "")
            target_number = str(target_identity_data.get("number") or "")
            try:
                target_year = int(target_identity_data.get("year"))
            except (TypeError, ValueError):
                target_year = None
            if work_licensing_case and target_type in _TYPE_LABELS and target_number and target_year:
                normalized_target_number = (
                    normalize_number(target_number).lstrip("0") or "0"
                )
                target_norm_label = (
                    f"{_TYPE_LABELS[target_type]} nº "
                    f"{normalized_target_number}/{target_year}"
                )
                targeted_question = (
                    f"Qual dispositivo da {target_norm_label} estabelece quando uma obra ou serviço "
                    "pode ser iniciado após obter licenciamento municipal ou Alvará de construção?"
                )
                for source in retrieve_archive_evidence(targeted_question, limit=10):
                    if not source.get("citation_id") or not source.get("full_text"):
                        continue
                    if not source_matches_pair(source):
                        continue
                    source_is_target_act = any(
                        _reference_identity(source_reference) == (
                            target_type,
                            normalized_target_number,
                            target_year,
                        )
                        for source_reference in parse_normative_references(
                            str(source.get("norma_ref") or source.get("citation_label") or "")
                        )
                        if source_reference.year is not None
                    )
                    source_text = str(source.get("full_text") or "")
                    work_start_rule = bool(
                        re.search(
                            r"\b(?:obra|servi[cç]o|edifica[cç][aã]o)\b.{0,240}"
                            r"\b(?:iniciad[oa]|come[cç]ar|in[ií]cio)\b",
                            source_text,
                            re.IGNORECASE | re.DOTALL,
                        )
                        and re.search(
                            r"\b(?:licenciamento|licen[cç]a|alvar[aá])\b",
                            source_text,
                            re.IGNORECASE,
                        )
                    )
                    if not (source_is_target_act and work_start_rule):
                        continue
                    if not any(
                        existing.get("citation_id") == source.get("citation_id")
                        for existing in pair_sources
                    ):
                        pair_sources.append(source)
        publication_metadata_source = None
        vacatio_rule_source = None
        derived_effective_date = None
        commencement_for_calculation = next(
            (
                source
                for source in pair_sources
                if _EFFECTIVE_DATE_OPERATIVE_RE.search(
                    str(source.get("full_text") or "")
                )
            ),
            None,
        )
        if (
            temporal_context_requested
            and candidate_source_reference is not None
            and commencement_for_calculation
            and commencement_for_calculation.get("source_kind") == "archive"
            and commencement_for_calculation.get("document_id")
        ):
            publication_metadata_source = _official_sapl_publication_source(
                candidate_source_reference
            )
            if publication_metadata_source and commencement_for_calculation:
                try:
                    registered_publication_date = date.fromisoformat(
                        str(publication_metadata_source["data_publicacao"])
                    )
                except (KeyError, TypeError, ValueError):
                    registered_publication_date = None
                if registered_publication_date:
                    derived_effective_date = _vacatio_effective_date(
                        str(commencement_for_calculation.get("full_text") or ""),
                        registered_publication_date,
                    )
                    if derived_effective_date:
                        pair_sources.append(publication_metadata_source)
                        vacatio_rule_source = _vacatio_counting_rule_source()
                        pair_sources.append(vacatio_rule_source)

        display_sources = [*pair_sources, *relation_candidate_sources]
        answer_lines = [
            "Encontrei evidências documentais para conferir a relação entre os dois atos. "
            "Os excertos do acervo ainda são candidatos e não certificam vigência:"
        ]
        grounding_claims = []
        for index, source in enumerate(pair_sources, start=1):
            label = str(
                source.get("citation_label")
                or f"{source.get('norma_ref') or 'Norma'}, {source.get('dispositivo_ref') or 'dispositivo'}"
            )
            quote = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
            if len(quote) > 900:
                quote = quote[:897].rstrip() + "…"
            if quote and source.get("citation_id"):
                answer_lines.append(f"- **{label}**: “{quote}” [[{index}]]")
                grounding_claims.append(
                    {
                        "text": f"O trecho extraído de {label} consta no PDF citado.",
                        "citation_ids": [str(source["citation_id"])],
                    }
                )
        candidate_offset = len(pair_sources)
        for offset, candidate in enumerate(relation_candidate_sources, start=1):
            index = candidate_offset + offset
            source_label = str(
                candidate.get("citation_label") or candidate.get("norma_ref") or "ato posterior"
            )
            action_quote = str(candidate.get("action_quote") or "cláusula de alteração/revogação")
            target_quote = str(candidate.get("target_text") or candidate.get("full_text") or "")
            answer_lines.append(
                f"- **Pista de relação** — {source_label}: a extração registra “{action_quote}” "
                f"e o item “{target_quote}” [[{index}]]. É uma associação documental candidata, "
                "não uma conclusão jurídica revisada."
            )
            grounding_claims.append(
                {
                    "text": "O PDF candidato contém a cláusula e o item textual citados; seus efeitos não foram validados.",
                    "citation_ids": [str(candidate["citation_id"])],
                }
            )
        if temporal_context_requested:
            citation_indexes = {
                str(source.get("citation_id")): index
                for index, source in enumerate(display_sources, start=1)
                if source.get("citation_id")
            }
            transition_source = next(
                (
                    source
                    for source in pair_sources
                    if _PROCESS_TRANSITION_EVIDENCE_RE.search(
                        str(source.get("full_text") or "")
                    )
                ),
                None,
            )
            commencement_source = next(
                (
                    source
                    for source in pair_sources
                    if re.search(
                        r"\bentra\s+em\s+vigor\b",
                        str(source.get("full_text") or ""),
                        re.IGNORECASE,
                    )
                ),
                None,
            )
            if transition_source:
                index = citation_indexes[str(transition_source["citation_id"])]
                answer_lines.append(
                    f"**Regra transitória:** o {transition_source.get('dispositivo_ref')} prevê "
                    "a legislação da data do protocolo para processos abrangidos que ainda não "
                    f"tinham despacho decisório, ressalvada a opção formal prevista no texto [[{index}]]."
                )
            if commencement_source:
                index = citation_indexes[str(commencement_source["citation_id"])]
                answer_lines.append(
                    f"**Entrada em vigor:** o {commencement_source.get('dispositivo_ref')} indica "
                    "90 dias após a publicação. A evidência desta resposta não confirma a data "
                    f"oficial de publicação, então não permite calcular aqui o dia exato [[{index}]]."
                )
            if (
                derived_effective_date
                and publication_metadata_source
                and vacatio_rule_source
                and commencement_source
            ):
                publication_index = citation_indexes[
                    str(publication_metadata_source["citation_id"])
                ]
                counting_rule_index = citation_indexes[str(vacatio_rule_source["citation_id"])]
                commencement_index = citation_indexes[str(commencement_source["citation_id"])]
                answer_lines[-1] = (
                    f"**Entrada em vigor:** o {commencement_source.get('dispositivo_ref')} prevê "
                    f"90 dias após a publicação [[{commencement_index}]]. O cadastro do SAPL "
                    f"registra publicação em {publication_metadata_source['data_publicacao'][8:10]}/"
                    f"{publication_metadata_source['data_publicacao'][5:7]}/"
                    f"{publication_metadata_source['data_publicacao'][:4]} [[{publication_index}]]. "
                    f"Pelo critério de contagem do Art. 8º, § 1º, da LC nº 95/1998 — que inclui "
                    f"o dia da publicação e o último dia, com vigência no dia seguinte — o cálculo "
                    f"resulta em **{derived_effective_date.strftime('%d/%m/%Y')}** [[{counting_rule_index}]]. "
                    "É um cálculo derivado de metadado do SAPL; confira a edição do Diário Oficial "
                    "e a aplicação do critério ao ato municipal antes de usá-lo como marco jurídico."
                )
                grounding_claims.append(
                    {
                        "text": (
                            "A data calculada resulta do prazo expresso no dispositivo, da data de "
                            "publicação cadastrada no SAPL e do critério de contagem citado."
                        ),
                        "citation_ids": [
                            str(commencement_source["citation_id"]),
                            str(publication_metadata_source["citation_id"]),
                            str(vacatio_rule_source["citation_id"]),
                        ],
                    }
                )
            if transition_source and commencement_source:
                if derived_effective_date:
                    answer_lines.append(
                        "**Aplicação ao cenário informado:** se forem comprovados o protocolo em "
                        "20/03/2025 e a ausência de despacho na data calculada, esses fatos são "
                        "temporalmente compatíveis com as condições descritas no Art. 262. Isso não "
                        "basta para decidir o processo: ainda é preciso conferir a publicação no DOM, "
                        "o estado e o objeto dos autos e eventual opção formal pela análise integral "
                        "sob a lei nova."
                    )
                else:
                    answer_lines.append(
                        "**Aplicação ao cenário informado:** as datas de protocolo e de ausência de "
                        "despacho precisam ser comparadas com a data de entrada em vigor comprovada "
                        "e com o estado real dos autos. Sem essa data e essa conferência, não concluo "
                        "se a regra de transição alcança o processo."
                    )
        target_identity = next(
            (
                (
                    str(target.get("type") or ""),
                    normalize_number(str(target.get("number") or "")).lstrip("0") or "0",
                    int(target.get("year")),
                )
                for candidate in relation_candidate_sources
                for target in [
                    (candidate.get("relation_candidate") or {}).get("target_identity") or {}
                ]
                if target.get("type") and target.get("number") and target.get("year")
            ),
            None,
        )
        prior_norm_sources = [
            source
            for source in pair_sources
            if any(
                _reference_identity(reference) == target_identity
                for reference in parse_normative_references(
                    str(source.get("norma_ref") or source.get("citation_label") or "")
                )
                if reference.year is not None
            )
        ]
        if not prior_norm_sources:
            answer_lines.append(
                "Não localizei nesta busca o texto integral do ato-alvo; portanto não reconstruo "
                "uma consolidação nem confirmo quais dispositivos dele permanecem vigentes."
            )
        elif temporal_context_requested:
            answer_lines.append(
                "Há excertos do ato-alvo na resposta, mas eles não constituem o texto integral "
                "nem uma cadeia revisada de alterações; não permitem afirmar quais dispositivos "
                "dele ainda permanecem vigentes."
            )
            historical_work_rule = next(
                (
                    source
                    for source in prior_norm_sources
                    if re.search(
                        r"\b(?:obra|servi[cç]o|edifica[cç][aã]o)\b.{0,240}"
                        r"\b(?:iniciad[oa]|come[cç]ar|in[ií]cio)\b",
                        str(source.get("full_text") or ""),
                        re.IGNORECASE | re.DOTALL,
                    )
                    and re.search(
                        r"\b(?:licenciamento|licen[cç]a|alvar[aá])\b",
                        str(source.get("full_text") or ""),
                        re.IGNORECASE,
                    )
                ),
                None,
            )
            if historical_work_rule:
                index = citation_indexes[str(historical_work_rule["citation_id"])]
                answer_lines.append(
                    f"O excerto do PDF arquivado para **{historical_work_rule.get('dispositivo_ref')}** "
                    "é evidência da redação histórica recuperada, não prova de que ela vigorava na "
                    f"data do protocolo; deve ser cotejado com a cláusula de revogação candidata e "
                    f"a regra de transição [[{index}]]."
                )
            historical_commencement = next(
                (
                    source
                    for source in prior_norm_sources
                    if _article_key(str(source.get("dispositivo_ref") or "")) == "188"
                    and re.search(
                        r"\b(?:sessenta\s*\(\s*60\s*\)|60\s*\(\s*sessenta\s*\))\s*dias\b",
                        str(source.get("full_text") or ""),
                        re.IGNORECASE,
                    )
                ),
                None,
            )
            if historical_commencement:
                index = citation_indexes[str(historical_commencement["citation_id"])]
                answer_lines.append(
                    f"O Art. 188 do PDF antigo registra uma cláusula inicial de entrada em vigor "
                    f"60 dias após a publicação [[{index}]]; isso é dado histórico do ato original, "
                    "não prova a cadeia posterior nem a regra aplicável ao caso de 2025."
                )
        answer_lines.append(
            "A associação entre espécies/números/anos, a publicação e eficácia do ato, eventuais "
            "alterações posteriores e a redação aplicável na data do caso exigem conferência das "
            "fontes oficiais e revisão jurídica. A ausência de texto anterior nesta resposta não "
            "prova que a norma não exista nem que tenha sido revogada integralmente."
        )
        answer = "\n\n".join(answer_lines)
        yield {"event": "status", "status": "insufficient_evidence"}
        yield {
            "event": "sources",
            "sources": display_sources,
            "confidence": None,
            "reason_code": "qa_archive_explicit_act_relation_candidate",
            "coverage": {
                "scope": "explicit_pair_of_acts",
                "coverage_status": "candidate_relation_unreviewed",
                "legal_effect_reviewed": False,
                "temporal_scope_available": False,
            },
        }
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": display_sources,
            "grounded": bool(grounding_claims),
            "grounding": {
                "grounded": bool(grounding_claims),
                "score": 1.0 if grounding_claims else 0.0,
                "claims": grounding_claims,
                "failed_claims": [],
                "validation_scope": "unreviewed_source_excerpts_and_explicit_act_relation_candidate",
            },
            "reason_code": "qa_archive_explicit_act_relation_candidate",
            "source_relevance": max(
                (float(source.get("similarity_score") or 0) for source in display_sources),
                default=0.0,
            ),
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return
    if not results:
        # A relation candidate is not enough to disambiguate a multi-norm
        # question: it may refer to another act mentioned in the same prompt.
        # Only a source retrieved for the explicitly paired devices can support
        # a comparison; when retrieval is empty, fail closed even if the
        # broader relation scan found tangential candidates.
        if _has_ambiguous_multi_norm_article_scope(question):
            answer = _ambiguous_article_scope_clarification(question)
            reason_code = "qa_archive_ambiguous_multi_norm_article_scope"
            coverage = {
                "corpus": "acervo histórico local pesquisável",
                "coverage_status": "unknown",
                "temporal_scope_available": False,
            }
        elif query_plan.relation_intent in {"modification", "mixed"}:
            if relation_candidate_sources and query_plan.article_targets:
                candidate = relation_candidate_sources[0]
                target_index = 1
                action_quote = str(
                    candidate.get("action_quote") or "a cláusula de alteração/revogação"
                )
                target_text = str(
                    candidate.get("target_text") or candidate.get("full_text") or ""
                ).strip()
                source_reference = str(
                    candidate.get("citation_label")
                    or candidate.get("norma_ref")
                    or "o ato posterior"
                )
                relation_candidates_text = (
                    f"No PDF de **{source_reference}**, a extração encontrou a expressão "
                    f"“{action_quote}” e o item “{target_text}” [[{target_index}]]. "
                    "Isso é um indício textual candidato, ainda sem revisão da extração ou "
                    "validação de seus efeitos jurídicos; não confirma, por si só, que o artigo "
                    "foi revogado ou qual redação está vigente."
                )
                requested = ", ".join(f"Art. {article}" for article in query_plan.article_targets)
                answer = (
                    f"Não localizei no acervo uma redação legível de {requested} da norma consultada, "
                    "portanto ainda não há base para comparar versões do dispositivo. "
                    + relation_candidates_text
                    + " Confira o documento original e os atos posteriores antes de usar a conclusão em peça."
                )
            elif query_plan.article_targets:
                requested = ", ".join(f"Art. {article}" for article in query_plan.article_targets)
                answer = (
                    f"Não localizei no acervo evidência legível do texto de {requested} nem do ato "
                    "alterador. Por isso, não posso informar a redação, autor ou data da alteração, "
                    "nem confirmar se o dispositivo foi alterado ou revogado; também não há redações "
                    "anterior e posterior para comparar. A ausência de resultado não prova que o artigo "
                    "foi revogado ou que continua vigente. O status permanece inconclusivo: confira o "
                    "texto consolidado e o histórico oficial de alterações antes de usar essa referência."
                )
            else:
                answer = (
                    "Não foi possível verificar, no acervo consultado, se o dispositivo foi alterado "
                    "ou revogado pela norma mencionada. A busca não encontrou evidência suficiente "
                    "do ato alterador nem uma redação anterior e posterior que permita comparar. "
                    "A ausência de resultado não prova que a alteração não ocorreu nem confirma que "
                    "o texto continua vigente; o status permanece inconclusivo até que a cadeia "
                    "normativa seja localizada e validada."
                )
            reason_code = "qa_archive_relation_history_no_match"
            coverage = {
                "corpus": "acervo histórico local pesquisável",
                "temporal_scope_available": False,
                "coverage_status": "unknown",
            }
        else:
            answer = (
                "Não localizei uma evidência legível que responda à pergunta nos PDFs pesquisáveis "
                "do acervo histórico. Como a cobertura e a extração desses documentos podem estar "
                "incompletas, esta busca não confirma que a norma ou o dispositivo não exista nem "
                "que esteja vigente. Confira o tipo, o número e o ano da norma e, se possível, "
                "verifique o documento oficial."
            )
            reason_code = "qa_archive_no_match"
            coverage = {
                "corpus": "acervo histórico local pesquisável",
                "coverage_status": "unknown",
                "temporal_scope_available": False,
            }
        catalog_source = None
        if reason_code in {"qa_archive_no_match", "qa_archive_relation_history_no_match"}:
            catalog_source = _metadata_only_sapl_norma_source(query_plan.reference)
        gazette_source = None
        if (
            catalog_source
            and query_plan.kind == "provision"
            and len(query_plan.article_targets) == 1
            and reason_code == "qa_archive_no_match"
        ):
            gazette_source = _official_dom_article_source(
                query_plan.reference,
                query_plan.article_targets[0],
                catalog_source.get("data_publicacao"),
            )
        if gazette_source:
            answer = (
                f"{gazette_source['full_text']} [[1]]\n\n"
                "Localizei o dispositivo na edição oficial do Diário Oficial correspondente à data de publicação registrada no SAPL. "
                "A transcrição foi extraída automaticamente e ainda não passou por revisão humana; confira o PDF. "
                "Esta recuperação do texto original não verifica alterações posteriores nem certifica a vigência atual."
            )
            reason_code = "qa_archive_official_gazette_extraction_unreviewed"
            display_sources = [gazette_source, catalog_source]
            coverage = {
                "corpus": "Diário Oficial do Município de Natal",
                "coverage_status": "exact_act_identity_match_unreviewed_extraction",
                "temporal_scope_available": False,
            }
            yield {"event": "status", "status": "insufficient_evidence"}
            yield {
                "event": "sources",
                "sources": display_sources,
                "confidence": None,
                "reason_code": reason_code,
                "coverage": coverage,
            }
            yield {"event": "chunk", "chunk": answer, "provisional": False}
            yield {
                "event": "done",
                "answer": answer,
                "sources": display_sources,
                "grounded": False,
                "reason_code": reason_code,
                "grounding": {"grounded": False, "claims": [], "failed_claims": []},
                "timings_ms": {"retrieval": retrieval_ms},
            }
            return
        if relation_candidate_sources and not _has_ambiguous_multi_norm_article_scope(question):
            relation_candidate_sources = [
                *relation_candidate_sources,
                *([catalog_source] if catalog_source else []),
            ]
            candidate = relation_candidate_sources[0]
            prior_device = next(
                (
                    source
                    for source in relation_candidate_sources[1:]
                    if source.get("evidence_scope") == "unreviewed_target_device_extraction"
                ),
                None,
            )
            target_reference = str(candidate.get("target_text") or "o dispositivo citado").strip()
            target_index = 1
            if prior_device:
                prior_index = relation_candidate_sources.index(prior_device) + 1
                prior_text = str(
                    prior_device.get("full_text") or prior_device.get("texto") or ""
                ).strip()
                new_text_match = re.search(
                    # OCR may insert a page boundary/header between the
                    # amendment formula and the quoted wording (as it does
                    # between LC 261/2025 Arts. 118 and the new §2º text).
                    r"seguinte\s+reda[cç][aã]o\s*:\s*.{0,1200}?[“\"](?P<text>.*?)[”\"]",
                    str(candidate.get("full_text") or ""),
                    re.IGNORECASE | re.DOTALL,
                )
                new_text = new_text_match.group("text").strip() if new_text_match else ""
                answer = (
                    "Os PDFs permitem comparar o texto anterior com o ato posterior. "
                    f"Na extração do PDF da **{prior_device.get('citation_label')}**, o trecho anterior é: "
                    f"“{prior_text}” [[{prior_index}]]. "
                    f"O **{candidate.get('citation_label')}** registra que o {target_reference} "
                    f"“{candidate.get('action_quote')}”."
                )
                if new_text:
                    answer += f" A redação nova transcrita no Art. 118 é: “{new_text}” [[{target_index}]]."
                else:
                    answer += (
                        f" O dispositivo do ato posterior está reproduzido em [[{target_index}]]."
                    )
                answer += (
                    " Isso documenta uma alteração textual pontual, não a revogação integral do Art. 18. "
                    "Como as extrações locais ainda estão pendentes de revisão e não foi verificado todo o "
                    "histórico posterior, esta resposta não certifica a redação vigente hoje; confira os PDFs "
                    "oficiais e os atos posteriores antes de usar em parecer ou peça."
                )
            else:
                answer = (
                    "Não localizei uma redação legível do dispositivo antigo para comparar versões. "
                    f"Encontrei, porém, no PDF de **{candidate.get('citation_label') or candidate.get('norma_ref')}**, "
                    f"um indício textual candidato: a extração associa “{candidate.get('action_quote')}” "
                    f"ao item “{target_reference}” [[{target_index}]]. A extração ainda não foi revisada "
                    "e isso não confirma efeito jurídico, revogação total ou parcial, nem vigência atual. "
                    "Confira o PDF e os atos posteriores antes de usar essa informação em uma fundamentação."
                )
            relation_coverage = {
                "corpus": "PDFs normativos do acervo QA",
                "coverage_status": (
                    "unreviewed_relation_candidate_with_prior_device_text"
                    if prior_device
                    else "unreviewed_relation_candidate_only"
                ),
                "temporal_scope_available": False,
                "legal_effect_reviewed": False,
            }
            yield {"event": "status", "status": "insufficient_evidence"}
            yield {
                "event": "sources",
                "sources": relation_candidate_sources,
                "confidence": None,
                "reason_code": "qa_archive_relation_candidate_unreviewed",
                "coverage": relation_coverage,
            }
            yield {"event": "chunk", "chunk": answer, "provisional": False}
            yield {
                "event": "done",
                "answer": answer,
                "sources": relation_candidate_sources,
                "grounded": True,
                "reason_code": "qa_archive_relation_candidate_unreviewed",
                "coverage": relation_coverage,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": "O trecho candidato foi extraído do PDF indicado, sem validar efeito jurídico.",
                            "citation_ids": [candidate["citation_id"]],
                        }
                    ],
                    "failed_claims": [],
                    "validation_scope": "literal_relation_candidate_only_no_legal_effect_review",
                },
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            }
            return
        if catalog_source:
            target_labels = []
            for article in query_plan.article_targets:
                match = re.fullmatch(r"(\d+)([a-z]?)", article, re.IGNORECASE)
                if match:
                    number, suffix = match.groups()
                    target_labels.append(f"Art. {number}º{f'-{suffix.upper()}' if suffix else ''}")
                else:
                    target_labels.append(f"Art. {article}")
            target = ", ".join(target_labels) if target_labels else "dispositivo solicitado"
            answer += (
                f"\n\nLocalizei no cadastro oficial do SAPL o registro de **{catalog_source['norma_ref']}**, "
                f"mas o texto de {target} não está integrado ao acervo pesquisável. O cadastro confirma "
                "a identificação do ato, não o conteúdo do dispositivo, sua vigência ou alterações posteriores. "
                "Consulte o registro oficial [[1]]."
            )
            reason_code = "qa_archive_catalog_metadata_only"
        search_limit = (
            _related_matter_search_limit(
                related_matter_status, article_scope=bool(query_plan.article_targets)
            )
            if explicit_legislative_matter_query
            else ""
        )
        if search_limit:
            answer = f"{answer}\n\n{search_limit}"
        yield {"event": "status", "status": "insufficient_evidence"}
        yield {
            "event": "sources",
            "sources": [catalog_source] if catalog_source else [],
            "confidence": None,
            "reason_code": reason_code,
            "coverage": coverage,
        }
        yield {"event": "chunk", "chunk": answer, "provisional": False}
        yield {
            "event": "done",
            "answer": answer,
            "sources": [catalog_source] if catalog_source else [],
            "grounded": False,
            "reason_code": reason_code,
            "grounding": {"grounded": False, "claims": [], "failed_claims": []},
            "timings_ms": {"retrieval": retrieval_ms},
        }
        return

    parsed_article_norm_pairs = _explicit_article_norm_pairs(question)
    paired_article_scope = (
        len(parsed_article_norm_pairs) == len(_article_reference_mentions(question))
        and len(parsed_article_norm_pairs) > 1
        and not _cross_reference_scan_scope(question)
    )
    # A repeated mention of the same article (for example, once as the old
    # citation and once in a follow-up question) is one evidence target, not a
    # request to quote the same PDF passage twice.
    paired_article_norm_pairs = tuple(dict.fromkeys(parsed_article_norm_pairs))
    textual_amendment_comparison = _archive_explicit_textual_amendment_comparison(
        question, results, paired_article_norm_pairs
    )
    if textual_amendment_comparison is not None:
        _, comparison_sources, _, _ = textual_amendment_comparison
        results = comparison_sources
        relation_candidate_sources = []
        supplemental_matter_sources = []

    supplemental_sources = [
        {key: value for key, value in source.items() if not key.startswith("_")}
        for source in supplemental_matter_sources
    ]

    def append_supplemental_matter_notes(answer_text: str) -> str:
        for offset, source in enumerate(supplemental_sources, start=1):
            citation_index = len(results) + offset
            label = str(source.get("citation_label") or "Matéria legislativa no SAPL")
            relation = str(source.get("relation_label") or "o dispositivo consultado")
            status = str(source.get("status_label") or "").strip()
            if not status:
                matter_status = source.get("matter_status")
                status = (
                    "Em tramitação no SAPL"
                    if matter_status is True
                    else "Fora de tramitação no SAPL"
                    if matter_status is False
                    else "Situação não informada pelo SAPL"
                )
            ementa = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
            if len(ementa) > 500:
                ementa = ementa[:497].rstrip() + "…"
            answer_text += (
                f"\n\nComo alerta de conferência, o SAPL registra **{label}** "
                f"mencionando {relation}"
                + (f": “{ementa}”" if ementa else "")
                + f" [[{citation_index}]]. Situação no SAPL: {status}. O cadastro de uma proposição não comprova, por si, "
                "que o texto foi aprovado, promulgado ou entrou em vigor."
            )
        return answer_text

    transition_synthesis = _archive_transition_synthesis(question, results)
    if transition_synthesis is not None:
        publication_sources = _archive_transition_publication_sources(question, results)
        official_articles = {
            (_archive_source_norm_identity(source), _archive_source_article(source)): source
            for source in publication_sources
            if source.get("source_kind") == "official_gazette_extraction"
        }
        replaced_articles = set()
        if official_articles:
            enriched_results = []
            for source in results:
                key = (_archive_source_norm_identity(source), _archive_source_article(source))
                if source.get("source_kind") == "archive" and key in official_articles:
                    if key not in replaced_articles:
                        enriched_results.append(official_articles[key])
                        replaced_articles.add(key)
                    continue
                enriched_results.append(source)
            results = enriched_results
        results.extend(
            source
            for source in publication_sources
            if source.get("source_kind") != "official_gazette_extraction"
            and source.get("citation_id") not in {
                item.get("citation_id") for item in results
            }
        )
        transition_synthesis = _archive_transition_synthesis(question, results)

    amendment_synthesis = _archive_explicit_amendment_synthesis(question, results)
    if amendment_synthesis is not None:
        _, amendment_sources, _, _ = amendment_synthesis
        results = amendment_sources
        relation_candidate_sources = []
        supplemental_sources = []

    yield {
        "event": "sources",
        "sources": [*results, *supplemental_sources, *relation_candidate_sources],
        "confidence": None,
        "cached": False,
        "retrieval_strategy": (
            "qa_archive_lexical_with_sapl_matter_context"
            if supplemental_sources
            else "qa_archive_lexical"
        ),
        "coverage": {
            **(results[0].get("coverage") or {}),
            "corpus": "acervo histórico local pesquisável",
            "sources_retrieved": len(results),
        },
    }

    if amendment_synthesis is not None:
        answer, amendment_sources, amendment_claims, amendment_coverage = amendment_synthesis
        yield {"event": "status", "status": "grounding"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": amendment_sources,
            "grounded": True,
            "source_only": True,
            "reason_code": "qa_archive_explicit_amendment_text",
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": amendment_claims,
                "failed_claims": [],
                "validation_scope": "literal_amendment_paragraphs_only_no_current_effect_conclusion",
            },
            "coverage": amendment_coverage,
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    if transition_synthesis is not None:
        answer, grounding_claims = transition_synthesis
        search_limit = _related_matter_search_limit(
            related_matter_status, article_scope=bool(query_plan.article_targets)
        )
        if search_limit:
            answer = f"{answer}\n\n{search_limit}"
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
            "source_only": True,
            "reason_code": "qa_archive_transition_relation_synthesis",
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": grounding_claims,
                "failed_claims": [],
                "validation_scope": "explicit_archive_repeal_and_transition_text_only_no_case_adjudication",
            },
            "coverage": {
                "coverage_status": "article_targets_retrieved_temporal_applicability_unverified",
                "temporal_scope_available": False,
                "requested_article_norm_pairs": [
                    {"normative_identity": list(identity), "article": article}
                    for identity, article in paired_article_norm_pairs
                ],
                "missing_article_norm_pairs": [],
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    transition_commencement = _archive_transition_commencement_synthesis(question, results)
    if transition_commencement is not None:
        answer, transition_claims = transition_commencement
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
            "source_only": True,
            "reason_code": "qa_archive_transition_and_commencement_text_synthesis",
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": transition_claims,
                "failed_claims": [],
                "validation_scope": "archive_transition_and_commencement_text_only_no_case_adjudication",
            },
            "coverage": {
                "coverage_status": "transition_and_commencement_evidence_retrieved_temporal_applicability_unverified",
                "temporal_scope_available": False,
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        yield {"event": "status", "status": "completed"}
        return

    repeal_scope_synthesis = _archive_explicit_repeal_scope_synthesis(question, results)
    if repeal_scope_synthesis is not None:
        answer, repeal_claims = repeal_scope_synthesis
        yield {"event": "status", "status": "grounding"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {
                "event": "chunk",
                "chunk": answer[offset : offset + 72],
                "provisional": False,
            }
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": results,
            "grounded": True,
            "source_only": True,
            "reason_code": "qa_archive_explicit_repeal_scope_text",
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": repeal_claims,
                "failed_claims": [],
                "validation_scope": "literal_target_scope_in_unreviewed_repeal_clause_no_effect_or_vigency_conclusion",
            },
            "coverage": {
                "coverage_status": "textual_targets_only",
                "temporal_scope_available": False,
                "repeal_target_scope_classification": "literal_text_only",
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    if textual_amendment_comparison is not None:
        answer, comparison_sources, comparison_claims, comparison_coverage = textual_amendment_comparison
        results = comparison_sources
        yield {"event": "status", "status": "grounding"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {
                "event": "chunk",
                "chunk": answer[offset : offset + 72],
                "provisional": False,
            }
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": results,
            "grounded": True,
            "source_only": True,
            "reason_code": "qa_archive_explicit_textual_amendment_comparison",
            "grounding": {
                "grounded": True,
                "score": 1.0,
                "claims": comparison_claims,
                "failed_claims": [],
                "validation_scope": (
                    "source_textual_difference_only_no_effective_status_or_case_applicability"
                ),
            },
            "coverage": comparison_coverage,
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    repeal_transition_relation = bool(_REPEAL_TRANSITION_RELATION_RE.search(question))
    if repeal_transition_relation:
        # The explicit article texts can support a bounded comparison even
        # when extraction coverage is incomplete. The helper quotes only the
        # requested provisions and states that they do not decide the process
        # outcome or certify the extraction.
        transition_pair = _archive_explicit_transition_pair_synthesis(question, results)
        if transition_pair is not None:
            answer, transition_claims = transition_pair
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
                    "claims": transition_claims,
                    "failed_claims": [],
                    "validation_scope": "archive_repeal_transition_text_only_no_case_adjudication",
                },
                "reason_code": "qa_archive_repeal_transition_text_synthesis",
                "source_relevance": min(
                    float(source.get("similarity_score") or 0)
                    for source in results
                    if source.get("citation_id")
                ),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            yield {"event": "status", "status": "completed"}
            return

    paired_norm_identity_count = len({identity for identity, _article in paired_article_norm_pairs})
    if paired_article_scope and (
        query_plan.relation_intent in {"modification", "mixed"}
        or (paired_norm_identity_count > 1 and _HISTORICAL_WORDING_QUERY_RE.search(question))
    ):
        source_indexes = {
            str(source.get("citation_id") or ""): index
            for index, source in enumerate(results, 1)
            if source.get("citation_id")
        }
        source_by_pair = {}
        for source in results:
            article_key = _article_key(str(source.get("dispositivo_ref") or ""))
            for reference in parse_normative_references(str(source.get("norma_ref") or "")):
                if reference.year is not None:
                    source_by_pair[(_reference_identity(reference), article_key)] = source
        answer_parts = []
        grounding_claims = []
        missing_claims = []
        for identity, article in paired_article_norm_pairs:
            source = source_by_pair.get((identity, article))
            if source is None:
                type_label = _TYPE_LABELS.get(identity[0], "Norma")
                missing_claims.append(
                    f"Art. {article} de {type_label} nº {identity[1]}/{identity[2]}"
                )
                continue
            citation_id = str(source.get("citation_id") or "")
            citation_index = source_indexes[citation_id]
            norma = str(source.get("norma_ref") or "norma consultada")
            device = str(source.get("dispositivo_ref") or f"Art. {article}")
            excerpt = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
            requested_paragraphs = _archive_requested_paragraphs(
                question, article, excerpt
            )
            if requested_paragraphs:
                paragraph_label, excerpt = requested_paragraphs
                device = f"{device}, {paragraph_label}"
            answer_parts.append(
                f"No PDF local da **{norma}**, o {device} contém o trecho recuperado: “{excerpt}” "
                f"[[{citation_index}]]."
            )
            grounding_claims.append(
                {
                    "text": f"Transcrição recuperada de {norma}, {device}",
                    "citation_ids": [citation_id],
                }
            )
        if missing_claims:
            answer_parts.append(
                "Não localizei no acervo pesquisável o texto de "
                + "; ".join(missing_claims)
                + ". Portanto, não consigo conferir a redação desse dispositivo nem reconstruir sua cadeia de alterações."
            )
        answer_parts.append(
            "Os trechos disponíveis são extrações locais pendentes de revisão. Eles não bastam, por si sós, "
            "para confirmar a vigência ou a data de eficácia aplicável a um processo; confira o ato oficial, "
            "a publicação e o histórico normativo antes de concluir."
        )
        answer = "\n\n".join(answer_parts)
        search_limit = _related_matter_search_limit(
            related_matter_status, article_scope=bool(query_plan.article_targets)
        )
        if search_limit:
            answer = f"{answer}\n\n{search_limit}"
        reason_code = (
            "qa_archive_partial_multi_norm_article_scope"
            if missing_claims
            else "qa_archive_multi_norm_article_evidence_only"
        )
        yield {
            "event": "status",
            "status": "insufficient_evidence" if missing_claims else "grounding",
        }
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": results,
            "grounded": not missing_claims,
            "source_only": True,
            "reason_code": reason_code,
            "grounding": {
                "grounded": not missing_claims,
                "score": 1.0 if not missing_claims else None,
                "claims": grounding_claims,
                "failed_claims": missing_claims,
                "validation_scope": "explicit_article_to_norm_pairs_only_no_temporal_adjudication",
            },
            "coverage": {
                "coverage_status": "unknown",
                "temporal_scope_available": False,
                "requested_article_norm_pairs": [
                    {"normative_identity": list(identity), "article": article}
                    for identity, article in paired_article_norm_pairs
                ],
                "missing_article_norm_pairs": missing_claims,
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    identity_topic_tokens = _norm_identity_topic_tokens(question)
    compound_article_targets = query_plan.article_targets
    if identity_topic_tokens and compound_article_targets:
        target_keys = set(compound_article_targets)
        identity_candidates = []
        for index, source in enumerate(results, 1):
            if _article_key(str(source.get("dispositivo_ref") or "")) in target_keys:
                continue
            evidence_tokens = _tokens(str(source.get("full_text") or ""))
            overlap = len(identity_topic_tokens & evidence_tokens) / len(identity_topic_tokens)
            if overlap >= 0.55:
                identity_candidates.append((overlap, index, source))

        if identity_candidates:
            _overlap, identity_index, identity_source = max(
                identity_candidates, key=lambda candidate: candidate[0]
            )
            target_sources = {}
            for index, source in enumerate(results, 1):
                if source.get("norma_ref") != identity_source.get("norma_ref"):
                    continue
                article_key = _article_key(str(source.get("dispositivo_ref") or ""))
                if article_key in target_keys:
                    target_sources.setdefault(article_key, (index, source))

            if target_keys <= target_sources.keys():
                identity_device = str(
                    identity_source.get("dispositivo_ref") or "dispositivo de identificação"
                )
                identity_text = str(identity_source.get("full_text") or "").strip()
                norm_ref = str(identity_source.get("norma_ref") or "norma consultada")
                answer_parts = [
                    f"A norma identificada é **{norm_ref}**. O {identity_device} "
                    f"estabelece: “{identity_text}” [[{identity_index}]]."
                ]
                grounding_claims = [
                    {
                        "text": f"{norm_ref} institui o objeto indicado na pergunta",
                        "citation_ids": [str(identity_source.get("citation_id") or "")],
                    }
                ]
                for target in compound_article_targets:
                    source_index, source = target_sources[target]
                    device = str(source.get("dispositivo_ref") or f"Art. {target}")
                    text = str(source.get("full_text") or "").strip()
                    article_topic = _article_topic_label(question)
                    qualifier = (
                        f"Quanto ao tema **{article_topic}**, "
                        if article_topic
                        else f"Quanto ao {device}, "
                    )
                    answer_parts.append(
                        f"{qualifier}o {device} da mesma norma dispõe: "
                        f"“{text}” [[{source_index}]]."
                    )
                    grounding_claims.append(
                        {
                            "text": f"Conteúdo do {device} da norma identificada",
                            "citation_ids": [str(source.get("citation_id") or "")],
                        }
                    )
                answer = "\n\n".join(answer_parts) + (
                    "\n\n*Transcrição automática do acervo local; confira o PDF original "
                    "antes de usar.*"
                )
                yield {"event": "status", "status": "grounding"}
                for offset in range(0, len(answer), 72):
                    raise_if_cancelled(should_cancel)
                    yield {
                        "event": "chunk",
                        "chunk": answer[offset : offset + 72],
                        "provisional": False,
                    }
                yield {"event": "status", "status": "finalizing"}
                yield {
                    "event": "done",
                    "answer": answer,
                    "sources": results,
                    "grounded": True,
                    "source_only": True,
                    "grounding": {
                        "grounded": True,
                        "score": 1.0,
                        "claims": grounding_claims,
                        "failed_claims": [],
                        "validation_scope": "explicit_norm_identity_and_requested_articles",
                    },
                    "reason_code": "archive_compound_norm_identity",
                    "source_relevance": max(
                        (float(source.get("similarity_score") or 0) for source in results),
                        default=0.0,
                    ),
                    "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                    "generation_attempts": [],
                }
                return

    # The isolated PDF archive is an original-text corpus, not an audited
    # amendment chain. A provision excerpt can establish its wording, but it
    # cannot establish whether later acts amended or revoked it. Avoid falling
    # through to the single-article transcription path for relation questions.
    cross_reference_question = bool(_CROSS_REFERENCE_SCAN_RE.search(question))
    if _is_normative_change_history_request(question, query_plan) and results:
        requested_articles = set(query_plan.article_targets)
        requested_reference = query_plan.reference
        original_sources = [
            (index, source)
            for index, source in enumerate(results, 1)
            if source.get("citation_id")
            and source.get("full_text")
            and requested_reference is not None
            and _reference_identity(requested_reference)
            in {
                _reference_identity(reference)
                for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                if reference.year is not None
            }
            and _article_key(str(source.get("dispositivo_ref") or "")) in requested_articles
        ]
        requested_target = ", ".join(f"Art. {article}" for article in query_plan.article_targets)
        if original_sources:
            source_index, _source = original_sources[0]
            article_list = f"O PDF citado registra a redação arquivada de origem, não o ato alterador [[{source_index}]]."
        else:
            article_list = (
                "Não encontrei uma redação original legível desse dispositivo para citar."
            )
        answer = (
            f"Nos documentos recuperados para este follow-up, não encontrei um ato posterior legível "
            f"que altere ou revogue {requested_target}. {article_list} "
            "Por isso, ainda não é possível identificar o ato modificador nem concluir a redação "
            "vigente. Para isso, falta localizar e conferir os atos posteriores, suas datas e efeitos, "
            "e confrontá-los com uma fonte oficial consolidada. A ausência de um ato entre os "
            "documentos recuperados não prova que ele não exista."
        )
        grounding_claims = [
            {
                "text": "O PDF local citado contém a redação arquivada de origem, não um ato alterador.",
                "citation_ids": [source["citation_id"]],
            }
            for _index, source in original_sources[:1]
        ]
        yield {"event": "status", "status": "insufficient_evidence"}
        for offset in range(0, len(answer), 72):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
        yield {"event": "status", "status": "finalizing"}
        yield {
            "event": "done",
            "answer": answer,
            "sources": results,
            "grounded": False,
            "source_only": True,
            "reason_code": "qa_archive_change_history_no_clause",
            "grounding": {
                "grounded": False,
                "claims": grounding_claims,
                "failed_claims": [f"ato posterior que altere ou revogue {requested_target}"],
                "validation_scope": "no_change_clause_retrieved_original_provision_is_not_change_evidence",
            },
            "coverage": {
                "coverage_status": "partial" if original_sources else "unknown",
                "temporal_scope_available": False,
                "change_clauses_retrieved": 0,
                "requested_article_targets": list(query_plan.article_targets),
            },
            "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
            "generation_attempts": [],
        }
        return

    if _is_normative_change_inventory_request(question, query_plan) and results:
        coverage = results[0].get("coverage") or {}
        lines = [
            f"Na extração local da **{results[0].get('norma_ref') or 'norma consultada'}**, "
            "localizei estas cláusulas expressas de alteração ou revogação:"
        ]
        grounding_claims = []
        for index, source in enumerate(results, 1):
            device = str(source.get("dispositivo_ref") or "dispositivo sem identificação")
            text = str(source.get("full_text") or "").strip()
            if (
                not text
                or not source.get("citation_id")
                or not _NORMATIVE_CHANGE_EVIDENCE_RE.search(text)
            ):
                continue
            lines.append(f"- **{device}**: “{text}” [[{index}]]")
            grounding_claims.append(
                {
                    "text": f"Transcrição da cláusula de ação normativa em {device}",
                    "citation_ids": [source["citation_id"]],
                }
            )
        if not grounding_claims:
            requested_articles = ", ".join(
                f"Art. {article}" for article in query_plan.article_targets
            )
            requested_target = requested_articles or "o dispositivo mencionado"
            original_sources = [
                (index, source)
                for index, source in enumerate(results, 1)
                if source.get("citation_id")
                and source.get("full_text")
                and query_plan.reference is not None
                and _reference_identity(query_plan.reference)
                in {
                    _reference_identity(reference)
                    for reference in parse_normative_references(str(source.get("norma_ref") or ""))
                    if reference.year is not None
                }
                and (
                    not query_plan.article_targets
                    or _article_key(str(source.get("dispositivo_ref") or ""))
                    in set(query_plan.article_targets)
                )
            ]
            cited_original = " ".join(
                f"O resultado recuperado é somente o texto do {source.get('dispositivo_ref') or requested_target} "
                f"da {source.get('norma_ref') or 'norma indicada'}, não uma cláusula de alteração [[{index}]]."
                for index, source in original_sources[:3]
            )
            answer = (
                f"Não localizei, na extração pesquisável do acervo, cláusula legível de alteração ou revogação posterior para {requested_target}. "
                f"{cited_original} "
                "Esse resultado não permite identificar o ato alterador nem confirmar a redação vigente. "
                "A ausência de um ato nos PDFs pesquisáveis não prova que ele não exista; consulte o histórico oficial antes de usar a referência."
            ).strip()
            claims = [
                {
                    "text": f"O trecho citado é o texto recuperado de {source.get('norma_ref')}, {source.get('dispositivo_ref')}; ele não é um ato alterador.",
                    "citation_ids": [source["citation_id"]],
                }
                for _index, source in original_sources[:3]
            ]
            yield {"event": "status", "status": "insufficient_evidence"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": results,
                "grounded": False,
                "source_only": True,
                "reason_code": "qa_archive_change_history_no_clause",
                "grounding": {
                    "grounded": False,
                    "claims": claims,
                    "failed_claims": [f"ato alterador legível para {requested_target}"],
                    "validation_scope": "no_change_clause_in_retrieved_archive_text_does_not_prove_no_change",
                },
                "coverage": {
                    "coverage_status": "unknown",
                    "temporal_scope_available": False,
                    "change_clauses_retrieved": 0,
                    "requested_article_targets": list(query_plan.article_targets),
                },
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return
        else:
            selected = coverage.get("inventory_selected", len(grounding_claims))
            total = coverage.get("inventory_total", len(grounding_claims))
            if coverage.get("inventory_complete"):
                lines.append(
                    f"\nA busca localizou {total} dispositivos com comandos expressos de alteração "
                    "ou revogação na extração consultada. O texto ainda está pendente de revisão; "
                    "isso não confirma efeitos posteriores nem a redação atualmente vigente."
                )
            else:
                lines.append(
                    f"\nA amostra contém {selected} de {total} dispositivos identificados. "
                    "A lista pode ser incompleta e a extração ainda está sob revisão."
                )
            lines.append(
                "Confira o PDF original e o histórico oficial de alterações antes de usar esta "
                "transcrição em uma fundamentação."
            )
            answer = "\n\n".join(lines)
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": results,
                "grounded": True,
                "source_only": True,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": grounding_claims,
                    "failed_claims": [],
                    "validation_scope": "verbatim_change_inventory_in_unreviewed_archive_extraction",
                },
                "reason_code": "qa_archive_normative_change_inventory",
                "source_relevance": min(
                    (float(source.get("similarity_score") or 0) for source in results),
                    default=0.0,
                ),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return
    relation_is_only_a_scope_qualifier = bool(
        _RELATION_SCOPE_QUALIFIER_RE.search(question)
    ) and not bool(_DIRECT_NORMATIVE_HISTORY_REQUEST_RE.search(question))
    explicit_transition_article_scope = bool(
        len(_article_reference_mentions(question)) == 1
        and len(
            {
                reference.identity
                for reference in parse_normative_references(question)
                if reference.year is not None and reference.number
            }
        )
        == 1
        and _PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question)
    )
    if (
        query_plan.relation_intent in {"modification", "mixed"}
        and not cross_reference_question
        and not relation_is_only_a_scope_qualifier
        and not explicit_transition_article_scope
        and not _enumerated_topic_facets(question)
    ):
        source = next(
            (item for item in results if item.get("citation_id") and item.get("full_text")),
            None,
        )
        if source:
            citation_index = next(index for index, item in enumerate(results, 1) if item is source)
            norm = str(source.get("norma_ref") or "norma consultada")
            device = str(source.get("dispositivo_ref") or "dispositivo localizado")
            text = str(source.get("full_text") or "").strip()
            answer = (
                "Com as evidências disponíveis, não foi possível confirmar se o dispositivo "
                "consultado foi alterado ou revogado, nem afirmar sua vigência atual. "
                f"O PDF arquivado registra a redação de origem de **{norm}, {device}**: "
                f"“{text}” [[{citation_index}]].\n\n"
                + (
                    "A vigência desta redação ainda não foi confirmada. "
                    if relation_candidate_sources
                    else "A extração consultada não está associada a uma cadeia de alterações e "
                    "revogações vinculada e revisada. "
                )
                + "Confira a linha do tempo normativa e os atos oficiais antes de usar essa redação "
                "em uma fundamentação."
            )
            source_norm_identities = {
                reference.identity
                for item in results
                for reference in parse_normative_references(str(item.get("norma_ref") or ""))
                if reference.year is not None
            }
            query_norm_identities = {
                reference.identity
                for reference in parse_normative_references(question)
                if reference.year is not None and reference.type_key.startswith("lei")
            }
            if (
                _LEGISLATIVE_MATTER_QUERY_RE.search(question)
                and source_norm_identities
                and source_norm_identities <= query_norm_identities
            ):
                answer += (
                    "\n\nOs trechos citados são da norma de origem; esta busca não trouxe "
                    "documentos oficiais sobre a tramitação ou o resultado do projeto/emenda "
                    "mencionado. Assim, não permite dizer se a proposta foi aprovada, sancionada "
                    "e publicada como lei."
                )
            search_limit = (
                _related_matter_search_limit(
                    related_matter_status, article_scope=bool(query_plan.article_targets)
                )
                if explicit_legislative_matter_query
                else ""
            )
            if search_limit:
                answer = f"{answer}\n\n{search_limit}"
            if supplemental_sources:
                answer = append_supplemental_matter_notes(answer)
            relation_candidate_citation_ids = []
            for offset, candidate in enumerate(relation_candidate_sources, start=1):
                citation_index = len(results) + len(supplemental_sources) + offset
                relation_candidate_citation_ids.append(candidate["citation_id"])
                action_quote = str(candidate.get("action_quote") or "a cláusula pertinente")
                target_text = str(
                    candidate.get("target_text") or candidate.get("full_text") or ""
                ).strip()
                answer += (
                    f"\n\nComo pista para a conferência, no PDF de **{candidate.get('citation_label') or candidate.get('norma_ref')}** "
                    f"a extração identifica “{action_quote}” e o item “{target_text}” "
                    f"[[{citation_index}]]. O vínculo é apenas candidato documental: a extração/relação "
                    "não está validada e não confirma, por si só, a revogação nem a redação vigente."
                )
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": [*results, *supplemental_sources, *relation_candidate_sources],
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [
                        {
                            "text": f"Transcrição da redação de origem de {norm}, {device}",
                            "citation_ids": [source["citation_id"]],
                        },
                        *[
                            {
                                "text": (
                                    "O PDF indicado contém os fragmentos textuais descritos; "
                                    "não há validação de efeito jurídico."
                                ),
                                "citation_ids": [candidate["citation_id"]],
                            }
                            for candidate in relation_candidate_sources
                        ],
                    ],
                    "failed_claims": [],
                    "validation_scope": (
                        "archive_original_text_plus_unreviewed_relation_candidates"
                        if relation_candidate_citation_ids
                        else "archive_original_text_only_no_audited_amendment_chain"
                    ),
                },
                "reason_code": (
                    "qa_archive_relation_candidate_unreviewed"
                    if relation_candidate_sources
                    else "qa_archive_relation_history_unavailable"
                ),
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
                "claims": [
                    {
                        "text": (
                            f"O excerto de {dispositivo_ref} menciona interstício mínimo, "
                            "mas não informa a duração no trecho recuperado."
                        ),
                        "citation_ids": [source["citation_id"]],
                    }
                ],
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
                source["citation_id"]: index for index, source in enumerate(results, 1)
            }
            target_label = next(
                (str(source.get("norma_ref") or "norma consultada") for source in results),
                "norma consultada",
            )
            if matched_sources:
                lines = [
                    f"Nos trechos legíveis recuperados de **{target_label}**, "
                    "identifiquei referência expressa à norma indicada nestes dispositivos:"
                ]
                for source in matched_sources:
                    index = result_indexes[source["citation_id"]]
                    # Keep the queried device visible in the answer itself;
                    # the numbered marker remains the structured link to its
                    # evidence card and official/local source.
                    device = str(
                        source.get("dispositivo_ref") or "Dispositivo identificado"
                    ).strip()
                    lines.append(f"- **{device}** [[{index}]]")
                lines.append(
                    "A lista se limita aos trechos recuperados e legíveis; ela não confirma "
                    "que os demais dispositivos da norma não contenham outras referências. "
                    "Uma remissão literal, por si só, não comprova alteração ou revogação da "
                    "norma citada; isso exige localizar o dispositivo de alteração e conferir "
                    "a cadeia normativa. A extração do PDF do acervo ainda está sob revisão."
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
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
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
    transition_scope_question = bool(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question))
    query_plan = classify_normative_query(question)
    if query_plan.explicit_target_overview and results:
        overview_sources = [
            source
            for source in results
            if source.get("citation_id") and source.get("full_text")
        ]
        if overview_sources:
            answer_parts = [
                f"No PDF local da **{query_plan.reference.type_key.replace('_', ' ').title()} "
                f"nº {query_plan.reference.number}/{query_plan.reference.year}**, a extração "
                "retornou estes dispositivos:"
            ]
            overview_claims = []
            for index, source in enumerate(overview_sources, start=1):
                label = str(source.get("dispositivo_ref") or "dispositivo")
                norm = str(source.get("norma_ref") or "norma consultada")
                text = re.sub(r"\s+", " ", str(source.get("full_text") or "")).strip()
                answer_parts.append(f"- **{norm}, {label}:** “{text}” [[{index}]]")
                overview_claims.append(
                    {
                        "text": f"Transcrição extraída de {norm}, {label}",
                        "citation_ids": [str(source["citation_id"])],
                    }
                )
            first_coverage = overview_sources[0].get("coverage") or {}
            selected_articles = first_coverage.get("selected_articles", len(overview_sources))
            total_articles = first_coverage.get("total_articles")
            complete = all(
                (source.get("coverage") or {}).get("complete", False)
                for source in overview_sources
            )
            if complete:
                answer_parts.append(
                    f"A extração identificou {len(overview_sources)} dispositivo(s) e marcou "
                    "a cobertura desta norma como completa no acervo consultado."
                )
            else:
                total_note = f" de {total_articles}" if total_articles is not None else ""
                answer_parts.append(
                    f"A amostra recuperou {selected_articles}{total_note} dispositivo(s); "
                    "a cobertura é parcial ou não pôde ser confirmada."
                )
            answer_parts.append(
                "Transcrição automática de PDF local pendente de revisão. A indicação de uma "
                "revogação em outro ato e estes trechos, isoladamente, não confirmam efeitos "
                "posteriores nem a vigência atual; confira o original e o histórico oficial."
            )
            answer = "\n\n".join(answer_parts)
            reason_code = "qa_archive_explicit_target_norm_verbatim_inventory"
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {"event": "chunk", "chunk": answer[offset : offset + 72], "provisional": False}
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": overview_sources,
                "grounded": True,
                "source_only": True,
                "reason_code": reason_code,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": overview_claims,
                    "failed_claims": [],
                    "validation_scope": "verbatim_article_inventory_only_no_legal_effect_review",
                },
                "coverage": {
                    "scope": "explicit_target_norm_article_inventory",
                    "selected_articles": selected_articles,
                    "total_articles": total_articles,
                    "complete": complete,
                    "legal_effect_reviewed": False,
                },
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return
    if (
        contextual_device_scope
        and not transition_scope_question
        and len(results) == 1
        and results[0].get("citation_id")
    ):
        source = results[0]
        device = str(source.get("dispositivo_ref") or "dispositivo citado")
        norm = str(source.get("norma_ref") or "norma consultada")
        text = str(source.get("full_text") or "").strip()
        if not text:
            # A device label alone is not evidence for a legal explanation.
            # Fall through to the normal grounded-generation/abstention path.
            contextual_device_scope = False
        else:
            if _CASE_RECORD_SUFFICIENCY_REQUEST_RE.search(question):
                answer = (
                    f"O {_archive_device_label(device, norm)} trata de exigências e providências "
                    f"no licenciamento: “{text}” [[1]]\n\n"
                    "**Esse artigo isolado não informa quais documentos foram juntados aos autos "
                    "nem permite concluir se a documentação do processo está completa ou suficiente.** "
                    "O trecho não examina os autos. Confira a lista de documentos do processo, "
                    "as pendências registradas e a redação oficial aplicável na data relevante.\n\n"
                    "*Transcrição automática do acervo local; extração e segmentação ainda estão "
                    "sob revisão. Confira o PDF original antes de usar.*"
                )
                validation_scope = "article_scope_limitation_without_case_file_access"
                reason_code = "qa_archive_article_application_limits"
                claim_text = (
                    "O artigo citado não permite certificar a suficiência dos documentos dos autos."
                )
            else:
                answer = (
                    f"No PDF arquivado, {_archive_device_label(device, norm)} estabelece: "
                    f"“{text}” [[1]]\n\n"
                    "*Transcrição automática; metadados e segmentação ainda estão sob revisão. "
                    "Confira o PDF original antes de usar.*"
                )
                validation_scope = "verbatim_quote_from_unreviewed_archive_pdf"
                reason_code = "qa_archive_contextual_device_verbatim"
                claim_text = text
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": results,
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": [{"text": claim_text, "citation_ids": [source["citation_id"]]}],
                    "failed_claims": [],
                    "validation_scope": validation_scope,
                },
                "reason_code": reason_code,
                "source_relevance": float(source.get("similarity_score") or 0),
                "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                "generation_attempts": [],
            }
            return

    # For an explicitly identified article, quote the retrieved PDF text rather
    # than asking a small local model to paraphrase it. This makes the first QA
    # MVP useful even when Ollama's claim validator rejects a semantically sound
    # paraphrase, and it cannot add facts absent from the extracted article.
    parsed_references = parse_normative_references(question)
    exact_references = [ref for ref in parsed_references if not ref.ambiguous]
    query_plan = classify_normative_query(question)
    article_targets = tuple(query_plan.article_targets)
    explicit_article_norm_pairs = tuple(dict.fromkeys(_explicit_article_norm_pairs(question)))
    has_complete_explicit_article_pairing = (
        bool(explicit_article_norm_pairs)
        and len(explicit_article_norm_pairs) == len(_article_reference_mentions(question))
    )
    requested_facets = _requested_topic_facets(question)
    # The reference parser intentionally marks a single norm mention as
    # ambiguous when a question names multiple articles: it cannot attach one
    # hierarchy to the norm. The norm identity itself is still explicit when
    # there is exactly one typed, year-qualified reference and the classifier
    # retained it as a provision query. Preserve that distinction so failed
    # synthesis can fall back to the requested article evidence instead of
    # incorrectly reporting that retrieval found nothing.
    single_explicit_norm_article_scope = (
        len(parsed_references) == 1
        and parsed_references[0].year is not None
        and len(article_targets) > 1
        and query_plan.kind == "provision"
        and query_plan.reference is not None
        and query_plan.reference.identity == parsed_references[0].identity
    )
    paired_explicit_norm_article_scope = (
        len(_explicit_article_norm_pairs(question)) == len(_article_reference_mentions(question))
        and len(article_targets) > 1
        and len({identity for identity, _article in _explicit_article_norm_pairs(question)}) == 1
        and not _cross_reference_scan_scope(question)
    )
    single_explicit_norm_article_scope = (
        single_explicit_norm_article_scope or paired_explicit_norm_article_scope
    )
    has_single_explicit_norm = len(exact_references) == 1 or single_explicit_norm_article_scope
    requires_article_coverage = (
        has_single_explicit_norm
        and len(article_targets) > 1
        and bool(_MULTI_ARTICLE_SYNTHESIS_RE.search(question))
    )
    if (
        has_single_explicit_norm
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
                source.get("full_text") and source.get("citation_id") for source in ordered_sources
            )
            and all(
                (source.get("coverage") or {}).get("complete", True) for source in ordered_sources
            )
        )
        if complete_comparison:
            transition_pair = _archive_explicit_transition_pair_synthesis(question, results)
            if transition_pair is not None:
                answer, transition_claims = transition_pair
                yield {"event": "status", "status": "grounding"}
                for offset in range(0, len(answer), 72):
                    raise_if_cancelled(should_cancel)
                    yield {
                        "event": "chunk",
                        "chunk": answer[offset : offset + 72],
                        "provisional": False,
                    }
                yield {"event": "status", "status": "finalizing"}
                yield {
                    "event": "done",
                    "answer": answer,
                    "sources": results,
                    "grounded": True,
                    "grounding": {
                        "grounded": True,
                        "score": 1.0,
                        "claims": transition_claims,
                        "failed_claims": [],
                        "validation_scope": "explicit_protocol_and_transition_articles_only_no_case_adjudication",
                    },
                    "reason_code": "qa_archive_explicit_transition_pair_synthesis",
                    "source_relevance": min(
                        float(source.get("similarity_score") or 0) for source in ordered_sources
                    ),
                    "timings_ms": {"retrieval": retrieval_ms, "generation": 0},
                    "generation_attempts": [],
                }
                yield {"event": "status", "status": "completed"}
                return

            source_indexes = {
                source["citation_id"]: index for index, source in enumerate(results, 1)
            }
            norm_label = ordered_sources[0]["norma_ref"]
            lines = [
                f"Nos trechos recuperados de **{norm_label}**, os dispositivos solicitados dizem:"
            ]
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
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
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
    transition_scope_question = bool(_PROCESS_TRANSITION_SCOPE_REQUEST_RE.search(question))
    if (
        (len(exact_references) == 1 or (contextual_device_scope and transition_scope_question))
        and len(results) == 1
        and (not contextual_device_scope or transition_scope_question)
        and (article_match or transition_scope_question)
    ):
        source = results[0]
        text = str(source.get("full_text") or "").strip()
        if text:
            device_label = _archive_device_label(source["dispositivo_ref"], source["norma_ref"])
            transition_evidence = bool(_PROCESS_TRANSITION_EVIDENCE_RE.search(text))
            transition_scope_answer = bool(
                transition_evidence
                and (_ARTICLE_SCOPE_LIMITS_REQUEST_RE.search(question) or transition_scope_question)
            )
            article_scope_limits_answer = bool(
                not transition_scope_answer
                and (
                    _ARTICLE_SCOPE_LIMITS_REQUEST_RE.search(question)
                    or _CASE_RECORD_SUFFICIENCY_REQUEST_RE.search(question)
                )
            )
            if transition_scope_answer and _AUTO_NEW_LAW_AFTER_DECISION_QUERY_RE.search(question):
                answer = (
                    f"O trecho recuperado de **{device_label}** não determina que a lei nova "
                    "se aplique automaticamente quando já existe despacho decisório. Ele trata "
                    "expressamente dos processos protocolados até a entrada em vigor e ainda sem "
                    "despacho, que seguem a legislação da data do protocolo, ressalvada a opção "
                    f"formal prevista no próprio artigo: “{text}” [[1]].\n\n"
                    "Portanto, este dispositivo isolado não define o regime aplicável a um processo "
                    "que já tinha despacho; essa conclusão exige conferir os demais dispositivos, "
                    "a publicação oficial e os fatos dos autos. A extração local ainda está sob "
                    "revisão e não substitui essa conferência."
                )
            elif transition_scope_answer:
                amendment_limit = (
                    " O acervo consultado também não contém uma cadeia de alterações e revogações "
                    "revisada; não permite afirmar se este dispositivo mudou depois."
                    if query_plan.relation_intent in {"modification", "mixed"}
                    else ""
                )
                answer = (
                    f"Encontrei no PDF a regra transitória do {device_label}: em síntese, "
                    "processos protocolados até a entrada em vigor da lei e ainda sem despacho "
                    "decisório são apreciados conforme a legislação vigente na data do protocolo; "
                    "o dispositivo ressalva a opção formal do interessado pela análise integral "
                    f"segundo a lei nova. O trecho recuperado diz: “{text}” [[1]]\n\n"
                    "Para verificar se o cenário se enquadra, confira no processo: (1) a data do "
                    "protocolo; (2) a data oficial de entrada em vigor da LC 258/2024; (3) se já "
                    "havia despacho decisório; e (4) se existe manifestação formal pela análise "
                    "integral conforme a lei nova. Depois, identifique a redação oficial vigente "
                    "na data do protocolo.\n\n"
                    "A extração local, ainda pendente de revisão, não comprova esses fatos nem "
                    "substitui a conferência da publicação oficial e dos autos."
                    f"{amendment_limit} Com apenas este "
                    "trecho, não concluo qual regime rege um processo concreto."
                )
            elif article_scope_limits_answer:
                if _CASE_RECORD_SUFFICIENCY_REQUEST_RE.search(question):
                    answer = (
                        f"O {device_label} trata de notificações para correções, esclarecimentos "
                        f"e complementações durante o licenciamento: “{text}” [[1]]\n\n"
                        "**Esse artigo isolado não informa quais documentos foram juntados aos autos "
                        "nem permite concluir se a documentação do processo está completa ou suficiente.** "
                        "O trecho não examina os autos. Confira a lista de documentos do "
                        "processo, as pendências registradas e a redação oficial aplicável na "
                        "data relevante.\n\n"
                        "*Transcrição automática do acervo local; extração e segmentação ainda "
                        "estão sob revisão. Confira o PDF original antes de usar.*"
                    )
                else:
                    answer = (
                        f"No PDF arquivado, {device_label} estabelece: "
                        f"“{text}” [[1]]\n\n"
                        "Esse trecho, por si só, não permite concluir se uma obra específica "
                        "está regular hoje: ele não avalia o projeto, a situação do imóvel nem "
                        "eventuais exigências de outros dispositivos. Para essa conclusão, seria "
                        "necessário conferir os documentos do caso e a redação oficial aplicável "
                        "na data relevante.\n\n"
                        "*Transcrição automática do acervo local; extração e segmentação ainda "
                        "estão sob revisão. Confira o PDF original antes de usar.*"
                    )
            else:
                answer = (
                    f"No PDF arquivado, "
                    f"{device_label} "
                    f"estabelece: "
                    f"“{text}” [[1]]\n\n"
                    "*Transcrição automática; metadados e segmentação ainda estão sob revisão. "
                    "Confira o PDF original antes de usar.*"
                )
            search_limit = _related_matter_search_limit(
                related_matter_status, article_scope=bool(query_plan.article_targets)
            )
            if search_limit:
                answer = f"{answer}\n\n{search_limit}"
            if supplemental_sources:
                answer = append_supplemental_matter_notes(answer)
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
            yield {"event": "status", "status": "finalizing"}
            yield {
                "event": "done",
                "answer": answer,
                "sources": [*results, *supplemental_sources],
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "score": 1.0,
                    "claims": (
                        (
                            [
                                {
                                    "text": "O trecho do artigo não determina aplicação automática da lei nova quando já existe despacho decisório.",
                                    "citation_ids": [source["citation_id"]],
                                },
                                {
                                    "text": "O dispositivo regula expressamente processos sem despacho e não permite definir sozinho o regime de um processo já decidido.",
                                    "citation_ids": [source["citation_id"]],
                                },
                            ]
                            if _AUTO_NEW_LAW_AFTER_DECISION_QUERY_RE.search(question)
                            else [
                                {
                                    "text": f"O {device_label} contém a regra transitória transcrita do PDF local.",
                                    "citation_ids": [source["citation_id"]],
                                },
                                {
                                    "text": "A aplicação ao caso depende da conferência das datas, da existência de despacho, de eventual manifestação formal e da redação oficial na data do protocolo.",
                                    "citation_ids": [source["citation_id"]],
                                },
                            ]
                        )
                        if transition_scope_answer
                        else [{"text": text, "citation_ids": [source["citation_id"]]}]
                    ),
                    "failed_claims": [],
                    "validation_scope": (
                        "single_unreviewed_transition_article_with_case_fact_checklist"
                        if transition_scope_answer
                        else (
                            "article_scope_limitation_without_case_file_access"
                            if article_scope_limits_answer
                            else "verbatim_quote_from_unreviewed_archive_pdf"
                        )
                    ),
                },
                "reason_code": (
                    "qa_archive_transition_scope_explanation"
                    if transition_scope_answer
                    else (
                        "qa_archive_article_application_limits"
                        if article_scope_limits_answer
                        else "qa_archive_verbatim_article"
                    )
                ),
                "source_relevance": source.get("similarity_score"),
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
        if (
            exact_phrase_sources
            and len({str(source.get("norma_ref") or "") for source in exact_phrase_sources}) == 1
        ):
            source_indexes = {
                source["citation_id"]: index for index, source in enumerate(results, 1)
            }
            norma_ref = str(exact_phrase_sources[0].get("norma_ref") or "norma consultada")
            article_refs = "\n".join(
                f"- [[{source_indexes[source['citation_id']]}]]" for source in exact_phrase_sources
            )
            answer = (
                f"A expressão consultada **“{article_topic_label}”** aparece nos seguintes "
                f"trechos de **{norma_ref}**:\n\n{article_refs}\n\n"
                "Esta busca localiza a expressão na transcrição do PDF; confira os trechos "
                "originais antes de interpretar ou aplicar a norma. A extração ainda está sob revisão."
            )
            yield {"event": "status", "status": "grounding"}
            for offset in range(0, len(answer), 72):
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "chunk",
                    "chunk": answer[offset : offset + 72],
                    "provisional": False,
                }
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
                f"A recuperação encontrou evidências em {selected} de {total} artigos identificados. "
                "Essa contagem não significa que todos serão resumidos; a geração pode usar uma amostra menor. "
            )
            coverage_disclosure = (
                f"A recuperação encontrou evidências em {selected} de {total} artigos identificados. "
                "A síntese abaixo usa apenas os excertos explicitados a seguir; não representa uma análise integral da norma. "
            )
        if coverage.get("annexes_present"):
            if coverage.get("selected_articles") == coverage.get("total_articles") and isinstance(
                coverage.get("total_articles"), int
            ):
                article_count = coverage["total_articles"]
                coverage_prompt_note += (
                    f"Todos os {article_count} artigos identificados foram selecionados, "
                    "mas os anexos normativos detectados não foram incluídos. "
                )
                coverage_disclosure = (
                    f"A recuperação encontrou evidências em {article_count} de {article_count} "
                    "artigos identificados. Os anexos normativos detectados não foram incluídos "
                    "nesta seleção; portanto, a visão geral é parcial e não representa uma "
                    "análise integral da norma."
                )
            coverage_prompt_note += (
                "O PDF contém anexos normativos que não foram incluídos na seleção de artigos. "
            )
            if coverage.get("selected_articles") != coverage.get("total_articles"):
                coverage_disclosure += "Anexos normativos também foram detectados no PDF e devem ser consultados à parte. "
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
        and (selected_articles < total_articles or coverage.get("annexes_present") is True)
    )
    if (
        whole_norm_overview
        and _COVERAGE_SCOPE_REQUEST_RE.search(question)
        and not coverage_disclosure
    ):
        coverage_disclosure = _coverage_scope_disclosure(coverage)
    if partial_norm_overview:
        # A 24k-character context containing dozens of complete provisions
        # overwhelms small local models and encourages narrow, rejected drafts.
        # Give generation a deterministic, distributed evidence sample while
        # keeping the full retrieval set for source cards and validation.
        prompt_excerpts = _partial_overview_excerpts(
            results,
            # The overview contract asks for at most three independent claims.
            # Do not offer the model extra excerpt choices that invite it to
            # exceed that contract or reuse a citation across claims.
            limit=min(
                _PARTIAL_OVERVIEW_MIN_CITED_SOURCES,
                _partial_overview_sample_limit(len(results)),
            ),
            max_chars=1200,
            question=question,
        )
        if prompt_excerpts:
            excerpt_by_index = {excerpt["citation_index"]: excerpt for excerpt in prompt_excerpts}
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
                validation_results.append(
                    {
                        **source,
                        "citation_index": index,
                        "evidence_text": excerpt["text"] if excerpt else "",
                    }
                )
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
                f" Para esta síntese, a geração usou {sampled_count} "
                f"{'excerto' if sampled_count == 1 else 'excertos'} de "
                f"{recovered_count} "
                f"{'dispositivo' if recovered_count == 1 else 'dispositivos'} recuperados. A resposta "
                "cita apenas os excertos que sustentam as afirmações apresentadas; os "
                "demais dispositivos não foram resumidos."
            )
    # Article-specific answers stay buffered until exact target coverage is
    # confirmed. Partial norm overviews instead release a prefix as soon as it
    # is both grounded and broad enough; this preserves safe progressive SSE.
    # Topic/facet requests remain buffered until all requested facets are
    # covered. For multi-article requests, wait only for the first grounded,
    # cited requested article, then stream the validator-approved remainder;
    # missing requested devices are disclosed explicitly at finalization.
    hold_generated_chunks = bool(requested_facets)
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
    prompt += _multi_norm_synthesis_instruction(question)
    prompt += _same_norm_article_synthesis_instruction(question)
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
                    sources=results,
                )
                and not has_redundant_content_phrase(answer)
                and not has_repeated_citation_marker(answer)
            )
            if partial_norm_overview
            else None
        ),
        stop_after_validated_prefix=(
            lambda answer, _validation: (
                _has_partial_overview_breadth(
                    answer,
                    len(results),
                    available_sample_sources=len(prompt_excerpts),
                    sources=results,
                )
                and not has_redundant_content_phrase(answer)
                and not has_repeated_citation_marker(answer)
            )
            if partial_norm_overview
            else None
        ),
        include_partial_notice=not partial_norm_overview,
        revision_instruction=(
            _PARTIAL_OVERVIEW_REVISION_INSTRUCTION if partial_norm_overview else None
        )
        or None,
    )
    streamed_answer = ""
    public_streamed_answer = ""
    public_stream_stopped = False
    article_coverage_buffer = ""
    article_coverage_released = False
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
                            sources=results,
                        )
                        and not has_redundant_content_phrase(candidate)
                        and not has_repeated_citation_marker(candidate)
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
                    and not has_repeated_citation_marker(candidate)
                ):
                    delta = candidate[len(public_streamed_answer) :]
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
            elif requires_article_coverage and not requested_facets:
                if not article_coverage_released:
                    article_coverage_buffer += generation_event.get("chunk", "")
                    if any(
                        _has_requested_article_coverage(article_coverage_buffer, (target,), results)
                        for target in article_targets
                    ):
                        article_coverage_released = True
                        public_streamed_answer = article_coverage_buffer
                        yield {
                            "event": "chunk",
                            "chunk": article_coverage_buffer,
                            "provisional": False,
                        }
                else:
                    chunk = generation_event.get("chunk", "")
                    public_streamed_answer += chunk
                    yield generation_event
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
        grounded
        and requested_facets
        and not _has_cited_facet_coverage(generation_answer, results, requested_facets)
    ):
        grounded = False
        # Facet-list answers remain buffered until every listed topic is
        # represented by a cited excerpt. The deterministic evidence map below
        # will disclose which requested topics were and were not retrieved.
        streamed_answer = ""
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
            prefix_candidates.append(
                {
                    "answer": generation_answer,
                    "grounding": generation_grounding,
                    "source_only": generation["source_only"],
                }
            )
        eligible_prefixes = [
            item
            for item in prefix_candidates
            if item.get("source_only")
            and bool((item.get("grounding") or {}).get("grounded"))
            and not has_redundant_content_phrase(str(item.get("answer") or ""))
            and not has_repeated_citation_marker(str(item.get("answer") or ""))
            and _has_partial_overview_breadth(
                str(item.get("answer") or ""),
                len(results),
                available_sample_sources=len(prompt_excerpts),
                sources=results,
            )
        ]
        if eligible_prefixes:
            chosen_prefix = max(
                eligible_prefixes,
                key=lambda item: (
                    len(
                        {
                            int(index)
                            for index in re.findall(r"\[\[(\d+)\]\]", str(item.get("answer") or ""))
                        }
                    ),
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
            sources=results,
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
    partial_article_coverage = False
    missing_article_targets: tuple[str, ...] = ()
    if grounded and requires_article_coverage:
        missing_article_targets = _requested_articles_without_coverage(
            generation_answer, article_targets, results
        )
    if grounded and missing_article_targets:
        if hold_generated_chunks or not article_coverage_released:
            grounded = False
            # The incomplete candidate was buffered, never emitted. The
            # evidence-map fallback is now the only answer sent to the user.
            streamed_answer = ""
        elif public_streamed_answer:
            # Preserve the already-visible, validated prefix. Finalize with a
            # clear disclosure for each requested article not covered by it.
            generation_answer = public_streamed_answer
            partial_article_coverage = True
    if grounded:
        answer = generation_answer
        if partial_article_coverage:
            source_indexes = {
                _article_key(str(source.get("dispositivo_ref") or "")): index
                for index, source in enumerate(results, 1)
                if source.get("citation_id")
            }
            disclosures = []
            for target in missing_article_targets:
                source_index = source_indexes.get(_article_key(target))
                article_label = f"Art. {target}"
                if source_index:
                    disclosures.append(
                        f"**{article_label}** foi recuperado ([[{source_index}]]), "
                        "mas não entrou na síntese validada."
                    )
                else:
                    disclosures.append(
                        f"Não localizei evidência recuperada suficiente para **{article_label}**."
                    )
            answer += "\n\n" + "A resposta é parcial: " + " ".join(disclosures)
        if coverage_disclosure:
            answer += "\n\n" + coverage_disclosure.rstrip()
        grounding_report = dict(generation_grounding)
        if partial_norm_overview:
            grounding_report["validation_scope"] = (
                "grounded_generated_claims_against_sampled_excerpts_from_unreviewed_archive_pdf"
            )
        reason_code = (
            "generation_partial_missing_requested_article"
            if partial_article_coverage
            else (
                "generation_partial_after_grounded_prefix"
                if generation.get("partial") or public_stream_stopped
                else None
            )
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
            references_by_norma.setdefault(norma_ref, []).append(f"{dispositivo_ref} [[{index}]]")
        reference_groups = [
            f"**{norma_ref}**: {', '.join(dispositivos)}"
            for norma_ref, dispositivos in references_by_norma.items()
        ]
        comparison_fallback = False
        evidence_map_fallback = False
        if partial_norm_overview:
            excerpts = _partial_overview_excerpts(
                results,
                # A rejected synthesis should degrade to a short evidence map,
                # not reproduce the entire generation sample as six quotes.
                # Keep the full recovered set in the source drawer.
                limit=min(
                    _PARTIAL_OVERVIEW_MIN_CITED_SOURCES,
                    _partial_overview_sample_limit(len(results)),
                ),
                question=question,
            )
            if isinstance(selected_articles, int) and isinstance(total_articles, int):
                evidence_count = "um" if selected_articles == 1 else str(selected_articles)
                excerpt_label = "excerto" if len(excerpts) == 1 else "excertos"
                partial_disclosure = (
                    f"A recuperação reuniu evidências em {evidence_count} dos "
                    f"{total_articles} artigos identificados na extração. Abaixo aparecem "
                    f"{len(excerpts)} {excerpt_label} selecionados; este mapa é parcial e não é "
                    "uma síntese integral da norma."
                )
            else:
                partial_disclosure = (
                    "A amostra recuperada é parcial e não permite analisar integralmente a norma."
                )
            answer_parts = [partial_disclosure]
            if coverage.get("annexes_present"):
                answer_parts.append(
                    "O PDF contém anexos identificados que não foram incluídos nessa seleção."
                )
            topic_scoped_partial = (
                bool(_whole_norm_topic_tokens(question))
                and isinstance(selected_articles, int)
                and isinstance(total_articles, int)
                and selected_articles < total_articles
            )
            answer_parts.append(
                "Para uma triagem inicial, seguem excertos literais e abreviados de dispositivos "
                "com correspondência textual ao assunto indicado. A seleção prioriza esse tema, "
                "mas continua parcial e não analisa os fatos do processo:"
                if topic_scoped_partial
                else (
                    "Para uma triagem inicial, seguem excertos literais e abreviados de diferentes "
                    "partes da norma. Eles ajudam a localizar os temas no PDF, mas não analisam os "
                    "fatos do processo nem representam uma síntese integral:"
                )
            )
            answer_parts.extend(_partial_overview_evidence_narrative(excerpts))
            limits_disclosure = _partial_overview_limits_disclosure(question)
            if limits_disclosure:
                answer_parts.append(limits_disclosure)
            triage_checklist = _partial_overview_triage_checklist(question)
            if triage_checklist:
                answer_parts.append(triage_checklist)
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
            has_single_explicit_norm
            and len(article_targets) > 1
            and _MULTI_ARTICLE_SYNTHESIS_RE.search(question)
        ):
            sources_by_article = {
                _article_key(str(source.get("dispositivo_ref") or "")): source
                for source in results
                if source.get("citation_id") and str(source.get("full_text") or "").strip()
            }
            requested_sources = [sources_by_article.get(article) for article in article_targets]
            same_complete_norm = (
                all(requested_sources)
                and len({str(source.get("norma_ref") or "") for source in requested_sources}) == 1
                and all(
                    (source.get("coverage") or {}).get("complete", True)
                    for source in requested_sources
                )
            )
            if same_complete_norm:
                source_indexes = {
                    source["citation_id"]: index for index, source in enumerate(results, 1)
                }
                answer_lines = ["Nos trechos recuperados, os dispositivos indicados estabelecem:"]
                for source in requested_sources:
                    citation = source_indexes[source["citation_id"]]
                    quote = str(source["full_text"]).strip()
                    article_ref = source.get("dispositivo_ref") or "Dispositivo"
                    answer_lines.append(f"- **{article_ref}**: “{quote}” [[{citation}]]")
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
        else:
            topical_evidence_map = not (
                has_single_explicit_norm or has_complete_explicit_article_pairing
            )
            if requested_facets:
                facet_sources = [
                    (index, source)
                    for index, source in enumerate(results, 1)
                    if source.get("citation_id")
                    and any(_source_matches_facet(facet, source) for facet in requested_facets)
                ]
                distinct_norms = list(
                    dict.fromkeys(
                        str(source.get("norma_ref") or "Norma não identificada")
                        for _index, source in facet_sources
                    )
                )
                if not facet_sources:
                    answer = (
                        "Não encontrei evidência direta suficiente nos trechos recuperados "
                        "para sustentar essa resposta com segurança; não vou associar fontes "
                        "periféricas ao tema. Tente informar o número da norma ou um artigo "
                        "específico."
                    )
                    facet_claims = []
                    # Keep the abstention authoritative; the generic source
                    # index fallback below must not relabel peripheral rows
                    # as useful evidence.
                    evidence_map_fallback = True
                elif len(distinct_norms) > 1:
                    answer_lines = [
                        "Os excertos recuperados sustentam referências em normas distintas:"
                    ]
                    facet_claims = []
                    for index, source in facet_sources:
                        norm_label = str(source.get("norma_ref") or "Norma não identificada")
                        device = str(source.get("dispositivo_ref") or "dispositivo")
                        quote = str(source.get("full_text") or "").strip()
                        answer_lines.append(f"- **{norm_label}, {device}**: “{quote}” [[{index}]]")
                        facet_claims.append(
                            {
                                "text": f"Transcrição de {device} de {norm_label}",
                                "citation_ids": [source["citation_id"]],
                            }
                        )
                    answer_lines.append(
                        "Essas extrações ainda estão pendentes de revisão. Elas não confirmam "
                        "a redação vigente e não permitem concluir se uma obra específica atende "
                        "às exigências; confira cada PDF e a redação oficial aplicável."
                    )
                    answer = "\n\n".join(answer_lines)
                    evidence_map_fallback = True
                else:
                    answer, facet_claims = _facet_evidence_map(
                        requested_facets,
                        results,
                        history_requested=(
                            query_plan.relation_intent in {"modification", "mixed"}
                            or bool(_DIRECT_NORMATIVE_HISTORY_REQUEST_RE.search(question))
                        ),
                    )
                    evidence_map_fallback = True
                grounding_report = {
                    "grounded": bool(facet_claims),
                    "score": 1.0 if facet_claims else 0.0,
                    "claims": facet_claims,
                    "failed_claims": [],
                    "validation_scope": "facet_by_facet_verbatim_evidence_map_from_unreviewed_archive_pdf",
                }
                grounded = bool(facet_claims)
                reason_code = (
                    "qa_archive_facet_evidence_map"
                    if grounded
                    else "qa_archive_topical_evidence_insufficient"
                )
            else:
                excerpts = _partial_overview_excerpts(
                    results,
                    limit=3,
                    question=question,
                    topical_only=topical_evidence_map,
                )
            if requested_facets:
                pass
            elif excerpts:
                answer_parts = [
                    "A busca local recuperou estes trechos relacionados à pergunta. Eles ajudam na "
                    "conferência, mas não comprovam que todos os dispositivos pertinentes foram encontrados:"
                ]
                excerpt_normas = list(
                    dict.fromkeys(
                        str(
                            results[excerpt["citation_index"] - 1].get("norma_ref")
                            or "Norma não identificada na extração"
                        )
                        for excerpt in excerpts
                    )
                )
                if len(excerpt_normas) > 1:
                    answer_parts.append(
                        "A recuperação encontrou dispositivos de normas distintas — "
                        + "; ".join(excerpt_normas)
                        + ". Mantenho os textos separados: esta busca não identifica, por si só, "
                        "qual redação rege a situação ou o período analisado."
                    )
                answer_parts.extend(
                    "- "
                    f"{results[excerpt['citation_index'] - 1].get('norma_ref') or 'Norma não identificada'}, "
                    f"{excerpt['device']}: “{excerpt['text']}” [[{excerpt['citation_index']}]]"
                    for excerpt in excerpts
                )
                missing_reference_pairs = _missing_explicit_article_norm_pairs(
                    question, results
                )
                if missing_reference_pairs:
                    answer_parts.append(
                        "Não localizei evidência legível entre as fontes recuperadas para "
                        + ", ".join(missing_reference_pairs)
                        + ". Isso não confirma que o dispositivo ou a norma não exista; "
                        "significa apenas que esta busca não trouxe esse trecho para conferência."
                    )
                if _ARTICLE_SCOPE_LIMITS_REQUEST_RE.search(question):
                    answer_parts.append(
                        "Esses excertos, isoladamente, não permitem concluir se uma obra "
                        "específica atende às exigências. Essa avaliação depende dos dados e "
                        "documentos do projeto, da confirmação da redação oficial aplicável "
                        "na data relevante e da verificação das normas técnicas citadas."
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
                if topical_evidence_map:
                    answer = (
                        "Não encontrei, nos trechos recuperados, um dispositivo que sustente "
                        "diretamente esse tema. Para evitar indicar artigos periféricos como se "
                        "respondessem à pergunta, não vou associar fontes a esta resposta. "
                        "Tente informar o número e o ano da norma ou reformular o tema com um "
                        "termo presente no texto legal."
                    )
                    grounded = False
                    reason_code = "qa_archive_topical_evidence_insufficient"
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
                    grounded = bool(reference_groups)
                    reason_code = "qa_archive_evidence_only_fallback"
                # This branch handled the failed synthesis explicitly. Do not
                # let the generic evidence-index fallback below relabel weak
                # topic matches as grounded.
                grounding_report = {
                    "grounded": grounded,
                    "score": 0.0,
                    "claims": [
                        {
                            "text": f"Dispositivo localizado: {source.get('norma_ref')}, {source.get('dispositivo_ref')}",
                            "citation_ids": [source["citation_id"]],
                        }
                        for source in results
                        if grounded and source.get("full_text") and source.get("citation_id")
                    ],
                    "failed_claims": [] if grounded else [question],
                    "validation_scope": "topical_evidence_unavailable"
                    if topical_evidence_map and not grounded
                    else "retrieved_source_index_only_after_synthesis_rejected",
                }
                evidence_map_fallback = True
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
    search_limit = _related_matter_search_limit(
        related_matter_status, article_scope=bool(query_plan.article_targets)
    )
    if search_limit and search_limit not in answer:
        answer = f"{answer}\n\n{search_limit}"
    if grounded and supplemental_sources:
        answer = append_supplemental_matter_notes(answer)
    yield {"event": "status", "status": "grounding" if grounded else "insufficient_evidence"}
    if partial_norm_overview:
        streamed_answer = public_streamed_answer if grounded else ""
    elif hold_generated_chunks:
        # The model's chunks were buffered for grounding/article-coverage
        # validation and never sent to the client. Do not treat that private
        # buffer as text already visible in the browser; release the validated
        # canonical answer through SSE now.
        streamed_answer = ""
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
        "sources": [*results, *supplemental_sources] if grounded else [],
        "grounded": grounded,
        "grounding": grounding_report,
        "reason_code": reason_code,
        "source_relevance": max(row["similarity_score"] for row in results),
        "timings_ms": {
            "retrieval": retrieval_ms,
            "generation": sum(
                attempt["duration_ms"] for attempt in generation["generation_attempts"]
            ),
        },
        "generation_attempts": generation["generation_attempts"],
    }
