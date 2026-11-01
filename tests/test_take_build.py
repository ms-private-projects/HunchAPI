"""A build writes the universe's bars before the portfolio graph values the basket, and only once.

On the first build in an Environment the bars table may hold nothing yet, so the universe's bars
are written before construction. The take's own names are part of that universe, so only a name
that has left it is written again. Research (`hunch.research.runs`) writes them the same way
before the quant evidence source reads them; `tests/test_take_research.py` covers that step.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from hunch.portfolios import build


class ConstructionStarted(Exception):
    """Raised by the fake construction so the build stops once the order is known."""


class CalendarReached(Exception):
    """Raised by the fake calendar so the build stops once the bars are decided."""


UNIVERSE = [SimpleNamespace(figi="F1"), SimpleNamespace(figi="F2")]
RESEARCH = SimpleNamespace(uid=uuid.uuid4(), number=1, mode="heuristic")


@pytest.fixture
def stored_research(monkeypatch):
    monkeypatch.setattr(build, "research_for_build", lambda take_uid, research_uid=None: RESEARCH)
    monkeypatch.setattr(build, "research_output", lambda row: SimpleNamespace(mode=row.mode))


def test_build_writes_the_universe_bars_before_construction(monkeypatch, stored_research) -> None:
    calls: list[tuple[object, ...]] = []
    take = SimpleNamespace(uid=uuid.uuid4(), status="draft", title="Grid-scale batteries")
    monkeypatch.setattr(build.Take, "get_by_uid", lambda uid: take)
    monkeypatch.setattr(build, "ensure_universe", lambda: UNIVERSE)
    monkeypatch.setattr(build, "take_revisions", lambda uid: [])

    def ensure_daily_bars(figis=None, *, end=None, provider=None):
        calls.append(("bars", figis, end))

    def construct_basket(*args, **kwargs):
        calls.append(("construction",))
        raise ConstructionStarted

    monkeypatch.setattr(build, "ensure_daily_bars", ensure_daily_bars)
    monkeypatch.setattr(build, "construct_basket", construct_basket)

    moment = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(ConstructionStarted):
        build.build_take(take.uid, now=moment)

    assert calls == [("bars", ["F1", "F2"], dt.date(2026, 10, 28)), ("construction",)]


@pytest.mark.parametrize(
    ("held", "written_again"),
    [(["F1"], []), (["F1", "GONE"], [["GONE"]])],
    ids=["inside the universe", "a name that left it"],
)
def test_build_writes_bars_again_only_for_names_outside_the_universe(
    monkeypatch, stored_research, held, written_again
) -> None:
    bars: list[list[str]] = []
    take = SimpleNamespace(uid=uuid.uuid4(), status="built", title="Grid-scale batteries")
    monkeypatch.setattr(build.Take, "get_by_uid", lambda uid: take)
    monkeypatch.setattr(build, "ensure_universe", lambda: UNIVERSE)
    monkeypatch.setattr(build, "take_revisions", lambda uid: [])
    monkeypatch.setattr(build, "take_universe", lambda uid, *extra: held)
    monkeypatch.setattr(
        build,
        "ensure_daily_bars",
        lambda figis=None, *, end=None, provider=None: bars.append(list(figis)),
    )
    proposal = SimpleNamespace(weights_by_figi=lambda: {"F1": 0.95})
    monkeypatch.setattr(build, "construct_basket", lambda *args, **kwargs: proposal)

    def calendar():
        raise CalendarReached

    monkeypatch.setattr(build, "ensure_trading_calendar", calendar)
    moment = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(CalendarReached):
        build.build_take(take.uid, now=moment)

    assert bars == [["F1", "F2"], *written_again]
