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
from typing import List, Dict, Any, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """
    Core engine for legal text consolidation.
    
    Applies alterations (REVOGA, ALTERA, ADICIONA, SUBSTITUI) to dispositivos
    to generate the consolidated version of a norma.
    
    Processes alterations strictly in chronological order based on the modifying
    norma's publication/enactment date.
    """
    
    # Actions that change the consolidated text. When one of them cannot be
    # applied, the norma must not be presented as fully consolidated.
    APPLYING_ACTIONS = ('REVOGA', 'ALTERA', 'SUBSTITUI', 'ADICIONA')
    ELEMENT_TYPES = ('artigo', 'paragrafo', 'inciso', 'alinea')

    def __init__(self, norma):
        """
        Initialize the consolidation engine for a specific norma.
        
        Args:
            norma: The Norma instance to consolidate
        """
        self.norma = norma
        self.dispositivos = []
        self.eventos = []
        self.revoked_dispositivos = {}  # disp_id -> {'evento', 'norma_ref'}
        self.altered_dispositivos = {}  # disp_id -> {'evento', 'fonte', 'new_text', 'norma_ref'}
        self.added_dispositivos = []    # list of addition entries (see _register_addition)
        self.unresolved_eventos = []    # events that could NOT be applied (see _mark_unresolved)
        self.applied_events = 0
        self._additions_by_anchor: Dict[int, List[Dict[str, Any]]] = {}
        self._emitted_anchors: Set[int] = set()
        
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
            f"{len(self.altered_dispositivos)} altered, "
            f"{len(self.added_dispositivos)} added, "
            f"{len(self.unresolved_eventos)} unresolved events"
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
    
    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------
    def _process_eventos(self):
        """
        Process alteration events chronologically to reconstruct state.
        
        Reconstructs:
        - revoked_dispositivos / altered_dispositivos: only for events whose
          target dispositivo is resolved.
        - added_dispositivos: additions we could extract and (when possible) place.
        - unresolved_eventos: applying events (REVOGA/ALTERA/SUBSTITUI/ADICIONA)
          that could NOT be applied. They are reported, never silently dropped.
        
        Informational actions (REGULAMENTA, REFERENCIA) never alter the text.
        """
        self.revoked_dispositivos = {}
        self.altered_dispositivos = {}
        self.added_dispositivos = []
        self.unresolved_eventos = []
        self.applied_events = 0
        additions: Dict[Tuple, Dict[str, Any]] = {}
        
        for evento in self.eventos:
            acao = (evento.acao or '').upper()
            target = evento.dispositivo_alvo
            fonte = evento.dispositivo_fonte
            norma_fonte = fonte.norma if fonte else None
            
            ref_str = ""
            if norma_fonte:
                ref_str = f"{norma_fonte.tipo} nº {norma_fonte.numero}/{norma_fonte.ano}"
            
            if acao == 'ADICIONA':
                self._register_addition(evento, fonte, ref_str, additions)
                continue
            
            if acao not in self.APPLYING_ACTIONS:
                continue  # REGULAMENTA / REFERENCIA: informational only
            
            if target is None:
                self._mark_unresolved(evento, ref_str, 'dispositivo alvo não identificado')
                continue
            
            if acao == 'REVOGA':
                self.revoked_dispositivos[target.id] = {
                    'evento': evento,
                    'norma_ref': ref_str,
                }
                # If previously altered, revocation overrides it
                if target.id in self.altered_dispositivos:
                    del self.altered_dispositivos[target.id]
                self.applied_events += 1
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
                self.applied_events += 1
                logger.debug(f"Dispositivo {target.id} marked as altered by {ref_str}")
        
        self.added_dispositivos = list(additions.values())
        self._place_additions()
    
    def _mark_unresolved(self, evento, ref_str: str, reason: str):
        """Record an applying event that could not be applied to the text."""
        self.unresolved_eventos.append({
            'evento': evento,
            'norma_ref': ref_str,
            'reason': reason,
        })
        logger.debug(f"Event {getattr(evento, 'id', None)} unresolved: {reason}")
    
    # -- additions ------------------------------------------------------
    @staticmethod
    def _article_key(numero) -> Optional[Tuple[int, str]]:
        """'2º' -> (2, ''), '2º-A' -> (2, 'A'). None when not an article number."""
        m = re.match(r'^\s*(\d+)\s*[ºª°o]?\s*(?:-\s*([A-Za-z]+))?\s*[.,]?\s*$', str(numero or ''))
        if not m:
            return None
        return (int(m.group(1)), (m.group(2) or '').upper())
    
    @staticmethod
    def _label(tipo: str, numero: str) -> str:
        if tipo == 'artigo':
            return f"Art. {numero}"
        if tipo == 'paragrafo':
            return "Parágrafo único" if numero.lower() in ('único', 'unico') else f"§ {numero}"
        if tipo == 'inciso':
            return f"Inciso {numero}"
        return f"Alínea {numero})"
    
    # '2', '2º', '2º-A', '4º-A' -> captures (digits, optional suffix letters)
    _NUM_RE = r'(\d+)\s*[ºª°o]?(?:\s*-\s*([A-Za-z]{1,2})(?![A-Za-z]))?'
    
    @staticmethod
    def _strip_label(candidate: str, tipo: str, numero: str) -> Optional[str]:
        """
        If `candidate` starts with the label of the expected device, return the
        text after the label; otherwise None.
        
        The label is parsed and its numeric key COMPARED with the expected one
        (never encoded in the regex), so 'Art. 2º' can never match 'Art. 2º-A'
        and '§ 4º' can never match '§ 4º-A' through regex backtracking.
        """
        num = ConsolidationEngine._NUM_RE
        if tipo == 'paragrafo' and numero.lower() in ('único', 'unico'):
            m = re.match(r'^\s*Par[áa]grafo\s+[úu]nico\s*[.\-–—]?\s*', candidate, re.IGNORECASE)
            return candidate[m.end():] if m else None
        if tipo in ('artigo', 'paragrafo'):
            expected = ConsolidationEngine._article_key(numero)
            if expected is None:
                return None
            head = r'Art\.?' if tipo == 'artigo' else '§'
            m = re.match(rf'^\s*{head}\s*{num}\s*[.\-–—]?\s*', candidate, re.IGNORECASE)
            if m and (int(m.group(1)), (m.group(2) or '').upper()) == expected:
                return candidate[m.end():]
            return None
        if tipo == 'inciso':
            m = re.match(r'^\s*([IVXLC]+)\s*[-–—.]\s*', candidate)
            return candidate[m.end():] if m and m.group(1) == numero.upper() else None
        if tipo == 'alinea':
            m = re.match(r'^\s*([a-z])\)\s*', candidate)
            return candidate[m.end():] if m and m.group(1) == numero.lower() else None
        return None
    
    @staticmethod
    def _quoted_passages(texto: str) -> List[str]:
        """
        Return the quoted passages of `texto`, honouring nesting of curly quotes.
        
        Amending laws often quote a term inside the quoted wording
        (“§ 4º Aplica-se o “Plano Diretor”.”); a non-greedy regex would cut the
        passage at the first closing quote. Unbalanced quotes yield nothing for
        that passage, so callers fall back instead of using a truncated text.
        Straight quotes (") cannot nest and pair with the next straight quote.
        """
        openers, closers = '“«', '”»'
        passages, i = [], 0
        while i < len(texto):
            ch = texto[i]
            if ch in openers:
                depth, j = 1, i + 1
                while j < len(texto) and depth:
                    if texto[j] in openers:
                        depth += 1
                    elif texto[j] in closers:
                        depth -= 1
                    j += 1
                if depth == 0:
                    passages.append(texto[i + 1:j - 1])
                    i = j
                    continue
            elif ch == '"':
                j = texto.find('"', i + 1)
                if j != -1:
                    passages.append(texto[i + 1:j])
                    i = j + 1
                    continue
            i += 1
        return passages
    
    @staticmethod
    def _extract_added_text(fonte_texto: str, tipo: str, numero: str) -> Tuple[str, bool]:
        """
        Extract the new device's wording from the amending dispositivo.
        
        Amending laws quote the new wording: 'Fica acrescido o Art. 2º-A: “Art. 2º-A O
        prazo é de 30 dias.”'. Only a quoted passage that STARTS with the expected
        label is accepted (a quoted 'Plano Diretor' must never become the text).
        
        Returns (text, extracted). When nothing can be extracted reliably, returns the
        whole amending text and extracted=False so the output can say so explicitly.
        """
        texto = fonte_texto or ''
        for candidate in ConsolidationEngine._quoted_passages(texto):
            body = ConsolidationEngine._strip_label(candidate.strip(), tipo, numero)
            if body is not None:
                return ' '.join(body.split()), True
        return ' '.join(texto.split()), False
    
    def _register_addition(self, evento, fonte, ref_str: str, additions: Dict[Tuple, Dict[str, Any]]):
        """Register an ADICIONA event as an added dispositivo, or flag it unresolved."""
        tipo = (evento.referencia_tipo or '').lower()
        numero = (evento.referencia_numero or '').strip()
        
        if tipo not in self.ELEMENT_TYPES or not numero:
            self._mark_unresolved(evento, ref_str, 'adição sem dispositivo identificável')
            return
        
        key = None
        if tipo == 'artigo':
            key = self._article_key(numero)
            if key is None:
                self._mark_unresolved(evento, ref_str, 'número de artigo inválido')
                return
            if any(d.tipo == 'artigo' and self._article_key(d.numero) == key
                   for d in self.dispositivos):
                # 'acrescido o § 4º ao Art. 2º' also yields an 'Art. 2º' reference:
                # that is an anchor, not a new article. Never duplicate Art. 2º.
                self._mark_unresolved(
                    evento, ref_str,
                    'artigo já existe: referência de âncora, não uma adição'
                )
                return
            dedupe_key = (tipo, key)  # a later law re-adding the same article supersedes
        else:
            # Without the parent path, equal numbers may be different devices.
            dedupe_key = (tipo, numero, getattr(evento, 'id', None))
        
        texto, extracted = self._extract_added_text(
            fonte.texto if fonte else '', tipo, numero
        )
        additions[dedupe_key] = {
            'evento': evento,
            'norma_ref': ref_str,
            'tipo': tipo,
            'numero': numero,
            'label': self._label(tipo, numero),
            'texto': texto,
            'extracted': extracted,
            'key': key,
            'anchor_id': None,
        }
        self.applied_events += 1
    
    def _place_additions(self):
        """
        Anchor each added article right after the closest preceding article
        (highest existing number <= the new one), so 'Art. 2º-A' lands after
        'Art. 2º'. Anything that cannot be placed is listed in a trailing section.
        """
        self._additions_by_anchor = {}
        keyed = [
            (self._article_key(d.numero), d)
            for d in self.dispositivos if d.tipo == 'artigo'
        ]
        keyed = [(k, d) for k, d in keyed if k is not None]
        
        for entry in self.added_dispositivos:
            entry['anchor_id'] = None
            if entry['tipo'] != 'artigo':
                continue
            candidates = [(k, d) for k, d in keyed if k <= entry['key']]
            if not candidates:
                continue
            _, anchor = max(candidates, key=lambda kd: kd[0])
            entry['anchor_id'] = anchor.id
            self._additions_by_anchor.setdefault(anchor.id, []).append(entry)
        
        for entries in self._additions_by_anchor.values():
            entries.sort(key=lambda e: e['key'])
    
    @staticmethod
    def _format_addition(entry: Dict[str, Any]) -> str:
        ref = entry.get('norma_ref')
        citation = f" (Incluído pela {ref})" if ref else " (Incluído)"
        if entry['extracted']:
            body = entry['texto']
        elif entry['texto']:
            body = f"[redação não extraída; texto da norma alteradora: {entry['texto']}]"
        else:
            body = "[redação não extraída]"
        return f"{entry['label']} {body}{citation}"
    
    def _emit_additions(self, disp_id: int, indent: str, lines: List[str]):
        """Emit additions anchored after the dispositivo `disp_id`."""
        for entry in self._additions_by_anchor.get(disp_id, []):
            lines.append(f"{indent}{self._format_addition(entry)}")
        if disp_id in self._additions_by_anchor:
            self._emitted_anchors.add(disp_id)
    
    # ------------------------------------------------------------------
    # Text building
    # ------------------------------------------------------------------
    def _build_consolidated_text(self) -> str:
        """
        Build deterministic consolidated text by reconstructing dispositivos hierarchy.
        
        Follows Brazilian legal standards (Decreto nº 9.191/2017):
        - Revoked devices are explicitly marked with citation.
        - Altered devices display the active updated text with citation.
        - Added devices are placed after their preceding article, or listed in an
          explicit trailing section when their position cannot be determined.
        - Events that could not be applied are listed, never hidden.
        - Output is 100% deterministic (no runtime timestamps in text).
        
        Returns:
            Formatted consolidated text
        """
        lines = []
        self._emitted_anchors = set()
        
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
        
        # Additions that could not be positioned (or whose anchor was not rendered,
        # e.g. inside a revoked division) are listed explicitly.
        trailing = [
            e for e in self.added_dispositivos
            if e['anchor_id'] is None or e['anchor_id'] not in self._emitted_anchors
        ]
        if trailing:
            lines.append("")
            lines.append("-" * 80)
            lines.append("DISPOSITIVOS ADICIONADOS (POSIÇÃO NÃO DETERMINADA; REVISÃO NECESSÁRIA):")
            for entry in trailing:
                lines.append(f"  {self._format_addition(entry)}")
        
        if self.unresolved_eventos:
            lines.append("")
            lines.append("-" * 80)
            lines.append("EVENTOS NÃO RESOLVIDOS (NÃO APLICADOS AO TEXTO ACIMA; REVISÃO NECESSÁRIA):")
            for item in self.unresolved_eventos:
                ev = item['evento']
                origem = f" [{item['norma_ref']}]" if item['norma_ref'] else ""
                ref = ' '.join((ev.target_text or '').split())[:120] or "(sem referência)"
                lines.append(f"  - {(ev.acao or '').upper()}{origem}: {ref} — {item['reason']}")
        
        # Footer with metadata (strictly deterministic)
        lines.append("")
        lines.append("-" * 80)
        lines.append("INFORMAÇÕES DE CONSOLIDAÇÃO:")
        lines.append(f"  - Total de dispositivos: {len(self.dispositivos)}")
        lines.append(f"  - Dispositivos revogados: {len(self.revoked_dispositivos)}")
        lines.append(f"  - Dispositivos alterados: {len(self.altered_dispositivos)}")
        lines.append(f"  - Dispositivos adicionados: {len(self.added_dispositivos)}")
        lines.append(f"  - Eventos considerados: {len(self.eventos)}")
        lines.append(f"  - Eventos aplicados: {self.applied_events}")
        lines.append(f"  - Eventos não resolvidos: {len(self.unresolved_eventos)}")
        if self.unresolved_eventos or self.added_dispositivos:
            lines.append("  - REVISÃO NECESSÁRIA: sim")
        
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
            self._emit_additions(disp_id, indent, lines)
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
        
        # Additions anchored after this dispositivo (after its whole subtree)
        self._emit_additions(disp_id, indent, lines)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get consolidation statistics.
        
        `events_processed` counts events CONSIDERED (kept for compatibility);
        `events_applied` counts those that actually changed the text, and
        `events_unresolved` those that could not be applied. `needs_review` is
        True whenever the result depends on unapplied or heuristically extracted
        content, so a norma is never presented as fully consolidated by accident.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_dispositivos': len(self.dispositivos),
            'revoked_count': len(self.revoked_dispositivos),
            'altered_count': len(self.altered_dispositivos),
            'added_count': len(self.added_dispositivos),
            'events_processed': len(self.eventos),
            'events_applied': self.applied_events,
            'events_unresolved': len(self.unresolved_eventos),
            'needs_review': bool(self.unresolved_eventos or self.added_dispositivos),
            'norma_str': str(self.norma),
        }
