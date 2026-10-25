"""The Interactive Brokers connector (`interactivebrokersbackend`) through its HTTP API.

The connector is read-only toward IBKR (reports and Flex queries, end of day) and registers no
owner on an account, so Hunch treats IBKR execution as **manual**: proposals are presented as an
order list the person executes at IBKR, and the next holdings capture reconciles the virtual fund.
Asset identity at the venue is ``IBKR::<conid>``; symbols and FIGIs live in the connector's
contract details, which Hunch reads through the asset routes when available.
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
from hunch.settings import CASH_ASSET_IDENTIFIER, VENUE_IBKR


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


class IBKRConnector:
    venue = VENUE_IBKR

    def __init__(self, client: ConnectorHTTPClient) -> None:
        self.client = client
        self._capabilities: dict[str, Any] | None = None

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            self._capabilities = self.client.get("/v1/project-state/capabilities") or {}
        return self._capabilities

    def execution_capability(self) -> ExecutionCapability:
        return "manual"

    @staticmethod
    def _account(item: dict[str, Any]) -> VenueAccount:
        return VenueAccount(
            venue=VENUE_IBKR,
            account_uid=str(item["account_uid"]),
            unique_identifier=str(
                item.get("account_unique_identifier") or item.get("unique_identifier") or ""
            ),
            is_paper=item.get("environment") == "paper",
            is_active=bool(item.get("account_is_active", True)),
            account_name=item.get("account_name") or item.get("account_title"),
            status=item.get("authorization_status"),
            currency=item.get("base_currency") or "USD",
            owner_user_uid=None,
            external_account_id=item.get("ibkr_account_id"),
            ownership_verifiable=False,
            raw=item,
        )

    def list_accounts(self, *, owner_user_uid: str | None = None) -> list[VenueAccount]:
        accounts: list[VenueAccount] = []
        offset, limit = 0, 100
        while True:
            page = self.client.get("/v1/accounts", params={"limit": limit, "offset": offset})
            accounts.extend(self._account(item) for item in page.get("items") or [])
            if not page.get("pageInfo", {}).get("hasNextPage"):
                break
            offset += limit
        return accounts

    def get_account(self, account_uid: str) -> VenueAccount | None:
        try:
            item = self.client.get(f"/v1/accounts/{account_uid}")
        except ConnectorCapabilityUnavailable:
            return None
        return self._account(item) if item else None

    @staticmethod
    def _holding(row: dict[str, Any]) -> VenueHolding:
        extra = row.get("extra_details") or {}
        is_cash = extra.get("kind") == "cash" or row["asset_identifier"] == CASH_ASSET_IDENTIFIER
        return VenueHolding(
            asset_identifier=str(row["asset_identifier"]),
            quantity=float(row["quantity"]),
            direction=int(row.get("direction") or 1),
            kind="cash" if is_cash else "position",
            symbol=extra.get("ticker"),
            market_value=_float(extra.get("market_value")),
            current_price=_float(extra.get("market_price")),
        )

    def latest_holdings(self, account_uid: str) -> HoldingsSnapshot | None:
        payload = self.client.get(f"/v1/accounts/{account_uid}/holdings/latest")
        if not payload:
            return None
        rows = payload.get("rows") or payload.get("positions") or []
        time_index = _time(payload.get("time_index")) or dt.datetime.now(dt.timezone.utc)
        return HoldingsSnapshot(
            account_uid=account_uid,
            time_index=time_index,
            holdings=[self._holding(row) for row in rows],
            holdings_set_uid=payload.get("uid"),
        )

    def capture_holdings(self, account_uid: str) -> HoldingsSnapshot:
        # The connector queues its Daily Sync Job (202); reports are end of day, so the latest
        # stored snapshot is what a caller can use now.
        self.client.post(
            f"/v1/accounts/{account_uid}/holdings/actions/capture", json={}, timeout=60
        )
        snapshot = self.latest_holdings(account_uid)
        if snapshot is None:
            raise ConnectorCapabilityUnavailable(
                "The connector has no holdings for this account yet."
            )
        return snapshot

    def resolve_assets(self, account_uid: str, figis: list[str]) -> dict[str, VenueAssetRef]:
        wanted = set(figis)
        resolved: dict[str, VenueAssetRef] = {}
        offset, limit = 0, 100
        while wanted:
            page = self.client.get("/v1/assets", params={"limit": limit, "offset": offset})
            for item in page.get("items") or []:
                figi = item.get("figi")
                if figi in wanted:
                    resolved[figi] = VenueAssetRef(
                        figi=figi,
                        asset_identifier=str(item["unique_identifier"]),
                        symbol=str(item.get("symbol") or item.get("ticker") or ""),
                        tradable=True,
                        fractionable=False,
                        asset_uid=str(item.get("uid") or "") or None,
                    )
                    wanted.discard(figi)
            if not page.get("pageInfo", {}).get("hasNextPage"):
                break
            offset += limit
        return resolved

    def submit_orders(
        self, account_uid: str, batch_id: str, legs: list[OrderLeg]
    ) -> SubmissionResult:
        raise ConnectorCapabilityUnavailable(
            "Interactive Brokers execution is manual: the person places the orders at IBKR."
        )

    def sync_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        raise ConnectorCapabilityUnavailable("Interactive Brokers execution is manual.")

    def cancel_orders(self, account_uid: str, batch_id: str) -> list[OrderState]:
        raise ConnectorCapabilityUnavailable("Interactive Brokers execution is manual.")


__all__ = ["IBKRConnector"]
