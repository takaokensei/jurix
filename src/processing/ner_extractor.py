"""
Named Entity Recognition (NER) for Legal Alterations.

This module implements pattern-based NER to identify legal modification events
and cross-references in Brazilian legislative texts.

Focuses on detecting:
- Alteration verbs (revoga, altera, adiciona, substitui, etc.)
- Legal references (Art. X, § Y, Lei Z/YYYY)
- Target entities (normas, dispositivos)
without Cartesian product between distinct actions in the same context.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class LegalNERExtractor:
    """
    Extract Named Entities and alteration events from legal dispositivos.

    Uses regex patterns with syntactic scoping to identify:
    1. Action verbs (revoga, altera, etc.)
    2. Legal references (Art. 5º, § 2º, Lei 123/2020)
    3. Target elements
    """

    # Action verb patterns (Brazilian Portuguese legal language)
    # Verbs that FOLLOW their reference: 'O art. 5º da Lei nº 123/2020 passa a vigorar com a
    # seguinte redação'. The reference lies before the verb, so its scope is the sentence up to
    # the verb instead of the text after it. This is the most common amendment wording.
    TRAILING_ACTION_PATTERNS = {
        'ALTERA': r'\bpassa(?:m)?\s+a\s+(?:vigorar|ter)\b',
    }

    ACTION_PATTERNS = {
        'REVOGA': r'\b(revog[a-z]+|ficam?\s+revogad[oa]s?)\b',
        # 'dê-se ao art. 5º ...' and 'dá-se/fica dada nova redação ao art. 5º' precede their reference
        'ALTERA': r'\b(alter[a-z]+|modific[a-z]+|ficam?\s+alterad[oa]s?|d[êe]-se|nova\s+reda[çc][ãa]o)\b',
        'ADICIONA': r'\b(adicion[a-z]+|acrescen[a-z]+|inclui[a-z]*|ficam?\s+adicionad[oa]s?)\b',
        'SUBSTITUI': r'\b(substitu[íi][a-z]*|ficam?\s+substitu[íi]d[oa]s?)\b',
        'REGULAMENTA': r'\b(regulamenta[a-z]*|disciplina[a-z]*)\b',
        'REFERENCIA': r'\b(conforme|nos\s+termos|de\s+acordo\s+com|previsto|disposto)\b',
    }

    # Priority for resolving overlapping matches
    ACTION_PRIORITY = {
        'REVOGA': 1,
        'ALTERA': 2,
        'SUBSTITUI': 3,
        'ADICIONA': 4,
        'REGULAMENTA': 5,
        'REFERENCIA': 6,
    }

    # Legal element patterns
    # Article references: singular ('art. 5º'), plural ('arts. 5º e 6º', 'artigos 5º e 6º'),
    # lists ('art. 5º, 6º e 7º') and ranges ('arts. 5º a 8º', '5º ao 8º').
    #
    # A partial extraction is the dangerous case: 'revogados o art. 5º e os arts. 7º e 8º' used to
    # yield only art. 5º, which the engine applied while 7º and 8º stayed in force with no warning.
    #
    # - The optional '-A' suffix (Art. 2º-A) is a different article from Art. 2º. No spaces are
    #   allowed around the hyphen and the letter must not start a word, so 'art. 5º - A revogação'
    #   / 'art. 5º-Aplicam' keep '5º'.
    # - Numbers after the first are at most 3 digits and are not followed by a unit, so 'art. 5º e
    #   10 dias', 'art. 5º, 2020' or 'art. 5º e 30%' are not swallowed into the list.
    _ART_NUM = r'\d+[º°ª]?(?:-[A-Z](?![a-zà-ú]))?'
    _ART_NEXT = (r'\d{1,3}(?!\d)[º°ª]?(?:-[A-Z](?![a-zà-ú]))?'
                 r'(?!\s*(?:dias?|m[êe]s(?:es)?|anos?|horas?|%|por\s*cento|reais|unidades?|vezes))')
    ARTICLE_PATTERN = re.compile(
        rf'\b(art(?:igo)?s?\.?\s*(?:n[º°]?\s*)?)'
        rf'({_ART_NUM}(?:(?:\s*,\s*(?:e\s+)?|\s+e\s+|\s+a\s+|\s+ao\s+|\s+at[ée]\s+(?:o\s+)?){_ART_NEXT})*)',
        re.IGNORECASE
    )
    _ART_TOKEN = re.compile(rf'({_ART_NUM})|\b(?:ao|at[ée]|a)\b', re.IGNORECASE)
    # A '.' right after one of these is an abbreviation, not the end of a sentence.
    ABBREVIATIONS = ('arts', 'art', 'nº', 'no', 'incs', 'inc')

    @classmethod
    def _is_abbreviation(cls, prefix: str) -> bool:
        return prefix.lower().endswith(cls.ABBREVIATIONS)


    PARAGRAPH_PATTERN = re.compile(
        r'(?:\bpar[áa]grafo|[§¶])\s*(?:n[º°]?\s*)?([\d]+[º°]?|[ÚUú]nico)',
        re.IGNORECASE
    )

    INCISO_PATTERN = re.compile(
        r'\binciso\s+([IVXLCDM]+|[\d]+)',
        re.IGNORECASE
    )

    ALINEA_PATTERN = re.compile(
        r'\bal[íi]nea\s+[\'\"“]?([a-z])[\'\"”]?\)?',
        re.IGNORECASE
    )

    # Complex law reference (Lei X/YYYY, LC X/YYYY, Decreto X/YYYY)
    LEI_PATTERN = re.compile(
        r'\b(lei\s+(?:complementar|ordinária|delegada)?|lc|decreto|resolução)\s*'
        r'(?:n[º°]?\s*)?([\d.,]+)\s*[/\-]?\s*(\d{4})?',
        re.IGNORECASE
    )

    # Strict "desta Lei" pattern (excludes references with an explicit number like "da Lei nº 123")
    DESTA_LEI_PATTERN = re.compile(
        r'\b(?:d[aeo]st[ae]\s+(?:lei|decreto|resolução|diploma|código)|'
        r'd[aeo]\s+(?:lei|decreto|resolução)\s+(?:supracitad[ao]|referid[ao]|mencionad[ao]))'
        r'(?!\s*(?:n[º°]?\s*)?\d)',
        re.IGNORECASE
    )

    def __init__(self):
        """Initialize the NER extractor with compiled patterns."""
        self.action_regex = {
            action: re.compile(pattern, re.IGNORECASE)
            for action, pattern in self.ACTION_PATTERNS.items()
        }
        self.trailing_regex = {
            action: re.compile(pattern, re.IGNORECASE)
            for action, pattern in self.TRAILING_ACTION_PATTERNS.items()
        }

    def extract_events(
        self,
        texto: str,
        dispositivo_id: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract alteration events from dispositivo text using windowed scoping.

        Prevents Cartesian product by binding references strictly to the verb
        whose scope they fall into (delimited by the next verb or sentence delimiter).
        """
        events = []
        if not texto or not texto.strip():
            return events

        # Step 1: Detect action verbs with deduplicated spans
        detected_actions = self._detect_actions(texto)
        if not detected_actions:
            logger.debug(f"No actions detected in dispositivo {dispositivo_id}")
            return events

        # Step 2: Global statute reference in the sentence (fallback if local window lacks it)
        global_norma_info = None
        global_law_matches = list(self.LEI_PATTERN.finditer(texto))
        if global_law_matches:
            last_match = global_law_matches[-1]
            tipo_lei = last_match.group(1).strip()
            numero = last_match.group(2).strip()
            ano = last_match.group(3) if last_match.group(3) else ''
            global_norma_info = {
                'tipo': tipo_lei,
                'numero': numero,
                'ano': ano,
                'text': last_match.group(0),
            }

        # Step 3: For each action, extract referenced entities in its exclusive window
        num_actions = len(detected_actions)
        for i, action_data in enumerate(detected_actions):
            action = action_data['action']
            action_span = action_data['span']

            # Exclusive context window: from action start to next action or delimiter
            context_start = action_span[0]

            if action_data.get('scope') == 'before':
                # The reference precedes the verb: scope = this sentence, up to the verb
                lower = detected_actions[i - 1]['span'][1] if i > 0 else 0
                context_start = self._sentence_start(texto, lower, action_span[0])
                context_end = action_span[1]
            elif i + 1 < num_actions:
                context_end = detected_actions[i + 1]['span'][0]
            else:
                raw_window_end = len(texto)
                sub_after_action = texto[action_span[1]:raw_window_end]
                punct_match = None
                for m in re.finditer(r'[.;]', sub_after_action):
                    pos = m.start()
                    prefix = sub_after_action[max(0, pos - 5):pos].lower()
                    if self._is_abbreviation(prefix):
                        continue
                    punct_match = m
                    break

                if punct_match:
                    context_end = action_span[1] + punct_match.start() + 1
                else:
                    context_end = raw_window_end

            context = texto[context_start:context_end]

            # Extract references solely within this specific scope
            references = self._extract_references(context)

            # Separate structural element references from statute references
            elem_refs = [r for r in references if r['tipo'] in ('artigo', 'paragrafo', 'inciso', 'alinea')]
            statute_refs = [r for r in references if r['tipo'] not in ('artigo', 'paragrafo', 'inciso', 'alinea')]

            # Determine applicable statute metadata for this window
            local_norma_info = None
            if statute_refs:
                first_statute = statute_refs[0]
                local_norma_info = first_statute.get('norma_info')
            if not local_norma_info:
                local_norma_info = global_norma_info

            if elem_refs:
                for ref in elem_refs:
                    events.append({
                        'acao': action,
                        'target_text': ref['text'],
                        'referencia_tipo': ref['tipo'],
                        'referencia_numero': ref['numero'],
                        'extraction_confidence': ref['confidence'],
                        'extraction_method': 'regex',
                        'norma_referenciada': local_norma_info,
                    })
            elif statute_refs:
                for ref in statute_refs:
                    events.append({
                        'acao': action,
                        'target_text': ref['text'],
                        'referencia_tipo': ref['tipo'],
                        'referencia_numero': ref.get('numero', ''),
                        'extraction_confidence': ref['confidence'],
                        'extraction_method': 'regex',
                        'norma_referenciada': ref.get('norma_info') or local_norma_info,
                    })
            else:
                # Action verb without direct element reference
                events.append({
                    'acao': action,
                    'target_text': context[:100].strip(),
                    'referencia_tipo': '',
                    'referencia_numero': '',
                    'extraction_confidence': 0.5,
                    'extraction_method': 'regex',
                    'norma_referenciada': local_norma_info,
                })

        return events

    @staticmethod
    def _sentence_start(texto: str, lower: int, upper: int) -> int:
        """Start of the sentence that ends at `upper`, never before `lower`.

        A '.' or ';' ends a sentence unless it belongs to an abbreviation ('art.', 'nº', 'inc.').
        """
        start = lower
        for m in re.finditer(r'[.;]', texto[lower:upper]):
            prefix = texto[max(0, lower + m.start() - 5):lower + m.start()].lower()
            if LegalNERExtractor._is_abbreviation(prefix):
                continue
            start = lower + m.end()
        return start

    def _detect_actions(self, texto: str) -> list[dict[str, Any]]:
        """
        Detect action verbs in text, deduplicating overlapping spans.

        Returns:
            Sorted list of non-overlapping {'action': str, 'span': Tuple[int, int], 'match': str}
        """
        raw_actions = []
        for action, regex in self.action_regex.items():
            for match in regex.finditer(texto):
                raw_actions.append({
                    'action': action,
                    'span': match.span(),
                    'match': match.group(0),
                    'priority': self.ACTION_PRIORITY.get(action, 99),
                    'scope': 'after',
                })
        for action, regex in self.trailing_regex.items():
            for match in regex.finditer(texto):
                raw_actions.append({
                    'action': action,
                    'span': match.span(),
                    'match': match.group(0),
                    'priority': self.ACTION_PRIORITY.get(action, 99),
                    'scope': 'before',
                })

        if not raw_actions:
            return []

        # Sort by start position, then by priority
        raw_actions.sort(key=lambda x: (x['span'][0], x['priority'], -(x['span'][1] - x['span'][0])))

        # Deduplicate overlapping matches
        filtered = []
        for act in raw_actions:
            overlap = False
            for existing in filtered:
                if max(act['span'][0], existing['span'][0]) < min(act['span'][1], existing['span'][1]):
                    overlap = True
                    break
            if not overlap:
                filtered.append(act)

        filtered.sort(key=lambda x: x['span'][0])
        return filtered

    def _article_numbers(self, listing: str) -> list[str]:
        """
        Expand the number list of one article reference into individual references.

        '5º, 6º e 7º' -> ['5º', '6º', '7º'];  '7º a 9º' -> ['7º a 9º'] (a range stays ONE
        reference: the consolidation resolves it against the norma, which is the only place that
        knows about suffixed articles such as 5º-A lying between the endpoints).
        """
        tokens = [m.group(1) or 'RANGE' for m in self._ART_TOKEN.finditer(listing)]
        numbers, i = [], 0
        while i < len(tokens):
            if tokens[i] == 'RANGE':
                i += 1
            elif i + 2 < len(tokens) + 0 and tokens[i + 1] == 'RANGE' and tokens[i + 2] != 'RANGE':
                numbers.append(f"{tokens[i]} a {tokens[i + 2]}")
                i += 3
            else:
                numbers.append(tokens[i])
                i += 1
        return numbers

    def _extract_references(self, texto: str) -> list[dict[str, Any]]:
        """
        Extract legal references strictly present within given text snippet.

        Returns:
            List of reference dictionaries with tipo, numero, text, confidence
        """
        references = []

        # 1. External law references (Lei X/YYYY)
        for match in self.LEI_PATTERN.finditer(texto):
            tipo_lei = match.group(1).strip()
            numero = match.group(2).strip()
            ano = match.group(3) if match.group(3) else ''
            ref_text = match.group(0)

            references.append({
                'tipo': tipo_lei.lower(),
                'numero': f"{numero}/{ano}" if ano else numero,
                'text': ref_text,
                'confidence': 0.95 if ano else 0.75,
                'norma_info': {
                    'tipo': tipo_lei,
                    'numero': numero,
                    'ano': ano
                } if ano else None
            })

        # 2. Strict "desta Lei" (self-reference)
        for match in self.DESTA_LEI_PATTERN.finditer(texto):
            references.append({
                'tipo': 'self_reference',
                'numero': '',
                'text': match.group(0),
                'confidence': 0.95,
                'norma_info': None
            })

        # 3. Article references (singular, plural, lists and ranges)
        for match in self.ARTICLE_PATTERN.finditer(texto):
            for numero in self._article_numbers(match.group(2)):
                references.append({
                    'tipo': 'artigo',
                    'numero': numero,
                    'text': match.group(0),
                    'confidence': 0.9,
                    'norma_info': None
                })

        # 4. Paragraph references
        for match in self.PARAGRAPH_PATTERN.finditer(texto):
            numero = match.group(1).strip() if match.group(1) else 'único'
            references.append({
                'tipo': 'paragrafo',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })

        # 5. Inciso references
        for match in self.INCISO_PATTERN.finditer(texto):
            numero = match.group(1).strip()
            references.append({
                'tipo': 'inciso',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })

        # 6. Alínea references
        for match in self.ALINEA_PATTERN.finditer(texto):
            numero = match.group(1).strip()
            references.append({
                'tipo': 'alinea',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })

        return references
