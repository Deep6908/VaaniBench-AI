import pytest

from vaanibench.report import Thresholds, compare, summary


def test_summary_denominators_and_unknown_usage(execute):
    data = summary(execute())
    assert data["total"] == data["successful"] == 20
    assert data["scored"] == 12
    assert data["not_scored"] == 8
    assert data["deterministic_score"] == 1.0
    assert data["input_tokens"]["known_total"] is None
    assert data["cost_usd"] is None


def test_self_comparison_passes_and_degradation_fails(execute):
    a = execute()
    assert compare(a, a, Thresholds())["passed"]
    data = compare(a, execute("degraded", mode="degraded"), Thresholds())
    assert not data["passed"]
    assert data["mean_paired_delta"] < 0
    assert data["paired_cases"] == 12


def test_failures_cannot_hide_as_missing_scores(execute):
    data = compare(execute(), execute("failure", mode="failure"), Thresholds())
    assert not data["passed"]
    assert data["scored_coverage"] == 0
    assert data["error_rate_delta"] == 1


def test_incompatible_input_rejected(execute):
    a = execute()
    b = a.model_copy(deep=True)
    b.cases[0].scenario_hash = "changed"
    with pytest.raises(ValueError, match="identical"):
        compare(a, b, Thresholds())
    b = a.model_copy(deep=True)
    b.dataset_sha256 = "changed"
    with pytest.raises(ValueError, match="incompatible"):
        compare(a, b, Thresholds())


def test_threshold_boundary(execute):
    a = execute()
    b = a.model_copy(deep=True)
    b.cases[0].metrics[0].score = 0.0
    assert compare(a, b, Thresholds(max_score_drop=1/12))["passed"]
    assert not compare(a, b, Thresholds(max_score_drop=.01))["passed"]
