from src.processing.data_integrity import check_numeric_range, summarize_issues


def test_numeric_range_accepts_valid_value():
    assert check_numeric_range(0.5, 0.0, 1.0, "score") == []


def test_numeric_range_rejects_invalid_value():
    issues = check_numeric_range(2.0, 0.0, 1.0, "score")
    assert issues
    assert issues[0].code == "score"


def test_summary_ok_when_no_errors():
    summary = summarize_issues(checked=10, issues=[])
    assert summary.ok
    assert summary.as_dict()["checked"] == 10
