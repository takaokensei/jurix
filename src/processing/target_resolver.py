"""
Resolve which Dispositivo of the target norma an alteration event refers to.

EventoAlteracao.dispositivo_alvo is never filled by the ingestion, so without this step a
REVOGA/ALTERA can never be applied. The extraction is regex-based and lossy, so resolution is
deliberately CONSERVATIVE: in a legal text, applying the wrong revocation is worse than
reporting an unresolved one. An event is resolved only when all of these hold:

1. The requested hierarchy must be explicit enough to recover its article ancestor.
2. When one sentence produces both an article anchor and a more specific reference
   ('§ 2º do art. 5º'), the specific event wins and the article anchor is not applied.
3. The amending text does not mix norms. The extractor attributes every reference in a sentence
   to the first norm it finds ('art. 5º da Lei 7/2019, e o art. 9º desta Lei' -> Lei 7).
4. Exactly one matching hierarchy path exists in the target norma.

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


_ARTICLE_IN_TEXT = re.compile(r'\bart\.?\s*(\d+)\s*[ºª°o]?(?:\s*-\s*([A-Za-z]+))?', re.I)
_PARAGRAPH_IN_TEXT = re.compile(r'§\s*(único|\d+\s*[ºª°o]?)', re.I)
_INCISO_IN_TEXT = re.compile(r'\binciso\s+([IVXLCDM]+)\b', re.I)
_ALINEA_IN_TEXT = re.compile(r'\balínea\s+([a-z])\s*\)?', re.I)
_ITEM_IN_TEXT = re.compile(r'\bitem\s+(\d+)\s*\)?', re.I)
_HIERARCHICAL_TYPES = {'paragrafo', 'inciso', 'alinea', 'item'}

MAX_RANGE_SPAN = 200


@dataclass(frozen=True)
class Resolution:
    """
    Outcome for one event: the dispositivos it targets (one, or several for a range), or none
    plus why it could not be resolved.
    """
    dispositivos: tuple = ()
    reason: str = ''

    @property
    def dispositivo(self) -> Any | None:
        """The single target, or None (unresolved, or a range with several targets)."""
        return self.dispositivos[0] if len(self.dispositivos) == 1 else None


def article_key(numero: Any) -> tuple[int, str] | None:
    """'5º' -> (5, ''), '5º-A' -> (5, 'A'); None when it is not an article number."""
    match = _ARTICLE_NUMBER.match(str(numero or ''))
    if not match:
        return None
    return (int(match.group(1)), (match.group(2) or '').upper())


def article_spec(numero: Any) -> tuple | None:
    """
    Parse an article reference: ('single', key) for '5º'/'5º-A', ('range', lo, hi) for '5º a 8º'.

    Range endpoints must be plain numbers with lo <= hi and a bounded span; anything else
    ('9º a 5º', '5º-A a 8º') is refused (None) rather than guessed.
    """
    text = str(numero or '')
    parts = re.split(r'\s+a\s+', text)
    if len(parts) == 2:
        lo, hi = article_key(parts[0]), article_key(parts[1])
        if lo and hi and not lo[1] and not hi[1] and lo[0] <= hi[0] and hi[0] - lo[0] <= MAX_RANGE_SPAN:
            return ('range', lo[0], hi[0])
        return None
    key = article_key(text)
    return ('single', key) if key else None


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



def _normalise_article_token(number: str) -> tuple[int, str] | None:
    return article_key(number)


def _ancestor_chain(dispositivo: Any) -> list[Any]:
    chain = []
    seen = set()
    current = dispositivo
    while current is not None and getattr(current, 'id', None) not in seen:
        seen.add(current.id)
        chain.append(current)
        current = getattr(current, 'dispositivo_pai', None)
    return chain


def _parse_hierarchy(text: str, reference_type: str, reference_number: str) -> dict[str, Any]:
    """Extract a conservative parent path from the raw legal reference."""
    raw = text or ''
    article_match = _ARTICLE_IN_TEXT.search(raw)
    path: dict[str, Any] = {
        'artigo': (
            _normalise_article_token(
                f"{article_match.group(1)}-{article_match.group(2)}"
                if article_match and article_match.group(2)
                else article_match.group(1)
            )
            if article_match else None
        )
    }
    ref_type = (reference_type or '').lower()
    ref_num = (reference_number or '').strip()
    path[ref_type] = ref_num

    for pattern, key in (
        (_PARAGRAPH_IN_TEXT, 'paragrafo'),
        (_INCISO_IN_TEXT, 'inciso'),
        (_ALINEA_IN_TEXT, 'alinea'),
        (_ITEM_IN_TEXT, 'item'),
    ):
        match = pattern.search(raw)
        if match:
            path[key] = match.group(1).strip()
    return path


def _number_equal(tipo: str, actual: str, expected: str) -> bool:
    a, b = str(actual or '').strip(), str(expected or '').strip()
    if tipo == 'paragrafo':
        return a.rstrip('ºª°o').lower() == b.rstrip('ºª°o').lower()
    if tipo == 'inciso':
        return a.upper().replace('.', '') == b.upper().replace('.', '')
    if tipo == 'alinea':
        return a.lower().rstrip(')') == b.lower().rstrip(')')
    if tipo == 'item':
        return re.sub(r'\D', '', a) == re.sub(r'\D', '', b)
    return a == b


def _resolve_hierarchical(
    event: Any,
    dispositivos: list[Any],
) -> Resolution:
    """Resolve paragraph/inciso/alínea/item through the materialized parent tree."""
    ref_type = (getattr(event, 'referencia_tipo', '') or '').lower()
    if ref_type not in _HIERARCHICAL_TYPES:
        return Resolution((), '')

    fonte = getattr(event, 'dispositivo_fonte', None)
    reason = _ambiguous_norma_reason(getattr(fonte, 'texto', '') if fonte else '')
    if reason:
        return Resolution((), reason)

    path = _parse_hierarchy(
        getattr(fonte, 'texto', '') if fonte else getattr(event, 'target_text', ''),
        ref_type,
        getattr(event, 'referencia_numero', ''),
    )
    article_key_value = path.get('artigo')
    if article_key_value is None:
        return Resolution((), 'referência hierárquica sem artigo ancestral identificável')

    candidates = []
    for dispositivo in dispositivos:
        if dispositivo.tipo != ref_type or not _number_equal(ref_type, dispositivo.numero, path[ref_type]):
            continue
        chain = _ancestor_chain(dispositivo)
        article_nodes = [node for node in chain if getattr(node, 'tipo', '') == 'artigo']
        if len(article_nodes) != 1:
            continue
        if _normalise_article_token(article_nodes[0].numero) != article_key_value:
            continue

        matched = True
        for parent_type in ('paragrafo', 'inciso', 'alinea', 'item'):
            expected = path.get(parent_type)
            if not expected or parent_type == ref_type:
                continue
            nodes = [node for node in chain if getattr(node, 'tipo', '') == parent_type]
            if nodes and not any(_number_equal(parent_type, node.numero, expected) for node in nodes):
                matched = False
        if matched:
            candidates.append(dispositivo)

    if not candidates:
        return Resolution((), 'referência hierárquica não encontrada na norma alvo')
    if len(candidates) > 1:
        return Resolution((), 'referência hierárquica duplicada na norma alvo')
    return Resolution((candidates[0],))


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
        ref_type = (e.referencia_tipo or '').lower()
        group_types = types_by_group[group]

        # The extractor commonly emits both the article anchor and the specific
        # child reference. Never revoke/alter the whole article when a child path
        # exists in the same source sentence.
        if ref_type == 'artigo' and group_types & _HIERARCHICAL_TYPES:
            result[e.id] = Resolution((), 'artigo é apenas âncora de referência hierárquica')
            continue

        if ref_type in _HIERARCHICAL_TYPES:
            resolved = _resolve_hierarchical(e, dispositivos)
            if resolved.dispositivos or resolved.reason:
                result[e.id] = resolved
            continue

        if ref_type != 'artigo':
            result[e.id] = Resolution((), 'evento sem artigo identificável')
            continue

        fonte = e.dispositivo_fonte
        reason = _ambiguous_norma_reason(getattr(fonte, 'texto', '') if fonte else '')
        if reason:
            result[e.id] = Resolution((), reason)
            continue

        spec = article_spec(e.referencia_numero)
        if spec is None:
            result[e.id] = Resolution((), 'número de artigo inválido')
            continue
        if spec[0] == 'range':
            if (e.acao or '').upper() != 'REVOGA':
                result[e.id] = Resolution((), 'intervalo de artigos só é suportado para revogação')
                continue
            # 'arts. 5º a 8º' includes 5º-A, 5º-B...: every article whose NUMBER lies in the range
            groups = [ds for (number, _suffix), ds in sorted(articles.items()) if spec[1] <= number <= spec[2]]
            if not groups:
                result[e.id] = Resolution((), 'artigo não encontrado na norma alvo')
            elif any(len(ds) > 1 for ds in groups):
                result[e.id] = Resolution((), 'numeração de artigo duplicada na norma alvo')
            else:
                result[e.id] = Resolution(tuple(ds[0] for ds in groups))
            continue
        candidates = articles.get(spec[1], [])
        if not candidates:
            result[e.id] = Resolution((), 'artigo não encontrado na norma alvo')
        elif len(candidates) > 1:
            result[e.id] = Resolution((), 'numeração de artigo duplicada na norma alvo')
        else:
            result[e.id] = Resolution((candidates[0],))
    return result
