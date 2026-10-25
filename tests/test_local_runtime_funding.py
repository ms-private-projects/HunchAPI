"""The funded-take loop against the local MetaTables runtime and the simulated venue.

Skipped unless `HUNCH_LOCAL_RUNTIME_TESTS=1`; needs the local MetaTables API up and migrated and
an SDK sign-in. It writes real rows into the local database (a take, an account, a fund).
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HUNCH_LOCAL_RUNTIME_TESTS"),
    reason="needs the local MetaTables runtime (HUNCH_LOCAL_RUNTIME_TESTS=1)",
)

USER = f"runtime-test-{uuid.uuid4().hex[:8]}"


def test_link_fund_approve_review_and_withdraw_on_the_local_runtime(monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_CONNECTOR_MODE", "simulated")
    monkeypatch.setenv("HUNCH_RESEARCH_MODE", "heuristic")
    from metatables import configure_local_client

    configure_local_client()
    from hunch.connectors import reset_connectors
    from hunch.funding import HunchFunding
    from hunch.funding.services import (
        FundingRequest,
        approve_proposal,
        fund_summary,
        fund_take,
        withdraw_take,
    )
    from hunch.operations.reviews import run_review
    from hunch.portfolios.build import activate_practice, build_take
    from hunch.profiles.accounts import link_holdings, start_link
    from hunch.runtime import start_markets_engine
    from hunch.takes import Take
    from hunch.takes.services import TakeCreate, create_take

    reset_connectors()
    start_markets_engine()
    take = create_take(
        USER,
        TakeCreate(title="Runtime test take", thesis_text="Humanoid robots in every home."),
        username="runtime@example.test",
    )
    build_take(take.uid, research_mode="heuristic", created_by="test")
    activate_practice(take.uid)

    link = start_link(USER, "alpaca", account_name="Runtime test account")
    assert link.status == "active" and link_holdings(link).cash() > 0

    funding, proposal = fund_take(
        USER, take.uid, FundingRequest(profile_account_uid=link.uid, target_notional=10_000)
    )
    assert proposal.status == "proposed" and len(proposal.legs_json) >= 3
    approved = approve_proposal(USER, proposal.uid)
    assert approved.status == "filled"
    funding = HunchFunding.get_by_uid(funding.uid)
    summary = fund_summary(funding)
    assert funding.status == "active" and abs(summary["nav"] - 10_000) < 1.0
    assert Take.get_by_uid(take.uid).status == "active_funded"

    review = run_review(take.uid)
    assert review.outcome == "hold" and review.drift_json["basis"] == "account"
    assert review.drift_json["max_abs_drift"] < 0.001

    withdrawn = withdraw_take(USER, take.uid)
    assert withdrawn.status == "filled" and withdrawn.trigger == "withdrawal"
    assert HunchFunding.get_by_uid(funding.uid).status == "closed"
    assert Take.get_by_uid(take.uid).status == "active_practice"
    snapshot = link_holdings(link)
    assert not snapshot.positions() and snapshot.cash() > 0
