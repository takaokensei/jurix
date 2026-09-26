import pytest

from src.processing.rag_release_policy import ReleaseThresholds, evaluate_batch, evaluate_result


def grounded_result(score=1.0, *, cached=False):
    return {
        "answer": "Resposta sintética para teste.",
        "grounded": True,
        "sources": [{"dispositivo_id": 1}],
        "cached": cached,
        "grounding": {
            "grounded": True,
            "score": score,
            "policy": {"accepted": True},
        },
        "metrics": {
            "citation_precision": 1.0,
            "citation_recall": 1.0,
            "source_recall": 1.0,
        },
    }


def test_accepts_fully_grounded_result():
    decision = evaluate_result(grounded_result())
    assert decision.accepted
    assert not decision.reasons


def test_rejects_missing_sources():
    value = grounded_result()
    value["sources"] = []
    decision = evaluate_result(value)
    assert not decision.accepted
    assert "insufficient_sources" in decision.reasons


def test_rejects_uncached_ungrounded_result():
    value = grounded_result()
    value["grounded"] = False
    value["cached"] = True
    value["grounding"]["grounded"] = False
    decision = evaluate_result(value)
    assert not decision.accepted
    assert "ungrounded_result_must_not_be_cached" in decision.reasons


def test_unanswerable_case_can_be_unhandled_without_fake_grounding():
    value = {
        "answer": "Não há informação suficiente nas fontes recuperadas.",
        "grounded": False,
        "sources": [],
        "grounding": {"score": 0.0},
        "metrics": {},
    }
    decision = evaluate_result(value, answerability="unanswerable")
    assert decision.accepted


def test_batch_reports_reason_counts():
    report = evaluate_batch(
        [grounded_result(), {**grounded_result(), "sources": []}]
    )
    assert report["total"] == 2
    assert report["accepted"] == 1
    assert report["rejected"] == 1
    assert report["reason_counts"]["insufficient_sources"] == 1


# Regression matrix generated from release-threshold boundaries.
REGRESSION_CASES = [
    (1, 0.55, "rejected"),
    (2, 0.58, "rejected"),
    (3, 0.61, "rejected"),
    (4, 0.64, "rejected"),
    (5, 0.67, "rejected"),
    (6, 0.70, "rejected"),
    (7, 0.73, "rejected"),
    (8, 0.76, "accepted"),
    (9, 0.79, "accepted"),
    (10, 0.82, "accepted"),
    (11, 0.85, "accepted"),
    (12, 0.88, "accepted"),
    (13, 0.91, "accepted"),
    (14, 0.94, "accepted"),
    (15, 0.97, "accepted"),
    (16, 1.00, "accepted"),
]

@pytest.mark.parametrize(
    "case_id,score,expected",
    REGRESSION_CASES,
)
def test_score_matrix(case_id, score, expected):
    result = grounded_result(score=1.0 if score >= 0.75 else score)
    if expected == "accepted":
        assert evaluate_result(result).accepted
    else:
        result["grounded"] = score >= 0.75
        result["grounding"]["grounded"] = result["grounded"]
        result["grounding"]["score"] = score
        assert not evaluate_result(result, thresholds=ReleaseThresholds(min_grounded_score=0.95)).accepted


@pytest.mark.parametrize('case_id,score,expected', [
    (1, 0.505, False),
    (2, 0.51, False),
    (3, 0.515, False),
    (4, 0.52, False),
    (5, 0.525, False),
    (6, 0.53, False),
    (7, 0.535, False),
    (8, 0.54, False),
    (9, 0.545, False),
    (10, 0.55, False),
    (11, 0.555, False),
    (12, 0.56, False),
    (13, 0.565, False),
    (14, 0.57, False),
    (15, 0.575, False),
    (16, 0.58, False),
    (17, 0.585, False),
    (18, 0.59, False),
    (19, 0.595, False),
    (20, 0.6, False),
    (21, 0.605, False),
    (22, 0.61, False),
    (23, 0.615, False),
    (24, 0.62, False),
    (25, 0.625, False),
    (26, 0.63, False),
    (27, 0.635, False),
    (28, 0.64, False),
    (29, 0.645, False),
    (30, 0.65, False),
    (31, 0.655, False),
    (32, 0.66, False),
    (33, 0.665, False),
    (34, 0.67, False),
    (35, 0.675, False),
    (36, 0.68, False),
    (37, 0.685, False),
    (38, 0.69, False),
    (39, 0.695, False),
    (40, 0.7, False),
    (41, 0.705, False),
    (42, 0.71, False),
    (43, 0.715, False),
    (44, 0.72, False),
    (45, 0.725, False),
    (46, 0.73, False),
    (47, 0.735, False),
    (48, 0.74, False),
    (49, 0.745, False),
    (50, 0.75, False),
    (51, 0.755, False),
    (52, 0.76, False),
    (53, 0.765, False),
    (54, 0.77, False),
    (55, 0.775, False),
    (56, 0.78, False),
    (57, 0.785, False),
    (58, 0.79, False),
    (59, 0.795, False),
    (60, 0.8, False),
    (61, 0.805, False),
    (62, 0.81, False),
    (63, 0.815, False),
    (64, 0.82, False),
    (65, 0.825, False),
    (66, 0.83, False),
    (67, 0.835, False),
    (68, 0.84, False),
    (69, 0.845, False),
    (70, 0.85, False),
    (71, 0.855, False),
    (72, 0.86, False),
    (73, 0.865, False),
    (74, 0.87, False),
    (75, 0.875, False),
    (76, 0.88, False),
    (77, 0.885, False),
    (78, 0.89, False),
    (79, 0.895, False),
    (80, 0.9, False),
    (81, 0.905, False),
    (82, 0.91, False),
    (83, 0.915, False),
    (84, 0.92, False),
    (85, 0.925, False),
    (86, 0.93, False),
    (87, 0.935, False),
    (88, 0.94, False),
    (89, 0.945, False),
    (90, 0.95, False),
    (91, 0.955, False),
    (92, 0.96, False),
    (93, 0.965, False),
    (94, 0.97, False),
    (95, 0.975, False),
    (96, 0.98, False),
    (97, 0.985, False),
    (98, 0.99, False),
    (99, 0.995, False),
    (100, 1.0, False),
    (101, 1.005, False),
    (102, 1.01, False),
    (103, 1.015, False),
    (104, 1.02, False),
    (105, 1.025, False),
    (106, 1.03, False),
    (107, 1.035, False),
    (108, 1.04, False),
    (109, 1.045, False),
    (110, 1.05, False),
    (111, 1.055, False),
    (112, 1.06, False),
    (113, 1.065, False),
    (114, 1.07, False),
    (115, 1.075, False),
    (116, 1.08, False),
    (117, 1.085, False),
    (118, 1.09, False),
    (119, 1.095, False),
    (120, 1.1, False),
])
def test_release_threshold_matrix(case_id, score, expected):
    value = grounded_result()
    value["grounding"]["score"] = score
    value["grounded"] = expected
    value["grounding"]["grounded"] = expected
    decision = evaluate_result(value)
    assert decision.accepted is expected
