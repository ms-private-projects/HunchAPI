"""Hunch's writes and reads of account holdings, funds, targets and the simulated execution ledger.

Everything here is deterministic service code under the Markets API boundary (ADR 0006):

- Registry rows (VirtualFund, account and fund holdings sets, allocation models, target
  allocations, position sets) are Markets rows written through the Markets API.
- The time series live in Hunch's own instances (`hunch.series`): each funded take's fund
  holdings and target positions, and the simulated venue's account holdings and its fills,
  which it keeps the way a connector keeps its own. A live connector keeps its own ledger, order
  batches included; Hunch identifies an execution by the batch id on its proposal.

The simulated venue uses the account-holdings and execution helpers to behave like a connector;
the funding services use the fund, target and read helpers for every venue.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pandas as pd

from hunch.connectors.base import HoldingsSnapshot, OrderLeg, OrderState, VenueHolding
from hunch.series import (
    fund_holdings_storage,
    series_table_uid,
    simulated_venue_storage,
    target_positions_storage,
)
from hunch.settings import CASH_ASSET_IDENTIFIER, HUNCH_PORTFOLIO_IDENTIFIER_PREFIX

UTC = dt.timezone.utc
ALLOCATION_MODEL_NAME = "hunch"
ORDER_SIDE = {"buy": 1, "sell": -1}


def _hex(value: Any) -> str:
    """UUIDs come back from frames as 32-hex strings; compare in that form."""
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, AttributeError, TypeError):
        return str(value)


def _utc(value: Any) -> dt.datetime:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)
    return stamp.to_pydatetime()


# -- account holdings ---------------------------------------------------------------------------


def write_account_snapshot(
    account_uid: uuid.UUID | str, time_index: dt.datetime, positions: list[dict[str, Any]]
) -> uuid.UUID:
    """One holdings snapshot of a simulated account (positive quantities).

    Like a connector, the simulated venue keeps the rows in its own holdings instance and records
    the holdings set, which names that instance, through the Markets API.
    """
    from msm.api.accounts import AccountHoldingsSet
    from msm.services.holdings import build_account_holdings_frame
    from msm.time_index.accounts import AccountHoldings

    storage = simulated_venue_storage()["holdings"]
    holdings_set = AccountHoldingsSet.upsert(
        account_uid=str(account_uid),
        time_index=time_index,
        source_storage_table_uid=series_table_uid(storage),
    )
    if positions:
        frame = build_account_holdings_frame(
            holdings_date=time_index,
            account_uid=str(account_uid),
            holdings_set_uid=str(holdings_set.uid),
            positions=positions,
        )
        node = AccountHoldings(config=AccountHoldings.default_config(), output_table=storage)
        node.set_frame(frame)
        error, _ = node.run(update_tree=False)
        if error:
            raise RuntimeError("Writing the account holdings failed.")
    return holdings_set.uid


def _holding_from_row(row: Any, asset_identifier: str) -> VenueHolding:
    extra = row.get("extra_details") or {}
    is_cash = extra.get("kind") == "cash" or asset_identifier == CASH_ASSET_IDENTIFIER
    return VenueHolding(
        asset_identifier=asset_identifier,
        quantity=float(row["quantity"]),
        direction=int(row.get("direction") or 1),
        kind="cash" if is_cash else "position",
        symbol=extra.get("symbol") or extra.get("ticker"),
        market_value=None,
        current_price=None,
    )


def account_latest_snapshot(account_uid: uuid.UUID | str) -> HoldingsSnapshot | None:
    """The newest holdings set of a simulated account, read back from its rows (never stale)."""
    from msm.api.accounts import AccountHoldingsSet
    from msm.time_index.accounts import AccountHoldings

    sets = AccountHoldingsSet.filter(account_uid=str(account_uid), order_by="-time_index", limit=1)
    if not sets:
        return None
    latest = sets[0]
    time_index = _utc(latest.time_index)
    node = AccountHoldings(
        config=AccountHoldings.default_config(), output_table=simulated_venue_storage()["holdings"]
    )
    frame = node.get_holdings_history(
        owner_unique_identifier=str(account_uid), start_date=time_index, end_date=time_index
    )
    holdings: list[VenueHolding] = []
    if frame is not None and not frame.empty:
        flat = frame.reset_index()
        if "holdings_set_uid" in flat:
            flat = flat[flat["holdings_set_uid"].map(_hex) == _hex(latest.uid)]
        for record in flat.to_dict(orient="records"):
            holdings.append(_holding_from_row(record, str(record["asset_identifier"])))
    return HoldingsSnapshot(
        account_uid=str(account_uid),
        time_index=time_index,
        holdings=holdings,
        holdings_set_uid=str(latest.uid),
    )


# -- virtual funds ------------------------------------------------------------------------------


def fund_identifier(take_uid: uuid.UUID | str, account_uid: uuid.UUID | str) -> str:
    return (
        f"{HUNCH_PORTFOLIO_IDENTIFIER_PREFIX.replace('PORTFOLIO', 'FUND')}__"
        f"{uuid.UUID(str(take_uid)).hex}__{uuid.UUID(str(account_uid)).hex[:12]}"
    )


def ensure_virtual_fund(
    identifier: str, account_uid: uuid.UUID | str, portfolio_uid: uuid.UUID | str
):
    from msm.api.virtual_funds import VirtualFund

    return VirtualFund.upsert(
        unique_identifier=identifier,
        account_uid=str(account_uid),
        target_portfolio_uid=str(portfolio_uid),
    )


def write_fund_holdings(
    virtual_fund_uid: uuid.UUID | str,
    *,
    source_account_holdings_set_uid: uuid.UUID | str,
    time_index: dt.datetime,
    allocations: list[dict[str, Any]],
    strategy: str = "hunch",
) -> uuid.UUID | None:
    """The fund's slice of the account after a fill: positions and its cash, positive quantities."""
    from msm.api.virtual_funds import VirtualFundHoldingsSet
    from msm.time_index.accounts.virtual_funds import VirtualFundHoldings

    holdings_set = VirtualFundHoldingsSet.upsert(
        virtual_fund_uid=str(virtual_fund_uid),
        source_account_holdings_set_uid=str(source_account_holdings_set_uid),
        time_index=time_index,
    )
    rows = [
        {
            "asset_identifier": item["asset_identifier"],
            "allocated_quantity": abs(float(item["quantity"])),
            "allocation_strategy": strategy,
            "direction": 1 if float(item["quantity"]) >= 0 else -1,
            "extra_details": item.get("extra_details") or {},
        }
        for item in allocations
        if abs(float(item["quantity"])) > 1e-9
    ]
    if rows:
        node = VirtualFundHoldings(
            config=VirtualFundHoldings.default_config(), output_table=fund_holdings_storage()
        )
        node.set_virtual_fund_holdings_frame(
            allocation_time=time_index,
            virtual_fund_uid=str(virtual_fund_uid),
            source_account_holdings_set_uid=str(source_account_holdings_set_uid),
            virtual_fund_holdings_set_uid=str(holdings_set.uid),
            allocations=rows,
        )
        error, _ = node.run(update_tree=False)
        if error:
            raise RuntimeError("Writing the virtual fund holdings failed.")
    return holdings_set.uid


