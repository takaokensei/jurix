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
