"""The take weights spend as few remote operations as they can.

One last-observation read gives the weights snapshot, the instrument rows come from a per-process
cache, the last closes are read only for rows stored without an execution price, and a series
table's catalog row is looked up once per process.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from hunch.instruments import services as instrument_services
from hunch.portfolios import build, graph

NOW = dt.datetime(2026, 10, 27, 21, 0, tzinfo=dt.timezone.utc)
EARLIER = NOW - dt.timedelta(days=7)


def _instrument(figi: str, ticker: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(figi=figi, ticker=ticker, name=name)


@pytest.fixture
def take() -> SimpleNamespace:
    return SimpleNamespace(uid=uuid.uuid4())


def test_take_weights_skip_the_bars_read_when_every_row_has_a_price(monkeypatch, take) -> None:
    rows = [
        {"asset_identifier": "F1", "weight": 0.15, "price_current": 47.78, "time_index": NOW},
        {"asset_identifier": "F2", "weight": 0.4, "price_current": 263.87, "time_index": NOW},
        {"asset_identifier": "F3", "weight": 0.0, "price_current": 10.0, "time_index": NOW},
    ]
    monkeypatch.setattr(build, "portfolio_latest_weights", lambda identifier: rows)
    monkeypatch.setattr(
        build,
        "cached_instruments",
        lambda: [_instrument("F1", "DUK", "Duke Energy"), _instrument("F2", "ALB", "Albemarle")],
    )

    def no_bars_read(figis):
        raise AssertionError("the bars must not be read when every row has a price")

    monkeypatch.setattr(build, "latest_closes", no_bars_read)

    items = build.take_weights(take)

    assert [(item["ticker"], item["weight"], item["price"]) for item in items] == [
        ("ALB", 0.4, 263.87),
        ("DUK", 0.15, 47.78),
    ]
    assert items[0]["name"] == "Albemarle" and items[0]["figi"] == "F2"


def test_take_weights_read_closes_only_for_rows_without_a_price(monkeypatch, take) -> None:
    rows = [
        {"asset_identifier": "F1", "weight": 0.15, "price_current": 47.78, "time_index": NOW},
        {"asset_identifier": "F2", "weight": 0.4, "price_current": None, "time_index": NOW},
    ]
    reads: list[list[str]] = []

    def latest_closes(figis):
        reads.append(list(figis))
        return {"F2": (NOW, 99.5)}

    monkeypatch.setattr(build, "portfolio_latest_weights", lambda identifier: rows)
    monkeypatch.setattr(
        build, "cached_instruments", lambda: [_instrument("F2", "ALB", "Albemarle")]
    )
    monkeypatch.setattr(build, "latest_closes", latest_closes)

    items = build.take_weights(take)

    assert reads == [["F2"]]
    assert [(item["figi"], item["price"]) for item in items] == [("F2", 99.5), ("F1", 47.78)]
    assert items[1]["ticker"] is None


def test_cached_instruments_read_once_per_window(monkeypatch) -> None:
    reads = 0

    def list_instruments():
        nonlocal reads
        reads += 1
        return [_instrument("F1", "DUK", "Duke Energy")]

    monkeypatch.setattr(instrument_services, "list_instruments", list_instruments)
    instrument_services.forget_cached_instruments()

    first = instrument_services.cached_instruments(now=0.0)
    first.clear()  # a caller's copy, not the cache
    assert [row.figi for row in instrument_services.cached_instruments(now=10.0)] == ["F1"]
    assert reads == 1

    instrument_services.cached_instruments(now=instrument_services.UNIVERSE_CACHE_SECONDS + 1.0)
    assert reads == 2

    instrument_services.forget_cached_instruments()
    instrument_services.cached_instruments(now=instrument_services.UNIVERSE_CACHE_SECONDS + 2.0)
    assert reads == 3


class FakeRef:
    """A weights table reference that answers one last-observation read and refuses a range read."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.filters: list[dict] = []

    def get_last_observation(self, *, dimension_filters=None, **_):
        self.filters.append(dimension_filters)
        return self.frame

    def get_df_between_dates(self, *args, **kwargs):
        raise AssertionError("the snapshot must come from the last-observation read alone")


def _weights_frame(rows: list[tuple[dt.datetime, str, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "time_index": pd.Timestamp(moment),
                "portfolio_identifier": "hunch__take",
                "asset_identifier": figi,
                "weight": weight,
                "price_current": price,
            }
            for moment, figi, weight, price in rows
        ]
    )
    return frame.set_index(["time_index", "portfolio_identifier", "asset_identifier"])


def test_portfolio_latest_weights_is_one_read_at_the_latest_time(monkeypatch) -> None:
    ref = FakeRef(
        _weights_frame(
            [
                (EARLIER, "GONE", 0.2, 10.0),  # left the portfolio a week ago
                (NOW, "F1", 0.15, 47.78),
                (NOW, "F2", 0.4, 263.87),
            ]
        )
    )
    monkeypatch.setattr(graph, "portfolio_series", lambda: {"weights": object()})
    monkeypatch.setattr(graph, "_series_ref", lambda storage: ref)

    rows = graph.portfolio_latest_weights("hunch__take")

    assert ref.filters == [{"portfolio_identifier": ["hunch__take"]}]
    assert sorted((row["asset_identifier"], row["weight"]) for row in rows) == [
        ("F1", 0.15),
        ("F2", 0.4),
    ]
    assert all(row["time_index"] == pd.Timestamp(NOW) for row in rows)


def test_portfolio_latest_weights_is_empty_without_observations(monkeypatch) -> None:
    ref = FakeRef(pd.DataFrame())
    monkeypatch.setattr(graph, "portfolio_series", lambda: {"weights": object()})
    monkeypatch.setattr(graph, "_series_ref", lambda storage: ref)

    assert graph.portfolio_latest_weights("hunch__take") == []


def test_series_ref_looks_a_table_up_once_per_process(monkeypatch) -> None:
    lookups: list[str] = []

    class FakeTableRef:
        def __init__(self, uid: str) -> None:
            self.uid = uid

        @classmethod
        def from_uid(cls, uid: str) -> FakeTableRef:
            lookups.append(uid)
            return cls(uid)

    handles = {
        "weights": SimpleNamespace(meta_table_uid="uid-weights"),
        "values": SimpleNamespace(meta_table_uid="uid-values"),
    }
    runtime = SimpleNamespace(table=lambda storage: handles[storage])
    monkeypatch.setattr(graph, "TimeIndexTableRef", FakeTableRef)
    monkeypatch.setattr(graph, "markets_runtime", lambda: runtime)
    graph._table_ref.cache_clear()

    first = graph._series_ref("weights")
    again = graph._series_ref("weights")
    other = graph._series_ref("values")

    assert first is again and other.uid == "uid-values"
    assert lookups == ["uid-weights", "uid-values"]
