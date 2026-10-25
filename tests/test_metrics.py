"""Performance metrics are computed from rebased value points."""

from __future__ import annotations

import math

from hunch.portfolios.metrics import performance_metrics


def test_metrics_need_two_points() -> None:
    assert performance_metrics([])["sessions"] == 0
    single = performance_metrics([{"close": 1.02}])
    assert single["total_return"] == 0.02 and single["sharpe_ratio"] is None


def test_metrics_follow_the_series() -> None:
    closes = [1.0, 1.1, 0.99, 1.05, 1.2]
    metrics = performance_metrics([{"close": c} for c in closes])
    assert metrics["sessions"] == 5
    assert metrics["total_return"] == 0.2
    assert metrics["max_drawdown"] == round(0.99 / 1.1 - 1, 6)
    assert metrics["best_day"] == round(1.2 / 1.05 - 1, 6)
    assert metrics["worst_day"] == round(0.99 / 1.1 - 1, 6)
    assert metrics["annualised_volatility"] > 0 and math.isfinite(metrics["sharpe_ratio"])
    assert metrics["annualised_return"] > metrics["total_return"]


def test_flat_series_has_no_sharpe() -> None:
    metrics = performance_metrics([{"close": 1.0}, {"close": 1.0}, {"close": 1.0}])
    assert metrics["sharpe_ratio"] is None and metrics["annualised_volatility"] == 0.0
