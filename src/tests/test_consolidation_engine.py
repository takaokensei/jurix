"""
Unit tests for ConsolidationEngine.

Verifies:
- Chronological ordering of alteration events
- Deterministic output (re-running gives identical SHA-256)
- Real legal consolidation semantics (ALTERA replaces text, REVOGA marks revoked)
"""

import hashlib
from datetime import date
from unittest.mock import Mock

import pytest

from src.processing.consolidation_engine import ConsolidationEngine


class TestConsolidationEngine:
    """Test suite for ConsolidationEngine."""

    @pytest.fixture
    def mock_norma(self):
        """Create mock base law to consolidate."""
        norma = Mock()
        norma.id = 100
        norma.tipo = "Lei Ordinária"
        norma.numero = "1000"
        norma.ano = 2020
        norma.data_publicacao = date(2020, 1, 10)
        norma.data_vigencia = date(2020, 1, 10)
        norma.ementa = "Institui o Código Tributário do Município."
        norma.texto_original = "Texto original completo..."
        norma.__str__ = Mock(return_value="Lei Ordinária 1000/2020")
        return norma

    @pytest.fixture
    def mock_dispositivos(self, mock_norma):
        """Create mock dispositivos hierarchy."""
        art1 = Mock()
        art1.id = 1
        art1.norma = mock_norma
        art1.tipo = "artigo"
        art1.numero = "1º"
        art1.texto = "Este código disciplina os tributos municipais."
        art1.ordem = 1
        art1.dispositivo_pai_id = None
        art1.__str__ = Mock(return_value="Art. 1º")

        art2 = Mock()
        art2.id = 2
        art2.norma = mock_norma
        art2.tipo = "artigo"
        art2.numero = "2º"
        art2.texto = "A alíquota do ISS é fixada em 5%."
        art2.ordem = 2
        art2.dispositivo_pai_id = None
        art2.__str__ = Mock(return_value="Art. 2º")

        art3 = Mock()
        art3.id = 3
        art3.norma = mock_norma
        art3.tipo = "artigo"
        art3.numero = "3º"
        art3.texto = "Fica isenta a taxa de iluminação pública."
        art3.ordem = 3
        art3.dispositivo_pai_id = None
        art3.__str__ = Mock(return_value="Art. 3º")

        return [art1, art2, art3]

    def _create_event(self, event_id, acao, target_disp, altering_norma_date, altering_num, target_text=""):
        """Helper to construct mocked alteration events with altering law metadata."""
        altering_norma = Mock()
        altering_norma.tipo = "Lei"
        altering_norma.numero = str(altering_num)
        altering_norma.ano = altering_norma_date.year
        altering_norma.data_publicacao = altering_norma_date
        altering_norma.data_vigencia = altering_norma_date

        fonte_disp = Mock()
        fonte_disp.norma = altering_norma
        fonte_disp.ordem = 1
        fonte_disp.texto = target_text

        evento = Mock()
        evento.id = event_id
        evento.acao = acao
        evento.dispositivo_alvo = target_disp
        evento.dispositivo_fonte = fonte_disp
        evento.target_text = target_text
        return evento

    def test_consolidation_deterministic_output(self, mock_norma, mock_dispositivos):
        """Test that running consolidate twice produces identical hash (determinism)."""
        engine = ConsolidationEngine(mock_norma)
        engine.dispositivos = mock_dispositivos
        engine.eventos = []

        engine._process_eventos()
        text_1 = engine._build_consolidated_text()
        text_2 = engine._build_consolidated_text()

        hash_1 = hashlib.sha256(text_1.encode("utf-8")).hexdigest()
        hash_2 = hashlib.sha256(text_2.encode("utf-8")).hexdigest()

        assert hash_1 == hash_2
        assert "TEXTO CONSOLIDADO" in text_1
        assert "Art. 1º Este código disciplina os tributos municipais." in text_1

    def test_consolidation_revocation(self, mock_norma, mock_dispositivos):
        """Test that revoked devices are marked with proper legal citation."""
        art3 = mock_dispositivos[2]
        ev_revoga = self._create_event(
            event_id=1,
            acao="REVOGA",
            target_disp=art3,
            altering_norma_date=date(2021, 6, 1),
            altering_num=200,
        )

        engine = ConsolidationEngine(mock_norma)
        engine.dispositivos = mock_dispositivos
        engine.eventos = [ev_revoga]

        engine._process_eventos()
        consolidated = engine._build_consolidated_text()

        assert "Art. 3º (Revogado pela Lei nº 200/2021)" in consolidated
        assert "Fica isenta a taxa de iluminação pública." not in consolidated

    def test_consolidation_alteration_replaces_text(self, mock_norma, mock_dispositivos):
        """Test that ALTERA replaces device text with new redaction and cites the statute."""
        art2 = mock_dispositivos[1]
        ev_altera = self._create_event(
            event_id=2,
            acao="ALTERA",
            target_disp=art2,
            altering_norma_date=date(2022, 3, 15),
            altering_num=300,
            target_text="A alíquota do ISS é fixada em 3%.",
        )

        engine = ConsolidationEngine(mock_norma)
        engine.dispositivos = mock_dispositivos
        engine.eventos = [ev_altera]

        engine._process_eventos()
        consolidated = engine._build_consolidated_text()

        assert "A alíquota do ISS é fixada em 3%." in consolidated
        assert "(Redação dada pela Lei nº 300/2022)" in consolidated
        assert "A alíquota do ISS é fixada em 5%." not in consolidated

    def test_chronological_ordering_overrides(self, mock_norma, mock_dispositivos):
        """Test that events are processed in chronological order regardless of list input order."""
        art2 = mock_dispositivos[1]

        # Earlier event: alters to 4%
        ev_earlier = self._create_event(
            event_id=10,
            acao="ALTERA",
            target_disp=art2,
            altering_norma_date=date(2021, 1, 1),
            altering_num=150,
            target_text="A alíquota do ISS é fixada em 4%.",
        )

        # Later event: alters to 2%
        ev_later = self._create_event(
            event_id=5,  # lower ID but later date
            acao="ALTERA",
            target_disp=art2,
            altering_norma_date=date(2023, 1, 1),
            altering_num=400,
            target_text="A alíquota do ISS é fixada em 2%.",
        )

        # Feed events in REVERSE chronological order
        engine = ConsolidationEngine(mock_norma)
        engine.dispositivos = mock_dispositivos
        engine.eventos = [ev_later, ev_earlier]

        # Sort key should place ev_earlier first, then ev_later
        engine.eventos.sort(key=engine._evento_sort_key)
        assert engine.eventos[0] == ev_earlier
        assert engine.eventos[1] == ev_later

        # Process chronologically: the later one wins!
        engine._process_eventos()
        consolidated = engine._build_consolidated_text()

        assert "A alíquota do ISS é fixada em 2%." in consolidated
        assert "(Redação dada pela Lei nº 400/2023)" in consolidated
