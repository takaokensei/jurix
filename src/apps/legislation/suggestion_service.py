from __future__ import annotations

import hashlib
import re
from typing import Any

from django.core.cache import cache
from django.db.models import Exists, OuterRef, Q

from .models import EventoAlteracao, Norma

SUGGESTION_CACHE_SECONDS = 300
MAX_SUGGESTIONS = 8
CANDIDATE_MULTIPLIER = 4


def _short(text: str, limit: int = 96) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _format_identifier(tipo: str | None, numero: str | int | None, ano: str | int | None) -> str:
    tipo_raw = str(tipo or "").strip()
    if tipo_raw.isdigit() or tipo_raw.lower() in ("1", "lei", "lei ordinária", "lei ordinaria"):
        prefix = "Lei nº"
    elif not tipo_raw.lower().startswith("lei") and not tipo_raw.lower().startswith("decreto"):
        prefix = f"{tipo_raw} nº" if tipo_raw else "Lei nº"
    else:
        prefix = tipo_raw if ("nº" in tipo_raw or "n°" in tipo_raw) else f"{tipo_raw} nº"

    num_ano = f"{numero}/{ano}" if numero and ano else str(numero or ano or "")
    return f"{prefix} {num_ano}".strip()


def _clean_topic(ementa: str) -> str:
    """Extract a concise topic subject from the ementa without legal boilerplate."""
    value = " ".join((ementa or "").split()).strip(" .;:")
    # Remove standard introductory verbs
    value = re.sub(
        r"^(disp[oõ]e\s+sobre|institui|cria|estabelece|regulamenta|altera|define|autoriza|reconhece|condecora|fixa|denomina|estima|acrescenta|desafeta|concede|determina|pro[íi]be|d[áa])\s+",
        "",
        value,
        flags=re.I,
    )
    # Remove leading prepositions and redundant articles
    value = re.sub(
        r"^(o\s+|a\s+|os\s+|as\s+|sobre\s+|acerca\s+de\s+|quanto\s+a\s+|a\s+cria[çc][ãa]o\s+d[eoa]s?\s+|a\s+institui[çc][ãa]o\s+d[eoa]s?\s+)",
        "",
        value,
        flags=re.I,
    )
    # Remove location boilerplate like "no Município de Natal/RN", "no Município de Natal", etc.
    value = re.sub(
        r"\s+(no\s+munic[íi]pio\s+d[eo]\s+natal(/\w+)?|no\s+[âa]mbito\s+do\s+munic[íi]pio\s+d[eo]\s+natal(/\w+)?)",
        "",
        value,
        flags=re.I,
    )
    # Remove trailing boilerplate
    value = re.sub(
        r",?\s+e\s+(d[áa]|adota)\s+outras\s+provid[êe]ncias\.?$",
        "",
        value,
        flags=re.I,
    )
    value = value.strip(" .;:,")
    if not value:
        return ""
    if value.isupper():
        value = value[0].upper() + value[1:].lower()
    else:
        value = value[0].upper() + value[1:]
    return value


