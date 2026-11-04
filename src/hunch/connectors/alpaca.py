"""The Alpaca connector (`alpaca-connectors`) through its HTTP API.

Today the connector registers accounts, captures holdings and resolves assets; it has no order
surface, so ``execution_capability`` reports ``unavailable`` until the connector ships the
execution routes this client already targets (``/v1/accounts/{uid}/orders/...``). Asset identity at
the venue is ``ALPACA::<asset uuid>``; the connector's asset catalog carries the FIGI, which Hunch
uses to map its instruments.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from hunch.connectors.base import (
    ConnectorCapabilityUnavailable,
    ExecutionCapability,
    HoldingsSnapshot,
    OrderLeg,
    OrderState,
    SubmissionResult,
    VenueAccount,
    VenueAssetRef,
    VenueHolding,
)
from hunch.connectors.http import ConnectorHTTPClient
from hunch.settings import CASH_ASSET_IDENTIFIER, VENUE_ALPACA

EXECUTION_FEATURE = "execution"


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


class AlpacaConnector:
    venue = VENUE_ALPACA

    ASSET_PAGES_SECONDS = 600.0

    def __init__(self, client: ConnectorHTTPClient) -> None:
        self._assets: tuple[float, list[dict[str, Any]]] | None = None
        self.client = client
        self._capabilities: dict[str, Any] | None = None

    # -- capabilities -------------------------------------------------------------------------
    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            self._capabilities = self.client.get("/v1/project-state/capabilities") or {}
        return self._capabilities

    def execution_capability(self) -> ExecutionCapability:
        features = self.capabilities().get("features") or self.capabilities().get("items") or []
        for feature in features:
            if isinstance(feature, dict) and feature.get("id") == EXECUTION_FEATURE:
                return "automatic" if feature.get("status") == "available" else "unavailable"
        return "unavailable"

    # -- accounts -----------------------------------------------------------------------------
    @staticmethod
    def _account(item: dict[str, Any]) -> VenueAccount:
        return VenueAccount(
            venue=VENUE_ALPACA,
            account_uid=str(item.get("account_uid") or item["uid"]),
            unique_identifier=str(item["unique_identifier"]),
            is_paper=bool(item.get("is_paper")),
            is_active=bool(item.get("account_is_active", True)),
            account_name=item.get("account_name"),
            status=item.get("status"),
            currency=item.get("currency") or "USD",
            equity=_float(item.get("equity")),
            cash=_float(item.get("cash")),
            buying_power=_float(item.get("buying_power")),
            owner_user_uid=item.get("credentials_updated_by_user_uid"),
            external_account_id=item.get("account_number"),
            # The connector names who saved the account's credentials; an account registered
            # without that (a seeded paper account) cannot be verified and links as unverified.
            ownership_verifiable=item.get("credentials_updated_by_user_uid") is not None,
            raw=item,
        )

    def list_accounts(self, *, owner_user_uid: str | None = None) -> list[VenueAccount]:
        accounts: list[VenueAccount] = []
        offset, limit = 0, 100
        while True:
            page = self.client.get("/v1/accounts", params={"limit": limit, "offset": offset})
            items = page.get("items") or []
            accounts.extend(self._account(item) for item in items)
            if not page.get("pageInfo", {}).get("hasNextPage"):
                break
            offset += limit
        if owner_user_uid is not None:
            accounts = [a for a in accounts if a.owner_user_uid == owner_user_uid]
        return accounts

    def get_account(self, account_uid: str) -> VenueAccount | None:
        try:
            item = self.client.get(f"/v1/accounts/{account_uid}")
        except ConnectorCapabilityUnavailable:
            return None
        return self._account(item) if item else None

    # -- holdings -----------------------------------------------------------------------------
    @staticmethod
    def _holding(row: dict[str, Any]) -> VenueHolding:
        extra = row.get("extra_details") or {}
        is_cash = extra.get("kind") == "cash" or row["asset_identifier"] == CASH_ASSET_IDENTIFIER
        return VenueHolding(
            asset_identifier=str(row["asset_identifier"]),
            quantity=float(row["quantity"]),
            direction=int(row.get("direction") or 1),
            kind="cash" if is_cash else "position",
            symbol=extra.get("symbol"),
            market_value=_float(extra.get("market_value")),
            current_price=_float(extra.get("current_price")),
        )

    def _snapshot(self, account_uid: str, payload: dict[str, Any]) -> HoldingsSnapshot | None:
        rows = payload.get("positions") or payload.get("items") or payload.get("rows") or []
        if not rows and not payload.get("time_index"):
            return None
        time_index = _time(payload.get("time_index")) or max(
            (_time(r.get("time_index")) for r in rows if r.get("time_index")),
            default=dt.datetime.now(dt.timezone.utc),
        )
        return HoldingsSnapshot(
            account_uid=account_uid,
            time_index=time_index,
            holdings=[self._holding(row) for row in rows],
            holdings_set_uid=payload.get("uid") or payload.get("holdings_set_uid"),
        )

    def latest_holdings(self, account_uid: str) -> HoldingsSnapshot | None:
        payload = self.client.get(f"/v1/accounts/{account_uid}/holdings/latest")
        if not payload:
            return None
        if "positions" in payload or "rows" in payload:
            return self._snapshot(account_uid, payload)
        items = payload.get("items") or []
        if not items:
            return None
        newest = max(
            (_time(r.get("time_index")) for r in items if r.get("time_index")), default=None
        )
        rows = [r for r in items if _time(r.get("time_index")) == newest]
        return self._snapshot(
            account_uid,
            {
                "items": rows,
                "time_index": newest,
                "uid": rows[0].get("holdings_set_uid") if rows else None,
            },
        )

    def capture_holdings(self, account_uid: str) -> HoldingsSnapshot:
        result = self.client.post(
            f"/v1/accounts/{account_uid}/holdings/actions/capture", json={}, timeout=120
        )
        set_uid = result.get("holdings_set_uid") if result else None
        if set_uid:
            payload = self.client.get(f"/v1/accounts/{account_uid}/holdings/{set_uid}")
            snapshot = self._snapshot(account_uid, payload)
            if snapshot is not None:
                return snapshot
        snapshot = self.latest_holdings(account_uid)
        if snapshot is None:
            raise ConnectorCapabilityUnavailable("The connector returned no holdings snapshot.")
        return snapshot

    # -- assets -------------------------------------------------------------------------------
    def resolve_assets(self, account_uid: str, figis: list[str]) -> dict[str, VenueAssetRef]:
        from hunch.instruments.services import instruments_for_figis

        wanted = set(figis)
        # The connector's registered assets may carry no FIGI; then the ticker Hunch knows for
        # the instrument identifies it (looked up once, when a row without a FIGI turns up).
        by_ticker: dict[str, str] | None = None
        resolved: dict[str, VenueAssetRef] = {}
        for item in self._asset_rows():
            if wanted:
                figi = item.get("figi") or item.get("composite_figi")
                if not figi:
                    if by_ticker is None:
                        by_ticker = {
                            row.ticker: known
                            for known, row in instruments_for_figis(figis).items()
                            if row.ticker
                        }
                    figi = by_ticker.get(item.get("ticker") or item.get("symbol"))
                if figi in wanted:
                    resolved[figi] = VenueAssetRef(
                        figi=figi,
                        asset_identifier=str(item["unique_identifier"]),
                        symbol=str(item.get("ticker") or item.get("symbol") or ""),
                        tradable=bool(item.get("tradable", True)),
                        fractionable=bool(item.get("fractionable", False)),
                        asset_uid=str(item.get("uid") or "") or None,
                    )
                    wanted.discard(figi)
        return resolved

    def _asset_rows(self) -> list[dict[str, Any]]:
        """The connector's registered assets, paged once and kept for a while.

        A hosted connector answers a page in tens of seconds and its universe changes rarely, so
        one funding (which resolves assets twice) and the proposals after it share the pages.
        """
        import time

        cached = self._assets
        if cached is not None and time.time() - cached[0] < self.ASSET_PAGES_SECONDS:
            return cached[1]
        rows: list[dict[str, Any]] = []
        offset, limit = 0, 100
        while True:
            page = self.client.get("/v1/assets", params={"limit": limit, "offset": offset})
            rows.extend(page.get("items") or [])
            if not page.get("pageInfo", {}).get("hasNextPage"):
                break
            offset += limit
        self._assets = (time.time(), rows)
        return rows

    # -- execution (the contract Hunch targets; absent from the connector today) -------------
    def _require_execution(self) -> None:
        if self.execution_capability() != "automatic":
            raise ConnectorCapabilityUnavailable(
                "The Alpaca connector release offers no order execution yet."
            )

    @staticmethod
    def _order(item: dict[str, Any]) -> OrderState:
        return OrderState(
            client_order_id=str(item["client_order_id"]),
            status=str(item.get("status") or "unknown"),
            broker_order_id=item.get("broker_order_id") or item.get("order_id"),
            filled_quantity=float(item.get("filled_quantity") or 0.0),
            average_fill_price=_float(item.get("average_fill_price")),
            submitted_at=_time(item.get("submitted_at")),
            updated_at=_time(item.get("updated_at")),
            message=item.get("message"),
            raw=item,
        )

    def submit_orders(
        self, account_uid: str, batch_id: str, legs: list[OrderLeg]
    ) -> SubmissionResult:
        self._require_execution()
        payload = {
            "batch_id": batch_id,
            # An approval given after the close is still an approval: the day orders queue at
            # Alpaca for the next session, and the execution sync books the fills when they come.
            "queue_when_closed": True,
            "orders": [
                {
                    "client_order_id": leg.client_order_id,
                    "asset_identifier": leg.asset_identifier,
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "order_type": leg.order_type,
                    "time_in_force": leg.time_in_force,
                }
                for leg in legs
            ],
        }
        result = self.client.post(
            f"/v1/accounts/{account_uid}/orders/actions/submit", json=payload, timeout=120
        )
        orders = [self._order(item) for item in (result.get("orders") or [])]
        return SubmissionResult(
            batch_id=batch_id,
            accepted=bool(result.get("accepted", True)),
            orders=orders,
            message=result.get("message"),
        )

    def sync_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        self._require_execution()
        result = self.client.post(
            f"/v1/accounts/{account_uid}/orders/actions/sync",
            json={"batch_id": batch_id},
            timeout=120,
        )
        return [self._order(item) for item in (result.get("orders") or [])]

    def cancel_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        self._require_execution()
        result = self.client.post(
            f"/v1/accounts/{account_uid}/orders/actions/cancel",
            json={"batch_id": batch_id},
            timeout=120,
        )
        return [self._order(item) for item in (result.get("orders") or [])]


__all__ = ["AlpacaConnector"]
