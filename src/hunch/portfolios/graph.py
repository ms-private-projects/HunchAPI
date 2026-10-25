"""The ms-markets portfolio graph behind a Hunch portfolio, and its reads.

Signal weights (the take's basket) → calendar-event rebalances at the XNYS close → portfolio
weights → portfolio values (NAV and returns), valued on the external daily prices. Hunch owns the
construction; every table is ms-markets'.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from hunch.portfolios.signal import HunchBasketSignal
from hunch.runtime import markets_runtime
from hunch.settings import (
    TRADING_CALENDAR_IDENTIFIER,
    TRADING_CALENDAR_SESSION,
    TRADING_CALENDAR_SOURCE,
    TRADING_CALENDAR_VALID_FROM,
    TRADING_CALENDAR_VALID_TO,
)
from metatables import TimeIndexTableRef
from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    FrontEndDetails,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
    ValuationAlignmentPolicy,
)
from msm_portfolios.data_nodes import (
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
    PortfoliosDataNode,
)
from msm_portfolios.data_nodes.prices.storage import ExternalPricesStorage
from msm_portfolios.rebalance_strategy import CalendarEventSignal
from msm_portfolios.services.portfolio_reads import latest_portfolio_weights, portfolio_values

UTC = dt.timezone.utc
# Equities trade on business days; a bar a few days old is still the last valuation.
VALUATION_MAX_STALENESS = dt.timedelta(days=5)


def ensure_trading_calendar() -> Calendar:
    """The persisted XNYS calendar, materialised through the configured horizon."""
    existing = Calendar.get_by_unique_identifier(TRADING_CALENDAR_IDENTIFIER)
    if existing is not None:
        valid_to = getattr(existing, "valid_to", None)
        if valid_to is not None and str(valid_to) >= TRADING_CALENDAR_VALID_TO:
            return existing
    return Calendar.create_from_pandas_calendar(
        source_identifier=TRADING_CALENDAR_SOURCE,
        unique_identifier=TRADING_CALENDAR_IDENTIFIER,
        display_name="New York Stock Exchange",
        valid_from=TRADING_CALENDAR_VALID_FROM,
        valid_to=TRADING_CALENDAR_VALID_TO,
        session_label=TRADING_CALENDAR_SESSION,
    )


def external_prices_ref() -> TimeIndexTableRef:
    """Read-only reference to the daily prices table the graph values on."""
    return TimeIndexTableRef.from_uid(
        str(markets_runtime().table(ExternalPricesStorage).meta_table_uid)
    )


class _FixedPortfolioResolver:
    """Return the Portfolio row Hunch created; the graph never creates portfolios itself."""

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def get_or_create_from_configuration_hash(self, **_: Any) -> Portfolio:
        return self.portfolio


class PortfolioGraph:
    """The nodes of one take's portfolio graph, run in dependency order."""

    def __init__(
        self,
        *,
        portfolio: Portfolio,
        signal: HunchBasketSignal,
        display_name: str,
        description: str | None = None,
        offset_start: dt.datetime | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.signal = signal
        self.calendar_events = PortfolioCalendarEvents(
            config=PortfolioCalendarEventsConfiguration(
                calendar_identifier=TRADING_CALENDAR_IDENTIFIER,
                session_label=TRADING_CALENDAR_SESSION,
                event_types=("market_close",),
            )
        )
        strategy = CalendarEventSignal(
            calendar_events_instance=self.calendar_events,
            calendar_identifier=TRADING_CALENDAR_IDENTIFIER,
            session_label=TRADING_CALENDAR_SESSION,
            rebalance_event="market_close",
            rebalance_cadence="every_session",
        )
        configuration = PortfolioConfiguration(
            portfolio_build_configuration=PortfolioBuildConfiguration(
                valuation_source_instance=external_prices_ref(),
                valuation_column="close",
                valuation_alignment_policy=ValuationAlignmentPolicy(
                    maximum_staleness=VALUATION_MAX_STALENESS,
                    fail_on_missing_values=False,
                ),
                execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
                backtesting_weights_configuration=BacktestingWeightsConfig(
                    signal_weights_instance=signal,
                    rebalance_strategy_instance=strategy,
                ),
            ),
            portfolio_markets_configuration=PortfolioMarketsConfig(
                portfolio_name=display_name,
                front_end_details=FrontEndDetails(description=description) if description else None,
            ),
        )
        self.values = PortfoliosDataNode(
            portfolio_configuration=configuration,
            portfolio_resolver=_FixedPortfolioResolver(portfolio),
            portfolio_description=description,
        )
        self.weights = self.values.portfolio_weights
        self.rebalance = self.weights.portfolio_rebalance if self.weights is not None else None
        if offset_start is not None:
            for node in (self.calendar_events, self.rebalance, self.weights, self.values):
                if node is not None:
                    node.OFFSET_START = offset_start

    def run(self) -> dict[str, Any]:
        """Run events, rebalance, weights and values; update the Portfolio row's pointers."""
        self.calendar_events.run(update_tree=False)
        if self.rebalance is not None:
            self.rebalance.run(update_tree=False)
        if self.weights is not None:
            self.weights.run(update_tree=False)
        return self.values.run(update_tree=False, update_pointers=True)


def portfolio_value_points(
    identifier: str, *, start: dt.datetime | None = None
) -> list[dict[str, Any]]:
    """NAV points (`time_index`, `close`, `return`) of one portfolio, oldest first."""
    rows = portfolio_values(identifier, start=start, repository_context=markets_runtime().context)
    return sorted(rows, key=lambda row: row["time_index"])


def portfolio_latest_weights(identifier: str) -> list[dict[str, Any]]:
    """The latest weight snapshot of one portfolio, one row per asset."""
    return latest_portfolio_weights(identifier, repository_context=markets_runtime().context)


def portfolio_unique_identifier(take_uid: uuid.UUID | str) -> str:
    from hunch.portfolios.services import hunch_portfolio_identifier

    return hunch_portfolio_identifier(take_uid)


__all__ = [
    "PortfolioGraph",
    "VALUATION_MAX_STALENESS",
    "ensure_trading_calendar",
    "external_prices_ref",
    "portfolio_latest_weights",
    "portfolio_unique_identifier",
    "portfolio_value_points",
]
