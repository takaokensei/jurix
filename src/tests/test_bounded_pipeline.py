from unittest.mock import MagicMock, patch

from src.apps.ingestion.bounded_pipeline import bounded_sapl_ingest_task


def test_bounded_task_does_not_enqueue_each_page():
    fake = MagicMock()
    fake.successful.return_value = True
    fake.result = {"count": 2}
    with patch("src.apps.ingestion.tasks.ingest_normas_task.apply", return_value=fake) as apply:
        result = bounded_sapl_ingest_task.apply(kwargs={"max_normas": 5, "batch_size": 2})
    assert result.successful()
    assert result.result["pages"] == 3
    assert apply.call_count == 3
