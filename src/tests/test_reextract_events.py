"""
Unit tests for reextract_events management command.
"""

from io import StringIO
from unittest.mock import Mock, patch
from django.core.management import call_command


class TestReextractEventsCommand:
    """Test suite for reextract_events management command."""

    @patch('src.apps.ingestion.management.commands.reextract_events.extract_entities_task')
    @patch('src.apps.ingestion.management.commands.reextract_events.EventoAlteracao')
    @patch('src.apps.ingestion.management.commands.reextract_events.Norma')
    def test_reextract_events_single_norma_sync(
        self, mock_norma_model, mock_evento_model, mock_extract_task
    ):
        """Test synchronous re-extraction for a specific norma."""
        mock_norma = Mock(id=42)
        mock_norma.__str__ = Mock(return_value="Lei 42/2024")
        mock_norma_model.objects.get.return_value = mock_norma

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([mock_norma]))
        mock_qs.count.return_value = 1
        mock_norma_model.objects.filter.return_value = mock_qs

        mock_evento_model.objects.count.side_effect = [10, 8]  # 2 fewer events
        mock_evento_model.objects.values_list.return_value.annotate.return_value = [
            ('REVOGA', 5),
            ('ALTERA', 3),
        ]

        mock_extract_task.return_value = {
            'success': True,
            'events_created': 8,
            'dispositivos_processed': 10,
        }

        out = StringIO()
        call_command('reextract_events', '--norma-id', '42', '--sync', stdout=out)
        output = out.getvalue()

        assert 'Found 1 Norma(s) eligible' in output
        assert 'Completed in' in output
        assert 'Successfully processed: 1' in output
        assert 'Net event delta:       -2' in output
        mock_extract_task.assert_called_once_with(42)

    @patch('src.apps.ingestion.management.commands.reextract_events.extract_entities_task.delay')
    @patch('src.apps.ingestion.management.commands.reextract_events.EventoAlteracao')
    @patch('src.apps.ingestion.management.commands.reextract_events.Norma')
    def test_reextract_events_async_dispatch(
        self, mock_norma_model, mock_evento_model, mock_delay
    ):
        """Test asynchronous dispatch via Celery for multiple normas."""
        norma1 = Mock(id=1)
        norma1.__str__ = Mock(return_value="Norma 1")
        norma2 = Mock(id=2)
        norma2.__str__ = Mock(return_value="Norma 2")

        mock_ordered_qs = Mock()
        mock_ordered_qs.__iter__ = Mock(return_value=iter([norma1, norma2]))
        mock_ordered_qs.count.return_value = 2

        mock_filtered_qs = Mock()
        mock_filtered_qs.distinct.return_value.order_by.return_value = mock_ordered_qs
        mock_norma_model.objects.filter.return_value = mock_filtered_qs

        mock_evento_model.objects.count.return_value = 100
        mock_task = Mock(id="task-celery-reextract-123")
        mock_delay.return_value = mock_task

        out = StringIO()
        call_command('reextract_events', '--async', stdout=out)
        output = out.getvalue()

        assert 'Found 2 Norma(s) eligible' in output
        assert 'Successfully processed: 2' in output
        assert 'Tasks dispatched asynchronously' in output
        assert mock_delay.call_count == 2
