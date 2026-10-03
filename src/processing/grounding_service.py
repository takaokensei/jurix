"""Claim-to-evidence grounding for Jurix RAG responses.

The service maps individual claims to the specific evidence items retrieved for
the answer. It does not expose similarity as calibrated answer confidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

_CLAUSE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_CITATION_RE = re.compile(
    r"\b(lei(?:\s+complementar|\s+ordinária|\s+orgânica)?|decreto(?:-lei|\s+legislativo)?|"
    r"resolução|emenda(?:\s+constitucional)?|portaria)\s+n?[º°o.]*\s*([\d.]+)\s*[/,]\s*(\d{2,4})",
    re.IGNORECASE,
)
_REFERENCE_ONLY_RE = re.compile(
    r"^(?:(?:lei(?:\s+(?:complementar|ordinária|orgânica))?|decreto(?:-lei|\s+legislativo)?|"
    r"resolução|emenda(?:\s+constitucional)?|portaria)\s+n?[º°o.]*\s*[\d.]+\s*[/,]\s*\d{2,4})"
    r"(?:\s*(?:[,;]\s*)?(?:arts?\.?\s*\d+[º°o]?"
    r"(?:\s*,\s*(?:inciso\s+[ivxlcdm]+|§\s*\d+[º°o]?|parágrafo\s+(?:único|\d+[º°o]?)))?))*$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{4,}", re.UNICODE)

_STOPWORDS = {
    "para",
    "como",
    "sobre",
    "entre",
    "essa",
    "este",
    "esta",
    "esse",
    "isso",
    "que",
    "uma",
    "por",
    "dos",
    "das",
    "com",
    "sem",
    "nos",
    "nas",
    "aos",
    "pelos",
    "pelas",
    "qual",
    "quais",
    "onde",
    "quando",
    "quem",
    "porque",
    "são",
    "ser",
    "tem",
    "mais",
    "menos",
    "muito",
    "muita",
    "muitas",
    "muitos",
    "pelo",
    "pela",
    "e",
    "ou",
    "portanto",
    "assim",
    "disso",
    "dessa",
    "dessas",
    "desse",
    "desses",
    "desta",
    "destas",
    "deste",
    "destes",
    "essas",
    "esses",
    "estas",
    "estes",
    "aquele",
    "aquela",
    "aqueles",
    "aquelas",
    "aquilo",
    "ademais",
    "outrossim",
    "sendo",
    "diante",
    "conforme",
    "segundo",
    "dispositivo",
    "dispositivos",
}
_NUMBER_WORDS = {
    "zero",
    "um",
    "uma",
    "dois",
    "duas",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "catorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
    "cem",
    "cento",
    "mil",
}


@dataclass(frozen=True)
class Claim:
    text: str
    citation_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    dispositivo_id: int | None
    text: str
    norma_ref: str
    identifier: str = ""
    start: int | None = None
    end: int | None = None
    dispositivo_ids: tuple[Any, ...] = ()
    citation_ids: tuple[str, ...] = ()
    norma_id: Any = None
    tipo: str = ""
    parent_id: Any = None
    parent_tipo: str = ""
    parent_norma_id: Any = None
    snippet_truncated: bool = False


@dataclass(frozen=True)
class ClaimEvidence:
    claim: str
    supported: bool
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    score: float
    claims: tuple[ClaimEvidence, ...]
    failed_claims: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "score": self.score,
            "claims": [
                {
                    "claim": item.claim,
                    "supported": item.supported,
                    "evidence": [asdict(ev) for ev in item.evidence],
                }
                for item in self.claims
            ],
            "failed_claims": list(self.failed_claims),
        }


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _stem(word: str) -> str:
    w = word.lower()
    for suffix in (
        "imentos",
        "imento",
        "ações",
        "ação",
        "acoes",
        "acao",
        "ições",
        "ição",
        "icoes",
        "icao",
        "idades",
        "idade",
        "amente",
        "mente",
        "tórios",
        "tório",
        "torios",
        "torio",
        "ativos",
        "ativo",
        "ativas",
        "ativa",
        "áveis",
        "ável",
        "aveis",
        "avel",
        "íveis",
        "ível",
        "iveis",
        "ivel",
        "âncias",
        "ância",
        "encias",
        "ência",
        "ismos",
        "ismo",
        "istas",
        "ista",
        "ados",
        "adas",
        "ado",
        "ada",
        "idos",
        "idas",
        "ido",
        "ida",
        "ando",
        "endo",
        "indo",
        "arem",
        "erem",
        "irem",
        "asse",
        "esse",
        "isse",
        "avam",
        "avas",
        "ava",
        "aria",
        "eria",
        "iria",
        "ores",
        "oras",
        "ora",
        "or",
        "ais",
        "eis",
        "al",
        "el",
        "ões",
        "oes",
        "ãos",
        "aos",
        "am",
        "em",
        "os",
        "as",
        "es",
        "o",
        "a",
        "e",
    ):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def _tokens(text: str) -> set[str]:
    raw_tokens = [
        token for token in _WORD_RE.findall((text or "").lower()) if token not in _STOPWORDS
    ]
    return {_stem(token) for token in raw_tokens}


def _is_reference_only_line(line: str) -> bool:
    """Recognize a standalone legal citation without suppressing factual text."""
    normalized = re.sub(r"^[-–—•\d.)\]]+\s*", "", line.strip())
    normalized = normalized.strip("*_` \t")
    return bool(_REFERENCE_ONLY_RE.fullmatch(normalized))


def extract_claims(answer: str) -> tuple[Claim, ...]:
    """Split a generated answer into independently auditable claims."""
    claims: list[Claim] = []
    # Filter out markdown formatting headers and dividers before claim extraction
    cleaned_lines = []
    _STRUCTURAL_HEADERS = {
        "resposta",
        "análise",
        "analise",
        "conclusão",
        "conclusao",
        "requisitos",
        "conteúdo",
        "conteudo",
        "observação",
        "observacao",
        "observações",
        "observacoes",
        "nota",
        "notas",
        "nota importante",
        "aviso",
        "avisos",
        "atenção",
        "atencao",
        "disclaimer",
        "ressalva",
        "ressalvas",
        "consideração",
        "consideracao",
        "considerações",
        "consideracoes",
        "considerações adicionais",
        "consideracoes adicionais",
        "considerações finais",
        "consideracoes finais",
        "resumo",
        "dispositivos",
        "fundamentação",
        "fundamentacao",
        "síntese",
        "sintese",
        "informações adicionais",
        "informacoes adicionais",
        "conclusão e regras aplicáveis",
        "conclusao e regras aplicaveis",
        "fonte",
        "fontes",
        "fonte consultada",
        "fontes consultadas",
        "referência",
        "referências",
        "referencias",
    }
    for line in (answer or "").splitlines():
        trimmed = line.strip()
        if _is_reference_only_line(trimmed):
            continue
        # Markdown headers (# Header) are formatting, not substantive claims
        if trimmed.startswith("#"):
            continue
        # Markdown dividers (---, ***, ___, ===) or header underlines (===..., ---...)
        if re.match(r"^[-=_*~]{2,}$", trimmed):
            continue
        # Source attribution lines like **Fonte:** Lei..., Fonte: ...
        if re.match(r"^[-–—•\s]*(?:\*\*)?fontes?(?:\s+consultadas?)?(?:\*\*)?\s*:", trimmed, re.I):
            continue
        # Structural headers like **Resposta:**, **Conclusão:**, - **Conclusão**, etc.
        unbulleted = re.sub(r"^[-–—•\d.)\]\s]+", "", trimmed).strip()
        clean_header = unbulleted.strip("*_#: \t").lower()
        if clean_header in _STRUCTURAL_HEADERS:
            continue
        if trimmed:
            cleaned_lines.append(trimmed)

    cleaned_text = "\n\n".join(cleaned_lines)
    # Protect common legal abbreviations so Art. 1º or nº. 2 is not split mid-token
    protected = re.sub(
        r"\b(art|arts|fl|fls|inc|n[º°o]|par)\.\s*",
        r"\1@@DOT@@ ",
        cleaned_text,
        flags=re.I,
    )
    _PREAMBLE_RE = re.compile(
        r"^(?:para responder|a pergunta do usu[áa]rio|a pergunta refere-se|em resposta|com base na consulta|conforme solicitado|a seguir|de acordo com a solicita[çc][ãa]o)\b",
        re.IGNORECASE,
    )
    _WRAPUP_RE = re.compile(
        r"^(?:ess[ea]s?\s+s[ãa]o\s+(?:as?\s+)?(?:disposi[çc][õo]es|principais\s+regras|dispositivos|pontos|informa[çc][õo]es)|"
        r"s[ãa]o\s+ess[ea]s?\s+as?\s+(?:disposi[çc][õo]es|regras|normas))\b",
        re.IGNORECASE,
    )
    _META_DISCLAIMER_RE = re.compile(
        r"(?:"
        r"\b(?:contexto\s+legal|fontes?\s+recuperadas?|contexto\s+fornecido|fontes?\s+consultadas?|fontes?\s+dispon[íi]veis?)\b|"
        r"^(?:n[ãa]o\s+h[áa]|n[ãa]o\s+constam?|n[ãa]o\s+existem?)\s+(?:outros?|outras?|mais)?\s*(?:dispositivos?|informa[çc][õo]es|regras?|regulamenta[çc][õo]es|dados|detalhes|men[çc][ãa]o|previs[ãa]o)\b|"
        r"^(?:para\s+verificar|recomenda-se|consulte\s+a\s+lei|cabe\s+conferir|[eé]\s+necess[áa]rio\s+conferir)\b|"
        r"^(?:(?:[eé]|importante|vale|cabe)\s+(?:lembrar|notar|ressaltar|destacar|observar)\s+que\s+(?:ess[ea]|est[ea]|n[ãa]o\s+h[áa]|apenas|somente))\b|"
        r"^(?:ess[ea]|est[ea])\s+[eé]\s+a\s+[úu]nica\s+informa[çc][ãa]o\b"
        r")",
        re.IGNORECASE,
    )
    for raw in re.split(r"(?<=[.!?])\s+|\n{2,}", protected):
        restored = raw.replace("@@DOT@@", ".").strip()
        text = " ".join(restored.split())
        if not text:
            continue
        # Skip source attribution lines
        if re.match(r"^[-–—•\s]*(?:\*\*)?fontes?(?:\s+consultadas?)?(?:\*\*)?\s*:", text, re.I):
            continue
        # Skip conversational concluding wrap-up sentences
        if _WRAPUP_RE.search(text):
            continue
        # Skip conversational disclaimers or RAG meta-commentary
        if _META_DISCLAIMER_RE.search(text):
            continue
        # Skip empty, trivial non-factual fragments or residual structural headers
        clean_text_check = re.sub(r"^[-–—•\d.)\]\s]+", "", text).strip("*_#: \t").lower()
        if clean_text_check in _STRUCTURAL_HEADERS:
            continue
        if not re.search(r"[A-Za-zÀ-ÿ]{3,}", text):
            continue
        if len(text) < 15 and not any(char.isdigit() for char in text):
            continue
        # Skip purely conversational preamble clauses that do not make substantive statutory claims
        if _PREAMBLE_RE.search(text) and not re.search(
            r"\b(?:fica\s+proibid|é\s+proibid|fica\s+vedad|é\s+vedad|prescreve|estabelece|determina|dispõe|pena|multa)\b",
            text,
            re.I,
        ):
            continue
        # Skip lead-in announcement preambles introducing subsequent bullet points
        if text.endswith(":") or re.search(
            r"\b(?:o\s+seguinte|os\s+seguintes\s+pontos|destacam-se\s+as\s+seguintes|destacam-se\s+os\s+seguintes)\s*:?$",
            text,
            re.I,
        ):
            continue
        refs = tuple(
            f"{m.group(1).lower()} {m.group(2)}/{m.group(3)[-2:]}"
            for m in _CITATION_RE.finditer(text)
        )
        claims.append(Claim(text=text, citation_refs=refs))
    return tuple(claims)


def _norma_ref_from_source(source: dict[str, Any]) -> str:
    value = source.get("norma") or source.get("norma_ref")
    if isinstance(value, dict):
        tipo = value.get("tipo") or ""
        if str(tipo).isdigit() or not tipo:
            tipo = "Lei"
        numero = value.get("numero") or ""
        ano = value.get("ano") or ""
        return " ".join(part for part in (tipo, f"{numero}/{ano}".strip("/")) if part).strip()
    if value and not str(value).isdigit():
        return str(value)

    dispositivo = source.get("dispositivo")
    norma = getattr(dispositivo, "norma", None)
    if norma is not None:
        tipo_getter = getattr(norma, "get_tipo_display_name", None)
        if callable(tipo_getter):
            tipo = tipo_getter()
        else:
            tipo_val = getattr(norma, "tipo", "") or ""
            tipo = "Lei" if str(tipo_val).isdigit() or not tipo_val else tipo_val
        numero = getattr(norma, "numero", "") or ""
        ano = getattr(norma, "ano", "") or ""
        return " ".join(part for part in (tipo, f"{numero}/{ano}".strip("/")) if part).strip()
    return ""


def _identifier_from_source(source: dict[str, Any]) -> str:
    value = source.get("identifier") or source.get("referencia") or source.get("label")
    if value:
        return str(value)
    dispositivo = source.get("dispositivo")
    getter = getattr(dispositivo, "get_full_identifier", None)
    if callable(getter):
        return str(getter())
    return ""


def build_evidence(sources: Iterable[dict[str, Any]]) -> tuple[Evidence, ...]:
    result: list[Evidence] = []
    for source in sources:
        dispositivo = source.get("dispositivo")
        # ``evidence_text`` is an internal, enriched representation used by
        # grounding.  It lets retrieval add authoritative norma metadata (for
        # example an ementa or publication clause) without polluting the
        # concise snippet shown in the source drawer.
        if "evidence_text" in source:
            # An explicitly empty bounded excerpt means this source supplied no
            # claim-supporting text to the model. Never fall back to text that
            # may have been omitted by the context budget.
            text = str(source.get("evidence_text") or "")
        else:
            text = str(
                source.get("text")
                or source.get("full_text")
                or getattr(dispositivo, "texto", "")
                or ""
            )
        if not text:
            continue
        dispositivo_id = (
            source.get("dispositivo_id")
            or source.get("id")
            or getattr(dispositivo, "id", None)
        )
        norma = getattr(dispositivo, "norma", None)
        parent = getattr(dispositivo, "dispositivo_pai", None)
        result.append(
            Evidence(
                dispositivo_id=dispositivo_id,
                text=text,
                norma_ref=_norma_ref_from_source(source),
                identifier=_identifier_from_source(source),
                start=source.get("start"),
                end=source.get("end"),
                dispositivo_ids=(dispositivo_id,) if dispositivo_id is not None else (),
                citation_ids=(source["citation_id"],) if source.get("citation_id") else (),
                norma_id=source.get("norma_id") or getattr(dispositivo, "norma_id", None) or getattr(norma, "id", None),
                tipo=str(getattr(dispositivo, "tipo", "") or "").lower(),
                parent_id=getattr(dispositivo, "dispositivo_pai_id", None) or getattr(parent, "id", None),
                parent_tipo=str(getattr(parent, "tipo", "") or "").lower(),
                parent_norma_id=getattr(parent, "norma_id", None) or getattr(getattr(parent, "norma", None), "id", None),
                snippet_truncated=bool(source.get("snippet_truncated")),
            )
        )
    return tuple(result)


def build_article_family_evidence(sources: Iterable[dict[str, Any]]) -> tuple[Evidence, ...]:
    """Add bounded caput + direct-inciso evidence, only within a verified article family."""
    sources = tuple(sources)
    evidence = build_evidence(sources)
    sent_device_ids = {
        source.get("dispositivo_id")
        or source.get("id")
        or getattr(source.get("dispositivo"), "id", None)
        for source in sources
        if "evidence_text" in source and source.get("evidence_text")
    }
    article_roots = {
        item.dispositivo_id: item
        for item in evidence
        if item.tipo == "artigo"
        and item.dispositivo_id is not None
        and item.dispositivo_id in sent_device_ids
        and item.parent_id is None
        and not item.snippet_truncated
    }
    groups: dict[tuple[Any, Any], list[Evidence]] = {}
    truncated_families = set()
    evidence_by_id = {item.dispositivo_id: item for item in evidence if item.dispositivo_id is not None}
    for source in sources:
        device = source.get("dispositivo")
        if "evidence_text" not in source or not source.get("evidence_text"):
            continue
        item = evidence_by_id.get(
            source.get("dispositivo_id") or source.get("id") or getattr(device, "id", None)
        )
        if not item or item.tipo != "inciso":
            continue
        parent = getattr(device, "dispositivo_pai", None)
        parent_id = getattr(device, "dispositivo_pai_id", None) or getattr(parent, "id", None)
        parent_norma_id = getattr(parent, "norma_id", None) or getattr(
            getattr(parent, "norma", None), "id", None
        )
        if (
            item
            and item.snippet_truncated
            and parent is not None
            and str(getattr(parent, "tipo", "")).lower() == "artigo"
            and parent_norma_id == item.norma_id
        ):
            truncated_families.add((item.norma_id, parent_id))
        if item.snippet_truncated:
            continue
        root = article_roots.get(parent_id)
        if (
            root is None
            or parent is None
            or getattr(parent, "id", None) != parent_id
            or str(getattr(parent, "tipo", "")).lower() != "artigo"
            or item.norma_id is None
            or root.norma_id != item.norma_id
            or parent_norma_id != item.norma_id
        ):
            continue
        groups.setdefault((item.norma_id, parent_id), [root]).append(item)

    composites = []
    for (_norma_id, _article_id), family in groups.items():
        if (_norma_id, _article_id) in truncated_families:
            continue
        unique = {item.dispositivo_id: item for item in family}
        family = list(unique.values())
        if len(family) < 2:
            continue
        root = article_roots[_article_id]
        sections = [f"{root.identifier}: {root.text}"]
        for item in family:
            if item.dispositivo_id == root.dispositivo_id:
                continue
            sections.append(f"{item.identifier}: {item.text}")
        ids = tuple(item.dispositivo_id for item in family if item.dispositivo_id is not None)
        citation_ids = tuple(dict.fromkeys(cid for item in family for cid in item.citation_ids))
        composites.append(
            Evidence(
                dispositivo_id=None,
                text="\n".join(sections),
                norma_ref=root.norma_ref,
                identifier=root.identifier,
                dispositivo_ids=ids,
                citation_ids=citation_ids,
                norma_id=root.norma_id,
                tipo="article_family",
            )
        )
    return (*evidence, *composites)


def _normalise_citation_text(text: str) -> str:
    norm = _normalise(text)
    norm = re.sub(r"\bn[º°o.]*\s*", "", norm)
    return re.sub(r"/(?:19|20)(\d{2})\b", r"/\1", norm)


def _citation_matches(claim: Claim, evidence: Evidence) -> bool:
    if not claim.citation_refs:
        return True
    haystack = _normalise_citation_text(
        f"{evidence.norma_ref} {evidence.identifier} {evidence.text}"
    )
    for ref in claim.citation_refs:
        norm_ref = _normalise_citation_text(ref)
        if norm_ref in haystack:
            continue
        match = re.search(r"(\d[\d.]*)/(\d{2,4})", ref)
        if match:
            num = match.group(1).replace(".", "")
            year_short = match.group(2)[-2:]
            year_full = match.group(2)
            if (
                f"{num}/{year_short}" in haystack
                or f"{num}/{year_full}" in haystack
                or f"{num}" in haystack
            ):
                continue
        return False
    return True


def _numeric_tokens(text: str) -> set[str]:
    digits = {token.replace(",", ".") for token in _NUMBER_RE.findall(text or "")}
    words = {
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ]+", (text or "").lower())
        if token in _NUMBER_WORDS
    }
    return digits | words


def _supports_claim(claim: Claim, evidence: Evidence) -> bool:
    if not _citation_matches(claim, evidence):
        return False

    full_ev_text = f"{evidence.norma_ref} {evidence.identifier} {evidence.text}".strip()
    claim_numbers = _numeric_tokens(claim.text)
    evidence_numbers = _numeric_tokens(full_ev_text)
    if claim_numbers - evidence_numbers:
        return False

    claim_words = _tokens(claim.text)
    if not claim_words:
        return True
    evidence_words = _tokens(full_ev_text)
    overlap = len(claim_words & evidence_words) / max(len(claim_words), 1)
    return overlap >= 0.35


def evaluate_grounding(
    answer: str,
    sources: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return a serializable claim -> evidence grounding report."""
    evidence = build_article_family_evidence(sources)
    claims = extract_claims(answer)

    matched: list[ClaimEvidence] = []
    failed: list[str] = []
    supported_count = 0

    for claim in claims:
        claim_evidence = tuple(item for item in evidence if _supports_claim(claim, item))
        supported = bool(claim_evidence)
        if supported:
            supported_count += 1
        else:
            failed.append(claim.text)
        matched.append(
            ClaimEvidence(
                claim=claim.text,
                supported=supported,
                evidence=claim_evidence,
            )
        )

    total = len(claims)
    score = supported_count / total if total else 0.0
    return GroundingResult(
        grounded=bool(claims) and supported_count == total,
        score=round(score, 4),
        claims=tuple(matched),
        failed_claims=tuple(failed),
    ).to_dict()
