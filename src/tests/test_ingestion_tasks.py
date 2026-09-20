"""
Unit tests for Ingestion tasks.

Verifies:
- Idempotency in _process_norma_data (never overwrites consolidated status)
- Asynchronous dispatch in bulk_ingest_normas_task using .delay()
"""

from unittest.mock import Mock, patch
import pytest

from src.apps.ingestion.tasks import _process_norma_data, bulk_ingest_normas_task
from src.apps.legislation.models import Norma


class TestIngestionTasks:
    """Test suite for Ingestion tasks."""

    @patch('src.apps.ingestion.tasks.Norma.objects.update_or_create')
    @patch('src.apps.ingestion.tasks.Norma.objects.filter')
    def test_reingest_preserves_consolidated_status(self, mock_filter, mock_update_or_create):
        """Test that re-ingesting a norma preserves its consolidated status."""
        # Setup existing norma in database with consolidated status
        existing_norma = Mock()
        existing_norma.status = 'consolidated'
        mock_qs = Mock()
        mock_qs.only.return_value.first.return_value = existing_norma
        mock_filter.return_value = mock_qs

        mock_updated_norma = Mock()
        mock_updated_norma.id = 42
        mock_update_or_create.return_value = (mock_updated_norma, False)

        payload = {
            'id': 12345,
            'tipo': {'descricao': 'Lei Complementar'},
            'numero': '50',
            'ano': 2021,
            'ementa': 'Ementa de teste',
        }

        result = _process_norma_data(payload, auto_download=False)

        assert result['created'] is False
        assert result['norma_id'] == 42

        # Verify update_or_create was called with preserved status 'consolidated'
        call_kwargs = mock_update_or_create.call_args[1]
        assert call_kwargs['defaults']['status'] == 'consolidated'

    @patch('src.apps.ingestion.tasks.ingest_normas_task.delay')
    def test_bulk_ingest_dispatches_async_tasks(self, mock_delay):
        """Test that bulk_ingest_normas_task dispatches tasks asynchronously with .delay()."""
        mock_subtask = Mock()
        mock_subtask.id = "task-async-uuid-123"
        mock_delay.return_value = mock_subtask

        result = bulk_ingest_normas_task(
            max_normas=100,
            tipo=None,
            ano=2024,
            page_size=50
        )

        # Should have dispatched 2 batches of 50
        assert mock_delay.call_count == 2
        assert len(result['dispatched_tasks']) == 2
        assert result['total_batches'] == 2
        assert result['dispatched_tasks'][0] == "task-async-uuid-123"


@pytest.mark.django_db
class TestConsolidationTaskReviewFlag:
    """Audit P0.3: a norma whose events could not be applied must be flagged."""

    def _make(self, with_events):
        from src.apps.legislation.models import Norma, Dispositivo, EventoAlteracao

        base = Norma.objects.create(tipo="Lei", numero="1000", ano=2020, status="entities_extracted")
        Dispositivo.objects.create(norma=base, tipo="artigo", numero="1º", texto="Primeiro.", ordem=1)
        if with_events:
            amending = Norma.objects.create(tipo="Lei", numero="2000", ano=2021)
            fonte = Dispositivo.objects.create(
                norma=amending, tipo="artigo", numero="1º", texto="Revoga-se o art. 9º.", ordem=1
            )
            EventoAlteracao.objects.create(
                dispositivo_fonte=fonte, acao="REVOGA", target_text="art. 9º",
                norma_alvo=base, referencia_tipo="artigo", referencia_numero="9º",
            )
        return base

    def test_unresolved_events_flag_norma_and_are_listed_in_text(self):
        from src.apps.ingestion.tasks import consolidate_norma_task

        base = self._make(with_events=True)
        result = consolidate_norma_task(base.id)
        base.refresh_from_db()

        assert result["success"] is True
        assert result["events_unresolved"] == 1
        assert result["events_applied"] == 0
        assert result["needs_review"] is True
        assert base.needs_review is True
        assert "EVENTOS NÃO RESOLVIDOS" in base.texto_consolidado

    def test_clean_norma_is_not_flagged(self):
        from src.apps.ingestion.tasks import consolidate_norma_task

        base = self._make(with_events=False)
        result = consolidate_norma_task(base.id)
        base.refresh_from_db()

        assert result["needs_review"] is False
        assert base.needs_review is False

    def test_consolidation_never_clears_a_manual_review_flag(self):
        from src.apps.ingestion.tasks import consolidate_norma_task

        base = self._make(with_events=False)
        base.needs_review = True
        base.save(update_fields=["needs_review"])
        consolidate_norma_task(base.id)
        base.refresh_from_db()

        assert base.needs_review is True


