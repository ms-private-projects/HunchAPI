"""A build writes the universe's bars before the portfolio graph values the basket, and only once.

On the first build in an Environment the bars table may hold nothing yet, so the universe's bars
are written before construction. The take's own names are part of that universe, so only a name
that has left it is written again. Research (`hunch.research.runs`) writes them the same way
before the quant evidence source reads them; `tests/test_take_research.py` covers that step.

Every build restates the take's signal from its signal time, so a second build in the same session
(or one after a failed build) stores its basket; before activation it restates the portfolio too,
so that basket reaches the weights and values at that close. An active take keeps its history.
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


class GraphRan(Exception):
    """Raised by the fake portfolio graph so the build stops once the graph would run."""


@pytest.mark.parametrize(
    ("activated_at", "restated"),
    [(None, True), (dt.datetime(2026, 10, 20, 21, tzinfo=dt.timezone.utc), False)],
    ids=["never activated", "active"],
)
def test_a_build_restates_the_signal_and_before_activation_the_portfolio_from_its_signal_time(
    monkeypatch, stored_research, activated_at, restated
) -> None:
    calls: list[tuple[object, ...]] = []
    take = SimpleNamespace(
        uid=uuid.uuid4(),
        owner_user_uid="u",
        status="built",
        title="Grid-scale batteries",
        activated_at=activated_at,
    )
    identifier = f"hunch-take-{take.uid}"
    monkeypatch.setattr(build.Take, "get_by_uid", lambda uid: take)
    monkeypatch.setattr(build, "ensure_universe", lambda: UNIVERSE)
    monkeypatch.setattr(build, "take_revisions", lambda uid: [])
    monkeypatch.setattr(build, "ensure_daily_bars", lambda figis=None, *, end=None: None)
    proposal = SimpleNamespace(weights_by_figi=lambda: {"F1": 0.95}, rationale_md="Because.")
    monkeypatch.setattr(build, "construct_basket", lambda *args, **kwargs: proposal)
    monkeypatch.setattr(build, "ensure_trading_calendar", lambda: SimpleNamespace(uid="cal"))
    monkeypatch.setattr(
        build, "basket_signal", lambda uid, universe: SimpleNamespace(signal_uid="sig")
    )
    monkeypatch.setattr(
        build,
        "publish_basket_observation",
        lambda signal, weights, time_index, description=None: calls.append(("publish", time_index)),
    )
    monkeypatch.setattr(
        build,
        "Portfolio",
        SimpleNamespace(
            upsert=lambda **kwargs: SimpleNamespace(
                uid=uuid.uuid4(), unique_identifier=kwargs["unique_identifier"]
            )
        ),
    )
    monkeypatch.setattr(build, "HunchPortfolio", SimpleNamespace(upsert=lambda **kwargs: None))
    monkeypatch.setattr(
        build,
        "restate_portfolio_from",
        lambda portfolio, time_index: calls.append(("restate portfolio", portfolio, time_index)),
    )
    monkeypatch.setattr(
        build,
        "restate_signal_from",
        lambda signal_uid, time_index: calls.append(("restate signal", signal_uid, time_index)),
    )

    class Graph:
        def __init__(self, **kwargs) -> None:
            calls.append(("graph", kwargs["offset_start"]))

        def run(self):
            raise GraphRan

    monkeypatch.setattr(build, "PortfolioGraph", Graph)
    monkeypatch.setattr(build, "hunch_portfolio_identifier", lambda uid: identifier)
    moment = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(GraphRan):
        build.build_take(take.uid, now=moment)

    (published,) = [call[1] for call in calls if call[0] == "publish"]
    # The portfolio is derived from the signal, so its rows go first.
    expected = [("restate portfolio", identifier, published)] if restated else []
    expected += [
        ("restate signal", "sig", published),
        ("publish", published),
        ("graph", published - dt.timedelta(days=1)),
    ]
    assert calls == expected
