"""The leaderboard: published takes ranked by return since activation.

Ranking uses the model-portfolio series (``PortfoliosTS`` rebased at activation), which is the
same basis for practice and funded takes; entries say whether the period is simulated. A nightly
Job writes a snapshot; readers serve the latest snapshot and fall back to a live computation when
none exists yet (local development, first day).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from hunch.community import HunchLeaderboardSnapshot
from hunch.profiles import utc_now
from hunch.takes import Take

LEADERBOARD_STATUSES: tuple[str, ...] = ("active_practice", "funding", "active_funded")
SNAPSHOT_LOOKBACK_DAYS = 7


def eligible_takes() -> list[Take]:
    """Published, activated takes in an active status."""
    rows = Take.filter(visibility="public")
    return [
        row for row in rows if row.status in LEADERBOARD_STATUSES and row.activated_at is not None
    ]


def compute_entries(
    snapshot_date: dt.date, takes: list[Take] | None = None
) -> list[dict[str, Any]]:
    """Ranked leaderboard entries for the given date, computed from the portfolio series."""
    from hunch.portfolios.build import take_performance
    from hunch.portfolios.metrics import performance_metrics

    entries: list[dict[str, Any]] = []
    for take in takes if takes is not None else eligible_takes():
        points = take_performance(take)
        if not points:
            continue
        last = points[-1]
        activated = take.activated_at
        days_active = max((snapshot_date - activated.date()).days, 0) if activated else 0
        entries.append(
            {
                "take_uid": take.uid,
                "return_since_activation": round(float(last["close"]) - 1.0, 6),
                "days_active": days_active,
                "value_points": len(points),
                "is_funded": take.status == "active_funded",
                "is_simulated": take.status != "active_funded",
                "last_time_index": last["time_index"],
                "metrics": performance_metrics(points),
            }
        )
    entries.sort(
        key=lambda e: (-e["return_since_activation"], -e["days_active"], str(e["take_uid"]))
    )
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return entries


def snapshot_leaderboard(snapshot_date: dt.date | None = None) -> list[HunchLeaderboardSnapshot]:
    """Write (or rewrite) the snapshot of one date and return its rows in rank order."""
    date = snapshot_date or utc_now().date()
    rows: list[HunchLeaderboardSnapshot] = []
    for entry in compute_entries(date):
        rows.append(
            HunchLeaderboardSnapshot.upsert(
                snapshot_date=date,
                take_uid=entry["take_uid"],
                rank=entry["rank"],
                return_since_activation=entry["return_since_activation"],
                days_active=entry["days_active"],
                value_points=entry["value_points"],
                is_simulated=entry["is_simulated"],
                is_funded=entry["is_funded"],
                created_at=utc_now(),
            )
        )
    return rows


def latest_snapshot(
    *, today: dt.date | None = None
) -> tuple[dt.date | None, list[HunchLeaderboardSnapshot]]:
    """The most recent snapshot within the lookback window, in rank order."""
    date = today or utc_now().date()
    for offset in range(SNAPSHOT_LOOKBACK_DAYS + 1):
        candidate = date - dt.timedelta(days=offset)
        rows = HunchLeaderboardSnapshot.filter(snapshot_date=candidate)
        if rows:
            return candidate, sorted(rows, key=lambda row: row.rank)
    return None, []


def leaderboard_entries(
    *, today: dt.date | None = None
) -> tuple[dt.date, bool, list[dict[str, Any]]]:
    """Entries to show: the latest snapshot, else a live computation (marked as such)."""
    date = today or utc_now().date()
    snapshot_date, rows = latest_snapshot(today=date)
    if snapshot_date is not None:
        return (
            snapshot_date,
            False,
            [
                {
                    "take_uid": row.take_uid,
                    "rank": row.rank,
                    "return_since_activation": row.return_since_activation,
                    "days_active": row.days_active,
                    "value_points": row.value_points,
                    "is_simulated": row.is_simulated,
                    "is_funded": row.is_funded,
                }
                for row in rows
            ],
        )
    return date, True, compute_entries(date)


def take_rank(take_uid: uuid.UUID | str, *, today: dt.date | None = None) -> dict[str, Any] | None:
    _, _, entries = leaderboard_entries(today=today)
    for entry in entries:
        if str(entry["take_uid"]) == str(take_uid):
            return entry
    return None


__all__ = [
    "LEADERBOARD_STATUSES",
    "compute_entries",
    "eligible_takes",
    "latest_snapshot",
    "leaderboard_entries",
    "snapshot_leaderboard",
    "take_rank",
]
