"""
Legal text parsing utilities for Brazilian legislation.

Regex-based parser to extract hierarchical structure from legal documents.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


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
        'artigo': re.compile(
            r'^Art\.?\s+(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s*',
            re.MULTILINE | re.IGNORECASE
        ),
        'paragrafo': re.compile(
            r'^§\s*(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s*',
            re.MULTILINE
        ),
        'paragrafo_unico': re.compile(
            r'^Parágrafo\s+único\.?\s*[\.–-]?\s*',
            re.MULTILINE | re.IGNORECASE
        ),
        'inciso': re.compile(
            r'^([IVX]+)\s*[\.–-]?\s*',
            re.MULTILINE
        ),
        'alinea': re.compile(
            r'^([a-z])\)\s+',
            re.MULTILINE
        ),
        'item': re.compile(
            r'^(\d+)\.\s+',
            re.MULTILINE
        ),
    }
    
    # Combined pattern to find ANY marker (for text extraction between markers)
    ALL_MARKERS_PATTERN = re.compile(
        r'^(?:Art\.?\s+\d+|§\s*\d+|Parágrafo\s+único|([IVX]+)\s*[\.–-]|([a-z])\)\s+|\d+\.\s+)',
        re.MULTILINE | re.IGNORECASE
    )
    
    # Patterns for structural divisions
    DIVISION_PATTERNS = {
        'capitulo': re.compile(
            r'^CAP[IÍ]TULO\s+([IVX]+|[0-9]+)\s*[–-]?\s*(.*?)$',
            re.MULTILINE | re.IGNORECASE
        ),
        'secao': re.compile(
            r'^SE[ÇC][ÃA]O\s+([IVX]+|[0-9]+)\s*[–-]?\s*(.*?)$',
            re.MULTILINE | re.IGNORECASE
        ),
        'titulo': re.compile(
            r'^T[IÍ]TULO\s+([IVX]+|[0-9]+)\s*[–-]?\s*(.*?)$',
            re.MULTILINE | re.IGNORECASE
        ),
    }
    
    @staticmethod
    def _find_all_markers(text: str) -> List[Tuple[int, str, Any]]:
        """
        Find all device markers in text and return sorted list.
        
        Returns:
            List of tuples: (position, tipo, match_object)
            Sorted by position
        """
        markers = []
        
        # Find all marker types
        for tipo, pattern in LegalTextParser.MARKER_PATTERNS.items():
            for match in pattern.finditer(text):
                markers.append((match.start(), tipo, match))
        
        # Sort by position
        markers.sort(key=lambda x: x[0])
        
        return markers
    
    @staticmethod
    def _extract_text_until_next_marker(
        text: str, 
        marker_start: int, 
        marker_end: int,
        all_markers: List[Tuple[int, str, Any]]
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
        extracted_text = re.sub(r'\n{3,}', '\n\n', extracted_text)
        # Normalize multiple spaces within lines (but keep newlines)
        lines = extracted_text.split('\n')
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]
        extracted_text = '\n'.join(lines)
        extracted_text = extracted_text.strip()
        
        return extracted_text
    
    @staticmethod
    def extract_articles(text: str, all_markers: Optional[List[Tuple[int, str, Any]]] = None) -> List[Dict[str, Any]]:
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
        
        for match in LegalTextParser.MARKER_PATTERNS['artigo'].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            
            articles.append({
                'tipo': 'artigo',
                'numero': match.group(1).strip(),
                'texto': texto,
                'start_pos': marker_start,
                'end_pos': marker_end + len(texto),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(articles)} articles")
        return articles
    
    @staticmethod
    def extract_paragraphs(text: str, all_markers: Optional[List[Tuple[int, str, Any]]] = None) -> List[Dict[str, Any]]:
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
        for match in LegalTextParser.MARKER_PATTERNS['paragrafo'].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            
            paragraphs.append({
                'tipo': 'paragrafo',
                'numero': match.group(1).strip(),
                'texto': texto,
                'start_pos': marker_start,
                'end_pos': marker_end + len(texto),
                'full_match': match.group(0)
            })
        
        # Extract "Parágrafo único"
        for match in LegalTextParser.MARKER_PATTERNS['paragrafo_unico'].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            
            paragraphs.append({
                'tipo': 'paragrafo',
                'numero': 'único',
                'texto': texto,
                'start_pos': marker_start,
                'end_pos': marker_end + len(texto),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(paragraphs)} paragraphs")
        return paragraphs
    
    @staticmethod
    def extract_incisos(text: str, all_markers: Optional[List[Tuple[int, str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Extract all incisos (I, II, III, etc.) from text (multiline support).
        
        Validates that the match is actually an inciso (not part of a date).
        
        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers (for efficiency)
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)
        
        incisos = []
        
        for match in LegalTextParser.MARKER_PATTERNS['inciso'].finditer(text):
            marker_start = match.start()
            
            # Skip if it's part of a date or other context
            before = text[max(0, marker_start-10):marker_start]
            if re.search(r'\d{4}|\d{1,2}/\d{1,2}', before):  # Likely part of date
                continue
            
            # Additional validation: inciso should start at line beginning or after article marker
            if marker_start > 0 and text[marker_start-1] not in ['\n', '.', ':', ';', ')', ']']:
                # Check if it's actually part of previous text
                continue
            
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            
            incisos.append({
                'tipo': 'inciso',
                'numero': match.group(1).strip(),
                'texto': texto,
                'start_pos': marker_start,
                'end_pos': marker_end + len(texto),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(incisos)} incisos")
        return incisos
    
    @staticmethod
    def extract_alineas(text: str, all_markers: Optional[List[Tuple[int, str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Extract all alíneas (a), b), c), etc.) from text (multiline support).
        
        Args:
            text: Full legal text
            all_markers: Optional pre-computed list of all markers (for efficiency)
        """
        if all_markers is None:
            all_markers = LegalTextParser._find_all_markers(text)
        
        alineas = []
        
        for match in LegalTextParser.MARKER_PATTERNS['alinea'].finditer(text):
            marker_start = match.start()
            marker_end = match.end()
            texto = LegalTextParser._extract_text_until_next_marker(
                text, marker_start, marker_end, all_markers
            )
            
            alineas.append({
                'tipo': 'alinea',
                'numero': match.group(1).strip(),
                'texto': texto,
                'start_pos': marker_start,
                'end_pos': marker_end + len(texto),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(alineas)} alineas")
        return alineas
    
    @staticmethod
    def parse_legal_text(text: str) -> List[Dict[str, Any]]:
        """
        Parse full legal text and extract all structured elements (multiline support).
        
        CRITICAL FIX: Now captures full multiline text until next marker.
        
        Returns a list of all elements sorted by position, ready for
        hierarchical organization.
        
        Args:
            text: Full legal text
            
        Returns:
            List of all extracted elements, sorted by position, with full text content
        """
        # Find all markers once for efficiency
        all_markers = LegalTextParser._find_all_markers(text)
        
        all_elements = []
        
        # Extract all types (pass all_markers to avoid recomputing)
        all_elements.extend(LegalTextParser.extract_articles(text, all_markers))
        all_elements.extend(LegalTextParser.extract_paragraphs(text, all_markers))
        all_elements.extend(LegalTextParser.extract_incisos(text, all_markers))
        all_elements.extend(LegalTextParser.extract_alineas(text, all_markers))
        
        # Sort by position in text
        all_elements.sort(key=lambda x: x['start_pos'])
        
        logger.info(
            f"Parsed legal text: {len(all_elements)} total elements "
            f"(articles, paragraphs, incisos, alineas) - FULL MULTILINE TEXT CAPTURED"
        )
        
        return all_elements
    
    @staticmethod
    def build_hierarchy(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build hierarchical structure from flat list of elements.
        
        Rules:
        - Articles are always root level
        - Paragraphs belong to the previous article
        - Incisos belong to the previous paragraph or article
        - Alíneas belong to the previous inciso
        
        Args:
            elements: Flat list of extracted elements
            
        Returns:
            List of elements with 'parent_index' field added
        """
        hierarchy = []
        last_article_idx = None
        last_paragrafo_idx = None
        last_inciso_idx = None
        
        for i, elem in enumerate(elements):
            elem_copy = elem.copy()
            elem_copy['index'] = i
            elem_copy['parent_index'] = None
            
            tipo = elem['tipo']
            
            if tipo == 'artigo':
                # Articles are root level
                last_article_idx = i
                last_paragrafo_idx = None
                last_inciso_idx = None
            
            elif tipo == 'paragrafo':
                # Paragraphs belong to last article
                if last_article_idx is not None:
                    elem_copy['parent_index'] = last_article_idx
                last_paragrafo_idx = i
                last_inciso_idx = None
            
            elif tipo == 'inciso':
                # Incisos belong to last paragraph or article
                if last_paragrafo_idx is not None:
                    elem_copy['parent_index'] = last_paragrafo_idx
                elif last_article_idx is not None:
                    elem_copy['parent_index'] = last_article_idx
                last_inciso_idx = i
            
            elif tipo == 'alinea':
                # Alíneas belong to last inciso
                if last_inciso_idx is not None:
                    elem_copy['parent_index'] = last_inciso_idx
                elif last_paragrafo_idx is not None:
                    elem_copy['parent_index'] = last_paragrafo_idx
                elif last_article_idx is not None:
                    elem_copy['parent_index'] = last_article_idx
            
            hierarchy.append(elem_copy)
        
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
        text = re.sub(r'\s+', ' ', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        # Normalize common characters
        text = text.replace('–', '-')  # En-dash to hyphen
        text = text.replace('—', '-')  # Em-dash to hyphen
        
        return text

