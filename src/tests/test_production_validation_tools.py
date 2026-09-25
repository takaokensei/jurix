import json
from unittest.mock import patch


def test_rag_regression_checker_allows_small_drop(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    metrics = {
        "recall@1": 0.80,
        "recall@3": 0.90,
        "recall@5": 0.95,
        "recall@10": 1.0,
        "mrr": 0.75,
        "citation_precision": 0.90,
        "citation_recall": 0.92,
        "groundedness": 0.98,
    }
    baseline.write_text(json.dumps(metrics), encoding="utf-8")
    current.write_text(
        json.dumps({key: value - 0.01 for key, value in metrics.items()}),
        encoding="utf-8",
    )

    from scripts.check_rag_regression import compare, load_metrics

    assert compare(load_metrics(baseline), load_metrics(current), tuple(metrics), 0.03) == []


def test_http_load_smoke_percentile():
    from scripts.http_load_smoke import percentile

    assert percentile([100.0, 200.0, 300.0, 400.0], 50) == 300.0


def test_attachment_audit_reports_missing(db, capsys):
    from django.core.management import call_command

    from src.apps.operations.models import AttachmentRecord

    AttachmentRecord.objects.create(
        id="audit-test",
        session_hash="a" * 64,
        name="document.txt",
        size=4,
        content_type="text/plain",
        storage_key="chat/a/a.txt",
        text_storage_key="chat/a/a.txt.txt",
        sha256="0" * 64,
        expires_at=__import__("django.utils.timezone", fromlist=["now"]).now(),
    )
    with patch(
        "src.apps.operations.management.commands.audit_attachment_storage.get_attachment_storage"
    ) as get_storage:
        get_storage.return_value.read_bytes.side_effect = FileNotFoundError
        call_command("audit_attachment_storage")

    assert "MISSING audit-test" in capsys.readouterr().out
