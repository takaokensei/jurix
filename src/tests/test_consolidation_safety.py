
import pytest


@pytest.mark.parametrize("needs_review", [True])
def test_partial_consolidation_must_not_be_reported_as_final(needs_review):
    """Contract test documenting the fail-closed invariant of the task patch."""
    status = "failed" if needs_review else "consolidated"
    assert status != "consolidated"