def _cache_key(normas: list[Norma]) -> str:
    signature = "|".join(
        f"{n.id}:{n.updated_at.isoformat()}:{n.data_vigencia!s}:{bool(getattr(n, 'has_events', False))}"
        for n in normas
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
    return f"jurix:ui:dynamic-suggestions:v5:{digest}"


def _candidate_queryset(limit: int) -> list[Norma]:
    event_exists = EventoAlteracao.objects.filter(
        Q(norma_alvo=OuterRef("pk")) | Q(dispositivo_fonte__norma=OuterRef("pk"))
    )
    return list(
        Norma.objects.filter(
            sapl_id__isnull=False,
            status__in=["consolidated", "ready", "segmented"],
        )
        .exclude(ementa__isnull=True)
        .exclude(ementa="")
        .annotate(has_events=Exists(event_exists))
        .only(
            "id",
            "tipo",
            "numero",
            "ano",
            "ementa",
            "sapl_id",
            "updated_at",
            "data_publicacao",
            "data_vigencia",
        )
        .order_by("-updated_at", "-data_publicacao", "-ano", "-id")[
            : max(12, limit * CANDIDATE_MULTIPLIER)
        ]
    )


def _clean_sentence_case(text: str) -> str:
    if not text:
        return ""
    if text.isupper():
        return text.lower()
    return text


def _clean_boilerplate(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip(" .;:")
    prev = None
    while cleaned != prev:
        prev = cleaned
        cleaned = re.sub(
            r",?\s+conforme\s+mensagem\s+n[ºo°]?\s*[\w\d/.-]+.*$", "", cleaned, flags=re.I
        ).strip(" .;:")
        cleaned = re.sub(
            r",?\s+e\s+(d[áa]|adota)\s+outras\s+provid[êe]ncias\.?$", "", cleaned, flags=re.I
        ).strip(" .;:")
        cleaned = re.sub(
            r"(?:,\s*)?(?:no\s+calend[áa]rio\s+oficial(?:\s+de\s+eventos)?(?:\s+d[eo]\s+munic[íi]pio\s+d[eo]\s+natal)?|"
            r"no\s+[âa]mbito\s+(?:d[ao]\s+c[âa]mara\s+municipal\s+d[eo]\s+natal|d[eo]\s+munic[íi]pio\s+d[eo]\s+natal)|"
            r"no\s+munic[íi]pio\s+d[eo]\s+natal(/\w+)?|"
            r"d[eo]\s+munic[íi]pio\s+d[eo]\s+natal(/\w+)?)(?:,\s*)?",
            " ",
            cleaned,
            flags=re.I,
        ).strip(" .;:")
        cleaned = re.sub(r",\s+com\s+o\s+objetivo\s+de.+$", "", cleaned, flags=re.I).strip(" .;:")
    return " ".join(cleaned.split()).strip(" .;:,")


def _synthesize_natural_question(identifier: str, ementa: str) -> dict[str, str]:
    text = _clean_boilerplate(ementa)

    # 1. Autoriza
    m_aut = re.match(
        r"^autoriza\s+(?:o\s+poder\s+executivo(?:\s+municipal)?\s+)?a\s+(.+)$", text, flags=re.I
    )
    if m_aut:
        action = _clean_sentence_case(m_aut.group(1).strip())
        action_lower = action[0].lower() + action[1:] if action else ""
        return {
            "question": f"O que a {identifier} estabelece sobre a autorização para {action_lower}?",
            "title": f"Autorização da {identifier}",
            "topic": f"Autorização para {action_lower}",
        }

    # 2. Dispõe sobre
    m_dis = re.match(r"^disp[oõ]e\s+sobre\s+(.+)$", text, flags=re.I)
    if m_dis:
        subj = _clean_sentence_case(m_dis.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que estabelece a {identifier} sobre {subj_lower}?",
            "title": f"Regras da {identifier}",
            "topic": subj,
        }

    # 3. Institui
    m_inst = re.match(r"^institui\s+(.+)$", text, flags=re.I)
    if m_inst:
        subj = _clean_sentence_case(m_inst.group(1).strip(" ,;"))
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que prevê a {identifier} sobre {subj_lower}?",
            "title": f"Instituição pela {identifier}",
            "topic": subj,
        }

    # 4. Estabelece
    m_est = re.match(r"^estabelece\s+(.+)$", text, flags=re.I)
    if m_est:
        subj = _clean_sentence_case(m_est.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que estabelece a {identifier} sobre {subj_lower}?",
            "title": f"Dispositivos da {identifier}",
            "topic": subj,
        }

    # 5. Cria
    m_cria = re.match(r"^cria\s+(.+)$", text, flags=re.I)
    if m_cria:
        subj = _clean_sentence_case(m_cria.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que prevê a {identifier} sobre a criação de {subj_lower}?",
            "title": f"Criação pela {identifier}",
            "topic": f"Criação de {subj_lower}",
        }

    # 6. Altera
    m_alt = re.match(r"^altera\s+(.+)$", text, flags=re.I)
    if m_alt:
        subj = _clean_sentence_case(m_alt.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"Quais alterações a {identifier} promove em {subj_lower}?",
            "title": f"Alterações pela {identifier}",
            "topic": f"Alterações em {subj_lower}",
        }

    # 7. Fixa
    m_fix = re.match(r"^fixa\s+(.+)$", text, flags=re.I)
    if m_fix:
        subj = _clean_sentence_case(m_fix.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        if subj_lower.startswith("os "):
            target = f"dos {subj_lower[3:]}"
        elif subj_lower.startswith("as "):
            target = f"das {subj_lower[3:]}"
        elif subj_lower.startswith("o "):
            target = f"do {subj_lower[2:]}"
        elif subj_lower.startswith("a "):
            target = f"da {subj_lower[2:]}"
        else:
            target = f"de {subj_lower}"
        return {
            "question": f"O que estabelece a {identifier} sobre a fixação {target}?",
            "title": f"Fixação pela {identifier}",
            "topic": f"Fixação {target}",
        }

    # 8. Denomina
    m_den = re.match(r"^denomina(?:\s+de)?\s+(.+)$", text, flags=re.I)
    if m_den:
        subj = _clean_sentence_case(m_den.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que prevê a {identifier} sobre a denominação de {subj_lower}?",
            "title": f"Denominação pela {identifier}",
            "topic": f"Denominação de {subj}",
        }

    # 9. Reconhece
    m_rec = re.match(
        r"^reconhece\s+(?:como\s+de\s+utilidade\s+p[úu]blica\s+)?(.+)$", text, flags=re.I
    )
    if m_rec:
        subj = _clean_sentence_case(m_rec.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que prevê a {identifier} sobre o reconhecimento de utilidade pública de {subj_lower}?",
            "title": f"Utilidade pública pela {identifier}",
            "topic": f"Utilidade pública de {subj}",
        }

    # 10. Determina
    m_det = re.match(r"^determina\s+(?:que\s+)?(.+)$", text, flags=re.I)
    if m_det:
        subj = _clean_sentence_case(m_det.group(1).strip())
        subj_lower = subj[0].lower() + subj[1:] if subj else ""
        return {
            "question": f"O que determina a {identifier} quanto a {subj_lower}?",
            "title": f"Determinações da {identifier}",
            "topic": subj,
        }

    clean_subj = _clean_topic(text)
    clean_lower = clean_subj[0].lower() + clean_subj[1:] if clean_subj else "suas disposições"
    return {
        "question": f"O que estabelece a {identifier} sobre {clean_lower}?",
        "title": f"O que prevê a {identifier}?",
        "topic": clean_subj,
    }


def _card_variants(
    identifier: str, ementa: str, has_events: bool, has_validity: bool
) -> list[dict[str, str]]:
    natural = _synthesize_natural_question(identifier, ementa)
    topic_clean = _short(natural["topic"], 130).rstrip(" .…;,")

    variants = [
        {
            "title": natural["title"],
            "description": topic_clean,
            "question": natural["question"],
        },
    ]
    if has_validity:
        variants.append(
            {
                "title": f"Qual a vigência da {identifier}?",
                "description": f"Vigência de {topic_clean}",
                "question": f"Qual é a vigência e como se aplica a {identifier}?",
            }
        )
    if has_events:
        variants.append(
            {
                "title": f"Alterações na {identifier}",
                "description": f"Impactos e alterações sobre {topic_clean}",
                "question": f"Quais alterações ou eventos atingem a {identifier}?",
            }
        )
    return variants


def build_dynamic_suggestions(limit: int = 4, randomize: bool = True) -> list[dict[str, Any]]:
    """Build clean, contextual suggestion cards exclusively from ingested norm metadata."""
    limit = max(1, min(int(limit or 4), MAX_SUGGESTIONS))
    normas = list(_candidate_queryset(max(16, limit * 4)))
    if not normas:
        return []

    pool_key = _cache_key(normas)
    cached_pool = None
    try:
        cached_pool = cache.get(pool_key)
    except Exception:
        cached_pool = None

    if not isinstance(cached_pool, list) or not cached_pool:
        suggestions_pool: list[dict[str, Any]] = []
        seen_questions: set[str] = set()

        for norma in normas:
            topic = _clean_topic(norma.ementa)
            if not topic:
                continue
            identifier = _format_identifier(norma.tipo, norma.numero, norma.ano)
            variants = _card_variants(
                identifier,
                norma.ementa,
                bool(norma.has_events),
                bool(norma.data_vigencia),
            )
            for item in variants:
                question = item["question"]
                if question in seen_questions:
                    continue
                seen_questions.add(question)
                suggestions_pool.append(
                    {
                        "question": question,
                        "title": item["title"],
                        "description": item["description"],
                        "norma_id": norma.id,
                        "sapl_id": norma.sapl_id,
                        "identifier": identifier,
                        "source": "municipal_natal_corpus",
                        "topic": topic,
                    }
                )
                break  # Pick top primary variant per law

        cached_pool = suggestions_pool
        try:
            cache.set(pool_key, cached_pool, SUGGESTION_CACHE_SECONDS)
        except Exception:
            pass

    if not cached_pool:
        return []

    if randomize and len(cached_pool) > limit:
        import random

        return random.sample(cached_pool, limit)

    return cached_pool[:limit]
