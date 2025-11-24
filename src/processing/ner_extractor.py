"""
Named Entity Recognition (NER) for Legal Alterations.

This module implements pattern-based NER to identify legal modification events
and cross-references in Brazilian legislative texts.

Focuses on detecting:
- Alteration verbs (revoga, altera, adiciona, substitui, etc.)
- Legal references (Art. X, § Y, Lei Z/YYYY)
- Target entities (normas, dispositivos)
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class LegalNERExtractor:
    """
    Extract Named Entities and alteration events from legal dispositivos.
    
    Uses regex patterns to identify:
    1. Action verbs (revoga, altera, etc.)
    2. Legal references (Art. 5º, § 2º, Lei 123/2020)
    3. Target elements
    """
    
    # Action verb patterns (Brazilian Portuguese legal language)
    ACTION_PATTERNS = {
        'REVOGA': r'\b(revog[a-z]+|ficam?\s+revogad[oa]s?)\b',
        'ALTERA': r'\b(alter[a-z]+|modific[a-z]+|ficam?\s+alterad[oa]s?)\b',
        'ADICIONA': r'\b(adicion[a-z]+|acrescen[a-z]+|inclui|ficam?\s+adicionad[oa]s?)\b',
        'SUBSTITUI': r'\b(substitu[íi][a-z]*|ficam?\s+substitu[íi]d[oa]s?)\b',
        'REGULAMENTA': r'\b(regulamenta[a-z]*|disciplina[a-z]*)\b',
        'REFERENCIA': r'\b(conforme|nos\s+termos|de\s+acordo\s+com|previsto|disposto)\b',
    }
    
    # Legal element patterns
    ARTICLE_PATTERN = re.compile(
        r'\b(art(?:igo)?\.?\s*(?:n[º°]?\s*)?)([\d]+[º°]?)',
        re.IGNORECASE
    )
    
    PARAGRAPH_PATTERN = re.compile(
        r'\b([§¶]|par[áa]grafo)\s*(?:n[º°]?\s*)?([\d]+[º°]?|[ÚUÚ]nico)',
        re.IGNORECASE
    )
    
    INCISO_PATTERN = re.compile(
        r'\binciso\s+([IVXLCDM]+|[\d]+)',
        re.IGNORECASE
    )
    
    ALINEA_PATTERN = re.compile(
        r'\bal[íi]nea\s+([a-z])\)',
        re.IGNORECASE
    )
    
    # Complex law reference (Lei X/YYYY, LC X/YYYY, Decreto X/YYYY)
    LEI_PATTERN = re.compile(
        r'\b(lei\s+(?:complementar|ordinária|delegada)?|lc|decreto|resolução)\s*'
        r'(?:n[º°]?\s*)?([\d.,]+)\s*[/\-]?\s*(\d{4})?',
        re.IGNORECASE
    )
    
    # "Da Lei X" or "desta Lei" patterns
    DESTA_LEI_PATTERN = re.compile(
        r'\b(d[aeo]st[ae]|d[aeo])\s+(lei|decreto|resolução)',
        re.IGNORECASE
    )
    
    def __init__(self):
        """Initialize the NER extractor with compiled patterns."""
        # Compile action patterns
        self.action_regex = {
            action: re.compile(pattern, re.IGNORECASE)
            for action, pattern in self.ACTION_PATTERNS.items()
        }
    
    def extract_events(
        self, 
        texto: str, 
        dispositivo_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract alteration events from dispositivo text.
        
        Args:
            texto: The text of the dispositivo
            dispositivo_id: Optional ID for debugging
            
        Returns:
            List of extracted events with structure:
            {
                'acao': str,
                'target_text': str,
                'referencia_tipo': str,
                'referencia_numero': str,
                'extraction_confidence': float,
                'extraction_method': str,
                'norma_referenciada': Optional[Dict],
            }
        """
        events = []
        
        # Step 1: Detect action verbs
        detected_actions = self._detect_actions(texto)
        
        if not detected_actions:
            logger.debug(f"No actions detected in dispositivo {dispositivo_id}")
            return events
        
        # Step 2: For each action, extract referenced entities
        for action_data in detected_actions:
            action = action_data['action']
            action_span = action_data['span']
            
            # Extract context around action (next 200 chars)
            context_start = action_span[0]
            context_end = min(len(texto), action_span[1] + 200)
            context = texto[context_start:context_end]
            
            # Extract references from context
            references = self._extract_references(context)
            
            if references:
                for ref in references:
                    event = {
                        'acao': action,
                        'target_text': ref['text'],
                        'referencia_tipo': ref['tipo'],
                        'referencia_numero': ref['numero'],
                        'extraction_confidence': ref['confidence'],
                        'extraction_method': 'regex',
                        'norma_referenciada': ref.get('norma_info'),
                    }
                    events.append(event)
            else:
                # Action without clear reference
                event = {
                    'acao': action,
                    'target_text': context[:100],  # First 100 chars as target
                    'referencia_tipo': '',
                    'referencia_numero': '',
                    'extraction_confidence': 0.5,
                    'extraction_method': 'regex',
                    'norma_referenciada': None,
                }
                events.append(event)
        
        return events
    
    def _detect_actions(self, texto: str) -> List[Dict[str, Any]]:
        """
        Detect action verbs in text.
        
        Returns:
            List of {'action': str, 'span': Tuple[int, int], 'match': str}
        """
        actions = []
        
        for action, regex in self.action_regex.items():
            matches = regex.finditer(texto)
            for match in matches:
                actions.append({
                    'action': action,
                    'span': match.span(),
                    'match': match.group(0)
                })
        
        return actions
    
    def _extract_references(self, texto: str) -> List[Dict[str, Any]]:
        """
        Extract legal references from text.
        
        Returns:
            List of reference dictionaries with tipo, numero, text, confidence
        """
        references = []
        
        # Check for law references (Lei X/YYYY)
        lei_matches = self.LEI_PATTERN.finditer(texto)
        for match in lei_matches:
            tipo_lei = match.group(1).strip()
            numero = match.group(2).strip()
            ano = match.group(3) if match.group(3) else ''
            
            ref_text = match.group(0)
            
            references.append({
                'tipo': tipo_lei.lower(),
                'numero': f"{numero}/{ano}" if ano else numero,
                'text': ref_text,
                'confidence': 0.9 if ano else 0.7,
                'norma_info': {
                    'tipo': tipo_lei,
                    'numero': numero,
                    'ano': ano
                } if ano else None
            })
        
        # Check for "desta Lei" (self-reference)
        desta_matches = self.DESTA_LEI_PATTERN.finditer(texto)
        for match in desta_matches:
            references.append({
                'tipo': 'self_reference',
                'numero': '',
                'text': match.group(0),
                'confidence': 0.95,
                'norma_info': None
            })
        
        # Check for article references
        art_matches = self.ARTICLE_PATTERN.finditer(texto)
        for match in art_matches:
            numero = match.group(2).strip()
            references.append({
                'tipo': 'artigo',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })
        
        # Check for paragraph references
        para_matches = self.PARAGRAPH_PATTERN.finditer(texto)
        for match in para_matches:
            numero = match.group(2).strip() if match.group(2) else 'único'
            references.append({
                'tipo': 'paragrafo',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })
        
        # Check for inciso references
        inciso_matches = self.INCISO_PATTERN.finditer(texto)
        for match in inciso_matches:
            numero = match.group(1).strip()
            references.append({
                'tipo': 'inciso',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })
        
        # Check for alínea references
        alinea_matches = self.ALINEA_PATTERN.finditer(texto)
        for match in alinea_matches:
            numero = match.group(1).strip()
            references.append({
                'tipo': 'alinea',
                'numero': numero,
                'text': match.group(0),
                'confidence': 0.9,
                'norma_info': None
            })
        
        return references
    
    def parse_norma_reference(
        self, 
        tipo: str, 
        numero: str, 
        ano: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a norma reference into structured components.
        
        Args:
            tipo: Type of norma (lei, decreto, etc.)
            numero: Number of the norma
            ano: Year (optional)
            
        Returns:
            Dictionary with tipo_normalizado, numero_normalizado, ano
        """
        # Normalize tipo
        tipo_map = {
            'lei': 'Lei',
            'lc': 'Lei Complementar',
            'lei complementar': 'Lei Complementar',
            'decreto': 'Decreto',
            'resolução': 'Resolução',
            'resoluçao': 'Resolução',
        }
        
        tipo_normalizado = tipo_map.get(tipo.lower(), tipo)
        
        # Clean numero (remove dots, commas)
        numero_normalizado = numero.replace('.', '').replace(',', '')
        
        return {
            'tipo': tipo_normalizado,
            'numero': numero_normalizado,
            'ano': ano
        }

