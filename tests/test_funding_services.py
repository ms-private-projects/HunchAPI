"""Leg computation and autopilot limits are deterministic and explainable."""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import patch

import pytest

from hunch.connectors.base import VenueAssetRef
from hunch.funding.services import AutopilotPolicy, autopilot_check, compute_legs

NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)
A, B, C = "BBG00000000A", "BBG00000000B", "BBG00000000C"


def _refs(fractionable: bool = True) -> dict[str, VenueAssetRef]:
    return {
        figi: VenueAssetRef(figi=figi, asset_identifier=figi, symbol=sym, fractionable=fractionable)
        for figi, sym in ((A, "AAA"), (B, "BBB"), (C, "CCC"))
    }


@pytest.fixture(autouse=True)
def _no_universe():
    with patch("hunch.funding.services.ensure_universe", return_value=[]):
        yield


def test_initial_legs_buy_the_basket_and_leave_the_cash_buffer() -> None:
    legs, notes = compute_legs(
        proposal_uid=uuid.uuid4(),
        target={A: 0.5, B: 0.4},
        notional=10_000,
        current={},
        prices={A: 100.0, B: 50.0},
        venue_assets=_refs(),
        cash_available=10_000,
    )
    assert [(leg["ticker"], leg["side"], leg["quantity"]) for leg in legs] == [
        ("AAA", "buy", 50.0),
        ("BBB", "buy", 80.0),
    ]
    assert sum(leg["estimated_notional"] for leg in legs) == 9_000
    assert notes == []


def test_rebalance_sells_exits_first_and_whole_shares_when_not_fractionable() -> None:
    legs, _ = compute_legs(
        proposal_uid=uuid.uuid4(),
        target={A: 0.6, C: 0.3},
        notional=10_000,
        current={A: 30.0, B: 80.0},
        prices={A: 100.0, B: 50.0, C: 33.0},
        venue_assets=_refs(fractionable=False),
        cash_available=2_000.0,
    )
    assert legs[0]["ticker"] == "BBB" and legs[0]["side"] == "sell" and legs[0]["reason"] == "exit"
    buys = {leg["ticker"]: leg for leg in legs if leg["side"] == "buy"}
    assert buys["AAA"]["quantity"] == 30.0  # 60 wanted - 30 held
    assert buys["CCC"]["quantity"] == 90.0  # floor(3000 / 33)
    assert all(float(leg["quantity"]).is_integer() for leg in legs)


def test_buys_scale_down_to_available_cash_and_say_so() -> None:
    legs, notes = compute_legs(
        proposal_uid=uuid.uuid4(),
        target={A: 0.9},
        notional=10_000,
        current={},
        prices={A: 100.0},
        venue_assets=_refs(),
        cash_available=4_500,
    )
    assert legs[0]["quantity"] == 45.0
    assert any("scaled" in note for note in notes)


def test_missing_prices_and_untradable_names_are_skipped_with_notes() -> None:
    legs, notes = compute_legs(
        proposal_uid=uuid.uuid4(),
        target={A: 0.5, B: 0.4},
        notional=1_000,
        current={},
        prices={A: 10.0},
        venue_assets={A: _refs()[A]},
        cash_available=1_000,
    )
    assert [leg["ticker"] for leg in legs] == ["AAA"]
    assert any("no stored price" in note for note in notes)


def test_autopilot_check_reports_every_breached_limit() -> None:
    legs = [
        {"ticker": "AAA", "figi": A, "side": "buy", "estimated_notional": 6_000.0},
        {"ticker": "CCC", "figi": C, "side": "buy", "estimated_notional": 500.0},
    ]
    check = autopilot_check(
        AutopilotPolicy(
            max_turnover_per_day=0.5,
            max_notional_per_order=5_000,
            max_single_name_weight=0.15,
            allow_new_instruments=False,
        ),
        legs,
        nav=10_000,
        current={A: 10.0},
        target={A: 0.6, C: 0.05},
        now=NOW,
    )
    assert check["ok"] is False
    assert len(check["reasons"]) == 4
    assert "CCC" in " ".join(check["reasons"])

    fine = autopilot_check(
        AutopilotPolicy(), legs[1:], nav=10_000, current={}, target={C: 0.05}, now=NOW
    )
    assert fine["ok"] is True and fine["turnover"] == 0.05
