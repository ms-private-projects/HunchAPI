"""Daily bars from the connected venue: the Alpaca connector's stored bars (ADR 0009).

The provider reads through ``AlpacaConnector.daily_bars`` (the connector's REST API, behind the
runtime grant ``ReleaseHTTPClient`` resolves), maps the connector's assets to Hunch instruments by
ticker as ``resolve_assets`` does, and restamps every bar at the XNYS session of its New York
date, so the rows match the synthetic provider's and the rest of Hunch reads them unchanged.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

import pandas as pd

from hunch.settings import VENUE_ALPACA

NEW_YORK = "America/New_York"
VENUE_BAR_COLUMNS = ("open", "high", "low", "close", "volume", "trade_count", "vwap")


def alpaca_market_data_connector() -> Any:
    """The Alpaca connector that serves bars: the configured one when live, else a live client.

    Orders may be simulated locally while prices come from the venue, so the bars connector does
    not follow ``HUNCH_CONNECTOR_MODE``.
    """
    from hunch.connectors import connector_for, connector_http_client
    from hunch.connectors.alpaca import AlpacaConnector
    from hunch.settings import connector_mode

    if connector_mode() == "live":
        return connector_for(VENUE_ALPACA)
    return AlpacaConnector(connector_http_client(VENUE_ALPACA))


def _empty() -> pd.DataFrame:
    from hunch.market_data import BAR_COLUMNS

    return pd.DataFrame(columns=["time_index", "asset_identifier", *BAR_COLUMNS])


def venue_rows_to_bars(
    rows_by_figi: dict[str, list[dict[str, Any]]], start: dt.date, end: dt.date
) -> pd.DataFrame:
    """The connector's rows as Hunch bars: one per XNYS session, stamped at its open and close.

    The connector stamps the scheduled 16:00 New York close even on early-close days; Hunch keys
    each bar by its New York date to the calendar's session, and drops a bar on a date that is no
    session or that has no close.
    """
    from hunch.market_data import session_schedule

    records = [
        {**row, "asset_identifier": figi} for figi, rows in rows_by_figi.items() for row in rows
    ]
    if not records:
        return _empty()
    frame = pd.DataFrame.from_records(records)
    for column in VENUE_BAR_COLUMNS:
        if column not in frame:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame = frame[frame["close"].notna()]
    stamped = pd.to_datetime(frame["time_index"], utc=True)
    frame = frame.assign(
        session=stamped.dt.tz_convert(NEW_YORK).dt.tz_localize(None).dt.normalize()
    )
    schedule = session_schedule(start, end)
    sessions = pd.DataFrame(
        {
            "session": pd.DatetimeIndex(schedule.index).normalize(),
            "open_time": schedule["market_open"].to_numpy(),
            "session_close": schedule["market_close"].to_numpy(),
        }
    )
    merged = frame.drop(columns=["time_index", "open_time"], errors="ignore").merge(
        sessions, on="session", how="inner"
    )
    merged = merged.drop_duplicates(subset=["session", "asset_identifier"], keep="last")
    return pd.DataFrame(
        {
            "time_index": merged["session_close"],
            "asset_identifier": merged["asset_identifier"].astype(str),
            "open_time": merged["open_time"],
            **{column: merged[column] for column in VENUE_BAR_COLUMNS},
            # Observed at the venue: not synthetic.
            "interpolated": False,
        }
    ).reset_index(drop=True)


class AlpacaBarsProvider:
    """Daily bars the Alpaca connector stores; synthetic only for instruments it does not list.

    ``incremental``: the updater asks only for the sessions after each instrument's last stored
    bar, because every page from a hosted connector costs tens of seconds.
    """

    name = "alpaca"
    incremental = True

    def __init__(self, connector: Any | None = None, *, fallback: Any | None = None) -> None:
        self._connector = connector
        self._fallback = fallback
        self.coverage: dict[str, list[str]] = {"venue": [], "synthetic": []}

    @property
    def connector(self) -> Any:
        if self._connector is None:
            self._connector = alpaca_market_data_connector()
        return self._connector

    def daily_bars(self, figis: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        from hunch.market_data import BARS_START, SyntheticBarsProvider

        wanted = list(dict.fromkeys(figis))
        rows_by_figi = self.connector.daily_bars(wanted, start, end) if wanted else {}
        unlisted = [figi for figi in wanted if figi not in rows_by_figi]
        self.coverage = {"venue": sorted(rows_by_figi), "synthetic": sorted(unlisted)}
        frames = [venue_rows_to_bars(rows_by_figi, start, end)]
        if unlisted:
            # The synthetic series is defined from BARS_START, so it is generated from there and
            # cut to the window; its rows say they are synthetic (`interpolated`).
            fallback = self._fallback or SyntheticBarsProvider()
            synthetic = fallback.daily_bars(unlisted, BARS_START, end)
            if not synthetic.empty:
                closes = pd.to_datetime(synthetic["time_index"], utc=True)
                floor = pd.Timestamp(start, tz="UTC")
                frames.append(synthetic[closes >= floor].assign(interpolated=True))
        filled = [frame for frame in frames if not frame.empty]
        if not filled:
            return _empty()
        return pd.concat(filled, ignore_index=True)


class FrameBarsProvider:
    """Serves bars already read (a restatement reads the venue once, then writes in runs)."""

    incremental = True

    def __init__(self, frame: pd.DataFrame, *, name: str) -> None:
        self.name = name
        self._frame = frame

    def daily_bars(self, figis: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        frame = self._frame
        if frame.empty:
            return frame
        closes = pd.to_datetime(frame["time_index"], utc=True)
        new_york = closes.dt.tz_convert(NEW_YORK).dt.date
        mask = frame["asset_identifier"].isin(list(figis)) & (new_york >= start) & (new_york <= end)
        return frame[mask].reset_index(drop=True)


__all__ = [
    "AlpacaBarsProvider",
    "FrameBarsProvider",
    "alpaca_market_data_connector",
    "venue_rows_to_bars",
]
