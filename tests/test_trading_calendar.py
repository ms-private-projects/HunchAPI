"""Hunch materialises the XNYS calendar itself and marks it complete only once its rows exist."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from hunch.portfolios import graph
from hunch.settings import TRADING_CALENDAR_VALID_FROM, TRADING_CALENDAR_VALID_TO


@pytest.fixture
def markets(monkeypatch):
    calls: list[str] = []
    state = {"existing": None, "fail_sessions": False}

    def upsert_calendar(**row):
        calls.append(f"calendar {row['valid_to']}")
        return SimpleNamespace(
            uid="calendar-uid", timezone=row["timezone"], valid_to=row["valid_to"]
        )

    def create_from_pandas_calendar(**_):
        raise AssertionError("the Markets API cannot materialise pandas calendars")

    def upsert_many(kind):
        def run(payloads):
            if kind == "sessions" and state["fail_sessions"]:
                raise RuntimeError("Markets API returned 500")
            assert all(row["calendar_uid"] == "calendar-uid" for row in payloads)
            calls.append(f"{kind} {len(payloads)}")
            return payloads

        return run

    monkeypatch.setattr(
        graph,
        "Calendar",
        SimpleNamespace(
            get_by_unique_identifier=lambda _: state["existing"],
            upsert=upsert_calendar,
            create_from_pandas_calendar=create_from_pandas_calendar,
        ),
    )
    monkeypatch.setattr(graph, "CalendarDate", SimpleNamespace(upsert_many=upsert_many("dates")))
    monkeypatch.setattr(
        graph, "CalendarSession", SimpleNamespace(upsert_many=upsert_many("sessions"))
    )
    return calls, state


def test_the_horizon_is_extended_after_the_rows_are_written(markets) -> None:
    calls, _ = markets
    calendar = graph.ensure_trading_calendar()

    start = dt.date.fromisoformat(TRADING_CALENDAR_VALID_FROM)
    end = dt.date.fromisoformat(TRADING_CALENDAR_VALID_TO)
    dates = (end - start).days + 1
    assert calls[0] == f"calendar {TRADING_CALENDAR_VALID_FROM}"
    assert calls[-1] == f"calendar {TRADING_CALENDAR_VALID_TO}"
    written = calls[1:-1]
    assert all(c.startswith(("dates ", "sessions ")) for c in written)
    assert sum(int(c.split()[1]) for c in written if c.startswith("dates ")) == dates
    sessions = sum(int(c.split()[1]) for c in written if c.startswith("sessions "))
    assert 0 < sessions < dates
    assert max(int(c.split()[1]) for c in written) <= graph.CALENDAR_UPSERT_BATCH
    assert calendar.timezone == "America/New_York"


def test_a_complete_calendar_is_reused(markets) -> None:
    calls, state = markets
    state["existing"] = SimpleNamespace(uid="calendar-uid", valid_to=TRADING_CALENDAR_VALID_TO)
    assert graph.ensure_trading_calendar() is state["existing"]
    assert calls == []


def test_a_failed_write_leaves_the_calendar_incomplete(markets) -> None:
    calls, state = markets
    state["fail_sessions"] = True
    with pytest.raises(RuntimeError):
        graph.ensure_trading_calendar()
    assert f"calendar {TRADING_CALENDAR_VALID_TO}" not in calls
