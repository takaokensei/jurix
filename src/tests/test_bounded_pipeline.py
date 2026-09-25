from unittest.mock import MagicMock, patch
import pytest

from src.apps.ingestion.bounded_pipeline import bounded_sapl_ingest_task


@pytest.mark.django_db
def test_bounded_task_does_not_enqueue_each_page():
    fake = MagicMock()
    fake.successful.return_value = True
    fake.result = {"total_fetched": 2}
    with patch("src.apps.ingestion.tasks.ingest_normas_task.apply", return_value=fake) as apply:
        result = bounded_sapl_ingest_task.apply(kwargs={"max_normas": 5, "batch_size": 2})
    assert result.successful()
    assert result.result["pages"] == 3
    assert apply.call_count == 3


@pytest.mark.django_db
def test_empty_page_stops_at_real_total():
    fake = MagicMock()
    fake.successful.return_value = True
    fake.result = {'total_fetched': 0, 'created': 0, 'updated': 0, 'failed': 0}
    with patch('src.apps.ingestion.tasks.ingest_normas_task.apply', return_value=fake) as apply:
        result = bounded_sapl_ingest_task.run(max_normas=500, batch_size=25)
    assert result['processed'] == 0
    assert apply.call_count == 1
