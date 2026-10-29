"""A build writes the universe's bars before research reads them.

On the first build in an Environment the bars table has no registered update yet, so the quant
evidence source cannot read it: the bars must be written before `propose_basket` runs.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from hunch.portfolios import build


class ResearchStarted(Exception):
    """Raised by the fake research so the build stops once the order is known."""


def test_build_writes_the_universe_bars_before_research(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []
    take = SimpleNamespace(uid=uuid.uuid4(), status="draft", title="Grid-scale batteries")
    monkeypatch.setattr(build.Take, "get_by_uid", lambda uid: take)
    monkeypatch.setattr(build, "ensure_universe", lambda: [])
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

    assert calls == [("bars", None, dt.date(2026, 10, 28)), ("research",)]
