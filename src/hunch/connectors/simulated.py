"""A simulated venue for local development and tests.

It behaves like a connector that fills every market order at the last stored close with no
commission, and it keeps its records the way a connector does under the Markets API boundary
(ADR 0006): an ``Account`` row and an ``AccountHoldingsSet`` per snapshot through the Markets API
(paper, owner recorded in ``metadata_json``), with the holdings rows and the fills in the
venue's own instances (``hunch.series.simulated_venue_storage``). Positions are held on Hunch's
canonical FIGI assets, so no venue asset mapping is needed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

from hunch.connectors.base import (
    ConnectorError,
    ExecutionCapability,
    HoldingsSnapshot,
    OrderLeg,
    OrderState,
    SubmissionResult,
    VenueAccount,
    VenueAssetRef,
    VenueHolding,
)
from hunch.profiles import utc_now
from hunch.settings import (
    CASH_ASSET_IDENTIFIER,
    SIMULATED_ACCOUNT_IDENTIFIER_PREFIX,
    SIMULATED_STARTING_CASH,
)

UTC = dt.timezone.utc


class SimulatedConnector:
    def __init__(self, venue: str) -> None:
        self.venue = venue

    # -- capabilities -------------------------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        return {
            "simulated": True,
            "features": [
                {"id": "accounts.connect", "status": "available"},
                {"id": "holdings.capture", "status": "available"},
                {"id": "execution", "status": "available"},
            ],
        }

    def execution_capability(self) -> ExecutionCapability:
        return "automatic"

    # -- accounts -----------------------------------------------------------------------------
    def _identifier(self, owner_user_uid: str) -> str:
        digest = hashlib.sha1(owner_user_uid.encode("utf-8")).hexdigest()[:8].upper()
        nonce = uuid.uuid4().hex[:4].upper()
        return f"{SIMULATED_ACCOUNT_IDENTIFIER_PREFIX}-{digest}{nonce}__{self.venue.upper()}_PAPER"

    def create_account(
        self,
        owner_user_uid: str,
        *,
        account_name: str | None = None,
        starting_cash: float = SIMULATED_STARTING_CASH,
    ) -> VenueAccount:
        """Register a simulated paper account for one person with a cash balance."""
        from hunch.funding.ledger import write_account_snapshot
        from hunch.instruments.services import ensure_cash_asset
        from msm.api.accounts import Account

        ensure_cash_asset()
        identifier = self._identifier(owner_user_uid)
        from hunch.series import series_table_uid, simulated_venue_storage

        account = Account.upsert(
            unique_identifier=identifier,
            account_name=account_name or f"Simulated {self.venue} paper account",
            is_paper=True,
            account_is_active=True,
            # Like a connector's account: its holdings rows live in the venue's own instance.
            holdings_storage_table_uid=series_table_uid(simulated_venue_storage()["holdings"]),
            metadata_json={
                "simulated": True,
                "venue": self.venue,
                "owner_user_uid": owner_user_uid,
                "created_at": utc_now().isoformat(),
                "starting_cash": starting_cash,
            },
        )
        positions = []
        if starting_cash > 0:
            positions.append(
                {
                    "asset_identifier": CASH_ASSET_IDENTIFIER,
                    "quantity": float(starting_cash),
                    "direction": 1,
                    "extra_details": {"kind": "cash", "source": "simulated"},
                }
            )
        write_account_snapshot(account.uid, utc_now(), positions)
        return self._venue_account(account)

    def _venue_account(self, account: Any) -> VenueAccount:
        metadata = account.metadata_json or {}
        snapshot = self.latest_holdings(str(account.uid))
        cash = snapshot.cash() if snapshot else None
        equity = self._equity(snapshot) if snapshot else None
        return VenueAccount(
            venue=self.venue,
            account_uid=str(account.uid),
            unique_identifier=account.unique_identifier,
            is_paper=True,
            is_active=bool(account.account_is_active),
            account_name=account.account_name,
            status="ACTIVE" if account.account_is_active else "INACTIVE",
            currency=CASH_ASSET_IDENTIFIER,
            equity=equity,
            cash=cash,
            buying_power=cash,
            owner_user_uid=metadata.get("owner_user_uid"),
            external_account_id=account.unique_identifier.split("__")[0],
            ownership_verifiable=True,
            raw={"metadata_json": metadata},
        )

    def _equity(self, snapshot: HoldingsSnapshot) -> float:
        from hunch.market_data import latest_closes

        positions = snapshot.positions()
        prices = latest_closes([h.asset_identifier for h in positions]) if positions else {}
        value = snapshot.cash()
        for holding in positions:
            price = prices.get(holding.asset_identifier)
            if price is not None:
                value += holding.signed_quantity * price[1]
        return round(value, 2)

    def _is_mine(self, account: Any) -> bool:
        metadata = account.metadata_json or {}
        return bool(metadata.get("simulated")) and metadata.get("venue") == self.venue

    def list_accounts(self, *, owner_user_uid: str | None = None) -> list[VenueAccount]:
        from msm.api.accounts import Account

        rows = [row for row in Account.filter(limit=5000) if self._is_mine(row)]
        if owner_user_uid is not None:
            rows = [
                row
                for row in rows
                if (row.metadata_json or {}).get("owner_user_uid") == owner_user_uid
            ]
        return [self._venue_account(row) for row in rows]

    def get_account(self, account_uid: str) -> VenueAccount | None:
        from msm.api.accounts import Account

        row = Account.get_by_uid(uuid.UUID(str(account_uid)))
        if row is None or not self._is_mine(row):
            return None
        return self._venue_account(row)

    # -- holdings -----------------------------------------------------------------------------
    def latest_holdings(self, account_uid: str) -> HoldingsSnapshot | None:
        from hunch.funding.ledger import account_latest_snapshot

        return account_latest_snapshot(account_uid)

    def capture_holdings(self, account_uid: str) -> HoldingsSnapshot:
        snapshot = self.latest_holdings(account_uid)
        if snapshot is None:
            raise ConnectorError("The simulated account has no holdings yet.", code="not_found")
        return snapshot

    # -- assets -------------------------------------------------------------------------------
    def resolve_assets(self, account_uid: str, figis: list[str]) -> dict[str, VenueAssetRef]:
        from hunch.instruments.services import instruments_for_figis

        return {
            row.figi: VenueAssetRef(
                figi=row.figi,
                asset_identifier=row.figi,
                symbol=row.ticker,
                tradable=bool(row.is_tradable),
                fractionable=True,
                asset_uid=str(row.asset_uid),
            )
            for row in instruments_for_figis(figis).values()
        }

    # -- execution ----------------------------------------------------------------------------
    def submit_orders(
        self, account_uid: str, batch_id: str, legs: list[OrderLeg]
    ) -> SubmissionResult:
        from hunch.funding.ledger import write_account_snapshot, write_simulated_fills
        from hunch.market_data import latest_closes
        from msm.api.accounts import Account

        account = Account.get_by_uid(uuid.UUID(str(account_uid)))
        if account is None or not self._is_mine(account):
            raise ConnectorError("Unknown simulated account.", code="not_found")
        snapshot = self.latest_holdings(account_uid)
        if snapshot is None:
            raise ConnectorError("The simulated account has no holdings yet.", code="not_found")
        prices = latest_closes([leg.asset_identifier for leg in legs])
        missing = [leg.symbol for leg in legs if leg.asset_identifier not in prices]
        if missing:
            raise ConnectorError(
                f"No stored price for {', '.join(missing)}.", code="provider_failure"
            )
        positions = {h.asset_identifier: h.signed_quantity for h in snapshot.positions()}
        cash = snapshot.cash()
        fills: list[OrderState] = []
        now = utc_now()
        if now <= snapshot.time_index:
            now = snapshot.time_index + dt.timedelta(seconds=1)
        for leg in legs:
            price = float(prices[leg.asset_identifier][1])
            signed = leg.quantity if leg.side == "buy" else -leg.quantity
            positions[leg.asset_identifier] = positions.get(leg.asset_identifier, 0.0) + signed
            cash -= signed * price
            fills.append(
                OrderState(
                    client_order_id=leg.client_order_id,
                    status="filled",
                    broker_order_id=f"sim-{uuid.uuid4().hex[:12]}",
                    filled_quantity=leg.quantity,
                    average_fill_price=price,
                    submitted_at=now,
                    updated_at=now,
                    raw={"asset_identifier": leg.asset_identifier, "side": leg.side},
                )
            )
        if cash < -0.01:
            raise ConnectorError(
                f"Insufficient cash: the batch needs {-cash:,.2f} more {CASH_ASSET_IDENTIFIER}.",
                code="insufficient_cash",
            )
        if any(quantity < -1e-9 for quantity in positions.values()):
            raise ConnectorError(
                "The batch would sell more than the account holds.", code="short_sale"
            )

        write_simulated_fills(
            account_identifier=account.unique_identifier,
            batch_id=batch_id,
            legs=legs,
            fills=fills,
            trade_time=now,
        )
        new_positions = [
            {
                "asset_identifier": asset,
                "quantity": abs(quantity),
                "direction": 1 if quantity > 0 else -1,
                "extra_details": {"source": "simulated"},
            }
            for asset, quantity in sorted(positions.items())
            if abs(quantity) > 1e-9
        ]
        if cash > 0.005:
            new_positions.append(
                {
                    "asset_identifier": CASH_ASSET_IDENTIFIER,
                    "quantity": round(cash, 2),
                    "direction": 1,
                    "extra_details": {"kind": "cash", "source": "simulated"},
                }
            )
        write_account_snapshot(account.uid, now, new_positions)
        return SubmissionResult(batch_id=batch_id, accepted=True, orders=fills)

    def sync_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        from hunch.funding.ledger import read_batch_orders
        from msm.api.accounts import Account

        account = Account.get_by_uid(uuid.UUID(str(account_uid)))
        if account is None:
            raise ConnectorError("Unknown simulated account.", code="not_found")
        return read_batch_orders(account.unique_identifier, batch_id)

    def cancel_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        return self.sync_orders(account_uid, batch_id)


__all__ = ["SimulatedConnector"]
