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


class TestConsolidationAdditionsAndHonestStats:
    """Regression tests for audit P0.3: ADICIONA used to be silently dropped
    while the footer still claimed the event had been processed."""

    @pytest.fixture
    def norma(self):
        n = Mock()
        n.id = 100
        n.tipo = "Lei Ordinária"
        n.numero = "1000"
        n.ano = 2020
        n.data_publicacao = date(2020, 1, 10)
        n.data_vigencia = None
        n.ementa = "Institui o Código."
        n.texto_original = "orig"
        n.__str__ = Mock(return_value="Lei Ordinária 1000/2020")
        return n

    @pytest.fixture
    def arts(self, norma):
        out = []
        for i, (num, txt) in enumerate(
            [("1º", "Primeiro."), ("2º", "Segundo."), ("3º", "Terceiro.")], start=1
        ):
            d = Mock()
            d.id = i
            d.norma = norma
            d.tipo = "artigo"
            d.numero = num
            d.texto = txt
            d.ordem = i
            d.dispositivo_pai_id = None
            d.__str__ = Mock(return_value=f"Art. {num}")
            out.append(d)
        return out

    def _event(self, ev_id, acao, alvo=None, *, ref_tipo="", ref_num="",
               fonte_texto="Fica acrescido dispositivo.", when=date(2021, 5, 1), num=200):
        norma_fonte = Mock()
        norma_fonte.tipo = "Lei"
        norma_fonte.numero = str(num)
        norma_fonte.ano = when.year
        norma_fonte.data_publicacao = when
        norma_fonte.data_vigencia = when
        fonte = Mock()
        fonte.norma = norma_fonte
        fonte.ordem = 1
        fonte.texto = fonte_texto
        ev = Mock()
        ev.id = ev_id
        ev.acao = acao
        ev.dispositivo_alvo = alvo
        ev.dispositivo_fonte = fonte
        ev.target_text = f"Art. {ref_num}" if ref_num else ""
        ev.referencia_tipo = ref_tipo
        ev.referencia_numero = ref_num
        return ev

    def _run(self, norma, arts, eventos):
        engine = ConsolidationEngine(norma)
        engine.dispositivos = arts
        engine.eventos = sorted(eventos, key=ConsolidationEngine._evento_sort_key)
        engine._process_eventos()
        return engine, engine._build_consolidated_text()

    def test_suffixed_article_is_inserted_right_after_its_base_article(self, norma, arts):
        ev = self._event(1, "ADICIONA", ref_tipo="artigo", ref_num="2º-A",
                         fonte_texto="Fica acrescido o Art. 2º-A com nova regra.")
        engine, text = self._run(norma, arts, [ev])

        assert "Art. 2º-A" in text
        assert "Incluído pela Lei nº 200/2021" in text
        # Position: after Art. 2º and before Art. 3º
        assert text.index("Art. 2º Segundo.") < text.index("Art. 2º-A") < text.index("Art. 3º Terceiro.")
        assert engine.get_statistics()["added_count"] == 1

    def test_unpositionable_addition_goes_to_explicit_trailing_section(self, norma, arts):
        ev = self._event(1, "ADICIONA", ref_tipo="paragrafo", ref_num="4º",
                         fonte_texto="Acrescenta o § 4º com nova regra.")
        engine, text = self._run(norma, arts, [ev])

        assert "DISPOSITIVOS ADICIONADOS" in text
        assert "§ 4º" in text
        assert text.index("Art. 3º Terceiro.") < text.index("DISPOSITIVOS ADICIONADOS")
        assert engine.get_statistics()["added_count"] == 1

    def test_additions_flag_norma_for_review(self, norma, arts):
        ev = self._event(1, "ADICIONA", ref_tipo="artigo", ref_num="2º-A")
        engine, _ = self._run(norma, arts, [ev])
        assert engine.get_statistics()["needs_review"] is True

    def test_revoga_without_resolved_target_is_reported_not_swallowed(self, norma, arts):
        ev = self._event(1, "REVOGA", alvo=None, ref_tipo="artigo", ref_num="9º")
        engine, text = self._run(norma, arts, [ev])
        stats = engine.get_statistics()

        assert stats["events_processed"] == 1      # considered
        assert stats["events_applied"] == 0        # but NOT applied
        assert stats["events_unresolved"] == 1
        assert stats["needs_review"] is True
        assert "não resolvidos" in text.lower()

    def test_informational_actions_do_not_require_review(self, norma, arts):
        ev = self._event(1, "REGULAMENTA")
        engine, _ = self._run(norma, arts, [ev])
        stats = engine.get_statistics()
        assert stats["events_unresolved"] == 0
        assert stats["needs_review"] is False

    def test_no_events_means_no_review(self, norma, arts):
        engine, _ = self._run(norma, arts, [])
        stats = engine.get_statistics()
        assert stats["needs_review"] is False
        assert stats["added_count"] == 0

    def test_applied_revocation_is_counted_as_applied(self, norma, arts):
        ev = self._event(1, "REVOGA", alvo=arts[1])
        engine, text = self._run(norma, arts, [ev])
        stats = engine.get_statistics()
        assert stats["events_applied"] == 1
        assert stats["events_unresolved"] == 0
        assert "Art. 2º (Revogado pela Lei nº 200/2021)" in text

    def test_output_with_additions_is_deterministic(self, norma, arts):
        evs = [
            self._event(2, "ADICIONA", ref_tipo="artigo", ref_num="2º-B", num=201),
            self._event(1, "ADICIONA", ref_tipo="artigo", ref_num="2º-A", num=200),
        ]
        e1, t1 = self._run(norma, arts, list(evs))
        e2, t2 = self._run(norma, arts, list(reversed(evs)))
        assert hashlib.sha256(t1.encode()).hexdigest() == hashlib.sha256(t2.encode()).hexdigest()
        # 2º-A must precede 2º-B
        assert t1.index("Art. 2º-A") < t1.index("Art. 2º-B")


