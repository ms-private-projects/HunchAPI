"""Bars are written in bounded runs of whole sessions and read in batches of instruments.

The MetaTables SDK gives one upload, and one read, a single deadline; the first build in an
Environment writes the whole universe's history and research reads it, both split so each
transfer fits.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from hunch import market_data
from hunch.market_data import bound_to_sessions, ensure_daily_bars, recent_bars

UTC = dt.timezone.utc


def _bars(sessions: int, assets: int) -> pd.DataFrame:
    rows = [
        {
            "time_index": dt.datetime(2024, 1, 2 + day, 21, tzinfo=UTC),
            "asset_identifier": f"FIGI{asset}",
            "close": 1.0 + day,
        }
        for day in range(sessions)
        for asset in range(assets)
    ]
    return pd.DataFrame(rows).set_index(["time_index", "asset_identifier"]).sort_index()


def test_bound_to_sessions_keeps_whole_sessions_and_counts_the_rest() -> None:
    frame = _bars(sessions=3, assets=4)
    kept, pending = bound_to_sessions(frame, max_rows=5)
    assert len(kept) == 8 and pending == 4
    assert kept.index.get_level_values("time_index").nunique() == 2
    assert set(kept.index.get_level_values("asset_identifier")) == set(
        frame.index.get_level_values("asset_identifier")
    )


def test_bound_to_sessions_leaves_a_small_frame_alone() -> None:
    frame = _bars(sessions=2, assets=3)
    kept, pending = bound_to_sessions(frame, max_rows=6)
    assert kept is frame and pending == 0


class FakeBars:
    """A bars node whose runs report the rows still pending, in order."""

    pending = [5000, 1200, 0]
    runs: list[dict] = []
    error = None

    def __init__(self) -> None:
        self._rows_pending = 0

    def configure(self, **kwargs):
        self.kwargs = kwargs
        return self

    def run(self, *, update_tree):
        self._rows_pending = type(self).pending[len(type(self).runs)]
        type(self).runs.append(self.kwargs)
        return type(self).error, None

    @property
    def rows_pending(self) -> int:
        return self._rows_pending


@pytest.fixture
def fake_bars(monkeypatch):
    FakeBars.runs = []
    FakeBars.error = None
    FakeBars.pending = [5000, 1200, 0]
    monkeypatch.setattr(market_data, "HunchDailyBars", FakeBars)
    return FakeBars


def test_ensure_daily_bars_runs_until_nothing_is_pending(fake_bars) -> None:
    node = ensure_daily_bars(["FIGI1"], end=dt.date(2026, 10, 29))
    assert len(fake_bars.runs) == 3 and node.rows_pending == 0
    assert all(run["asset_identifiers"] == ["FIGI1"] for run in fake_bars.runs)


def test_ensure_daily_bars_stops_on_a_failed_run(fake_bars) -> None:
    fake_bars.error = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="failed"):
        ensure_daily_bars()
    assert len(fake_bars.runs) == 1


def test_ensure_daily_bars_gives_up_after_the_allowed_runs(fake_bars, monkeypatch) -> None:
    fake_bars.pending = [10] * 5
    monkeypatch.setattr(market_data, "BARS_MAX_RUNS", 3)
    with pytest.raises(RuntimeError, match="allowed runs"):
        ensure_daily_bars()
    assert len(fake_bars.runs) == 3


class FakeReader:
    """A bars node that answers each read with the bars of the instruments asked for."""

    reads: list[dict] = []
    empty = False

    def configure(self, **kwargs):
        return self

    def get_df_between_dates(self, **kwargs):
        type(self).reads.append(kwargs)
        if type(self).empty:
            return pd.DataFrame()
        figis = kwargs["dimension_filters"]["asset_identifier"]
        frame = _bars(sessions=2, assets=1).reset_index()
        return pd.concat([frame.assign(asset_identifier=figi) for figi in figis]).set_index(
            ["time_index", "asset_identifier"]
        )


@pytest.fixture
def fake_reader(monkeypatch):
    FakeReader.reads = []
    FakeReader.empty = False
    monkeypatch.setattr(market_data, "HunchDailyBars", FakeReader)
    return FakeReader


def test_recent_bars_reads_in_instrument_batches_at_the_largest_page(fake_reader) -> None:
    figis = [f"FIGI{index}" for index in range(45)] + ["FIGI0"]
    frame = recent_bars(figis, days=10)
    batches = [read["dimension_filters"]["asset_identifier"] for read in fake_reader.reads]
    assert [len(batch) for batch in batches] == [20, 20, 5]
    assert all(read["page_size"] == 10_000 for read in fake_reader.reads)
    assert all(read["columns"] == ["close", "volume"] for read in fake_reader.reads)
    assert len(frame) == 45 * 2
    assert frame.index.get_level_values("asset_identifier").nunique() == 45


def test_recent_bars_without_stored_bars_is_empty(fake_reader) -> None:
    fake_reader.empty = True
    assert recent_bars(["FIGI1", "FIGI2"]).empty and len(fake_reader.reads) == 1
    assert recent_bars([]).empty and len(fake_reader.reads) == 1
