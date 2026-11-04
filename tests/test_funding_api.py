"""Linking, funding, proposals, reviews and notifications over REST with a fake venue."""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tests.fakes import install_fake_rows

from hunch.api.app.main import create_app
from hunch.community import HunchNotification
from hunch.connectors import reset_connectors
from hunch.connectors.base import (
    HoldingsSnapshot,
    OrderState,
    SubmissionResult,
    VenueAccount,
    VenueAssetRef,
    VenueHolding,
)
from hunch.funding import HunchFunding, HunchRebalanceProposal
from hunch.portfolios import HunchPortfolio
from hunch.profiles import HunchUserProfile, HunchUserProfileAccount
from hunch.reviews import HunchDailyReview
from hunch.takes import Take
from hunch.takes.revisions import TakeRevision

NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)
FIGI = "BBG000N9MNX3"


class FakeVenue:
    """A connector double that fills every order at 100 and records what it was asked."""

    venue = "alpaca"

    def __init__(self) -> None:
        self.owner = None
        self.account_uid = str(uuid.uuid4())
        self.cash = 50_000.0
        self.positions: dict[str, float] = {}
        self.submitted: list[tuple[str, list]] = []
        self.calls: list[str] = []
        self.states: list[OrderState] = []

    def capabilities(self):
        return {"features": [{"id": "execution", "status": "available"}]}

    def execution_capability(self):
        return "automatic"

    def _account(self):
        return VenueAccount(
            venue="alpaca",
            account_uid=self.account_uid,
            unique_identifier="ACCT__ALPACA_PAPER",
            is_paper=True,
            is_active=True,
            account_name="Paper",
            owner_user_uid=self.owner,
            cash=self.cash,
            equity=self.cash,
        )

    def create_account(self, owner_user_uid, *, account_name=None):
        self.owner = owner_user_uid
        return self._account()

    def list_accounts(self, *, owner_user_uid=None):
        return [self._account()] if owner_user_uid in (None, self.owner) else []

    def get_account(self, account_uid):
        return self._account() if account_uid == self.account_uid else None

    def latest_holdings(self, account_uid):
        holdings = [VenueHolding(asset_identifier="USD", quantity=self.cash, kind="cash")]
        holdings += [
            VenueHolding(asset_identifier=a, quantity=q) for a, q in self.positions.items()
        ]
        return HoldingsSnapshot(
            account_uid=account_uid,
            time_index=NOW,
            holdings=holdings,
            holdings_set_uid=str(uuid.uuid4()),
        )

    def capture_holdings(self, account_uid):
        return self.latest_holdings(account_uid)

    def resolve_assets(self, account_uid, figis):
        return {
            f: VenueAssetRef(figi=f, asset_identifier=f, symbol="TSLA", fractionable=True)
            for f in figis
        }

    def submit_orders(self, account_uid, batch_id, legs):
        self.submitted.append((batch_id, legs))
        self.states = []
        for leg in legs:
            signed = leg.quantity if leg.side == "buy" else -leg.quantity
            self.positions[leg.asset_identifier] = (
                self.positions.get(leg.asset_identifier, 0.0) + signed
            )
            self.cash -= signed * 100.0
            self.states.append(
                OrderState(
                    client_order_id=leg.client_order_id,
                    status="filled",
                    broker_order_id="b1",
                    filled_quantity=leg.quantity,
                    average_fill_price=100.0,
                    updated_at=NOW,
                )
            )
        return SubmissionResult(batch_id=batch_id, accepted=True, orders=self.states)

    def sync_orders(self, account_uid, batch_id):
        return self.states

    def cancel_orders(self, account_uid, batch_id):
        return self.states


@pytest.fixture
def venue(monkeypatch):
    fake = FakeVenue()
    reset_connectors()
    monkeypatch.setenv("HUNCH_CONNECTOR_MODE", "simulated")
    monkeypatch.setattr("hunch.connectors.connector_for", lambda venue: fake)
    monkeypatch.setattr("hunch.profiles.accounts.connector_for", lambda venue: fake)
    # The fake venue's account is the registry row itself, as in a shared Markets registry.
    monkeypatch.setattr(
        "hunch.profiles.accounts.registry_account_uid",
        lambda venue, account: uuid.UUID(account.account_uid),
    )
    monkeypatch.setattr("hunch.funding.services.connector_for", lambda venue: fake)
    yield fake
    reset_connectors()


