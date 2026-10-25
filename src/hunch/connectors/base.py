"""The venue connector port: what Hunch needs from a brokerage connector, and nothing more.

Hunch owns the logic (targets, proposals, approvals, autopilot limits). A connector owns the
broker credentials, the account registry, holdings capture and the exact orders. Hunch services
and Jobs call a connector deterministically through this port; the Agent and the model never do.

Three implementations exist: the Alpaca connector's HTTP API, the Interactive Brokers connector's
HTTP API (read-only today, so execution is manual), and the simulated venue used locally and in
tests, which keeps every ms-markets row a real connector would write.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ExecutionCapability = Literal["automatic", "manual", "unavailable"]
Side = Literal["buy", "sell"]


class ConnectorError(RuntimeError):
    """A connector call failed; ``code`` follows the connectors' error vocabulary."""

    def __init__(self, message: str, *, code: str = "provider_failure", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ConnectorCapabilityUnavailable(ConnectorError):
    """The connector release does not offer the capability (for example order submission)."""

    def __init__(self, message: str):
        super().__init__(message, code="capability_unavailable", retryable=False)


@dataclass(frozen=True)
class VenueAccount:
    venue: str
    account_uid: str
    unique_identifier: str
    is_paper: bool
    is_active: bool
    account_name: str | None = None
    status: str | None = None
    currency: str | None = "USD"
    equity: float | None = None
    cash: float | None = None
    buying_power: float | None = None
    owner_user_uid: str | None = None
    external_account_id: str | None = None
    ownership_verifiable: bool = True
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class VenueHolding:
    asset_identifier: str
    quantity: float
    direction: int = 1
    kind: Literal["position", "cash"] = "position"
    symbol: str | None = None
    figi: str | None = None
    market_value: float | None = None
    current_price: float | None = None

    @property
    def signed_quantity(self) -> float:
        return self.quantity * (1 if self.direction >= 0 else -1)


@dataclass(frozen=True)
class HoldingsSnapshot:
    account_uid: str
    time_index: dt.datetime
    holdings: list[VenueHolding]
    holdings_set_uid: str | None = None

    def cash(self, currency: str = "USD") -> float:
        return sum(
            h.signed_quantity
            for h in self.holdings
            if h.kind == "cash" and h.asset_identifier == currency
        )

    def positions(self) -> list[VenueHolding]:
        return [h for h in self.holdings if h.kind == "position"]


@dataclass(frozen=True)
class VenueAssetRef:
    """How one Hunch instrument (FIGI) is traded at a venue."""

    figi: str
    asset_identifier: str
    symbol: str
    tradable: bool = True
    fractionable: bool = False
    asset_uid: str | None = None


@dataclass(frozen=True)
class OrderLeg:
    client_order_id: str
    figi: str
    asset_identifier: str
    symbol: str
    side: Side
    quantity: float
    order_type: Literal["market"] = "market"
    time_in_force: Literal["day"] = "day"
    estimated_price: float | None = None


@dataclass(frozen=True)
class OrderState:
    client_order_id: str
    status: str
    broker_order_id: str | None = None
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    submitted_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_ORDER_STATUSES

    @property
    def filled(self) -> bool:
        return self.status == "filled"


TERMINAL_ORDER_STATUSES: frozenset[str] = frozenset(
    {"filled", "cancelled", "canceled", "rejected", "expired", "failed"}
)


@dataclass(frozen=True)
class SubmissionResult:
    batch_id: str
    accepted: bool
    orders: list[OrderState]
    message: str | None = None


class VenueConnector(Protocol):
    """The port. Implementations raise ``ConnectorError`` for any provider or transport failure."""

    venue: str

    def capabilities(self) -> dict[str, Any]: ...

    def execution_capability(self) -> ExecutionCapability: ...

    def list_accounts(self, *, owner_user_uid: str | None = None) -> list[VenueAccount]: ...

    def get_account(self, account_uid: str) -> VenueAccount | None: ...

    def latest_holdings(self, account_uid: str) -> HoldingsSnapshot | None: ...

    def capture_holdings(self, account_uid: str) -> HoldingsSnapshot: ...

    def resolve_assets(self, account_uid: str, figis: list[str]) -> dict[str, VenueAssetRef]: ...

    def submit_orders(
        self, account_uid: str, batch_id: str, legs: list[OrderLeg]
    ) -> SubmissionResult: ...

    def sync_orders(self, account_uid: str, batch_id: str) -> list[OrderState]: ...

    def cancel_orders(self, account_uid: str, batch_id: str) -> list[OrderState]: ...


__all__ = [
    "ConnectorCapabilityUnavailable",
    "ConnectorError",
    "ExecutionCapability",
    "HoldingsSnapshot",
    "OrderLeg",
    "OrderState",
    "Side",
    "SubmissionResult",
    "TERMINAL_ORDER_STATUSES",
    "VenueAccount",
    "VenueAssetRef",
    "VenueConnector",
    "VenueHolding",
]
