"""The ms-markets compatibility shims change only what they say they change."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from hunch.compat import install_compat_patches
from msm_portfolios.time_index import portfolios as portfolio_updaters
from msm_portfolios.time_index.portfolios import rebalance, weights

LATEST = dt.datetime(2026, 10, 23, 20, 0, tzinfo=dt.timezone.utc)


def _statistics(progress: dict | None) -> SimpleNamespace:
    return SimpleNamespace(index_progress=progress, max_time_index_value=LATEST)


def test_a_new_portfolio_starts_from_offset_start_when_others_filled_the_table() -> None:
    install_compat_patches()
    cases = (
        (rebalance.PortfolioRebalance, "_latest_transition_time_index_value"),
        (weights.PortfolioWeights, "_latest_projection_time_index_value"),
        (portfolio_updaters.PortfoliosUpdater, "_latest_portfolio_time_index_value"),
    )
    for updater_class, method_name in cases:
        method = getattr(updater_class, method_name)
        assert getattr(method, "_hunch_compat", False), (updater_class, method_name)
        node = SimpleNamespace(
            _resolve_portfolio_identifier=lambda: "HUNCH_PORTFOLIO__new",
            _portfolio_progress_identifier=lambda: "HUNCH_PORTFOLIO__new",
            _max_in_nested_values=lambda value: max(value.values()),
        )
        # Another portfolio's progress must not become this portfolio's starting point.
        node.update_statistics = _statistics({"HUNCH_PORTFOLIO__other": {"x": LATEST}})
        assert method(node) is None, (updater_class, method_name)
        # This portfolio's own progress still counts.
        node.update_statistics = _statistics({"HUNCH_PORTFOLIO__new": LATEST})
        assert method(node) == LATEST, (updater_class, method_name)
        # Without per-portfolio progress the upstream fallback stays in place.
        node.update_statistics = _statistics(None)
        assert method(node) == LATEST, (updater_class, method_name)


def test_installing_twice_does_not_stack_the_shims() -> None:
    install_compat_patches()
    first = rebalance.PortfolioRebalance._latest_transition_time_index_value
    install_compat_patches()
    assert rebalance.PortfolioRebalance._latest_transition_time_index_value is first
