"""The connector clients parse the connectors' contracts; the registry and linking rules hold."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from tests.fakes import install_fake_rows

from hunch.connectors import connector_for, connector_status, reset_connectors
from hunch.connectors.alpaca import AlpacaConnector
from hunch.connectors.base import (
    ConnectorCapabilityUnavailable,
    ConnectorError,
    OrderLeg,
    VenueAccount,
)
from hunch.connectors.http import ConnectorHTTPClient
from hunch.connectors.ibkr import IBKRConnector
from hunch.profiles import HunchUserProfile, HunchUserProfileAccount
from hunch.profiles.accounts import LinkError, start_link

ME = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class CannedHTTP:
    """A ConnectorHTTPClient double answering canned payloads by (method, path)."""

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, path, *, params=None, json=None, timeout=None):
        self.calls.append((method, path, params or json))
        key = (method, path)
        if key not in self.routes:
            raise ConnectorCapabilityUnavailable(f"The connector does not offer {method} {path}.")
        answer = self.routes[key]
        return answer(params or json or {}) if callable(answer) else answer

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


def _page(items, offset, has_next=False):
    return {
        "items": items,
        "pageInfo": {
            "pageIndex": offset,
            "pageSize": 100,
            "totalItems": len(items),
            "hasNextPage": has_next,
            "hasPreviousPage": False,
        },
    }


def test_alpaca_client_reads_accounts_holdings_and_assets_and_has_no_execution_yet() -> None:
    accounts = [
        {
            "uid": "a1",
            "account_uid": "a1",
            "unique_identifier": "PA3__ALPACA_PAPER",
            "is_paper": True,
            "account_is_active": True,
            "account_name": "Paper",
            "status": "ACTIVE",
            "currency": "USD",
            "equity": "1000.5",
            "cash": "400",
            "buying_power": "800",
            "credentials_updated_by_user_uid": ME,
            "account_number": "PA3",
        },
    ]
    http = CannedHTTP(
        {
            ("GET", "/v1/project-state/capabilities"): {
                "features": [{"id": "accounts.connect", "status": "available"}]
            },
            ("GET", "/v1/accounts"): lambda q: _page(accounts, q.get("offset", 0)),
            ("GET", "/v1/accounts/a1"): accounts[0],
            ("GET", "/v1/accounts/a1/holdings/latest"): {
                "uid": "set-1",
                "time_index": "2026-10-24T20:00:00Z",
                "positions": [
                    {
                        "asset_identifier": "ALPACA::abc",
                        "quantity": "3",
                        "direction": 1,
                        "extra_details": {"symbol": "TSLA", "market_value": "900"},
                    },
                    {
                        "asset_identifier": "USD",
                        "quantity": "400",
                        "direction": 1,
                        "extra_details": {"kind": "cash"},
                    },
                ],
            },
            ("GET", "/v1/assets"): lambda q: _page(
                [
                    {
                        "uid": "x1",
                        "unique_identifier": "ALPACA::abc",
                        "ticker": "TSLA",
                        "figi": "BBG000N9MNX3",
                        "tradable": True,
                        "fractionable": True,
                    },
                    {
                        "uid": "x2",
                        "unique_identifier": "ALPACA::def",
                        "ticker": "ZZZ",
                        "figi": "BBG00000000Z",
                        "tradable": False,
                    },
                ],
                q.get("offset", 0),
            ),
        }
    )
    connector = AlpacaConnector(http)  # type: ignore[arg-type]
    mine = connector.list_accounts(owner_user_uid=ME)
    assert len(mine) == 1 and mine[0].owner_user_uid == ME and mine[0].cash == 400.0
    assert connector.list_accounts(owner_user_uid=OTHER) == []
    snapshot = connector.latest_holdings("a1")
    assert snapshot.cash() == 400.0 and [h.asset_identifier for h in snapshot.positions()] == [
        "ALPACA::abc"
    ]
    assert snapshot.positions()[0].symbol == "TSLA" and snapshot.holdings_set_uid == "set-1"
    refs = connector.resolve_assets("a1", ["BBG000N9MNX3", "BBG0MISSING"])
    assert set(refs) == {"BBG000N9MNX3"} and refs["BBG000N9MNX3"].asset_identifier == "ALPACA::abc"
    assert connector.execution_capability() == "unavailable"
    with pytest.raises(ConnectorCapabilityUnavailable):
        connector.submit_orders(
            "a1", "batch", [OrderLeg("c1", "BBG000N9MNX3", "ALPACA::abc", "TSLA", "buy", 1.0)]
        )


def test_ibkr_client_is_manual_and_reports_no_owner() -> None:
    http = CannedHTTP(
        {
            ("GET", "/v1/accounts"): lambda q: _page(
                [
                    {
                        "account_uid": "i1",
                        "account_unique_identifier": "U123__IBKR_PAPER",
                        "environment": "paper",
                        "account_is_active": True,
                        "ibkr_account_id": "DU123",
                        "base_currency": "USD",
                    }
                ],
                0,
            ),
            ("GET", "/v1/accounts/i1/holdings/latest"): {
                "uid": "s",
                "time_index": "2026-10-24T00:00:00Z",
                "rows": [
                    {
                        "asset_identifier": "IBKR::265598",
                        "quantity": "2",
                        "direction": 1,
                        "extra_details": {"ticker": "AAPL"},
                    }
                ],
            },
        }
    )
    connector = IBKRConnector(http)  # type: ignore[arg-type]
    account = connector.list_accounts()[0]
    assert (
        account.ownership_verifiable is False
        and account.owner_user_uid is None
        and account.is_paper
    )
    assert connector.execution_capability() == "manual"
    assert connector.latest_holdings("i1").positions()[0].symbol == "AAPL"
    with pytest.raises(ConnectorCapabilityUnavailable):
        connector.sync_orders("i1", "b")


def test_http_client_maps_connector_errors_and_missing_routes() -> None:
    class Response:
        def __init__(self, status, body=None):
            self.status_code = status
            self._body = body
            self.content = b"x" if body is not None else b""

        def json(self):
            if self._body is None:
                raise ValueError
            return self._body

    class Session:
        def __init__(self, response):
            self.response = response
            self.kwargs = None

        def request(self, method, url, **kwargs):
            self.kwargs = (method, url, kwargs)
            return self.response

    client = ConnectorHTTPClient(
        "http://connector.test/",
        headers=lambda: {"Authorization": "Bearer t"},
        release_uid="rel",
        session=Session(Response(404, {"detail": "Not Found"})),
    )
    with pytest.raises(ConnectorCapabilityUnavailable):
        client.post("/v1/accounts/a/orders/actions/submit", json={})
    assert client._session.kwargs[2]["headers"]["X-Resource-Release-UID"] == "rel"

    client = ConnectorHTTPClient(
        "http://connector.test",
        session=Session(
            Response(
                409, {"detail": {"code": "action_conflict", "message": "busy", "retryable": False}}
            )
        ),
        headers=lambda: {},
    )
    with pytest.raises(ConnectorError) as info:
        client.get("/v1/accounts")
    assert info.value.code == "action_conflict" and not info.value.retryable

    client = ConnectorHTTPClient(
        "http://connector.test",
        session=Session(
            Response(
                503,
                {"detail": {"code": "provider_unavailable", "message": "down", "retryable": True}},
            )
        ),
        headers=lambda: {},
    )
    with pytest.raises(ConnectorError) as info:
        client.get("/v1/accounts")
    assert info.value.retryable is True
    assert ConnectorHTTPClient(
        "http://c.test", session=Session(Response(200, {"ok": 1})), headers=lambda: {}
    ).get("/x") == {"ok": 1}


def test_registry_follows_the_connector_mode(monkeypatch) -> None:
    reset_connectors()
    monkeypatch.setenv("HUNCH_CONNECTOR_MODE", "simulated")
    assert type(connector_for("alpaca")).__name__ == "SimulatedConnector"
    assert connector_status("ibkr") == {
        "venue": "ibkr",
        "mode": "simulated",
        "configured": True,
        "base_url": None,
    }
    reset_connectors()
    monkeypatch.setenv("HUNCH_CONNECTOR_MODE", "live")
    monkeypatch.delenv("HUNCH_ALPACA_CONNECTOR_URL", raising=False)
    with pytest.raises(ConnectorError) as info:
        connector_for("alpaca")
    assert info.value.code == "dependency_unavailable"
    monkeypatch.setenv("HUNCH_IBKR_CONNECTOR_URL", "http://ibkr.test/")
    assert isinstance(connector_for("ibkr"), IBKRConnector)
    with pytest.raises(ValueError):
        connector_for("binance")
    reset_connectors()


class OwnerVenue:
    venue = "alpaca"

    def __init__(self, owner, verifiable=True):
        self.account = VenueAccount(
            venue="alpaca",
            account_uid=str(uuid.uuid4()),
            unique_identifier="X__ALPACA_PAPER",
            is_paper=True,
            is_active=True,
            owner_user_uid=owner,
            ownership_verifiable=verifiable,
            cash=1.0,
        )

    def get_account(self, account_uid):
        return self.account if account_uid == self.account.account_uid else None

    def list_accounts(self, *, owner_user_uid=None):
        return [self.account]


def test_linking_rules_check_ownership_and_exclusivity(monkeypatch) -> None:
    install_fake_rows(monkeypatch, HunchUserProfile, HunchUserProfileAccount)
    monkeypatch.setenv("HUNCH_CONNECTOR_MODE", "live")
    with patch("hunch.profiles.accounts.notify"):
        theirs = OwnerVenue(OTHER)
        with (
            patch("hunch.profiles.accounts.connector_for", return_value=theirs),
            pytest.raises(LinkError),
        ):
            start_link(ME, "alpaca", account_uid=theirs.account.account_uid)
        mine = OwnerVenue(ME)
        with patch("hunch.profiles.accounts.connector_for", return_value=mine):
            link = start_link(ME, "alpaca", account_uid=mine.account.account_uid)
            assert link.status == "active" and link.metadata_json["ownership_verified"] is True
            with pytest.raises(LinkError):
                start_link(OTHER, "alpaca", account_uid=mine.account.account_uid)
        unverifiable = OwnerVenue(None, verifiable=False)
        with patch("hunch.profiles.accounts.connector_for", return_value=unverifiable):
            link = start_link(ME, "ibkr", account_uid=unverifiable.account.account_uid)
            assert link.metadata_json["ownership_verified"] is False
        with (
            patch("hunch.profiles.accounts.connector_for", return_value=mine),
            pytest.raises(LinkError),
        ):
            start_link(ME, "binance")