@pytest.fixture
def client(local_caller, monkeypatch, venue) -> TestClient:
    install_fake_rows(
        monkeypatch,
        HunchUserProfile,
        HunchUserProfileAccount,
        Take,
        TakeRevision,
        HunchPortfolio,
        HunchFunding,
        HunchRebalanceProposal,
        HunchDailyReview,
        HunchNotification,
    )
    monkeypatch.setattr("hunch.funding.services.ensure_universe", lambda: [])
    monkeypatch.setattr(
        "hunch.funding.services.latest_closes", lambda figis: {f: (NOW, 100.0) for f in figis}
    )
    monkeypatch.setattr(
        "hunch.funding.services.ensure_virtual_fund",
        lambda ident, acct, pf: type("VF", (), {"uid": uuid.uuid4()})(),
    )
    monkeypatch.setattr(
        "hunch.funding.services.publish_account_target", lambda *a, **k: {"position_set_uid": "ps"}
    )
    fund_state: dict[str, float] = {}
    monkeypatch.setattr(
        "hunch.funding.services.fund_latest_holdings", lambda vf: (NOW, dict(fund_state))
    )

    def write(vf, *, source_account_holdings_set_uid, time_index, allocations, strategy="hunch"):
        fund_state.clear()
        fund_state.update({a["asset_identifier"]: float(a["quantity"]) for a in allocations})
        return uuid.uuid4()

    monkeypatch.setattr("hunch.funding.services.write_fund_holdings", write)
    return TestClient(create_app(), headers=local_caller.headers)


def _built_take(client) -> str:
    created = client.post(
        "/v1/takes", json={"title": "Robots", "thesis_text": "Robots everywhere"}
    ).json()
    take = Take.update(
        created["uid"], status="active_practice", signal_uid="s", activated_at=NOW, updated_at=NOW
    )
    TakeRevision.create(
        take_uid=take.uid,
        revision=1,
        kind="initial",
        rationale_md="",
        created_by="heuristic",
        weights_json=[{"figi": FIGI, "ticker": "TSLA", "weight": 0.9, "role": "pure_play"}],
        created_at=NOW,
    )
    HunchPortfolio.create(
        portfolio_uid=uuid.uuid4(),
        take_uid=take.uid,
        owner_user_uid=take.owner_user_uid,
        basket_revision=1,
        is_simulated=True,
        created_at=NOW,
    )
    return str(take.uid)


