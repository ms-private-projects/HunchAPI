"""Venue connectors: the port, its implementations and the registry that picks one per venue."""

from __future__ import annotations

from typing import Any

from hunch.connectors.base import (
    ConnectorCapabilityUnavailable,
    ConnectorError,
    HoldingsSnapshot,
    OrderLeg,
    OrderState,
    SubmissionResult,
    VenueAccount,
    VenueAssetRef,
    VenueConnector,
    VenueHolding,
)
from hunch.settings import VENUES, connector_mode, connector_release_uid, connector_url

_REGISTRY: dict[str, Any] = {}


def connector_for(venue: str) -> VenueConnector:
    """The connector of a venue in the configured mode (cached per process)."""
    if venue not in VENUES:
        raise ValueError(f"Unknown venue {venue!r}.")
    key = f"{connector_mode()}:{venue}"
    if key in _REGISTRY:
        return _REGISTRY[key]
    if connector_mode() == "simulated":
        from hunch.connectors.simulated import SimulatedConnector

        connector: VenueConnector = SimulatedConnector(venue)
    else:
        from hunch.connectors.http import ConnectorHTTPClient

        base_url = connector_url(venue)
        if base_url is None:
            raise ConnectorError(
                f"No connector URL is configured for {venue} (HUNCH_{venue.upper()}_CONNECTOR_URL).",
                code="dependency_unavailable",
                retryable=False,
            )
        client = ConnectorHTTPClient(base_url, release_uid=connector_release_uid(venue))
        if venue == "alpaca":
            from hunch.connectors.alpaca import AlpacaConnector

            connector = AlpacaConnector(client)
        else:
            from hunch.connectors.ibkr import IBKRConnector

            connector = IBKRConnector(client)
    _REGISTRY[key] = connector
    return connector


def reset_connectors() -> None:
    _REGISTRY.clear()


def connector_status(venue: str) -> dict[str, Any]:
    """What the configuration says about a venue, without calling it."""
    mode = connector_mode()
    return {
        "venue": venue,
        "mode": mode,
        "configured": mode == "simulated" or connector_url(venue) is not None,
        "base_url": None if mode == "simulated" else connector_url(venue),
    }


__all__ = [
    "ConnectorCapabilityUnavailable",
    "ConnectorError",
    "HoldingsSnapshot",
    "OrderLeg",
    "OrderState",
    "SubmissionResult",
    "VenueAccount",
    "VenueAssetRef",
    "VenueConnector",
    "VenueHolding",
    "connector_for",
    "connector_status",
    "reset_connectors",
]
