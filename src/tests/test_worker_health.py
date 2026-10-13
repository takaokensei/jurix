import pytest

from src.apps.operations.worker_health import get_normative_worker_health


def test_worker_health_requires_worker_consuming_the_normative_queue():
    report = get_normative_worker_health(
        inspect_factory=lambda **_kwargs: type(
            "Inspector",
            (),
            {"active_queues": lambda self: {"worker-1": [{"name": "default"}]}},
        )()
    )

    assert report == {"status": "queue_missing", "responding_workers": 1, "queue_workers": 0}


def test_worker_health_counts_workers_without_exposing_their_names():
    report = get_normative_worker_health(
        inspect_factory=lambda **_kwargs: type(
            "Inspector",
            (),
            {
                "active_queues": lambda self: {
                    "private-worker-host": [{"name": "normative_qa"}],
                    "other-worker": [{"name": "default"}, {"name": "normative_qa"}],
                }
            },
        )()
    )

    assert report == {"status": "current", "responding_workers": 2, "queue_workers": 2}
    assert "private-worker-host" not in repr(report)


def test_worker_health_distinguishes_unreachable_broker_from_empty_queue():
    report = get_normative_worker_health(
        inspect_factory=lambda **_kwargs: type("Inspector", (), {"active_queues": lambda self: None})()
    )
    assert report["status"] == "unavailable"
    assert report["responding_workers"] == 0

    def broken_inspector(**_kwargs):
        raise RuntimeError("private connection details")

    failed = get_normative_worker_health(inspect_factory=broken_inspector)
    assert failed["status"] == "unavailable"
    assert "private connection details" not in repr(failed)


@pytest.mark.parametrize("timeout", [0, -1, 5.1])
def test_worker_health_bounds_inspection_timeout(timeout):
    with pytest.raises(ValueError, match="between 0 and 5"):
        get_normative_worker_health(inspect_factory=lambda **_kwargs: None, timeout=timeout)
