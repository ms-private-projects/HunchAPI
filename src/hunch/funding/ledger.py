"""Hunch's writes and reads of the ms-markets account, virtual-fund and execution tables.

Everything here is deterministic service code. The simulated venue uses the account-holdings and
execution writers to behave like a connector; the funding services use the virtual-fund, target
and read helpers for every venue.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pandas as pd

from hunch.connectors.base import HoldingsSnapshot, OrderLeg, OrderState, VenueHolding
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
    """One ``AccountHoldingsSet`` plus its ``AccountHoldingsTS`` rows (positive quantities)."""
    from msm.api.accounts import AccountHoldingsSet
    from msm.services.holdings import build_account_holdings_frame
    from msm.time_index.accounts import AccountHoldings

    holdings_set = AccountHoldingsSet.upsert(account_uid=str(account_uid), time_index=time_index)
    if positions:
        frame = build_account_holdings_frame(
            holdings_date=time_index,
            account_uid=str(account_uid),
            holdings_set_uid=str(holdings_set.uid),
            positions=positions,
        )
        node = AccountHoldings(config=AccountHoldings.default_config())
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
    """The newest holdings set of an account, read back from its own rows (never stale)."""
    from msm.api.accounts import AccountHoldingsSet
    from msm.time_index.accounts import AccountHoldings

    sets = AccountHoldingsSet.filter(account_uid=str(account_uid), limit=5000)
    if not sets:
        return None
    latest = max(sets, key=lambda row: pd.Timestamp(row.time_index))
    time_index = _utc(latest.time_index)
    node = AccountHoldings(config=AccountHoldings.default_config())
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
        node = VirtualFundHoldings(config=VirtualFundHoldings.default_config())
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
    node = VirtualFundHoldings(config=VirtualFundHoldings.default_config())
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
    node = TargetPositions(config=TargetPositions.default_config())
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


def create_order_batch(
    batch_id: str, account_uid: uuid.UUID | str, target_time: dt.datetime, *, status: str
):
    from msm.api.execution import OrderManager

    return OrderManager.create_batch(
        unique_identifier=batch_id,
        target_account_uid=str(account_uid),
        target_time=target_time,
        order_received_time=target_time,
        status=status,
    )


def update_order_batch(batch_id: str, **values: Any) -> None:
    from msm.api.execution import OrderManager

    rows = OrderManager.filter(unique_identifier=batch_id)
    for row in rows:
        OrderManager.update(row.uid, **values)


def write_orders_and_trades(
    *,
    account_identifier: str,
    batch_id: str,
    legs: list[OrderLeg],
    fills: list[OrderState],
    order_time: dt.datetime,
) -> None:
    """One ``OrdersTS`` row per leg and one ``TradesTS`` row per fill (side +1 buy, -1 sell)."""
    from msm.time_index.execution import Orders, Trades

    by_id = {state.client_order_id: state for state in fills}
    order_rows, trade_rows = [], []
    for leg in legs:
        state = by_id.get(leg.client_order_id)
        filled_quantity = state.filled_quantity if state else 0.0
        filled_price = (state.average_fill_price or 0.0) if state else 0.0
        order_rows.append(
            {
                "order_time": order_time,
                "order_identifier": leg.client_order_id,
                "account_identifier": account_identifier,
                "order_manager_identifier": batch_id,
                "asset_identifier": leg.asset_identifier,
                "order_remote_id": (state.broker_order_id if state else "") or "",
                "client_order_id": leg.client_order_id,
                "order_type": leg.order_type,
                "order_side": ORDER_SIDE[leg.side],
                "quantity": float(leg.quantity),
                "status": state.status if state else "submitted",
                "filled_quantity": float(filled_quantity),
                "filled_price": float(filled_price),
                "expires_time": order_time,
                "limit_price": 0.0,
                "time_in_force": leg.time_in_force,
                "comments": f"hunch {batch_id}",
                "venue_metadata": {"symbol": leg.symbol, "figi": leg.figi},
            }
        )
        if state and state.filled_quantity > 0:
            trade_rows.append(
                {
                    "trade_time": state.updated_at or order_time,
                    "trade_identifier": f"{leg.client_order_id}:fill",
                    "account_identifier": account_identifier,
                    "order_identifier": leg.client_order_id,
                    "asset_identifier": leg.asset_identifier,
                    "trade_side": ORDER_SIDE[leg.side],
                    "quantity": float(state.filled_quantity),
                    "price": float(state.average_fill_price or 0.0),
                    "commission": 0.0,
                    "commission_asset_identifier": CASH_ASSET_IDENTIFIER,
                    "settlement_cost": float(
                        state.filled_quantity * (state.average_fill_price or 0.0)
                    ),
                    "settlement_asset_identifier": CASH_ASSET_IDENTIFIER,
                    "comments": f"hunch {batch_id}",
                    "venue_metadata": {
                        "symbol": leg.symbol,
                        "broker_order_id": state.broker_order_id,
                    },
                }
            )
    if order_rows:
        error, _ = (
            Orders(config=Orders.default_config())
            .set_frame(pd.DataFrame(order_rows))
            .run(update_tree=False)
        )
        if error:
            raise RuntimeError("Writing the orders failed.")
    if trade_rows:
        error, _ = (
            Trades(config=Trades.default_config())
            .set_frame(pd.DataFrame(trade_rows))
            .run(update_tree=False)
        )
        if error:
            raise RuntimeError("Writing the trades failed.")


def read_batch_orders(account_identifier: str, batch_id: str) -> list[OrderState]:
    from msm.time_index.execution import Orders

    node = Orders(config=Orders.default_config())
    frame = node.get_df_between_dates(
        dimension_filters={"account_identifier": [account_identifier]}
    )
    if frame is None or frame.empty:
        return []
    flat = frame.reset_index()
    flat = flat[flat["order_manager_identifier"].astype(str) == batch_id]
    states = []
    for record in flat.to_dict(orient="records"):
        states.append(
            OrderState(
                client_order_id=str(record["client_order_id"]),
                status=str(record["status"]),
                broker_order_id=str(record.get("order_remote_id") or "") or None,
                filled_quantity=float(record.get("filled_quantity") or 0.0),
                average_fill_price=float(record["filled_price"])
                if record.get("filled_price")
                else None,
                submitted_at=_utc(record["order_time"]),
                updated_at=_utc(record["order_time"]),
                raw={
                    "asset_identifier": record["asset_identifier"],
                    "side": int(record["order_side"]),
                },
            )
        )
    return states


__all__ = [
    "account_latest_snapshot",
    "create_order_batch",
    "ensure_virtual_fund",
    "fund_identifier",
    "fund_latest_holdings",
    "publish_account_target",
    "read_batch_orders",
    "update_order_batch",
    "write_account_snapshot",
    "write_fund_holdings",
    "write_orders_and_trades",
]
