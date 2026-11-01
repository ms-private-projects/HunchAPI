"""A build writes the universe's bars before research reads them, and only once.

On the first build in an Environment the bars table has no registered update yet, so the quant
evidence source cannot read it: the bars must be written before `propose_basket` runs. The take's
own names are part of that universe, so only a name that has left it is written again.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from hunch.portfolios import build


class ResearchStarted(Exception):
    """Raised by the fake research so the build stops once the order is known."""


class CalendarReached(Exception):
    """Raised by the fake calendar so the build stops once the bars are decided."""


UNIVERSE = [SimpleNamespace(figi="F1"), SimpleNamespace(figi="F2")]


def test_build_writes_the_universe_bars_before_research(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []
    take = SimpleNamespace(uid=uuid.uuid4(), status="draft", title="Grid-scale batteries")
    monkeypatch.setattr(build.Take, "get_by_uid", lambda uid: take)
    monkeypatch.setattr(build, "ensure_universe", lambda: UNIVERSE)
    monkeypatch.setattr(build, "take_revisions", lambda uid: [])

    def ensure_daily_bars(figis=None, *, end=None, provider=None):
        calls.append(("bars", figis, end))

    def propose_basket(*args, **kwargs):
        calls.append(("research",))
        raise ResearchStarted

    monkeypatch.setattr(build, "ensure_daily_bars", ensure_daily_bars)
    monkeypatch.setattr(build, "propose_basket", propose_basket)

    moment = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(ResearchStarted):
        build.build_take(take.uid, research_mode="heuristic", now=moment)

    assert calls == [("bars", ["F1", "F2"], dt.date(2026, 10, 28)), ("research",)]


@pytest.mark.parametrize(
    ("held", "written_again"),
    [(["F1"], []), (["F1", "GONE"], [["GONE"]])],
    ids=["inside the universe", "a name that left it"],
)
def test_build_writes_bars_again_only_for_names_outside_the_universe(
    monkeypatch, held, written_again
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
    monkeypatch.setattr(build, "propose_basket", lambda *args, **kwargs: proposal)

    def calendar():
        raise CalendarReached

    monkeypatch.setattr(build, "ensure_trading_calendar", calendar)
    moment = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(CalendarReached):
        build.build_take(take.uid, research_mode="heuristic", now=moment)

    assert bars == [["F1", "F2"], *written_again]