@pytest.mark.django_db
class TestRagCacheInvalidation:
    """Audit P1.3: pipeline steps that change what the RAG can answer must bump the corpus version."""

    @pytest.fixture(autouse=True)
    def locmem(self, settings):
        settings.CACHES = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "inval"}
        }

    def test_successful_consolidation_bumps_the_corpus_version(self):
        from src.apps.ingestion.tasks import consolidate_norma_task
        from src.processing.cache_service import get_cache_service

        base = TestConsolidationTaskReviewFlag()._make(with_events=False)
        before = get_cache_service().get_corpus_version()
        assert consolidate_norma_task(base.id)["success"] is True
        assert get_cache_service().get_corpus_version() == before + 1

    def test_failed_consolidation_does_not_bump(self):
        from src.apps.ingestion.tasks import consolidate_norma_task
        from src.processing.cache_service import get_cache_service

        before = get_cache_service().get_corpus_version()
        assert consolidate_norma_task(999999)["success"] is False   # unknown norma
        assert get_cache_service().get_corpus_version() == before

    def test_a_cache_outage_never_fails_the_task(self):
        from src.apps.ingestion.tasks import _invalidate_rag_cache

        with patch("src.apps.ingestion.tasks.get_cache_service", side_effect=RuntimeError("boom")):
            _invalidate_rag_cache()   # must not raise

    @pytest.mark.parametrize("task_name", ["segment_text_task", "consolidate_norma_task", "generate_embedding_task"])
    def test_every_corpus_changing_task_invalidates_on_success(self, task_name):
        """Guard: the success path of each of these tasks must call the invalidator."""
        import inspect
        from src.apps.ingestion import tasks

        source = inspect.getsource(getattr(tasks, task_name))
        assert "_invalidate_rag_cache()" in source


@pytest.mark.django_db
class TestMarkNormaFailed:
    """Audit P2.2: five copies of the failure block, each with a bare `except: pass`."""

    def _norma(self):
        from src.apps.legislation.models import Norma
        return Norma.objects.create(tipo="Lei", numero="9", ano=2020, status="consolidation")

    def test_marks_failed_flags_review_and_truncates_the_message(self):
        from src.apps.ingestion.tasks import _mark_norma_failed

        n = self._norma()
        _mark_norma_failed(n.id, "Consolidation error", RuntimeError("x" * 500))
        n.refresh_from_db()

        assert n.status == "failed" and n.needs_review is True
        assert n.processing_error.startswith("Consolidation error: xxx")
        assert len(n.processing_error) == len("Consolidation error: ") + 200

    def test_download_variant_keeps_the_current_status(self):
        from src.apps.ingestion.tasks import _mark_norma_failed

        n = self._norma()
        _mark_norma_failed(n.id, "Erro crítico", RuntimeError("boom"), set_failed_status=False)
        n.refresh_from_db()

        assert n.status == "consolidation" and n.needs_review is True

    def test_missing_norma_is_logged_not_raised(self):
        from src.apps.ingestion.tasks import _mark_norma_failed

        # (patching the logger: the project's LOGGING config stops propagation to caplog)
        with patch("src.apps.ingestion.tasks.logger") as log:
            _mark_norma_failed(999999, "x", RuntimeError("boom"))   # must not raise
        assert "Could not record failure on Norma ID=999999" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["exc_info"] is True

    def test_does_not_swallow_keyboard_interrupt(self):
        """The old bare `except:` also swallowed SystemExit/KeyboardInterrupt."""
        from src.apps.ingestion.tasks import _mark_norma_failed

        with patch("src.apps.ingestion.tasks.Norma.objects.get", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                _mark_norma_failed(1, "x", RuntimeError("boom"))


def test_no_bare_except_in_production_code():
    """Guard: `except:` catches SystemExit/KeyboardInterrupt and hides real failures."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1]
    offenders = []
    for path in src.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f"{path.relative_to(src)}:{node.lineno}")
    assert offenders == []
