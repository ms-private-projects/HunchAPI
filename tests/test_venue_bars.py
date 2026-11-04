"""Daily bars from the Alpaca connector (ADR 0009): the read, the mapping and the restatement."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
from tests.test_connectors import CannedHTTP, _page

from hunch import market_data
from hunch.connectors.alpaca import AlpacaConnector
from hunch.connectors.base import ConnectorCapabilityUnavailable
from hunch.market_data import (
    BAR_COLUMNS,
    SyntheticBarsProvider,
    bars_provider_instance,
    restate_daily_bars,
    session_schedule,
)
from hunch.market_data.venue import AlpacaBarsProvider, FrameBarsProvider

UTC = dt.timezone.utc
CAT, VST, BIL = "BBG000BF0K17", "BBG00DXDL6Q1", "BBG000RFQSH8"
DATASET = "e0030da2-e6ae-4914-8157-b98cf2bd4288"


def _bar(identifier: str, day: dt.date, close: float, *, hour: int = 20) -> dict:
    return {
        "time_index": dt.datetime(day.year, day.month, day.day, hour, tzinfo=UTC).isoformat(),
        "open_time": dt.datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC).isoformat(),
        "asset_identifier": identifier,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1000.0,
        "trade_count": None,
        "vwap": None,
        "asset_uid": "ignored",
    }


@pytest.fixture
def venue(monkeypatch):
    """A connector listing CAT and VST (no FIGI, as the hosted one) and storing their bars."""
    monkeypatch.setattr(
        "hunch.instruments.services.instruments_for_figis",
        lambda figis: {
            CAT: SimpleNamespace(figi=CAT, ticker="CAT"),
            VST: SimpleNamespace(figi=VST, ticker="VST"),
            BIL: SimpleNamespace(figi=BIL, ticker="BIL"),
        },
    )
    stored = {
        "ALPACA::cat": [
            _bar("ALPACA::cat", dt.date(2026, 9, day), 800.0 + day) for day in (1, 2, 3, 4)
        ],
        "ALPACA::vst": [_bar("ALPACA::vst", dt.date(2026, 9, day), 150.0 + day) for day in (2, 3)],
    }
    # A bar on a Saturday is no session and is dropped.
    stored["ALPACA::vst"].append(_bar("ALPACA::vst", dt.date(2026, 9, 5), 1.0))

    def observations(query):
        assert query["ordering"] == "time_index" and query["offset"] % query["limit"] == 0
        start = dt.datetime.fromisoformat(query["start"])
        end = dt.datetime.fromisoformat(query["end"])
        rows = [
            row
            for identifier in query["asset_identifier"]
            for row in stored.get(identifier, [])
            if start <= dt.datetime.fromisoformat(row["time_index"]) <= end
        ]
        rows.sort(key=lambda row: row["time_index"])
        page = rows[query["offset"] : query["offset"] + query["limit"]]
        return _page(page, query["offset"], has_next=query["offset"] + query["limit"] < len(rows))

    http = CannedHTTP(
        {
            ("GET", "/v1/assets"): lambda q: _page(
                [
                    {
                        "uid": "u1",
                        "unique_identifier": "ALPACA::cat",
                        "ticker": "CAT",
                        "figi": None,
                    },
                    {
                        "uid": "u2",
                        "unique_identifier": "ALPACA::vst",
                        "ticker": "VST",
                        "figi": None,
                    },
                ],
                q.get("offset", 0),
            ),
            ("GET", "/v1/market-data/datasets"): _page(
                [
                    {"uid": "iex", "key": "1d/iex/raw", "row_count": 0},
                    {"uid": DATASET, "key": "1d/sip/all", "row_count": 6},
                ],
                0,
            ),
            ("GET", f"/v1/market-data/datasets/{DATASET}/observations"): observations,
        }
    )
    return http


def test_the_connector_pages_its_stored_bars_by_figi(venue, monkeypatch) -> None:
    connector = AlpacaConnector(venue)  # type: ignore[arg-type]
    monkeypatch.setattr(AlpacaConnector, "BARS_PAGE_SIZE", 2)
    bars = connector.daily_bars([CAT, VST, BIL], dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    # BIL is not listed at the venue: no key. Listed instruments get their rows.
    assert set(bars) == {CAT, VST}
    assert [row["close"] for row in bars[CAT]] == [801.0, 802.0, 803.0, 804.0]
    pages = [call for call in venue.calls if call[1].endswith("/observations")]
    assert len(pages) == 4  # seven rows, two a page
    assert pages[0][2]["asset_identifier"] == ["ALPACA::cat", "ALPACA::vst"]
    # The dataset is looked up once per client.
    assert sum(1 for call in venue.calls if call[1] == "/v1/market-data/datasets") == 1


def test_the_connector_says_when_it_stores_no_daily_bars(venue) -> None:
    venue.routes[("GET", "/v1/market-data/datasets")] = _page([], 0)
    with pytest.raises(ConnectorCapabilityUnavailable):
        AlpacaConnector(venue).daily_bars([CAT], dt.date(2026, 9, 1), dt.date(2026, 9, 4))  # type: ignore[arg-type]


def test_venue_bars_are_stamped_at_the_session_and_unlisted_names_stay_synthetic(venue) -> None:
    provider = AlpacaBarsProvider(AlpacaConnector(venue))  # type: ignore[arg-type]
    start, end = dt.date(2026, 9, 1), dt.date(2026, 9, 8)
    frame = provider.daily_bars([CAT, VST, BIL], start, end)
    assert set(BAR_COLUMNS) <= set(frame.columns)
    assert provider.coverage == {"venue": sorted([CAT, VST]), "synthetic": [BIL]}
    observed = frame[~frame["interpolated"]]
    assert set(observed["asset_identifier"]) == {CAT, VST}
    assert len(observed) == 6  # the Saturday bar is gone
    sessions = session_schedule(start, end)
    closes = set(pd.to_datetime(observed["time_index"], utc=True))
    assert closes <= set(sessions["market_close"])
    cat = observed[observed["asset_identifier"] == CAT].sort_values("time_index")
    assert cat["close"].tolist() == [801.0, 802.0, 803.0, 804.0]
    assert cat["vwap"].isna().all()
    # BIL keeps the synthetic series (defined from BARS_START), cut to the window and flagged.
    synthetic = frame[frame["asset_identifier"] == BIL]
    assert synthetic["interpolated"].all() and len(synthetic) == len(sessions)
    reference = SyntheticBarsProvider().daily_bars([BIL], market_data.BARS_START, end)
    assert synthetic["close"].tolist() == reference["close"].tail(len(sessions)).tolist()


def test_the_configured_provider_is_selectable(monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_BARS_PROVIDER", "alpaca")
    assert isinstance(bars_provider_instance(), AlpacaBarsProvider)
    monkeypatch.setenv("HUNCH_BARS_PROVIDER", "synthetic")
    assert isinstance(bars_provider_instance(), SyntheticBarsProvider)
    monkeypatch.setenv("HUNCH_BARS_PROVIDER", "yahoo")
    with pytest.raises(ValueError):
        bars_provider_instance()


def test_a_venue_provider_is_asked_only_for_sessions_after_the_stored_bars() -> None:
    node = market_data.HunchDailyBars.__new__(market_data.HunchDailyBars)
    node._asset_identifiers = [CAT, VST]
    node.update_statistics = SimpleNamespace(
        index_progress={
            CAT: dt.datetime(2026, 10, 30, 20, tzinfo=UTC),
            VST: dt.datetime(2026, 11, 2, 21, tzinfo=UTC),
        }
    )
    assert node._fetch_start() == dt.date(2026, 10, 30)
    node.update_statistics = SimpleNamespace(index_progress={})
    assert node._fetch_start() == market_data.BARS_START


class RestatingBars:
    """A bars node that records each restatement run and writes the provider's rows."""

    runs: list[dict] = []

    def __init__(self) -> None:
        self.provenance: dict = {}
        self._rows_pending = 0

    def configure(self, **kwargs):
        self.kwargs = kwargs
        return self

    def run(self, *, update_tree):
        kwargs = self.kwargs
        after = pd.Timestamp(kwargs["restate_after"])
        frame = kwargs["provider"].daily_bars(
            kwargs["asset_identifiers"], after.date(), kwargs["end"]
        )
        frame = frame[pd.to_datetime(frame["time_index"], utc=True) > after]
        frame = market_data._normalize_bars(frame.copy())
        bounded, self._rows_pending = market_data.bound_to_sessions(frame, max_rows=4)
        self.provenance = market_data.bars_provenance("alpaca", bounded)
        type(self).runs.append({**kwargs, "rows": len(bounded)})
        return None, None

    @property
    def rows_pending(self) -> int:
        return self._rows_pending


