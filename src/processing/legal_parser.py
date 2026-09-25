"""
Legal text parsing utilities for Brazilian legislation.

Regex-based parser to extract hierarchical structure from legal documents.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page-artifact patterns produced by the OCR pipeline
# ---------------------------------------------------------------------------

# "--- Página 1 ---"  /  "--- Page 1 ---"  /  "=== Página 2 ==="  etc.
_PAGE_SEPARATOR_RE = re.compile(
    r"^[ \t]*[-=]{2,}[ \t]*(?:P[aá]gina|Page)[ \t]+\d+[ \t]*[-=]{2,}[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)

# Recurring Brazilian-legislative page headers (all-caps lines that appear
# at the top of every physical page in Câmara/Assembleia PDFs).
# We match only lines that are entirely composed of known header tokens so we
# don't accidentally strip content that happens to contain these words.
_PAGE_HEADER_LINE_RE = re.compile(
    r"^[ \t]*(?:"
    r"ESTADO\s+DO\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]+"  # "ESTADO DO RIO GRANDE DO NORTE"
    r"|C[AÂ]MARA\s+MUNICIPAL\s+DE\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ\s]+"  # "CÂMARA MUNICIPAL DE NATAL"
    r"|ASSEMBLEIA\s+LEGISLATIVA\s+DO\s+[A-Z\s]+"
    r"|PAL[AÁ]CIO\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ\s]+"  # "PALÁCIO PADRE MIGUELINHO"
    r"|DIÁRIO\s+OFICIAL\s+(?:DO|DA|DE)\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ\s]+"
    r"|PODER\s+LEGISLATIVO\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ\s]*"
    r")[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


class LegalTextParser:
    """
    Parser for Brazilian legal text structure using regex patterns.

    Extracts hierarchical elements like articles, paragraphs, items, etc.
    Follows ABNT NBR 6022 and Brazilian legislative writing conventions.

    CRITICAL FIX: Patterns now capture multiline text until next marker.
    """

    # Regex patterns for legal structure markers (start of devices only)
    # These patterns match the START of a device, not capture its text
    MARKER_PATTERNS = {
        "artigo": re.compile(
            r"^\s*Art\.?\s+(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s*", re.MULTILINE | re.IGNORECASE
        ),
        "paragrafo": re.compile(r"^\s*§\s*(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s*", re.MULTILINE),
        "paragrafo_unico": re.compile(
            r"^\s*Parágrafo\s+único\.?\s*[\.–-]?\s*", re.MULTILINE | re.IGNORECASE
        ),
        # A real inciso needs an explicit separator ('-', '–', '—' or '.') right
        # after the roman numeral. Anchoring with [ \t]* (never \s*) keeps the
        # match on its own line. Numeral validity is checked in _is_valid_marker.
        "inciso": re.compile(r"^[ \t]*([IVX]+)[ \t]*[-–—.][ \t]*", re.MULTILINE),
        "alinea": re.compile(r"^\s*([a-z])\)\s+", re.MULTILINE),
        # Items are 1-2 digit numbers; a year ('2020.') at line start is not one.
        "item": re.compile(r"^[ \t]*(\d{1,2})[ \t]*\.[ \t]+", re.MULTILINE),
    }

    # Combined pattern to find ANY marker (for text extraction between markers)
    ALL_MARKERS_PATTERN = re.compile(
        r"^\s*(?:Art\.?\s+\d+|§\s*\d+|Parágrafo\s+único|([IVX]+)\s*[\.–-]|([a-z])\)\s+|\d+\.\s+)",
        re.MULTILINE | re.IGNORECASE,
    )

    # Patterns for structural divisions (Parte, Livro, Título, Capítulo, Seção, Subseção)
    DIVISION_PATTERNS = {
        "parte": re.compile(
            r"^\s*(?:PARTE|Parte)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$", re.MULTILINE
        ),
        "livro": re.compile(
            r"^\s*(?:LIVRO|Livro)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$", re.MULTILINE
        ),
        "titulo": re.compile(
            r"^\s*(?:T[IÍ]TULO|T[ií]tulo)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$", re.MULTILINE
        ),
        "capitulo": re.compile(
            r"^\s*(?:CAP[IÍ]TULO|Cap[ií]tulo)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$",
            re.MULTILINE,
        ),
        "secao": re.compile(
            r"^\s*(?:SE[ÇC][ÃA]O|Se[çc][ãa]o)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$",
            re.MULTILINE,
        ),
        "subsecao": re.compile(
            r"^\s*(?:SUBSE[ÇC][ÃA]O|Subse[çc][ãa]o)\s+([IVX0-9]+|[A-ZÀ-Ú\s]+?)(?:[\s–-]+(.*))?$",
            re.MULTILINE,
        ),
    }

    # Valid roman numerals for incisos (I..XXXIX). Rejects 'IIII', 'VX', 'XIIII'.
    _ROMAN_INCISO_RE = re.compile(r"^(?=[IVX])X{0,3}(?:IX|IV|V?I{0,3})$")

    @staticmethod
    def _is_valid_marker(tipo: str, match: "re.Match", text: str) -> bool:
        """
        Decide whether a regex match is a real structural marker.

        Regexes only find candidates; prose and citations can look like markers.
        This is the single source of truth used both to compute text boundaries
        (_find_all_markers) and to build elements (extract_*), so the two can
        never disagree.

        - inciso: the numeral must be a valid roman numeral (I..XXXIX).
        - artigo: a lowercase letter or comma right after the number means the
          line is a citation broken across lines ('Art. 10 da Lei 123/2020 ...'),
          not a new article. Real articles start with a capital, quote or '('.
        """
        if tipo == "inciso":
            return bool(LegalTextParser._ROMAN_INCISO_RE.match(match.group(1)))
        if tipo == "artigo":
            nxt = text[match.end() : match.end() + 1]
            if nxt and (nxt.islower() or nxt == ","):
                return False
        return True

    @staticmethod
    def _iter_valid(tipo: str, text: str):
        """Yield only the matches of MARKER_PATTERNS[tipo] that are real markers."""
        for match in LegalTextParser.MARKER_PATTERNS[tipo].finditer(text):
            if LegalTextParser._is_valid_marker(tipo, match, text):
                yield match

    @staticmethod
    def _find_all_markers(text: str) -> list[tuple[int, str, Any]]:
        """
        Find all device and division markers in text and return sorted list.

        Returns:
            List of tuples: (position, tipo, match_object)
            Sorted by position
        """
        markers = []

        # Find all device marker types
        for tipo in LegalTextParser.MARKER_PATTERNS:
            for match in LegalTextParser._iter_valid(tipo, text):
                markers.append((match.start(), tipo, match))

        # Find all structural division types
        for tipo, pattern in LegalTextParser.DIVISION_PATTERNS.items():
            for match in pattern.finditer(text):
                markers.append((match.start(), tipo, match))

        # Sort by position
        markers.sort(key=lambda x: x[0])

        return markers

    @staticmethod
    def _extract_text_until_next_marker(
        text: str, marker_start: int, marker_end: int, all_markers: list[tuple[int, str, Any]]
    ) -> str:
        """
        Extract text from a device marker until the next marker (multiline).

        Args:
            text: Full legal text
            marker_start: Start position of current marker
            marker_end: End position of current marker (where text begins)
            all_markers: List of all markers (from _find_all_markers)

        Returns:
            Extracted text (multiline) until next marker, cleaned and normalized
        """
        # Find the next marker after current position
        next_marker_pos = None
        for pos, _, _ in all_markers:
            if pos > marker_start:
                next_marker_pos = pos
                break

        # Extract text from end of marker to next marker (or end of text)
        if next_marker_pos is not None:
            extracted_text = text[marker_end:next_marker_pos]
        else:
            extracted_text = text[marker_end:]

        # Clean text: preserve structure but normalize whitespace
        extracted_text = extracted_text.rstrip()  # Remove trailing whitespace
        # Normalize multiple consecutive newlines to max 2 (paragraph break)
        extracted_text = re.sub(r"\n{3,}", "\n\n", extracted_text)
        # Normalize multiple spaces within lines (but keep newlines)
        lines = extracted_text.split("\n")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
        extracted_text = "\n".join(lines)
        extracted_text = extracted_text.strip()

        return extracted_text

    @staticmethod
    def extract_articles(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract all articles from legal text (multiline support).

        Args:
            text: Full text of the legal document
            all_markers: Optional pre-computed list of all markers (for efficiency)

        Returns:
            List of dicts with article info:
            {
                'tipo': 'artigo',
                'numero': '1º',
                'texto': '...',  # Full multiline text
                'start_pos': int,
                'end_pos': int
            }
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        articles = []

        for match in LegalTextParser._iter_valid("artigo", text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )

            articles.append(
                {
                    "tipo": "artigo",
                    "numero": match.group(1).strip(),
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        logger.debug(f"Extracted {len(articles)} articles")
        return articles

    @staticmethod
    def extract_paragraphs(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract all paragraphs (§) and "Parágrafo único" from text (multiline support).

        Returns both numbered paragraphs (§ 1º, § 2º) and "Parágrafo único".

        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers (for efficiency)
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        paragraphs = []

        # Extract numbered paragraphs (§ 1º, § 2º, etc.)
        for match in LegalTextParser.MARKER_PATTERNS["paragrafo"].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )

            paragraphs.append(
                {
                    "tipo": "paragrafo",
                    "numero": match.group(1).strip(),
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        # Extract "Parágrafo único"
        for match in LegalTextParser.MARKER_PATTERNS["paragrafo_unico"].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )

            paragraphs.append(
                {
                    "tipo": "paragrafo",
                    "numero": "único",
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        logger.debug(f"Extracted {len(paragraphs)} paragraphs")
        return paragraphs

    @staticmethod
    def extract_incisos(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract all incisos (I, II, III, etc.) from text (multiline support).

        Only lines that start with a valid roman numeral plus an explicit separator count.

        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers (for efficiency)
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        incisos = []

        # The pattern is anchored at line start and requires a separator, and
        # _iter_valid enforces a valid roman numeral. The former look-behind for
        # dates ('\\d{4}' in the previous 10 chars) is gone: it silently dropped
        # legitimate incisos following 'Lei nº 8.666/1993:' or 'em 2020:'.
        for match in LegalTextParser._iter_valid("inciso", text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )

            incisos.append(
                {
                    "tipo": "inciso",
                    "numero": match.group(1).strip(),
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        logger.debug(f"Extracted {len(incisos)} incisos")
        return incisos

    @staticmethod
    def extract_alineas(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract all alíneas (a), b), c), etc.) from text (multiline support).

        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers (for efficiency)
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        alineas = []

        for match in LegalTextParser.MARKER_PATTERNS["alinea"].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )

            alineas.append(
                {
                    "tipo": "alinea",
                    "numero": match.group(1).strip(),
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        logger.debug(f"Extracted {len(alineas)} alineas")
        return alineas

    @staticmethod
    def _drop_repeated_blocks(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Drop article blocks that are exact repeats of an earlier block (OCR artifact:
        a page or line captured twice).

        A block is an article plus everything up to the next article. It is dropped
        only when its number AND the normalized text of every element in it match an
        earlier block, so nothing legitimate is lost: an article that reuses a number
        with different text, or with a different subtree, is kept for a human to see.
        Repeated numbering of incisos/paragraphs across different articles is not
        affected (those live in different blocks with different signatures).
        """
        blocks: list[list[dict[str, Any]]] = [[]]  # blocks[0] = anything before the first article
        for element in elements:
            if element["tipo"] == "artigo":
                blocks.append([])
            blocks[-1].append(element)

        seen = set()
        kept: list[dict[str, Any]] = list(blocks[0])
        for block in blocks[1:]:
            signature = tuple(
                (e["tipo"], e["numero"], LegalTextParser.clean_text(e["texto"])) for e in block
            )
            if signature in seen:
                logger.warning(
                    f"Dropped duplicate block for {block[0]['tipo']} {block[0]['numero']} "
                    f"(exact repeat, likely OCR); {len(block)} element(s) removed"
                )
                continue
            seen.add(signature)
            kept.extend(block)
        return kept

    @staticmethod
    def extract_items(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract numbered items ('1.', '2.', ...) that subdivide an inciso/alínea.

        Item markers were already used as text boundaries, but never extracted,
        so their text was silently lost. They are now first-class elements.
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        items = []
        for match in LegalTextParser._iter_valid("item", text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            items.append(
                {
                    "tipo": "item",
                    "numero": match.group(1).strip(),
                    "texto": texto,
                    "start_pos": marker_start,
                    "end_pos": marker_end + len(texto),
                    "full_match": match.group(0),
                }
            )

        logger.debug(f"Extracted {len(items)} items")
        return items

    @staticmethod
    def extract_divisions(
        text: str, all_markers: list[tuple[int, str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Extract structural divisions (Parte, Livro, Título, Capítulo, Seção, Subseção).

        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers

        Returns:
            List of dicts with division information
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)

        divisions = []
        for tipo, pattern in LegalTextParser.DIVISION_PATTERNS.items():
            for match in pattern.finditer(text):
                marker_start = match.start()
                marker_end = match.end()
                texto = LegalTextParser._extract_text_until_next_marker(
                    text, marker_start, marker_end, all_markers
                )
                numero = match.group(1).strip()
                inline_heading = (
                    match.group(2).strip()
                    if match.lastindex and match.lastindex >= 2 and match.group(2)
                    else ""
                )
                full_text = (inline_heading + "\n" + texto).strip() if inline_heading else texto

                divisions.append(
                    {
                        "tipo": tipo,
                        "numero": numero,
                        "texto": full_text,
                        "start_pos": marker_start,
                        "end_pos": marker_end + len(texto),
                        "full_match": match.group(0),
                    }
                )
        logger.debug(f"Extracted {len(divisions)} divisions")
        return divisions

    @staticmethod
    def strip_page_artifacts(text: str) -> str:
        """
        Remove OCR page-boundary artifacts before structural parsing.

        The OCR pipeline inserts "--- Página N ---" separators and the physical
        page headers that appear on every page of the printed document
        (e.g. "CÂMARA MUNICIPAL DE NATAL / PALÁCIO PADRE MIGUELINHO") get
        captured as literal text.  Without this step those strings end up
        inside inciso / article texts because they fall between two markers.

        Strategy:
          1. Remove "--- Página N ---" separator lines entirely.
          2. Remove known institutional header lines (all-caps, line-exact match).
          3. Collapse runs of blank lines left behind to at most one blank line.
        """
        # Step 1: page separators
        text = _PAGE_SEPARATOR_RE.sub("", text)

        # Step 2: institutional header lines
        text = _PAGE_HEADER_LINE_RE.sub("", text)

        # Step 3: collapse excessive blank lines (3+ → 1 blank line)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    @staticmethod
    def parse_legal_text(text: str) -> list[dict[str, Any]]:
        """
        Parse full legal text and extract all structured elements (multiline support).

        Returns a list of all elements sorted by position, ready for
        hierarchical organization.

        Args:
            text: Full legal text

        Returns:
            List of all extracted elements, sorted by position, with full text content
        """
        # Strip OCR page artifacts FIRST, before any marker detection.
        # This prevents page separators and institutional headers from bleeding
        # into the text content of incisos, artigos, etc.
        text = LegalTextParser.strip_page_artifacts(text)

        # Find all markers once for efficiency
        all_markers = LegalTextParser._find_all_markers(text)

        all_elements = []

        # Extract divisions and devices (pass all_markers to avoid recomputing)
        all_elements.extend(LegalTextParser.extract_divisions(text, all_markers))
        all_elements.extend(LegalTextParser.extract_articles(text, all_markers))
        all_elements.extend(LegalTextParser.extract_paragraphs(text, all_markers))
        all_elements.extend(LegalTextParser.extract_incisos(text, all_markers))
        all_elements.extend(LegalTextParser.extract_alineas(text, all_markers))
        all_elements.extend(LegalTextParser.extract_items(text, all_markers))

        # Sort by position in text
        all_elements.sort(key=lambda x: x["start_pos"])

        all_elements = LegalTextParser._drop_repeated_blocks(all_elements)

        logger.info(
            f"Parsed legal text: {len(all_elements)} total elements "
            f"(divisions, articles, paragraphs, incisos, alineas)"
        )

        return all_elements

    @staticmethod
    def build_hierarchy(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Build hierarchical structure from flat list of elements.

        Rules:
        - Structural divisions nest according to legal hierarchy (Parte -> Livro -> Título -> Capítulo -> Seção -> Subseção)
        - Articles belong to the active division, or are root level if outside divisions
        - Paragraphs belong to the previous article
        - Incisos belong to the previous paragraph or article
        - Alíneas belong to the previous inciso
        - Every element is annotated with `caminho` and `nivel`

        Args:
            elements: Flat list of extracted elements

        Returns:
            List of elements with 'parent_index', 'caminho', and 'nivel' fields added
        """
        hierarchy = []

        division_levels = ["parte", "livro", "titulo", "capitulo", "secao", "subsecao"]
        active_divisions: dict[str, int | None] = {d: None for d in division_levels}

        last_article_idx = None
        last_paragrafo_idx = None
        last_inciso_idx = None
        last_alinea_idx = None

        def _get_active_division_parent(current_div_type: str) -> int | None:
            """Find closest active parent division above current division type."""
            curr_idx = division_levels.index(current_div_type)
            for div in reversed(division_levels[:curr_idx]):
                if active_divisions[div] is not None:
                    return active_divisions[div]
            return None

        def _get_deepest_active_division() -> int | None:
            """Find deepest active division for articles."""
            for div in reversed(division_levels):
                if active_divisions[div] is not None:
                    return active_divisions[div]
            return None

        for i, elem in enumerate(elements):
            elem_copy = elem.copy()
            elem_copy["index"] = i
            elem_copy["parent_index"] = None

            tipo = elem["tipo"]

            if tipo in division_levels:
                parent_div = _get_active_division_parent(tipo)
                if parent_div is not None:
                    elem_copy["parent_index"] = parent_div

                # Update active divisions: set current and clear deeper divisions
                div_idx = division_levels.index(tipo)
                active_divisions[tipo] = i
                for deeper in division_levels[div_idx + 1 :]:
                    active_divisions[deeper] = None

                # Reset device pointers
                last_article_idx = None
                last_paragrafo_idx = None
                last_inciso_idx = None
                last_alinea_idx = None

            elif tipo == "artigo":
                # Articles belong to enclosing division or are root level
                deepest_div = _get_deepest_active_division()
                if deepest_div is not None:
                    elem_copy["parent_index"] = deepest_div

                last_article_idx = i
                last_paragrafo_idx = None
                last_inciso_idx = None
                last_alinea_idx = None

            elif tipo == "paragrafo":
                # Paragraphs belong to last article
                if last_article_idx is not None:
                    elem_copy["parent_index"] = last_article_idx
                last_paragrafo_idx = i
                last_inciso_idx = None
                last_alinea_idx = None

            elif tipo == "inciso":
                # Incisos belong to last paragraph or article
                if last_paragrafo_idx is not None:
                    elem_copy["parent_index"] = last_paragrafo_idx
                elif last_article_idx is not None:
                    elem_copy["parent_index"] = last_article_idx
                last_inciso_idx = i
                last_alinea_idx = None

            elif tipo == "alinea":
                # Alíneas belong to last inciso
                if last_inciso_idx is not None:
                    elem_copy["parent_index"] = last_inciso_idx
                elif last_paragrafo_idx is not None:
                    elem_copy["parent_index"] = last_paragrafo_idx
                elif last_article_idx is not None:
                    elem_copy["parent_index"] = last_article_idx
                last_alinea_idx = i

            elif tipo == "item":
                # Items belong to the closest enclosing device
                for parent in (
                    last_alinea_idx,
                    last_inciso_idx,
                    last_paragrafo_idx,
                    last_article_idx,
                ):
                    if parent is not None:
                        elem_copy["parent_index"] = parent
                        break

            hierarchy.append(elem_copy)

        def _format_label(item: dict[str, Any]) -> str:
            t = item.get("tipo", "")
            num = str(item.get("numero", "")).strip()
            if t == "artigo":
                return f"Art. {num}"
            elif t == "paragrafo":
                return "Parágrafo único" if num.lower() in ("único", "unico") else f"§ {num}"
            elif t == "inciso":
                return f"Inciso {num}"
            elif t == "alinea":
                return f"Alínea {num}"
            elif t == "item":
                return f"Item {num}"
            elif t == "capitulo":
                return f"Capítulo {num}"
            elif t == "secao":
                return f"Seção {num}"
            elif t == "subsecao":
                return f"Subseção {num}"
            elif t == "titulo":
                return f"Título {num}"
            elif t == "livro":
                return f"Livro {num}"
            elif t == "parte":
                return f"Parte {num}"
            return f"{t.title()} {num}".strip()

        # Materialize caminho and nivel for each element
        for elem in hierarchy:
            labels = [_format_label(elem)]
            curr_parent_idx = elem.get("parent_index")
            while curr_parent_idx is not None and 0 <= curr_parent_idx < len(hierarchy):
                parent_elem = hierarchy[curr_parent_idx]
                labels.insert(0, _format_label(parent_elem))
                curr_parent_idx = parent_elem.get("parent_index")
            elem["caminho"] = " > ".join(labels)
            elem["nivel"] = len(labels) - 1

        logger.debug(f"Built hierarchy with {len(hierarchy)} elements")
        return hierarchy

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean extracted text by removing extra whitespace and normalizing.

        Args:
            text: Raw extracted text

        Returns:
            Cleaned text
        """
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove leading/trailing whitespace
        text = text.strip()

        # Normalize common characters
        text = text.replace("–", "-")  # En-dash to hyphen
        text = text.replace("—", "-")  # Em-dash to hyphen

        return text
