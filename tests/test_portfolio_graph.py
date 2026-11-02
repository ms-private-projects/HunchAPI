"""The take graph's updater identity is the portfolio's construction, never a build's text.

The rebalance, weights and values updaters hash their portfolio configuration. Every build and
every refresh of one take must reach the same three updaters; another take reaches its own.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from hunch.portfolios import graph
from hunch.portfolios.services import hunch_portfolio_identifier
from hunch.portfolios.signal import basket_signal
from metatables import TimeIndexTableRef
from metatables.models import TimeIndexMetaTable

UTC = dt.timezone.utc
NODES = ("calendar_events", "rebalance", "weights", "values")


@pytest.fixture(autouse=True)
def offline_prices(monkeypatch):
    table = TimeIndexMetaTable.model_construct(
        uid=str(uuid.UUID(int=7)), data_source_uid=str(uuid.UUID(int=8))
    )
    ref = TimeIndexTableRef(output_table=table)
    monkeypatch.setattr(graph, "external_prices_ref", lambda: ref)


def _hashes(take_uid: uuid.UUID, **kwargs) -> dict[str, str]:
    portfolio = SimpleNamespace(
        uid=uuid.uuid5(take_uid, "portfolio"),
        unique_identifier=hunch_portfolio_identifier(take_uid),
        calendar_uid=uuid.UUID(int=3),
    )
    built = graph.PortfolioGraph(
        portfolio=portfolio, signal=basket_signal(take_uid, ["F1", "F2"]), **kwargs
    )
    return {name: getattr(built, name).update_hash for name in NODES}


def test_builds_and_refreshes_of_a_take_reach_the_same_updaters() -> None:
    take = uuid.UUID(int=1)
    first = _hashes(
        take,
        description="Utilities add storage with every renewable project.",
        offset_start=dt.datetime(2026, 10, 27, 20, tzinfo=UTC),
    )
    rebuilt = _hashes(
        take,
        description="A rationale written by a later build.",
        offset_start=dt.datetime(2026, 10, 28, 20, tzinfo=UTC),
    )
    refreshed = _hashes(take, offset_start=dt.datetime(2026, 10, 27, 20, tzinfo=UTC))
    assert first == rebuilt == refreshed


def test_another_take_has_its_own_updaters() -> None:
    first = _hashes(uuid.UUID(int=1))
    other = _hashes(uuid.UUID(int=2))
    for name in ("rebalance", "weights", "values"):
        assert other[name] != first[name]