def test_a_restatement_rewrites_only_what_the_venue_covers_through_the_stored_end(
    venue, monkeypatch
) -> None:
    RestatingBars.runs = []
    monkeypatch.setattr(market_data, "HunchDailyBars", RestatingBars)
    monkeypatch.setattr(
        market_data,
        "last_stored_bars",
        lambda figis: {
            # CAT's stored bars end where the venue's do; VST's run past the venue's last bar.
            CAT: dt.datetime(2026, 9, 4, 20, tzinfo=UTC),
            VST: dt.datetime(2026, 11, 3, 21, tzinfo=UTC),
            BIL: dt.datetime(2026, 11, 3, 21, tzinfo=UTC),
        },
    )
    provider = AlpacaBarsProvider(AlpacaConnector(venue))  # type: ignore[arg-type]
    report = restate_daily_bars(
        [CAT, VST, BIL], provider=provider, since=dt.date(2026, 9, 1), end=dt.date(2026, 9, 8)
    )
    assert report["restated"] == [CAT]
    assert set(report["kept"]) == {VST, BIL}
    assert "2026-09-03" in report["kept"][VST]
    # Four CAT rows, written in bounded runs that each start after the last one written.
    assert report["rows"] == 4
    assert [run["rows"] for run in RestatingBars.runs] == [4]
    first = RestatingBars.runs[0]
    assert first["asset_identifiers"] == [CAT]
    assert isinstance(first["provider"], FrameBarsProvider)
    assert pd.Timestamp(first["restate_after"]) < pd.Timestamp("2026-09-01", tz="UTC")
    assert report["first"].date() == dt.date(2026, 9, 1)
    assert report["last"].date() == dt.date(2026, 9, 4)


def test_a_restatement_advances_through_bounded_runs(venue, monkeypatch) -> None:
    RestatingBars.runs = []
    monkeypatch.setattr(market_data, "HunchDailyBars", RestatingBars)
    monkeypatch.setattr(market_data, "last_stored_bars", lambda figis: {})
    provider = AlpacaBarsProvider(AlpacaConnector(venue))  # type: ignore[arg-type]
    report = restate_daily_bars(
        [CAT, VST], provider=provider, since=dt.date(2026, 9, 1), end=dt.date(2026, 9, 8)
    )
    assert report["restated"] == [CAT, VST] and report["rows"] == 6
    # Four rows a run, whole sessions: 1 Sep (CAT), 2 and 3 Sep (both), then 4 Sep (CAT).
    assert [run["rows"] for run in RestatingBars.runs] == [5, 1]
    second = pd.Timestamp(RestatingBars.runs[1]["restate_after"])
    assert second == pd.Timestamp("2026-09-03 20:00", tz="UTC")
