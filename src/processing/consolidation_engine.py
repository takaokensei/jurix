"""
Consolidation Engine for Legal Norms.

This module implements the core algorithm for applying legal alterations
(revogações, alterações, adições) to generate consolidated legal texts.

The engine processes EventoAlteracao instances temporally based on the
chronological order of enacting laws to reconstruct the current legal state.
"""

import logging
import re
from datetime import date
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """
    Core engine for legal text consolidation.
    
    Applies alterations (REVOGA, ALTERA, ADICIONA, SUBSTITUI) to dispositivos
    to generate the consolidated version of a norma.
    
    Processes alterations strictly in chronological order based on the modifying
    norma's publication/enactment date.
    """
    
    def __init__(self, norma):
        """
        Initialize the consolidation engine for a specific norma.
        
        Args:
            norma: The Norma instance to consolidate
        """
        self.norma = norma
        self.dispositivos = []
        self.eventos = []
        self.revoked_dispositivos = {}  # disp_id -> EventoAlteracao
        self.altered_dispositivos = {}  # disp_id -> EventoAlteracao
        self.added_dispositivos = []    # list of EventoAlteracao or synthetic Dispositivo
        
    def consolidate(self) -> str:
        """
        Execute the consolidation process and return deterministic consolidated text.
        
        Returns:
            String containing the consolidated legal text
        """
        logger.info(f"Starting consolidation for {self.norma}")
        
        # Step 1: Load all dispositivos for this norma
        self._load_dispositivos()
        
        if not self.dispositivos:
            logger.warning(f"No dispositivos found for {self.norma}")
            return self.norma.texto_original or ""
        
        # Step 2: Load all alteration events affecting this norma
        self._load_eventos()
        
        # Step 3: Process events to identify revocations and alterations
        self._process_eventos()
        
        # Step 4: Build consolidated text
        consolidated_text = self._build_consolidated_text()
        
        logger.info(
            f"Consolidation completed for {self.norma}: "
            f"{len(self.dispositivos)} dispositivos, "
            f"{len(self.revoked_dispositivos)} revoked, "
            f"{len(self.altered_dispositivos)} altered"
        )
        
        return consolidated_text
    
    def _load_dispositivos(self):
        """Load all dispositivos for the norma, ordered hierarchically."""
        from src.apps.legislation.models import Dispositivo
        
        self.dispositivos = list(
            Dispositivo.objects.filter(norma=self.norma)
            .order_by('ordem', 'id')
            .select_related('dispositivo_pai')
        )
        
        logger.debug(f"Loaded {len(self.dispositivos)} dispositivos")
    
    @staticmethod
    def _evento_sort_key(evento):
        """
        Generate chronological sort key for an alteration event.
        
        Orders by:
        1. Publication / enactment date of the modifying norma
        2. Year of the modifying norma
        3. Numeric identifier of the modifying norma
        4. Order of the modifying dispositivo
        5. Database ID as deterministic tie-breaker
        """
        fonte = getattr(evento, 'dispositivo_fonte', None)
        norma_fonte = getattr(fonte, 'norma', None) if fonte else None
        
        # Prefer publication date, then enactment date
        data = None
        if norma_fonte:
            data = norma_fonte.data_publicacao or norma_fonte.data_vigencia
            
        ano = (norma_fonte.ano or 0) if norma_fonte else 0
        
        num = 0
        if norma_fonte and norma_fonte.numero:
            digits = re.sub(r'\D', '', str(norma_fonte.numero))
            num = int(digits) if digits else 0
            
        ordem = fonte.ordem if (fonte and fonte.ordem is not None) else 0
        ev_id = evento.id or 0
        
        # date.min for null dates to ensure consistent sortable comparison
        sort_date = data if isinstance(data, date) else date.min
        
        return (sort_date, ano, num, ordem, ev_id)
    
    def _load_eventos(self):
        """
        Load all alteration events that affect this norma with deterministic ordering.
        
        Deduplicates by ID and sorts strictly chronologically according to the
        enacting statute's legal date.
        """
        from src.apps.legislation.models import EventoAlteracao
        
        # Events where this norma is the target
        eventos_recebidos = list(
            EventoAlteracao.objects.filter(norma_alvo=self.norma)
            .select_related(
                'dispositivo_fonte',
                'dispositivo_fonte__norma',
                'dispositivo_alvo'
            )
        )
        
        # Events where dispositivos of this norma reference themselves
        eventos_internos = list(
            EventoAlteracao.objects.filter(
                dispositivo_fonte__norma=self.norma,
                norma_alvo=self.norma
            ).select_related(
                'dispositivo_fonte',
                'dispositivo_alvo'
            )
        )
        
        # Combine and deduplicate preserving deterministic order
        seen_ids = set()
        unique_eventos = []
        for ev in eventos_recebidos + eventos_internos:
            if ev.id not in seen_ids:
                seen_ids.add(ev.id)
                unique_eventos.append(ev)
        
        # Sort chronologically by enacting law
        unique_eventos.sort(key=self._evento_sort_key)
        self.eventos = unique_eventos
        
        logger.debug(f"Loaded {len(self.eventos)} alteration events deterministically")
    
    def _process_eventos(self):
        """
        Process alteration events chronologically to reconstruct state.
        
        Reconstructs:
        - revoked_dispositivos: disp_id -> EventoAlteracao
        - altered_dispositivos: disp_id -> {evento, new_text, source_ref}
        - added_dispositivos: list of EventoAlteracao
        """
        self.revoked_dispositivos = {}
        self.altered_dispositivos = {}
        self.added_dispositivos = []
        
        for evento in self.eventos:
            acao = (evento.acao or '').upper()
            target = evento.dispositivo_alvo
            fonte = evento.dispositivo_fonte
            norma_fonte = fonte.norma if fonte else None
            
            ref_str = ""
            if norma_fonte:
                ref_str = f"{norma_fonte.tipo} nº {norma_fonte.numero}/{norma_fonte.ano}"
            
            if target:
                if acao == 'REVOGA':
                    self.revoked_dispositivos[target.id] = {
                        'evento': evento,
                        'norma_ref': ref_str,
                    }
                    # If previously altered, revocation overrides it
                    if target.id in self.altered_dispositivos:
                        del self.altered_dispositivos[target.id]
                    logger.debug(f"Dispositivo {target.id} marked as revoked by {ref_str}")
                    
                elif acao in ('ALTERA', 'SUBSTITUI'):
                    # If device is revoked, subsequent alteration might restore or redefine it
                    if target.id in self.revoked_dispositivos:
                        del self.revoked_dispositivos[target.id]
                    
                    # The new text comes from target_text or the source dispositivo's text
                    new_text = ""
                    if evento.target_text and not evento.target_text.lower().startswith('art'):
                        new_text = evento.target_text.strip()
                    elif fonte and fonte.texto:
                        new_text = fonte.texto.strip()
                        
                    self.altered_dispositivos[target.id] = {
                        'evento': evento,
                        'fonte': fonte,
                        'new_text': new_text,
                        'norma_ref': ref_str,
                    }
                    logger.debug(f"Dispositivo {target.id} marked as altered by {ref_str}")
            else:
                if acao == 'ADICIONA':
                    self.added_dispositivos.append({
                        'evento': evento,
                        'norma_ref': ref_str,
                    })
                    logger.debug(f"Event {evento.id} recorded as added dispositivo")
    
    def _build_consolidated_text(self) -> str:
        """
        Build deterministic consolidated text by reconstructing dispositivos hierarchy.
        
        Follows Brazilian legal standards (Decreto nº 9.191/2017):
        - Revoked devices are explicitly marked with citation.
        - Altered devices display the active updated text with citation.
        - Output is 100% deterministic (no runtime timestamps in text).
        
        Returns:
            Formatted consolidated text
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append(f"{self.norma.tipo} Nº {self.norma.numero}/{self.norma.ano}")
        lines.append("TEXTO CONSOLIDADO")
        lines.append("=" * 80)
        lines.append("")
        
        if self.norma.ementa:
            lines.append(f"EMENTA: {self.norma.ementa}")
            lines.append("")
        
        # Process dispositivos hierarchically
        root_dispositivos = [d for d in self.dispositivos if d.dispositivo_pai_id is None]
        
        for dispositivo in root_dispositivos:
            self._add_dispositivo_to_text(dispositivo, lines, level=0)
        
        # Footer with metadata (strictly deterministic)
        lines.append("")
        lines.append("-" * 80)
        lines.append("INFORMAÇÕES DE CONSOLIDAÇÃO:")
        lines.append(f"  - Total de dispositivos: {len(self.dispositivos)}")
        lines.append(f"  - Dispositivos revogados: {len(self.revoked_dispositivos)}")
        lines.append(f"  - Dispositivos alterados: {len(self.altered_dispositivos)}")
        lines.append(f"  - Eventos processados: {len(self.eventos)}")
        
        if self.norma.data_publicacao:
            lines.append(f"  - Data de publicação: {self.norma.data_publicacao}")
        if self.norma.data_vigencia:
            lines.append(f"  - Data de vigência: {self.norma.data_vigencia}")
            
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def _add_dispositivo_to_text(
        self, 
        dispositivo, 
        lines: List[str], 
        level: int
    ):
        """
        Recursively add dispositivo and its children to the text.
        
        Args:
            dispositivo: The Dispositivo instance
            lines: List of text lines to append to
            level: Current hierarchy level (for indentation)
        """
        indent = "  " * level
        disp_id = dispositivo.id
        header = str(dispositivo).strip()
        
        # Case 1: Device is revoked
        if disp_id in self.revoked_dispositivos:
            rev_info = self.revoked_dispositivos[disp_id]
            ref = rev_info.get('norma_ref')
            citation = f" (Revogado pela {ref})" if ref else " (Revogado)"
            lines.append(f"{indent}{header}{citation}")
            return
        
        # Case 2: Device has been altered
        if disp_id in self.altered_dispositivos:
            alt_info = self.altered_dispositivos[disp_id]
            ref = alt_info.get('norma_ref')
            new_text = alt_info.get('new_text')
            
            # Use new text if available, otherwise original text
            effective_text = new_text if new_text else dispositivo.texto
            citation = f" (Redação dada pela {ref})" if ref else " (Alterado)"
            
            lines.append(f"{indent}{header} {effective_text}{citation}")
        else:
            # Case 3: Normal untouched device
            lines.append(f"{indent}{header} {dispositivo.texto}")
        
        # Add children recursively
        children = [
            d for d in self.dispositivos 
            if d.dispositivo_pai_id == disp_id
        ]
        
        for child in children:
            self._add_dispositivo_to_text(child, lines, level + 1)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get consolidation statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_dispositivos': len(self.dispositivos),
            'revoked_count': len(self.revoked_dispositivos),
            'altered_count': len(self.altered_dispositivos),
            'events_processed': len(self.eventos),
            'norma_str': str(self.norma),
        }
