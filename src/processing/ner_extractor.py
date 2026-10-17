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
        "ALTERA": r"\bpassa(?:m)?\s+a\s+(?:vigorar|ter)\b",
    }

    ACTION_PATTERNS = {
        "REVOGA": r"\b(revog(?:a|am|ou|ar|ando|ado|ada|ados|adas|ue|uem)|ficam?\s+revogad[oa]s?)\b",
        # 'dê-se ao art. 5º ...' and 'dá-se/fica dada nova redação ao art. 5º' precede their reference
        # Ordinary concepts such as alternativas, adicionais, and incluindo are not
        # themselves legal amendments. Match bounded verb inflections and explicit forms.
        "ALTERA": r"\b(alter(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em)|modific(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em)|ficam?\s+alterad[oa]s?|d[êe]-se|nova\s+reda[çc][ãa]o)\b",
        "ADICIONA": r"\b(adicion(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em)|acrescent(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em)|acrescid[oa]s?|inclui(?:-se)?|incluem-se|inclu[ií]d[oa]s?|ficam?\s+(?:adicionad[oa]s?|acrescid[oa]s?))\b",
        "SUBSTITUI": r"\b(substitu[íi](?:a|am|iu|ir|indo|ído|ída|ídos|ídas)|ficam?\s+substitu[íi]d[oa]s?)\b",
        "REGULAMENTA": r"\b(regulament(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em)|disciplin(?:a|am|ou|ar|ando|ado|ada|ados|adas|e|em))\b",
        "REFERENCIA": r"\b(conforme|nos\s+termos|de\s+acordo\s+com|previsto|disposto|refer[eê]ncia|referencia)\b",
    }

    # Priority for resolving overlapping matches
    ACTION_PRIORITY = {
        "REVOGA": 1,
        "ALTERA": 2,
        "SUBSTITUI": 3,
        "ADICIONA": 4,
        "REGULAMENTA": 5,
        "REFERENCIA": 6,
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
    # PDF text extraction can wrap a suffixed article at the hyphen, e.g. ``98-\n A``.
    # Accept layout whitespace only inside this suffix, then normalize the identifier below.
    _ART_NUM = r"\d+[º°ª]?(?:-\s*[A-Z](?![a-zà-ú]))?"
    _ART_NEXT = (
        r"\d{1,3}(?!\d)[º°ª]?(?:-\s*[A-Z](?![a-zà-ú]))?"
        r"(?!\s*(?:dias?|m[êe]s(?:es)?|anos?|horas?|%|por\s*cento|reais|unidades?|vezes))"
    )
    ARTICLE_PATTERN = re.compile(
        rf"\b(art(?:igo)?s?\.?\s*(?:n[º°]?\s*)?)"
        rf"({_ART_NUM}(?:(?:\s*,\s*(?:e\s+)?|\s+e\s+|\s+a\s+|\s+ao\s+|\s+at[ée]\s+(?:o\s+)?){_ART_NEXT})*)",
        re.IGNORECASE,
    )
    _ART_TOKEN = re.compile(rf"({_ART_NUM})|\b(?:ao|at[ée]|a)\b", re.IGNORECASE)
    # A '.' right after one of these is an abbreviation, not the end of a sentence.
    ABBREVIATIONS = ("arts", "art", "nº", "no", "incs", "inc")

    @classmethod
    def _is_abbreviation(cls, prefix: str) -> bool:
        return prefix.lower().endswith(cls.ABBREVIATIONS)

    @staticmethod
    def _is_numeric_separator(text: str, position: int) -> bool:
        """A dot between digits is a thousands/decimal separator, not sentence punctuation."""
        return (
            text[position] == "."
            and position > 0
            and position + 1 < len(text)
            and text[position - 1].isdigit()
            and text[position + 1].isdigit()
        )

    @staticmethod
    def _year_value(value: str | None) -> str:
        raw = (value or "").strip().casefold()
        if raw.isdigit():
            return raw
        unit = {
            "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
            "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
            "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
            "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
            "dezoito": 18, "dezenove": 19,
        }
        tens = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
                "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90}
        hundreds = {"cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
                    "quinhentos": 500, "seiscentos": 600, "setecentos": 700,
                    "oitocentos": 800, "novecentos": 900}
        words = {**unit, **tens, **hundreds}
        tokens = [token for token in re.split(r"\s+|\be\b", raw) if token]
        if tokens[:2] == ["dois", "mil"]:
            total, tail = 2000, tokens[2:]
        elif tokens[:1] == ["mil"]:
            total, tail = 1000, tokens[1:]
        else:
            return ""
        if any(token not in words for token in tail):
            return ""
        total += sum(words[token] for token in tail)
        return str(total) if 1000 <= total <= 2099 else ""

    PARAGRAPH_PATTERN = re.compile(
        r"(?:\bpar[áa]grafo|[§¶])\s*(?:n[º°]?\s*)?([\d]+[º°]?|[ÚUú]nico)", re.IGNORECASE
    )

    INCISO_PATTERN = re.compile(r"\binciso\s+([IVXLCDM]+|[\d]+)", re.IGNORECASE)

    ALINEA_PATTERN = re.compile(r"\bal[íi]nea\s+[\'\"“]?([a-z])[\'\"”]?\)?", re.IGNORECASE)

    # Complex law reference (Lei X/YYYY, LC X/YYYY, Decreto X/YYYY)
    _YEAR_UNIT_RE = r"um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|dezenove"
    _YEAR_TENS_RE = rf"vinte(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|trinta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|quarenta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|cinquenta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|sessenta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|setenta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|oitenta(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?|noventa(?:\s+e\s+(?:{_YEAR_UNIT_RE}))?"
    _YEAR_HUNDRED_RE = r"cento|duzentos|trezentos|quatrocentos|quinhentos|seiscentos|setecentos|oitocentos|novecentos"
    _YEAR_WORD_RE = rf"(?:mil(?:\s+novecentos(?:\s+e\s+(?:{_YEAR_TENS_RE}))?)?|dois\s+mil(?:\s+e\s+(?:{_YEAR_HUNDRED_RE}|{_YEAR_TENS_RE}|{_YEAR_UNIT_RE}))?)"
    LEI_PATTERN = re.compile(
        r"\b(lei\s+(?:complementar|ordinária|delegada|promulgada)?|lc|decreto|resolução)s?\s*"
        r"(?:municipal(?:is)?(?:\s+de\s+Natal)?|do\s+município(?:\s+de\s+Natal)?)?\s*"
        # A small number of PDF text layers replace the numero ordinal glyph with
        # U+FFFD (for example, ``n� 275``). Accept that damaged marker while
        # preserving the literal evidence span; never infer a missing digit.
        rf"(?:n[º°\ufffd]?\s*)?([\d.,]+)(?:\s*[/\-]\s*(\d{{4}}|{_YEAR_WORD_RE})|"
        rf"\s*,?\s+de\s+(?:(?:\d{{1,2}}\s+de\s+[A-Za-zÀ-ÿ]+\s+de\s+)?(\d{{4}}|{_YEAR_WORD_RE})))?",
        re.IGNORECASE,
    )

    # Strict "desta Lei" pattern (excludes references with an explicit number like "da Lei nº 123")
    DESTA_LEI_PATTERN = re.compile(
        r"\b(?:d[aeo]st[ae]\s+(?:lei|decreto|resolução|diploma|código)|"
        r"d[aeo]\s+(?:lei|decreto|resolução)\s+(?:supracitad[ao]|referid[ao]|mencionad[ao]))"
        r"(?!\s*(?:n[º°]?\s*)?\d)",
        re.IGNORECASE,
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

    def extract_events(self, texto: str, dispositivo_id: int | None = None) -> list[dict[str, Any]]:
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
            numero = last_match.group(2).strip().rstrip(".,;:")
            ano = self._year_value(last_match.group(3) or last_match.group(4))
            global_norma_info = {
                "tipo": tipo_lei,
                "numero": numero,
                "ano": ano,
                "text": last_match.group(0),
            }

        # Step 3: For each action, extract referenced entities in its exclusive window
        num_actions = len(detected_actions)
        for i, action_data in enumerate(detected_actions):
            action = action_data["action"]
            action_span = action_data["span"]

            # Exclusive context window: from action start to next action or delimiter
            context_start = action_span[0]

            if action_data.get("scope") == "before":
                # The reference precedes the verb: scope = this sentence, up to the verb
                lower = detected_actions[i - 1]["span"][1] if i > 0 else 0
                context_start = self._sentence_start(texto, lower, action_span[0])
                context_end = action_span[1]
            elif i + 1 < num_actions:
                context_end = detected_actions[i + 1]["span"][0]
            else:
                raw_window_end = len(texto)
                sub_after_action = texto[action_span[1] : raw_window_end]
                punct_match = None
                for m in re.finditer(r"[.;]", sub_after_action):
                    pos = m.start()
                    if self._is_numeric_separator(sub_after_action, pos):
                        continue
                    prefix = sub_after_action[max(0, pos - 5) : pos].lower()
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
            elem_refs = [
                r for r in references if r["tipo"] in ("artigo", "paragrafo", "inciso", "alinea")
            ]
            statute_refs = [
                r
                for r in references
                if r["tipo"] not in ("artigo", "paragrafo", "inciso", "alinea")
            ]

            # Determine applicable statute metadata for this window
            local_norma_info = None
            if statute_refs:
                first_statute = statute_refs[0]
                local_norma_info = first_statute.get("norma_info")
            if not local_norma_info:
                local_norma_info = global_norma_info

            if elem_refs:
                for ref in elem_refs:
                    evidence = self._build_evidence(
                        texto, action_data, context_start, [ref, *statute_refs]
                    )
                    target_resolution = (
                        "ambiguous_multiple_normas" if len(statute_refs) > 1
                        else "range_unresolved" if re.search(r"\ba\b", ref["numero"], re.IGNORECASE)
                        else "candidate" if local_norma_info
                        else "unresolved"
                    )
                    events.append(
                        {
                            "acao": action,
                            "target_text": ref["text"],
                            "referencia_tipo": ref["tipo"],
                            "referencia_numero": ref["numero"],
                            "extraction_confidence": ref["confidence"],
                            "extraction_method": "regex",
                            "norma_referenciada": local_norma_info,
                            "evidence": evidence,
                            "target_resolution": target_resolution,
                        }
                    )
            elif statute_refs:
                for ref in statute_refs:
                    evidence = self._build_evidence(texto, action_data, context_start, [ref])
                    target_resolution = "ambiguous_multiple_normas" if len(statute_refs) > 1 else (
                        "candidate" if ref.get("norma_info") or local_norma_info else "unresolved"
                    )
                    events.append(
                        {
                            "acao": action,
                            "target_text": ref["text"],
                            "referencia_tipo": ref["tipo"],
                            "referencia_numero": ref.get("numero", ""),
                            "extraction_confidence": ref["confidence"],
                            "extraction_method": "regex",
                            "norma_referenciada": ref.get("norma_info") or local_norma_info,
                            "evidence": evidence,
                            "target_resolution": target_resolution,
                        }
                    )
            else:
                # Action verb without direct element reference
                events.append(
                    {
                        "acao": action,
                        "target_text": context[:100].strip(),
                        "referencia_tipo": "",
                        "referencia_numero": "",
                        "extraction_confidence": 0.5,
                        "extraction_method": "regex",
                        "norma_referenciada": local_norma_info,
                        "evidence": self._build_evidence(texto, action_data, context_start, None),
                        "target_resolution": "unresolved",
                    }
                )

        return events

    @staticmethod
    def _build_evidence(texto, action_data, context_start, references):
        action_start, action_end = action_data["span"]
        reference_spans = [
            ref.get("span") for ref in (references or []) if ref.get("span")
        ]
        if reference_spans:
            target_start = context_start + min(span[0] for span in reference_spans)
            target_end = context_start + max(span[1] for span in reference_spans)
        else:
            target_start, target_end = action_start, action_end
        start = min(action_start, target_start)
        end = max(action_end, target_end)
        return {
            "schema_version": 2,
            "offset_unit": "python_unicode_codepoint",
            "start_offset": start,
            "end_offset": end,
            "action_start_offset": action_start,
            "action_end_offset": action_end,
            "target_start_offset": target_start,
            "target_end_offset": target_end,
            "action_quote": texto[action_start:action_end],
            "target_quote": texto[target_start:target_end],
            "quote": texto[start:end],
        }

    @staticmethod
    def _sentence_start(texto: str, lower: int, upper: int) -> int:
        """Start of the sentence that ends at `upper`, never before `lower`.

        A '.' or ';' ends a sentence unless it belongs to an abbreviation ('art.', 'nº', 'inc.').
        """
        start = lower
        for m in re.finditer(r"[.;]", texto[lower:upper]):
            if LegalNERExtractor._is_numeric_separator(texto, lower + m.start()):
                continue
            prefix = texto[max(0, lower + m.start() - 5) : lower + m.start()].lower()
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
                raw_actions.append(
                    {
                        "action": action,
                        "span": match.span(),
                        "match": match.group(0),
                        "priority": self.ACTION_PRIORITY.get(action, 99),
                        "scope": "after",
                    }
                )
        for action, regex in self.trailing_regex.items():
            for match in regex.finditer(texto):
                raw_actions.append(
                    {
                        "action": action,
                        "span": match.span(),
                        "match": match.group(0),
                        "priority": self.ACTION_PRIORITY.get(action, 99),
                        "scope": "before",
                    }
                )

        if not raw_actions:
            return []

        # Sort by start position, then by priority
        raw_actions.sort(
            key=lambda x: (x["span"][0], x["priority"], -(x["span"][1] - x["span"][0]))
        )

        # Deduplicate overlapping matches
        filtered = []
        for act in raw_actions:
            overlap = False
            for existing in filtered:
                if max(act["span"][0], existing["span"][0]) < min(
                    act["span"][1], existing["span"][1]
                ):
                    overlap = True
                    break
            if not overlap:
                filtered.append(act)

        filtered.sort(key=lambda x: x["span"][0])
        return filtered

    def list_action_introduction(self, text: str) -> dict[str, Any] | None:
        """Recognize a standalone action clause that introduces a following list."""
        actions = self._detect_actions(text or "")
        if len(actions) != 1:
            return None
        action = actions[0]
        if action["action"] not in {"REVOGA", "ALTERA", "ADICIONA", "SUBSTITUI"}:
            return None
        stripped = (text or "").rstrip()
        colon_index = stripped.rfind(":")
        if colon_index < 0:
            return None
        trailing_layout = " ".join(
            re.sub(
                r"[-–—]*\s*p.gina\s+\d+\s*[-–—]*",
                " ",
                stripped[colon_index + 1 :],
                flags=re.IGNORECASE,
            )
            .casefold()
            .replace("\ufffd", "a")
            .split()
        )
        if trailing_layout and not re.fullmatch(
            r"(?:(?:estado do rio grande do norte|c.mara municipal de natal|"
            r"pal.cio padre miguelinho)\s*)+",
            trailing_layout,
        ):
            return None
        # List introductions may carry a qualifying phrase between the verb and
        # colon (e.g. “Revogam-se as disposições em contrário, em especial:”);
        # retain that whole literal clause so the inherited action is auditable.
        quote_end = colon_index
        if quote_end < action["span"][1]:
            return None
        quote = stripped[action["span"][0] : quote_end].rstrip()
        quote_end = action["span"][0] + len(quote)
        return {
            "action": action["action"],
            "quote": quote,
            "start_offset": action["span"][0],
            "end_offset": quote_end,
        }

    def extract_inherited_list_item_events(
        self, action_introduction: dict[str, Any], item_text: str
    ) -> list[dict[str, Any]]:
        """Extract a list item's explicit target under its parent's action clause.

        The item text remains the event's primary evidence span. The inherited clause is
        carried separately so callers can resolve and verify both immutable source spans.
        """
        item = (item_text or "").strip()
        action_quote = str(action_introduction.get("quote") or "").strip()
        expected_action = action_introduction.get("action")
        if not item or not action_quote or expected_action not in {
            "REVOGA",
            "ALTERA",
            "ADICIONA",
            "SUBSTITUI",
        }:
            return []

        repeated_citations = list(
            re.finditer(
                r"\bn[º°o.]?\s*(?P<number>\d[\d.]*)\s+de\s+\d{1,2}\s+de\s+"
                r"[A-Za-zÀ-ÿ]+\s+de\s+(?P<year>(?:19|20)\d{2})\b",
                item,
                flags=re.IGNORECASE,
            )
        )
        if len(repeated_citations) > 1:
            type_match = re.search(
                r"\blei(?:s)?\s+(?P<kind>complementar(?:es)?|promulgada(?:s)?|"
                r"ordin[áa]ria(?:s)?|delegada(?:s)?|org[âa]nica(?:s)?)?",
                item,
                flags=re.IGNORECASE,
            )
            raw_type = (type_match.group("kind") if type_match else "") or ""
            normalized_type = {
                "complementar": "Lei Complementar",
                "complementares": "Lei Complementar",
                "promulgada": "Lei Promulgada",
                "promulgadas": "Lei Promulgada",
                "ordinária": "Lei",
                "ordinarias": "Lei",
                "delegada": "Lei",
                "delegadas": "Lei",
                "orgânica": "Lei Orgânica",
                "organicas": "Lei Orgânica",
            }.get(raw_type.casefold(), "Lei")
            events = []
            for citation in repeated_citations:
                number = citation.group("number")
                year = citation.group("year")
                target_quote = citation.group(0)
                target_start, target_end = citation.span()
                events.append(
                    {
                        "acao": expected_action,
                        "target_text": target_quote,
                        "referencia_tipo": normalized_type.casefold(),
                        "referencia_numero": f"{number}/{year}",
                        "extraction_confidence": 0.8,
                        "extraction_method": "regex_inherited_list",
                        "norma_referenciada": {
                            "tipo": normalized_type,
                            "numero": number,
                            "ano": year,
                        },
                        "target_resolution": "candidate",
                        "evidence": {
                            "schema_version": 3,
                            "offset_unit": "python_unicode_codepoint",
                            "start_offset": 0,
                            "end_offset": len(item),
                            "action_start_offset": None,
                            "action_end_offset": None,
                            "target_start_offset": target_start,
                            "target_end_offset": target_end,
                            "action_quote": action_quote,
                            "target_quote": target_quote,
                            "quote": item,
                            "action_context": {
                                "kind": "inherited_list_action",
                                "action": expected_action,
                                "source_quote": action_quote,
                            },
                        },
                    }
                )
            return events

        synthetic = f"{action_quote}: {item}"
        item_offset = len(action_quote) + 2
        extracted = self.extract_events(synthetic)
        inciso_list = re.search(
            r"\bincisos?\s+(?P<listing>[IVXLCDM]+(?:\s*,\s*[IVXLCDM]+)*"
            r"(?:\s+e\s+[IVXLCDM]+)?)\s+do\s+art(?:igo)?\.?\s*"
            r"(?P<article>\d+[A-Za-z]?(?:-[A-Za-z])?)\b",
            item,
            flags=re.IGNORECASE,
        )
        if inciso_list:
            reference_event = next(
                (
                    event
                    for event in extracted
                    if event.get("acao") == expected_action
                    and isinstance(event.get("norma_referenciada"), dict)
                    and event["norma_referenciada"].get("ano")
                ),
                None,
            )
            if reference_event:
                target_start, target_end = inciso_list.span()
                target_quote = item[target_start:target_end]
                article_number = inciso_list.group("article")
                events = []
                for token in re.finditer(r"[IVXLCDM]+", inciso_list.group("listing"), re.I):
                    number = token.group(0).upper()
                    events.append(
                        {
                            "acao": expected_action,
                            "target_text": target_quote,
                            "referencia_tipo": "inciso",
                            "referencia_numero": number,
                            "extraction_confidence": 0.8,
                            "extraction_method": "regex_inherited_enumerated_incisos",
                            "norma_referenciada": reference_event["norma_referenciada"],
                            "target_resolution": "candidate",
                            "evidence": {
                                "schema_version": 3,
                                "offset_unit": "python_unicode_codepoint",
                                "start_offset": 0,
                                "end_offset": len(item),
                                "action_start_offset": None,
                                "action_end_offset": None,
                                "target_start_offset": target_start,
                                "target_end_offset": target_end,
                                "action_quote": action_quote,
                                "target_quote": target_quote,
                                "quote": item,
                                "structural_article_number": article_number,
                                "action_context": {
                                    "kind": "inherited_list_action",
                                    "action": expected_action,
                                    "source_quote": action_quote,
                                },
                            },
                        }
                    )
                return events
        result = []
        for event in extracted:
            if event.get("acao") != expected_action:
                continue
            evidence = dict(event.get("evidence") or {})
            target_start = evidence.get("target_start_offset")
            target_end = evidence.get("target_end_offset")
            if not isinstance(target_start, int) or not isinstance(target_end, int):
                continue
            target_start -= item_offset
            target_end -= item_offset
            if not 0 <= target_start < target_end <= len(item):
                continue
            target_quote = item[target_start:target_end]
            if not target_quote.strip():
                continue
            evidence.update(
                {
                    "schema_version": 3,
                    "start_offset": 0,
                    "end_offset": len(item),
                    "action_start_offset": None,
                    "action_end_offset": None,
                    "target_start_offset": target_start,
                    "target_end_offset": target_end,
                    "action_quote": action_quote,
                    "target_quote": target_quote,
                    "quote": item,
                    "action_context": {
                        "kind": "inherited_list_action",
                        "action": expected_action,
                        "source_quote": action_quote,
                    },
                }
            )
            event["evidence"] = evidence
            result.append(event)
        return result

    def _article_numbers(self, listing: str) -> list[str]:
        """
        Expand the number list of one article reference into individual references.

        '5º, 6º e 7º' -> ['5º', '6º', '7º'];  '7º a 9º' -> ['7º a 9º'] (a range stays ONE
        reference: the consolidation resolves it against the norma, which is the only place that
        knows about suffixed articles such as 5º-A lying between the endpoints).
        """
        tokens = [
            re.sub(r"-\s+(?=[A-Z](?:\b|$))", "-", m.group(1)) if m.group(1) else "RANGE"
            for m in self._ART_TOKEN.finditer(listing)
        ]
        numbers, i = [], 0
        while i < len(tokens):
            if tokens[i] == "RANGE":
                i += 1
            elif i + 2 < len(tokens) + 0 and tokens[i + 1] == "RANGE" and tokens[i + 2] != "RANGE":
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
            numero = match.group(2).strip().rstrip(".,;:")
            ano = self._year_value(match.group(3) or match.group(4))
            ref_text = match.group(0)

            references.append(
                {
                    "tipo": tipo_lei.lower(),
                    "numero": f"{numero}/{ano}" if ano else numero,
                    "text": ref_text,
                    "span": [match.start(), match.end()],
                    "confidence": 0.95 if ano else 0.75,
                    "norma_info": {"tipo": tipo_lei, "numero": numero, "ano": ano} if ano else None,
                }
            )

        # 2. Strict "desta Lei" (self-reference)
        for match in self.DESTA_LEI_PATTERN.finditer(texto):
            references.append(
                {
                    "tipo": "self_reference",
                    "numero": "",
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                    "confidence": 0.95,
                    "norma_info": None,
                }
            )

        # 3. Article references (singular, plural, lists and ranges)
        for match in self.ARTICLE_PATTERN.finditer(texto):
            for numero in self._article_numbers(match.group(2)):
                references.append(
                    {
                        "tipo": "artigo",
                        "numero": numero,
                        "text": match.group(0),
                        "span": [match.start(), match.end()],
                        "confidence": 0.9,
                        "norma_info": None,
                    }
                )

        # 4. Paragraph references
        for match in self.PARAGRAPH_PATTERN.finditer(texto):
            numero = match.group(1).strip() if match.group(1) else "único"
            references.append(
                {
                    "tipo": "paragrafo",
                    "numero": numero,
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                    "confidence": 0.9,
                    "norma_info": None,
                }
            )

        # 5. Inciso references
        for match in self.INCISO_PATTERN.finditer(texto):
            numero = match.group(1).strip()
            references.append(
                {
                    "tipo": "inciso",
                    "numero": numero,
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                    "confidence": 0.9,
                    "norma_info": None,
                }
            )

        # 6. Alínea references
        for match in self.ALINEA_PATTERN.finditer(texto):
            numero = match.group(1).strip()
            references.append(
                {
                    "tipo": "alinea",
                    "numero": numero,
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                    "confidence": 0.9,
                    "norma_info": None,
                }
            )

        return references