def fund_latest_holdings(
    virtual_fund_uid: uuid.UUID | str,
) -> tuple[dt.datetime | None, dict[str, float]]:
    """The fund's latest allocation as {asset_identifier: signed quantity} and its time."""
    from msm.api.virtual_funds import VirtualFundHoldingsSet
    from msm.time_index.accounts.virtual_funds import VirtualFundHoldings

    sets = VirtualFundHoldingsSet.filter(virtual_fund_uid=str(virtual_fund_uid), limit=5000)
    if not sets:
        return None, {}
    latest = max(sets, key=lambda row: pd.Timestamp(row.time_index))
    time_index = _utc(latest.time_index)
    node = VirtualFundHoldings(
        config=VirtualFundHoldings.default_config(), output_table=fund_holdings_storage()
    )
    frame = node.get_holdings_history(
        owner_unique_identifier=str(virtual_fund_uid), start_date=time_index, end_date=time_index
    )
    quantities: dict[str, float] = {}
    if frame is not None and not frame.empty:
        flat = frame.reset_index()
        if "virtual_fund_holdings_set_uid" in flat:
            flat = flat[flat["virtual_fund_holdings_set_uid"].map(_hex) == _hex(latest.uid)]
        for record in flat.to_dict(orient="records"):
            quantities[str(record["asset_identifier"])] = float(record["allocated_quantity"]) * (
                1 if int(record.get("direction") or 1) >= 0 else -1
            )
    return time_index, quantities


# -- account target positions -------------------------------------------------------------------


