"""
Resolve which Dispositivo of the target norma an alteration event refers to.

EventoAlteracao.dispositivo_alvo is never filled by the ingestion, so without this step a
REVOGA/ALTERA can never be applied. The extraction is regex-based and lossy, so resolution is
deliberately CONSERVATIVE: in a legal text, applying the wrong revocation is worse than
reporting an unresolved one. An event is resolved only when all of these hold:

1. It targets a top-level ARTICLE. References to paragraphs, incisos and alíneas cannot be
   resolved because the parent chain is not recovered.
2. Its source dispositivo produced no hierarchical reference for the same action. 'Fica revogado
   o § 2º do art. 5º' makes the extractor emit BOTH an 'artigo 5º' and a 'paragrafo 2º' event;
   resolving the first one would revoke the whole article.
3. The amending text does not mix norms. The extractor attributes every reference in a sentence
   to the first norm it finds ('art. 5º da Lei 7/2019, e o art. 9º desta Lei' -> Lei 7).
4. Exactly one article of the target norma has that number.

Anything else is returned with a human-readable reason, never silently dropped.
"""
import re
from dataclasses import dataclass
from typing import Any

RESOLVABLE_ACTIONS = ('REVOGA', 'ALTERA', 'SUBSTITUI')

_ARTICLE_NUMBER = re.compile(r'^\s*(\d+)\s*[ºª°o]?\s*(?:-\s*([A-Za-z]+))?\s*[.,]?\s*$')

_NORMA_REFERENCE = re.compile(
    r'\b(lei(?:\s+complementar|\s+ordin[áa]ria|\s+org[âa]nica)?|decreto(?:-lei|\s+legislativo)?|'
    r'resolu[çc][ãa]o|emenda(?:\s+constitucional)?|portaria)\s+n?[º°o.]*\s*([\d.]+)\s*[/,]\s*(\d{2,4})',
    re.IGNORECASE,
)
_THIS_NORMA = re.compile(
    r'\b(?:desta|esta|da\s+presente|nesta|neste|deste)\s+'
    r'(?:lei|decreto|resolu[çc][ãa]o|emenda|portaria)\b',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Resolution:
    """Outcome for one event: the dispositivo, or None plus why it could not be resolved."""
    dispositivo: Any | None
    reason: str = ''


def article_key(numero: Any) -> tuple[int, str] | None:
    """'5º' -> (5, ''), '5º-A' -> (5, 'A'); None when it is not an article number."""
    match = _ARTICLE_NUMBER.match(str(numero or ''))
    if not match:
        return None
    return (int(match.group(1)), (match.group(2) or '').upper())


def _ambiguous_norma_reason(text: str) -> str:
    """Why the amending text cannot be trusted to name a single target norma ('' if it can)."""
    norms = {
        (' '.join(m.group(1).lower().split()), re.sub(r'\D', '', m.group(2)), m.group(3)[-2:])
        for m in _NORMA_REFERENCE.finditer(text or '')
    }
    if len(norms) > 1:
        return 'o texto alterador cita mais de uma norma'
    if norms and _THIS_NORMA.search(text or ''):
        return 'o texto alterador mistura "desta Lei" com outra norma'
    return ''


def resolve_targets(eventos: list, dispositivos: list) -> dict[Any, Resolution]:
    """
    Resolve the target of every applying event that has none yet.

    Args:
        eventos: events whose target norma is the one being consolidated
        dispositivos: all dispositivos of that norma

    Returns:
        {evento.id: Resolution}. Events that already have a target, or whose action does not
        change the text, are not included.
    """
    pending = [
        e for e in eventos
        if e.dispositivo_alvo is None and (e.acao or '').upper() in RESOLVABLE_ACTIONS
    ]

    # (source dispositivo, action) -> reference types produced by that sentence
    types_by_group: dict[tuple, set[str]] = {}
    for e in pending:
        group = (getattr(e, 'dispositivo_fonte_id', None), (e.acao or '').upper())
        types_by_group.setdefault(group, set()).add((e.referencia_tipo or '').lower())

    articles: dict[tuple[int, str], list] = {}
    for d in dispositivos:
        if d.tipo == 'artigo' and (key := article_key(d.numero)) is not None:
            articles.setdefault(key, []).append(d)

    result: dict[Any, Resolution] = {}
    for e in pending:
        group = (getattr(e, 'dispositivo_fonte_id', None), (e.acao or '').upper())
        if types_by_group[group] - {'artigo'}:
            result[e.id] = Resolution(None, 'referência hierárquica (parágrafo/inciso/alínea) não suportada')
            continue
        if (e.referencia_tipo or '').lower() != 'artigo':
            result[e.id] = Resolution(None, 'evento sem artigo identificável')
            continue

        fonte = e.dispositivo_fonte
        reason = _ambiguous_norma_reason(getattr(fonte, 'texto', '') if fonte else '')
        if reason:
            result[e.id] = Resolution(None, reason)
            continue

        key = article_key(e.referencia_numero)
        if key is None:
            result[e.id] = Resolution(None, 'número de artigo inválido')
            continue
        candidates = articles.get(key, [])
        if not candidates:
            result[e.id] = Resolution(None, 'artigo não encontrado na norma alvo')
        elif len(candidates) > 1:
            result[e.id] = Resolution(None, 'numeração de artigo duplicada na norma alvo')
        else:
            result[e.id] = Resolution(candidates[0])
    return result
