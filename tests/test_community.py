"""Notifications, leaderboard and daily reviews against the in-memory row store."""

from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import patch

import pytest
from tests.fakes import install_fake_rows

from hunch.community import HunchLeaderboardSnapshot, HunchNotification
from hunch.community.leaderboard import compute_entries, leaderboard_entries, snapshot_leaderboard
from hunch.community.notifications import list_notifications, mark_read, notify, unread_count
from hunch.profiles import HunchUserProfile
from hunch.reviews import HunchDailyReview
from hunch.reviews.services import compute_drift, review_take
from hunch.takes import Take
from hunch.takes.revisions import TakeRevision

ALICE = "11111111-1111-4111-8111-111111111111"
NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)
TODAY = NOW.date()


@pytest.fixture
def rows(monkeypatch):
    return install_fake_rows(
        monkeypatch,
        HunchUserProfile,
        Take,
        TakeRevision,
        HunchNotification,
        HunchLeaderboardSnapshot,
        HunchDailyReview,
    )


def _take(**kwargs) -> Take:
    defaults = dict(
        owner_user_uid=ALICE,
        title="Robots",
        thesis_text="Robots everywhere",
        status="active_practice",
        visibility="public",
        activated_at=NOW - dt.timedelta(days=10),
    )
    defaults.update(kwargs)
    return Take.create(**defaults)


def test_notifications_are_per_user_newest_first_and_marked_read(rows) -> None:
    HunchUserProfile.create(user_uid=ALICE, handle="alice")
    first = notify(ALICE, "take_built", "Built", created_at=NOW)
    second = notify(ALICE, "review_hold", "Holding", created_at=NOW + dt.timedelta(minutes=1))
    notify("other", "take_built", "Not mine", created_at=NOW)
    assert [n.title for n in list_notifications(ALICE)] == ["Holding", "Built"]
    assert unread_count(ALICE) == 2
    mark_read(ALICE, [first.uid])
    assert [n.title for n in list_notifications(ALICE, unread_only=True)] == ["Holding"]
    mark_read(ALICE)
    assert unread_count(ALICE) == 0 and second.read_at is None  # the row, not the stale object
    with pytest.raises(ValueError):
        notify(ALICE, "unknown_kind", "x")


def test_leaderboard_ranks_public_active_takes_and_snapshots(rows) -> None:
    winner = _take(title="Winner")
    loser = _take(title="Loser", activated_at=NOW - dt.timedelta(days=3))
    _take(title="Private", visibility="private")
    _take(title="Draft", status="draft", activated_at=None)
    series = {
        str(winner.uid): [{"time_index": NOW, "close": 1.12, "return": 0.0}],
        str(loser.uid): [{"time_index": NOW, "close": 0.97, "return": 0.0}],
    }
    with patch(
        "hunch.portfolios.build.take_performance",
        side_effect=lambda take: series.get(str(take.uid), []),
    ):
        entries = compute_entries(TODAY)
        assert [(e["rank"], e["return_since_activation"], e["days_active"]) for e in entries] == [
            (1, 0.12, 10),
            (2, -0.03, 3),
        ]
        snapshot = snapshot_leaderboard(TODAY)
        assert len(snapshot) == 2 and snapshot[0].take_uid == winner.uid
        date, live, shown = leaderboard_entries(today=TODAY)
        assert (date, live) == (TODAY, False) and shown[0]["rank"] == 1
        # No snapshot in the lookback window: computed live instead.
        far = TODAY + dt.timedelta(days=30)
        _, live_now, _ = leaderboard_entries(today=far)
        assert live_now is True


def test_drift_is_measured_per_instrument_and_in_total() -> None:
    drift = compute_drift({"A": 0.5, "B": 0.3}, {"A": 0.55, "C": 0.1})
    assert drift["max_abs_drift"] == 0.3 and drift["total_abs_drift"] == 0.45
    assert {p["figi"]: p["drift"] for p in drift["positions"]} == {"A": 0.05, "B": -0.3, "C": 0.1}


def test_practice_review_holds_and_notifies_the_owner(rows) -> None:
    HunchUserProfile.create(user_uid=ALICE, handle="alice")
    take = _take()
    TakeRevision.create(
        take_uid=take.uid,
        revision=1,
        kind="initial",
        rationale_md="",
        weights_json=[{"figi": "A", "ticker": "AAA", "weight": 0.6, "role": "pure_play"}],
        created_by="heuristic",
        created_at=NOW,
    )
    with (
        patch("hunch.portfolios.build.take_weights", return_value=[{"figi": "A", "weight": 0.6}]),
        patch(
            "hunch.portfolios.build.take_performance",
            return_value=[{"time_index": NOW, "close": 1.05, "return": 0.0}],
        ),
    ):
        review = review_take(take.uid, review_date=TODAY, mode="heuristic")
    assert review.outcome == "hold" and review.thesis_check_json["verdict"] == "hold"
    assert review.drift_json["basis"] == "model_portfolio"
    assert "+5.00%" in review.summary_md
    notes = list_notifications(ALICE)
    assert notes and notes[0].kind == "review_hold"
    # Idempotent per take and date.
    with (
        patch("hunch.portfolios.build.take_weights", return_value=[{"figi": "A", "weight": 0.6}]),
        patch("hunch.portfolios.build.take_performance", return_value=[]),
    ):
        again = review_take(take.uid, review_date=TODAY, mode="heuristic")
    assert again.uid == review.uid and len(HunchDailyReview.filter(take_uid=take.uid)) == 1


def test_funded_review_with_drift_asks_the_proposal_hook(rows) -> None:
    HunchUserProfile.create(user_uid=ALICE, handle="alice")
    take = _take(status="active_funded", execution_mode="approval")
    TakeRevision.create(
        take_uid=take.uid,
        revision=1,
        kind="initial",
        rationale_md="",
        weights_json=[{"figi": "A", "ticker": "AAA", "weight": 0.6, "role": "pure_play"}],
        created_by="heuristic",
        created_at=NOW,
    )
    calls = []

    class Proposal:
        uid = uuid.uuid4()
        status = "proposed"

    def hook(**kwargs):
        calls.append(kwargs)
        return Proposal()

    with patch("hunch.portfolios.build.take_performance", return_value=[]):
        review = review_take(
            take.uid,
            review_date=TODAY,
            mode="heuristic",
            current_weights={"A": 0.45},
            proposal_factory=hook,
        )
    assert review.outcome == "proposed" and review.proposal_uid == Proposal.uid
    assert calls and calls[0]["trigger"] == "drift"
    assert list_notifications(ALICE)[0].kind == "proposal_awaiting_approval"
