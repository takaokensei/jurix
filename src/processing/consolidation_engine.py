"""
Consolidation Engine for Legal Norms.

This module implements the core algorithm for applying legal alterations
(revogações, alterações, adições) to generate consolidated legal texts.

The engine processes EventoAlteracao instances temporally to reconstruct
the current state of a legal norm.
"""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """
    Core engine for legal text consolidation.
    
    Applies alterations (REVOGA, ALTERA, ADICIONA) to dispositivos
    to generate the consolidated version of a norma.
    
    The engine operates on a temporal basis, processing alterations
    in chronological order based on the norma's publication date.
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
        self.revoked_dispositivos = set()
        self.altered_dispositivos = {}
        
    def consolidate(self) -> str:
        """
        Execute the consolidation process and return consolidated text.
        
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
            .order_by('ordem')
            .select_related('dispositivo_pai')
        )
        
        logger.debug(f"Loaded {len(self.dispositivos)} dispositivos")
    
    def _load_eventos(self):
        """
        Load all alteration events that affect this norma.
        
        This includes:
        - Self-alterations (dispositivos of this norma altering other dispositivos)
        - External alterations (other normas altering this one)
        """
        from src.apps.legislation.models import EventoAlteracao
        
        # Events where this norma is the target
        eventos_recebidos = EventoAlteracao.objects.filter(
            norma_alvo=self.norma
        ).select_related(
            'dispositivo_fonte',
            'dispositivo_fonte__norma',
            'dispositivo_alvo'
        ).order_by('created_at')
        
        # Events where dispositivos of this norma reference themselves
        eventos_internos = EventoAlteracao.objects.filter(
            dispositivo_fonte__norma=self.norma,
            norma_alvo=self.norma
        ).select_related(
            'dispositivo_fonte',
            'dispositivo_alvo'
        ).order_by('created_at')
        
        # Combine and deduplicate
        self.eventos = list(set(list(eventos_recebidos) + list(eventos_internos)))
        
        logger.debug(f"Loaded {len(self.eventos)} alteration events")
    
    def _process_eventos(self):
        """
        Process alteration events to identify which dispositivos are affected.
        
        Builds internal state:
        - revoked_dispositivos: Set of dispositivo IDs that were revoked
        - altered_dispositivos: Dict of dispositivo ID -> alteration info
        """
        for evento in self.eventos:
            if evento.dispositivo_alvo:
                # Specific dispositivo target identified
                if evento.acao == 'REVOGA':
                    self.revoked_dispositivos.add(evento.dispositivo_alvo.id)
                    logger.debug(
                        f"Marked dispositivo {evento.dispositivo_alvo.id} as revoked"
                    )
                    
                elif evento.acao == 'ALTERA':
                    self.altered_dispositivos[evento.dispositivo_alvo.id] = {
                        'evento': evento,
                        'fonte': evento.dispositivo_fonte,
                        'target_text': evento.target_text
                    }
                    logger.debug(
                        f"Marked dispositivo {evento.dispositivo_alvo.id} as altered"
                    )
            else:
                # No specific target, log for reference
                logger.debug(
                    f"Event {evento.id} ({evento.acao}) has no specific dispositivo target"
                )
    
    def _build_consolidated_text(self) -> str:
        """
        Build the consolidated text by reconstructing dispositivos hierarchy.
        
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
        root_dispositivos = [d for d in self.dispositivos if d.dispositivo_pai is None]
        
        for dispositivo in root_dispositivos:
            self._add_dispositivo_to_text(dispositivo, lines, level=0)
        
        # Footer with metadata
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
        
        lines.append(f"  - Consolidado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
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
        # Check if revoked
        if dispositivo.id in self.revoked_dispositivos:
            indent = "  " * level
            lines.append(
                f"{indent}{str(dispositivo)} "
                f"(REVOGADO)"
            )
            return
        
        # Check if altered
        if dispositivo.id in self.altered_dispositivos:
            indent = "  " * level
            alteration = self.altered_dispositivos[dispositivo.id]
            fonte_norma = alteration['fonte'].norma
            
            lines.append(
                f"{indent}{str(dispositivo)} "
                f"{dispositivo.texto}"
            )
            lines.append(
                f"{indent}  [ALTERADO pela {fonte_norma.tipo} {fonte_norma.numero}/{fonte_norma.ano}]"
            )
        else:
            # Normal dispositivo
            indent = "  " * level
            lines.append(
                f"{indent}{str(dispositivo)} {dispositivo.texto}"
            )
        
        # Add children recursively
        children = [
            d for d in self.dispositivos 
            if d.dispositivo_pai_id == dispositivo.id
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

