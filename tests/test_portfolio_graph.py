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


@pytest.fixture(autouse=True)
def offline_catalog(monkeypatch):
    """Bind Hunch's series tables to stand-in catalog rows, as a signed-in process would.

    An updater looks up its output table's catalog row when it is built; without a MetaTables
    Environment (a fresh clone, CI) that lookup fails before any hash is computed.
    """
    for number, storage in enumerate(graph.portfolio_series().values(), start=10):
        if storage.get_time_index_meta_table() is not None:
            continue
        row = TimeIndexMetaTable.model_construct(
            uid=str(uuid.UUID(int=number)), data_source_uid=str(uuid.UUID(int=8))
        )
        for name, value in (
            ("__time_index_meta_table__", row),
            ("__metatable__", row),
            ("__metatable_uid__", row.uid),
            ("__metatable_data_source_uid__", row.data_source_uid),
        ):
            monkeypatch.setattr(storage, name, value, raising=False)


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


def test_a_restatement_deletes_one_portfolio_from_that_time_downstream_first(monkeypatch) -> None:
    deleted = []

    class Table:
        def __init__(self, role: str) -> None:
            self.role = role

        def delete_after_date(self, after_date, *, dimension_filters=None):
            deleted.append((self.role, after_date, dimension_filters))
            return {"deleted_count": 1}

    roles = ("values", "weights", "signal_weights", "rebalance_state", "calendar_events")
    monkeypatch.setattr(graph, "portfolio_series", lambda: {role: role for role in roles})
    monkeypatch.setattr(
        graph, "_series_ref", lambda storage: SimpleNamespace(output_table=Table(storage))
    )
    close = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)
    graph.restate_portfolio_from("hunch-take-1", close)
    # The signal and the calendar events are not the portfolio's; derived rows go first.
    assert deleted == [
        (role, close, {"portfolio_identifier": ["hunch-take-1"]})
        for role in ("values", "weights", "rebalance_state")
    ]


def test_a_signal_restatement_deletes_one_signal_from_that_time(monkeypatch) -> None:
    deleted = []

    class Table:
        def __init__(self, role: str) -> None:
            self.role = role

        def delete_after_date(self, after_date, *, dimension_filters=None):
            deleted.append((self.role, after_date, dimension_filters))
            return {"deleted_count": 15}

    roles = ("values", "weights", "signal_weights", "rebalance_state", "calendar_events")
    monkeypatch.setattr(graph, "portfolio_series", lambda: {role: role for role in roles})
    monkeypatch.setattr(
        graph, "_series_ref", lambda storage: SimpleNamespace(output_table=Table(storage))
    )
    close = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)
    graph.restate_signal_from("sig-1", close)
    assert deleted == [("signal_weights", close, {"signal_uid": ["sig-1"]})]
