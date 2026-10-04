"""Conservative thematic suggestions; topics are not legal relationships."""

from __future__ import annotations

import re
import unicodedata

TOPIC_RULES = {
    "educacao": ("Educação", ("educacao", "escola", "ensino", "creche", "professor")),
    "saude": ("Saúde", ("saude", "hospital", "vacina", "vigilancia sanitaria")),
    "meio-ambiente": ("Meio ambiente", ("meio ambiente", "ambiental", "arvore", "residuo")),
    "urbanismo": ("Urbanismo", ("zoneamento", "uso do solo", "imovel", "edificacao", "urbano")),
    "orcamento": ("Orçamento público", ("orcamento", "despesa publica", "credito adicional", "receita municipal")),
    "servidor-publico": ("Servidor público", ("servidor publico", "cargo publico", "remuneracao", "funcionario municipal")),
    "tributario": ("Tributário", ("tributo", "iptu", "issqn", "taxa municipal", "imposto")),
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def suggest_topics(norma) -> list[dict[str, object]]:
    """Return rule-based candidate labels from metadata only; never confirm them."""
    content = _normalize(" ".join((getattr(norma, "ementa", "") or "", getattr(norma, "texto_consolidado", "") or "")))
    suggestions = []
    for code, (label, terms) in TOPIC_RULES.items():
        matches = [term for term in terms if _normalize(term) in content]
        if matches:
            suggestions.append({"code": code, "label": label, "status": "candidate", "matched_terms": matches})
    return suggestions


def persist_topic_candidates(norma) -> int:
    """Idempotently persist suggestions; do not overwrite confirmed/manual tags."""
    from src.apps.legislation.topic_models import NormaTopic, Topic

    created = 0
    for suggestion in suggest_topics(norma):
        topic, _ = Topic.objects.get_or_create(
            code=suggestion["code"],
            defaults={"label": suggestion["label"]},
        )
        _, was_created = NormaTopic.objects.get_or_create(
            norma=norma,
            topic=topic,
            version=1,
            defaults={"origin": NormaTopic.Origin.RULE, "status": NormaTopic.Status.CANDIDATE},
        )
        created += int(was_created)
    return created
