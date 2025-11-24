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
    """
    
    # Regex patterns for legal structure
    PATTERNS = {
        'artigo': re.compile(
            r'^Art\.?\s+(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s+(.*?)$',
            re.MULTILINE | re.IGNORECASE
        ),
        'paragrafo': re.compile(
            r'^§\s*(\d+[ºª°]?(?:-[A-Z])?)\s*[\.–-]?\s+(.*?)$',
            re.MULTILINE
        ),
        'inciso': re.compile(
            r'^([IVX]+)\s*[\.–-]?\s+(.*?)$',
            re.MULTILINE
        ),
        'alinea': re.compile(
            r'^([a-z])\)\s+(.*?)$',
            re.MULTILINE
        ),
        'item': re.compile(
            r'^(\d+)\.\s+(.*?)$',
            re.MULTILINE
        ),
    }
    
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
    def extract_articles(text: str) -> List[Dict[str, Any]]:
        """
        Extract all articles from legal text.
        
        Args:
            text: Full text of the legal document
            
        Returns:
            List of dicts with article info:
            {
                'tipo': 'artigo',
                'numero': '1º',
                'texto': '...',
                'start_pos': int,
                'end_pos': int
            }
        """
        articles = []
        
        for match in LegalTextParser.PATTERNS['artigo'].finditer(text):
            articles.append({
                'tipo': 'artigo',
                'numero': match.group(1).strip(),
                'texto': match.group(2).strip(),
                'start_pos': match.start(),
                'end_pos': match.end(),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(articles)} articles")
        return articles
    
    @staticmethod
    def extract_paragraphs(text: str) -> List[Dict[str, Any]]:
        """Extract all paragraphs (§) from text."""
        paragraphs = []
        
        for match in LegalTextParser.PATTERNS['paragrafo'].finditer(text):
            paragraphs.append({
                'tipo': 'paragrafo',
                'numero': match.group(1).strip(),
                'texto': match.group(2).strip(),
                'start_pos': match.start(),
                'end_pos': match.end(),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(paragraphs)} paragraphs")
        return paragraphs
    
    @staticmethod
    def extract_incisos(text: str) -> List[Dict[str, Any]]:
        """Extract all incisos (I, II, III, etc.) from text."""
        incisos = []
        
        for match in LegalTextParser.PATTERNS['inciso'].finditer(text):
            # Skip if it's part of a date or other context
            before = text[max(0, match.start()-5):match.start()]
            if re.search(r'\d', before):  # Likely part of date
                continue
            
            incisos.append({
                'tipo': 'inciso',
                'numero': match.group(1).strip(),
                'texto': match.group(2).strip(),
                'start_pos': match.start(),
                'end_pos': match.end(),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(incisos)} incisos")
        return incisos
    
    @staticmethod
    def extract_alineas(text: str) -> List[Dict[str, Any]]:
        """Extract all alíneas (a), b), c), etc.) from text."""
        alineas = []
        
        for match in LegalTextParser.PATTERNS['alinea'].finditer(text):
            alineas.append({
                'tipo': 'alinea',
                'numero': match.group(1).strip(),
                'texto': match.group(2).strip(),
                'start_pos': match.start(),
                'end_pos': match.end(),
                'full_match': match.group(0)
            })
        
        logger.debug(f"Extracted {len(alineas)} alineas")
        return alineas
    
    @staticmethod
    def parse_legal_text(text: str) -> List[Dict[str, Any]]:
        """
        Parse full legal text and extract all structured elements.
        
        Returns a list of all elements sorted by position, ready for
        hierarchical organization.
        
        Args:
            text: Full legal text
            
        Returns:
            List of all extracted elements, sorted by position
        """
        all_elements = []
        
        # Extract all types
        all_elements.extend(LegalTextParser.extract_articles(text))
        all_elements.extend(LegalTextParser.extract_paragraphs(text))
        all_elements.extend(LegalTextParser.extract_incisos(text))
        all_elements.extend(LegalTextParser.extract_alineas(text))
        
        # Sort by position in text
        all_elements.sort(key=lambda x: x['start_pos'])
        
        logger.info(
            f"Parsed legal text: {len(all_elements)} total elements "
            f"(articles, paragraphs, incisos, alineas)"
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