def publish_account_target(
    account_uid: uuid.UUID | str,
    *,
    portfolio_uid: uuid.UUID | str,
    notional: float,
    time_index: dt.datetime,
    take_uid: uuid.UUID | str,
) -> dict[str, str]:
    """Record the intent in ms-markets: a portfolio target with a constant notional exposure."""
    from msm.api.accounts import AccountAllocationModel, AccountTargetAllocation, PositionSet
    from msm.time_index.accounts import TargetPositions

    model = AccountAllocationModel.upsert(
        allocation_model_name=ALLOCATION_MODEL_NAME,
        allocation_model_description="Hunch takes funded into brokerage accounts.",
    )
    allocation = AccountTargetAllocation.upsert(
        unique_identifier=f"HUNCH_TARGET__{uuid.UUID(str(account_uid)).hex}__{uuid.UUID(str(take_uid)).hex[:12]}",
        account_uid=str(account_uid),
        account_allocation_model_uid=str(model.uid),
        display_name=f"Hunch take {take_uid}",
        is_active=True,
        source="hunch",
    )
    position_set = PositionSet.upsert(
        account_target_allocation_uid=str(allocation.uid),
        position_set_time=time_index,
        source="hunch",
    )
    node = TargetPositions(
        config=TargetPositions.default_config(), output_table=target_positions_storage()
    )
    node.set_target_positions_frame(
        target_positions_date=time_index,
        position_set_uid=str(position_set.uid),
        positions=[
            {"portfolio_uid": str(portfolio_uid), "constant_notional_exposure": float(notional)}
        ],
    )
    error, _ = node.run(update_tree=False)
    if error:
        raise RuntimeError("Writing the account target positions failed.")
    return {
        "allocation_model_uid": str(model.uid),
        "account_target_allocation_uid": str(allocation.uid),
        "position_set_uid": str(position_set.uid),
    }


# -- execution ledger ---------------------------------------------------------------------------


def write_simulated_fills(
    *,
    account_identifier: str,
    batch_id: str,
    legs: list[OrderLeg],
    fills: list[OrderState],
    trade_time: dt.datetime,
) -> None:
    """The simulated venue's ledger: one trade row per fill (side +1 buy, -1 sell).

    The simulated venue fills every order at once, so its trades are its whole execution record.
    It keeps no order rows: the ``OrdersTS`` contract keys each order to a Markets order batch,
    and a batch belongs to a live connector's own ledger, never to Hunch (ADR 0006).
    """
    from msm.time_index.execution import Trades

    by_id = {state.client_order_id: state for state in fills}
    rows = []
    for leg in legs:
        state = by_id.get(leg.client_order_id)
        if state is None or state.filled_quantity <= 0:
            continue
        price = float(state.average_fill_price or 0.0)
        rows.append(
            {
                "trade_time": state.updated_at or trade_time,
                "trade_identifier": f"{leg.client_order_id}:fill",
                "account_identifier": account_identifier,
                "order_identifier": leg.client_order_id,
                "asset_identifier": leg.asset_identifier,
                "trade_side": ORDER_SIDE[leg.side],
                "quantity": float(state.filled_quantity),
                "price": price,
                "commission": 0.0,
                "commission_asset_identifier": CASH_ASSET_IDENTIFIER,
                "settlement_cost": float(state.filled_quantity * price),
                "settlement_asset_identifier": CASH_ASSET_IDENTIFIER,
                "comments": f"hunch {batch_id}",
                "venue_metadata": {
                    "batch_id": batch_id,
                    "symbol": leg.symbol,
                    "figi": leg.figi,
                    "broker_order_id": state.broker_order_id,
                    "submitted_at": (state.submitted_at or trade_time).isoformat(),
                },
            }
        )
    if not rows:
        return
    error, _ = (
        Trades(config=Trades.default_config(), output_table=simulated_venue_storage()["trades"])
        .set_frame(pd.DataFrame(rows))
        .run(update_tree=False)
    )
    if error:
        raise RuntimeError("Writing the simulated fills failed.")


def read_batch_orders(account_identifier: str, batch_id: str) -> list[OrderState]:
    """The order states of one simulated batch, rebuilt from its fills."""
    from msm.time_index.execution import Trades

    node = Trades(config=Trades.default_config(), output_table=simulated_venue_storage()["trades"])
    frame = node.get_df_between_dates(
        dimension_filters={"account_identifier": [account_identifier]}
    )
    if frame is None or frame.empty:
        return []
    flat = frame.reset_index()
    metadata = flat["venue_metadata"].map(lambda value: value if isinstance(value, dict) else {})
    flat = flat[metadata.map(lambda value: value.get("batch_id")) == batch_id]
    states = []
    for record in flat.to_dict(orient="records"):
        details = (
            record.get("venue_metadata") if isinstance(record.get("venue_metadata"), dict) else {}
        )
        traded_at = _utc(record["trade_time"])
        submitted = details.get("submitted_at")
        states.append(
            OrderState(
                client_order_id=str(record["order_identifier"]),
                status="filled",
                broker_order_id=details.get("broker_order_id") or None,
                filled_quantity=float(record.get("quantity") or 0.0),
                average_fill_price=float(record["price"]) if record.get("price") else None,
                submitted_at=_utc(submitted) if submitted else traded_at,
                updated_at=traded_at,
                raw={
                    "asset_identifier": record["asset_identifier"],
                    "side": int(record["trade_side"]),
                },
            )
        )
    return states


__all__ = [
    "account_latest_snapshot",
    "ensure_virtual_fund",
    "fund_identifier",
    "fund_latest_holdings",
    "publish_account_target",
    "read_batch_orders",
    "write_account_snapshot",
    "write_fund_holdings",
    "write_simulated_fills",
]
