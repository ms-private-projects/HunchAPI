"""The ms-markets portfolio graph behind a Hunch portfolio, and its reads.

Signal weights (the take's basket) → calendar-event rebalances at the XNYS close → portfolio
weights → portfolio values (NAV and returns), valued on Hunch's daily bars. Hunch owns the
construction and every series it writes: each updater is bound to Hunch's instance of the
ms-markets contract (`hunch.series`), and the take's Portfolio row, its calendar and its signal
metadata are Markets registries reached through the Markets API (ADR 0006).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from hunch.portfolios.signal import HunchBasketSignal
from hunch.runtime import markets_runtime
from hunch.series import daily_bars_storage, portfolio_series
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
from msm_portfolios.rebalance_strategy import CalendarEventSignal
from msm_portfolios.time_index import (
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
    PortfoliosUpdater,
)

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


def _series_ref(storage: type[Any]) -> TimeIndexTableRef:
    return TimeIndexTableRef.from_uid(str(markets_runtime().table(storage).meta_table_uid))


def external_prices_ref() -> TimeIndexTableRef:
    """Read-only reference to Hunch's daily bars, the prices the graph values on."""
    return _series_ref(daily_bars_storage())


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
        series = portfolio_series()
        self.portfolio = portfolio
        self.signal = signal
        self.calendar_events = PortfolioCalendarEvents(
            config=PortfolioCalendarEventsConfiguration(
                calendar_identifier=TRADING_CALENDAR_IDENTIFIER,
                session_label=TRADING_CALENDAR_SESSION,
                event_types=("market_close",),
            ),
            output_table=series["calendar_events"],
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
        self.values = PortfoliosUpdater(
            portfolio_configuration=configuration,
            portfolio_resolver=_FixedPortfolioResolver(portfolio),
            portfolio_description=description,
            output_table=series["values"],
            weights_output_table=series["weights"],
            rebalance_output_table=series["rebalance_state"],
        )
        self.weights = self.values.portfolio_weights
        self.rebalance = self.weights.portfolio_rebalance if self.weights is not None else None
        if offset_start is not None:
            for node in (self.calendar_events, self.rebalance, self.weights, self.values):
                if node is not None:
                    node.OFFSET_START = offset_start

    def run(self) -> dict[str, Any]:
        """Run events, rebalance, weights and values; update the pointers and the catalog."""
        self.calendar_events.run(update_tree=False)
        if self.rebalance is not None:
            self.rebalance.run(update_tree=False)
        if self.weights is not None:
            self.weights.run(update_tree=False)
        result = self.values.run(update_tree=False, update_pointers=True)
        register_portfolio_datasets(self.portfolio.uid)
        return result


def register_portfolio_datasets(portfolio_uid: uuid.UUID | str) -> Any:
    """Record the take's values, weights and signal instances in the Markets catalog.

    Registering again is an upsert that also reconciles, so it runs after every graph run; Markets
    then serves the take's frames from Hunch's instances (`MarketsClient.portfolio_values`).
    """
    from msm_portfolios.api.datasets import PortfolioDatasets

    runtime = markets_runtime()
    series = portfolio_series()
    return PortfolioDatasets.register(
        {
            "portfolio_uid": uuid.UUID(str(portfolio_uid)),
            "values_meta_table_uid": str(runtime.table(series["values"]).meta_table_uid),
            "weights_meta_table_uid": str(runtime.table(series["weights"]).meta_table_uid),
            "signal_meta_table_uid": str(runtime.table(series["signal_weights"]).meta_table_uid),
        }
    )


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    flat = frame.reset_index()
    return [
        {key: (None if value != value else value) for key, value in record.items()}
        for record in flat.to_dict(orient="records")
    ]


def portfolio_value_points(
    identifier: str, *, start: dt.datetime | None = None
) -> list[dict[str, Any]]:
    """NAV points (`time_index`, `close`, `return`) of one portfolio, oldest first.

    Read from Hunch's own values instance, which Hunch holds a grant on; Markets serves the same
    rows to other readers through its catalog.
    """
    frame = _series_ref(portfolio_series()["values"]).get_df_between_dates(
        start_date=start,
        dimension_filters={"portfolio_identifier": [identifier]},
        columns=["close", "return"],
    )
    rows = [
        {"time_index": row["time_index"], "close": row["close"], "return": row.get("return")}
        for row in _records(frame)
    ]
    return sorted(rows, key=lambda row: row["time_index"])


def portfolio_latest_weights(identifier: str) -> list[dict[str, Any]]:
    """The latest weight snapshot of one portfolio, one row per asset, from Hunch's instance."""
    ref = _series_ref(portfolio_series()["weights"])
    last = ref.get_last_observation(dimension_filters={"portfolio_identifier": [identifier]})
    latest = _last_time_index(last)
    if latest is None:
        return []
    frame = ref.get_df_between_dates(
        start_date=latest,
        end_date=latest,
        dimension_filters={"portfolio_identifier": [identifier]},
    )
    return _records(frame)


def _last_time_index(observation: Any) -> dt.datetime | None:
    """The time index of a `get_last_observation` result (a frame, a mapping or a row)."""
    if observation is None:
        return None
    if hasattr(observation, "empty"):
        if observation.empty:
            return None
        flat = observation.reset_index()
        return flat["time_index"].max().to_pydatetime()
    value = (
        observation.get("time_index")
        if isinstance(observation, dict)
        else getattr(observation, "time_index", None)
    )
    if value is None:
        return None
    import pandas as pd

    return pd.Timestamp(value).to_pydatetime()


def portfolio_unique_identifier(take_uid: uuid.UUID | str) -> str:
    from hunch.portfolios.services import hunch_portfolio_identifier

    return hunch_portfolio_identifier(take_uid)


__all__ = [
    "PortfolioGraph",
    "register_portfolio_datasets",
    "VALUATION_MAX_STALENESS",
    "ensure_trading_calendar",
    "external_prices_ref",
    "portfolio_latest_weights",
    "portfolio_unique_identifier",
    "portfolio_value_points",
]