def test_link_fund_approve_review_and_withdraw_over_rest(client, venue) -> None:
    linked = client.post("/v1/profile/accounts/actions/link", json={"venue": "alpaca"})
    assert linked.status_code == 201, linked.text
    link = linked.json()
    assert (
        link["status"] == "active" and link["ownership_verified"] is True and link["cash"] == 50_000
    )
    assert client.get("/v1/profile/accounts").json()[0]["uid"] == link["uid"]
    holdings = client.get(f"/v1/profile/accounts/{link['uid']}/holdings").json()
    assert holdings["cash"] == 50_000 and holdings["holdings"][0]["kind"] == "cash"

    take_uid = _built_take(client)
    funded = client.post(
        f"/v1/takes/{take_uid}/actions/fund",
        json={"profile_account_uid": link["uid"], "target_notional": 10_000},
    )
    assert funded.status_code == 200, funded.text
    body = funded.json()
    assert (
        body["funding"]["status"] == "pending_initial" and body["proposal"]["status"] == "proposed"
    )
    assert body["proposal"]["legs"][0]["quantity"] == 90.0  # 0.9 x 10,000 / 100
    assert client.get(f"/v1/takes/{take_uid}").json()["status"] == "funding"
    pending = client.get("/v1/proposals", params={"open_only": "true"}).json()
    assert [p["uid"] for p in pending] == [body["proposal"]["uid"]]

    approved = client.post(f"/v1/proposals/{body['proposal']['uid']}/actions/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "filled" and venue.submitted[0][1][0].quantity == 90.0
    funding = client.get(f"/v1/takes/{take_uid}/funding").json()
    assert funding["status"] == "active" and funding["positions"][0]["quantity"] == 90.0
    assert funding["cash"] == 1_000.0 and funding["nav"] == 10_000.0
    assert client.get(f"/v1/takes/{take_uid}").json()["status"] == "active_funded"

    again = client.post(
        f"/v1/takes/{take_uid}/actions/fund",
        json={"profile_account_uid": link["uid"], "target_notional": 1_000},
    )
    assert again.status_code == 409 and again.json()["detail"]["code"] == "funding_rule"

    with patch("hunch.portfolios.build.take_performance", return_value=[]):
        review = client.post(
            f"/v1/takes/{take_uid}/actions/review", json={"research_mode": "heuristic"}
        )
    assert review.status_code == 200, review.text
    assert review.json()["outcome"] == "hold" and review.json()["drift"]["basis"] == "account"
    assert client.get(f"/v1/takes/{take_uid}/reviews").json()[0]["uid"] == review.json()["uid"]

    revoke = client.post(f"/v1/profile/accounts/{link['uid']}/actions/revoke")
    assert revoke.status_code == 409 and revoke.json()["detail"]["code"] == "link_rule"

    withdrawn = client.post(f"/v1/takes/{take_uid}/actions/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["trigger"] == "withdrawal" and withdrawn.json()["status"] == "filled"
    assert client.get(f"/v1/takes/{take_uid}").json()["status"] == "active_practice"
    assert client.get(f"/v1/fundings").json()[0]["status"] == "closed"

    feed = client.get("/v1/notifications").json()
    kinds = [item["kind"] for item in feed["items"]]
    assert {
        "funding_closed",
        "proposal_executed",
        "proposal_awaiting_approval",
        "funding_active",
    } <= set(kinds)
    assert feed["unread"] == len(kinds)
    read = client.post("/v1/notifications/actions/mark-read", json={})
    assert read.json()["unread"] == 0
    assert (
        client.post(f"/v1/profile/accounts/{link['uid']}/actions/revoke").json()["status"]
        == "revoked"
    )


def test_autopilot_executes_within_policy_and_holds_back_outside_it(client, venue) -> None:
    link = client.post("/v1/profile/accounts/actions/link", json={"venue": "alpaca"}).json()
    take_uid = _built_take(client)
    held = client.post(
        f"/v1/takes/{take_uid}/actions/fund",
        json={
            "profile_account_uid": link["uid"],
            "target_notional": 10_000,
            "execution_mode": "autopilot",
            "autopilot_policy": {"max_notional_per_order": 1_000},
        },
    ).json()
    assert (
        held["proposal"]["status"] == "proposed"
        and held["proposal"]["autopilot_check"]["ok"] is False
    )
    rejected = client.post(
        f"/v1/proposals/{held['proposal']['uid']}/actions/reject", json={"reason": "too big"}
    )
    assert rejected.json()["status"] == "rejected"
    assert client.get(f"/v1/takes/{take_uid}").json()["status"] == "active_practice"

    second = _built_take(client)
    executed = client.post(
        f"/v1/takes/{second}/actions/fund",
        json={
            "profile_account_uid": link["uid"],
            "target_notional": 10_000,
            "execution_mode": "autopilot",
            "autopilot_policy": {
                "max_turnover_per_day": 1.0,
                "max_notional_per_order": 50_000,
                "max_single_name_weight": 1.0,
            },
        },
    ).json()
    assert executed["proposal"]["status"] == "filled" and executed["funding"]["status"] == "active"


def test_other_users_cannot_see_my_links_fundings_or_proposals(client, venue, local_caller) -> None:
    link = client.post("/v1/profile/accounts/actions/link", json={"venue": "alpaca"}).json()
    take_uid = _built_take(client)
    body = client.post(
        f"/v1/takes/{take_uid}/actions/fund",
        json={"profile_account_uid": link["uid"], "target_notional": 5_000},
    ).json()
    other = TestClient(create_app(), headers=local_caller.other_headers)
    assert other.get(f"/v1/profile/accounts/{link['uid']}").status_code == 404
    assert other.get(f"/v1/proposals/{body['proposal']['uid']}").status_code == 404
    assert other.post(f"/v1/proposals/{body['proposal']['uid']}/actions/approve").status_code == 404
    assert other.get(f"/v1/takes/{take_uid}/funding").status_code == 404
    assert other.get("/v1/proposals").json() == []
