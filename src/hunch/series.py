"""Hunch-owned instances of the ms-markets time-series contracts (ADR 0047, Hunch ADR 0006).

Every time series Hunch produces lives in its own catalog namespace (`hunch`), migrated by the
Hunch migration provider and written by Hunch's updaters through ``output_table=``. ms-markets
owns each contract (columns, dtypes, time index, index names, foreign keys to its registries);
Hunch owns these tables. Markets finds the portfolio series through its catalog
(`PortfolioDatasets.register`), which the take build fills.

| Series | Contract | Written by |
| --- | --- | --- |
| Take portfolio values, weights, signal weights, rebalance state, calendar events | the five portfolio contracts | the take graph (`hunch.portfolios.graph`) |
| Daily bars | `ExternalPricesTS` | `hunch.market_data.HunchDailyBars` |
| Each funded take's slice of its account | `VirtualFundHoldingsTS` | `hunch.funding.ledger` |
| Each funded take's target exposure | `TargetPositionsTS` | `hunch.funding.ledger` |
| The simulated venue's account holdings and fills | `AccountHoldingsTS`, `TradesTS` | `hunch.connectors.simulated` |

The registry rows these series hang off (Portfolio, SignalMetadata, VirtualFund, holdings sets,
allocations, position sets, order batches) are Markets rows written through the Markets API. A
simulated account behaves like a connector's: its `holdings_storage_table_uid` and each holdings
set's `source_storage_table_uid` name the simulated holdings instance.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from hunch.metatables import PROJECT_METATABLE_NAMESPACE, PROJECT_TABLE_APP

# One instance per contract: every take shares it, partitioned by portfolio identifier.
TAKES_INSTANCE_KEY = "takes"
BARS_INSTANCE_KEY = "daily"
SIMULATED_VENUE_INSTANCE_KEY = "simulated"


def _instance_options() -> dict[str, Any]:
    return {"namespace": PROJECT_METATABLE_NAMESPACE, "storage_app": PROJECT_TABLE_APP}


@lru_cache(maxsize=1)
def portfolio_series() -> dict[str, type[Any]]:
    """The take graph's five portfolio contract instances, keyed by role."""
    from msm_portfolios.time_index.contract_instances import (
        configured_portfolio_calendar_events_storage,
        configured_portfolio_rebalance_state_storage,
        configured_portfolio_weights_storage,
        configured_portfolios_storage,
        configured_signal_weights_storage,
    )

    options = {"instance_key": TAKES_INSTANCE_KEY, **_instance_options()}
    return {
        "values": configured_portfolios_storage(**options),
        "weights": configured_portfolio_weights_storage(**options),
        "signal_weights": configured_signal_weights_storage(**options),
        "rebalance_state": configured_portfolio_rebalance_state_storage(**options),
        "calendar_events": configured_portfolio_calendar_events_storage(**options),
    }


def _instance(core_storage: type[Any], instance_key: str) -> type[Any]:
    from msm.storage_instances import configured_time_index_instance

    return configured_time_index_instance(
        core_storage, instance_key=instance_key, **_instance_options()
    )


@lru_cache(maxsize=1)
def daily_bars_storage() -> type[Any]:
    from msm_portfolios.time_index.prices.storage import ExternalPricesStorage

    return _instance(ExternalPricesStorage, BARS_INSTANCE_KEY)


@lru_cache(maxsize=1)
def fund_holdings_storage() -> type[Any]:
    from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage

    return _instance(VirtualFundHoldingsStorage, TAKES_INSTANCE_KEY)


@lru_cache(maxsize=1)
def target_positions_storage() -> type[Any]:
    from msm.time_index.accounts.storage import TargetPositionsStorage

    return _instance(TargetPositionsStorage, TAKES_INSTANCE_KEY)


@lru_cache(maxsize=1)
def simulated_venue_storage() -> dict[str, type[Any]]:
    """The simulated venue's own series: account holdings and fills.

    No ``OrdersTS`` instance: that contract keys each order to a Markets order batch, which only
    a live connector's ledger holds. The simulated venue fills at once, so trades suffice.
    """
    from msm.time_index.accounts.storage import AccountHoldingsStorage
    from msm.time_index.execution.storage import TradesStorage

    return {
        "holdings": _instance(AccountHoldingsStorage, SIMULATED_VENUE_INSTANCE_KEY),
        "trades": _instance(TradesStorage, SIMULATED_VENUE_INSTANCE_KEY),
    }


def series_table_uid(storage: type[Any]) -> str:
    """The MetaTable uid of one Hunch instance in the attached runtime."""
    from hunch.runtime import markets_runtime

    return str(markets_runtime().table(storage).meta_table_uid)


def project_series_models() -> list[type[Any]]:
    """Every Hunch-owned time-series instance, for the runtime and the migration provider."""
    return [
        *portfolio_series().values(),
        daily_bars_storage(),
        fund_holdings_storage(),
        target_positions_storage(),
        *simulated_venue_storage().values(),
    ]


__all__ = [
    "BARS_INSTANCE_KEY",
    "SIMULATED_VENUE_INSTANCE_KEY",
    "TAKES_INSTANCE_KEY",
    "daily_bars_storage",
    "fund_holdings_storage",
    "portfolio_series",
    "project_series_models",
    "series_table_uid",
    "simulated_venue_storage",
    "target_positions_storage",
]