class TestAddedTextExtraction:
    """The new wording is taken from the amending law's quoted passage."""

    def test_quoted_wording_replaces_instruction_sentence(self):
        text, ok = ConsolidationEngine._extract_added_text(
            "Fica acrescido o Art. 2º-A: “Art. 2º-A O prazo é de 30 dias.”", "artigo", "2º-A"
        )
        assert ok is True
        assert text == "O prazo é de 30 dias."

    def test_nested_quotes_are_not_truncated(self):
        text, ok = ConsolidationEngine._extract_added_text(
            "Acrescenta o § 4º: “§ 4º Aplica-se o disposto no “Plano Diretor”.”", "paragrafo", "4º"
        )
        assert ok is True
        assert text == "Aplica-se o disposto no “Plano Diretor”."

    def test_quoted_term_that_is_not_the_new_device_is_ignored(self):
        text, ok = ConsolidationEngine._extract_added_text(
            "Fica acrescido o Art. 2º-A, nos termos do “Plano Diretor”, ao Código.",
            "artigo", "2º-A",
        )
        assert ok is False                      # 'Plano Diretor' must never become the text
        assert text.startswith("Fica acrescido")

    def test_unbalanced_quote_falls_back_instead_of_truncating(self):
        text, ok = ConsolidationEngine._extract_added_text(
            "Acrescenta: “Art. 2º-A O prazo é de 30 dias.", "artigo", "2º-A"
        )
        assert ok is False

    def test_label_of_2_does_not_match_2_a(self):
        text, ok = ConsolidationEngine._extract_added_text(
            "Acrescenta: “Art. 2º-A Texto do 2-A.”", "artigo", "2º"
        )
        assert ok is False

    def test_unextracted_wording_is_flagged_in_output(self):
        entry = {
            "label": "Art. 2º-A", "texto": "Fica acrescido o Art. 2º-A.", "extracted": False,
            "norma_ref": "Lei nº 200/2021",
        }
        line = ConsolidationEngine._format_addition(entry)
        assert "redação não extraída" in line
        assert line.endswith("(Incluído pela Lei nº 200/2021)")

    def test_article_key_parsing(self):
        k = ConsolidationEngine._article_key
        assert k("2º") == (2, "") and k("2º-A") == (2, "A") and k("10") == (10, "")
        assert k("2º") < k("2º-A") < k("3º")
        assert k("abc") is None

    def test_paragraph_4_does_not_match_paragraph_4_a(self):
        _, ok = ConsolidationEngine._extract_added_text(
            "Acrescenta: “§ 4º-A Texto do 4º-A.”", "paragrafo", "4º"
        )
        assert ok is False
        text, ok = ConsolidationEngine._extract_added_text(
            "Acrescenta: “§ 4º-A Texto do 4º-A.”", "paragrafo", "4º-A"
        )
        assert ok is True and text == "Texto do 4º-A."

    def test_paragrafo_unico_inciso_alinea_labels(self):
        ex = ConsolidationEngine._extract_added_text
        assert ex("“Parágrafo único. Vale para todos.”", "paragrafo", "único") == ("Vale para todos.", True)
        assert ex("“IV - quarto requisito;”", "inciso", "IV") == ("quarto requisito;", True)
        assert ex("“IV - quarto”", "inciso", "V")[1] is False
        assert ex("“c) terceira alínea;”", "alinea", "c") == ("terceira alínea;", True)
        assert ex("“c) terceira”", "alinea", "d")[1] is False
