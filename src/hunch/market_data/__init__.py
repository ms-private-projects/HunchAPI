"""Daily prices for every Hunch instrument, in Hunch's instance of ms-markets' `ExternalPricesTS`.

One asset-indexed updater, `HunchDailyBars`, writes daily OHLCV bars stamped at the session close
of the XNYS calendar for the whole Hunch universe. Its identity is constant: the MetaTables
updater hashes constructor arguments into the node identity, so the node takes none, reads its
asset list from the instrument universe, and receives its options after construction. Where the
bars come from is a provider port (ADR 0009): the synthetic provider serves tests and offline
development with a deterministic series per instrument; the Alpaca provider
(`hunch.market_data.venue`) reads the daily bars the Alpaca connector stores. `restate_daily_bars`
replaces stored history when an Environment moves from one provider to the other.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from hunch.settings import (
    TRADING_CALENDAR_SOURCE,
    TRADING_CALENDAR_VALID_FROM,
    bars_provider,
)
from msm.time_index.assets.asset_indexed import (
    AssetIndexedUpdater,
    AssetIndexedUpdaterConfiguration,
)
from msm_portfolios.time_index.prices.storage import ExternalPricesStorage

logger = logging.getLogger(__name__)

UTC = dt.timezone.utc
BARS_START = dt.date.fromisoformat(TRADING_CALENDAR_VALID_FROM)
# The MetaTables SDK gives one upload a single deadline (60 s), and the development MetaTables
# API persists about 380 rows a second, so a run writes at most this many rows (whole sessions)
# and `ensure_daily_bars` runs again until nothing is pending. A daily refresh is one row per
# name; the 65-name backfill since 2024 is about 40k rows, written over several runs.
BARS_MAX_ROWS_PER_RUN = 6_000
BARS_MAX_RUNS = 40
# A read pages through the Markets API under the same 60 s deadline, a page holding at most the
# server's 10,000 rows (the SDK's default page is 500), and that API answers a page in seconds:
# bars are read per batch of instruments at the largest page (20 names over 400 days are ~5.5k
# rows), so a whole-universe read is a few requests instead of dozens.
BARS_READ_BATCH = 20
BARS_READ_PAGE_SIZE = 10_000
BAR_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
    "interpolated",
)


class BarsProvider(Protocol):
    """Daily bars for instruments between two dates, stamped at the session close (UTC)."""

    name: str

    def daily_bars(self, figis: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame: ...


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return mcal.get_calendar(TRADING_CALENDAR_SOURCE)


def session_schedule(start: dt.date, end: dt.date) -> pd.DataFrame:
    """XNYS sessions between two dates with UTC `market_open` and `market_close`."""
    schedule = _calendar().schedule(start_date=start.isoformat(), end_date=end.isoformat())
    for column in ("market_open", "market_close"):
        schedule[column] = pd.to_datetime(schedule[column], utc=True)
    return schedule


def last_completed_session_close(now: dt.datetime | None = None) -> dt.datetime:
    """The most recent XNYS regular-session close at or before `now` (UTC)."""
    moment = (now or dt.datetime.now(UTC)).astimezone(UTC)
    schedule = session_schedule(moment.date() - dt.timedelta(days=10), moment.date())
    closes = [ts.to_pydatetime() for ts in schedule["market_close"] if ts <= moment]
    if not closes:
        raise RuntimeError("No completed trading session found in the last ten days.")
    return closes[-1]


class SyntheticBarsProvider:
    """Deterministic geometric-Brownian bars per FIGI, identical on every call."""

    name = "synthetic"

    def daily_bars(self, figis: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        schedule = session_schedule(start, end)
        if schedule.empty:
            return pd.DataFrame(columns=["time_index", "asset_identifier", *BAR_COLUMNS])
        frames = []
        for figi in figis:
            seed = int(hashlib.sha1(figi.encode()).hexdigest()[:8], 16)
            random = np.random.RandomState(seed)
            start_price = 20.0 + (seed % 380)
            annual_vol = 0.15 + (seed % 20) / 100.0
            daily_vol = annual_vol / np.sqrt(252.0)
            daily_drift = 0.08 / 252.0 - 0.5 * daily_vol**2
            count = len(schedule)
            returns = random.normal(daily_drift, daily_vol, size=count)
            closes = start_price * np.exp(np.cumsum(returns))
            opens = np.concatenate(([start_price], closes[:-1])) * (
                1 + random.normal(0, daily_vol / 4, size=count)
            )
            highs = np.maximum(opens, closes) * (1 + np.abs(random.normal(0, daily_vol / 3, count)))
            lows = np.minimum(opens, closes) * (1 - np.abs(random.normal(0, daily_vol / 3, count)))
            volumes = np.abs(random.normal(2_000_000, 500_000, count)).round()
            frames.append(
                pd.DataFrame(
                    {
                        "time_index": schedule["market_close"].to_numpy(),
                        "asset_identifier": figi,
                        "open_time": schedule["market_open"].to_numpy(),
                        "open": opens,
                        "high": highs,
                        "low": lows,
                        "close": closes,
                        "volume": volumes,
                        "trade_count": (volumes / 150.0).round(),
                        "vwap": (opens + closes + highs + lows) / 4.0,
                        # Not an observed bar: the contract's flag for synthetic prices.
                        "interpolated": True,
                    }
                )
            )
        return pd.concat(frames, ignore_index=True)


def bars_provider_instance(name: str | None = None) -> BarsProvider:
    selected = name or bars_provider()
    if selected == "synthetic":
        return SyntheticBarsProvider()
    if selected == "alpaca":
        from hunch.market_data.venue import AlpacaBarsProvider

        return AlpacaBarsProvider()
    raise ValueError(f"Unknown bars provider {selected!r}.")


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    for column in ("time_index", "open_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True).astype("datetime64[ns, UTC]")
    for column in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
        frame[column] = frame[column].astype("float64")
    frame["interpolated"] = frame["interpolated"].astype(bool)
    return frame.set_index(["time_index", "asset_identifier"]).sort_index()


def bound_to_sessions(
    frame: pd.DataFrame, max_rows: int = BARS_MAX_ROWS_PER_RUN
) -> tuple[pd.DataFrame, int]:
    """The earliest whole sessions of ``frame`` that fit ``max_rows``, and the rows left over.

    Whole sessions keep every instrument's latest bar at the same close, so the next run
    continues from one session for all of them (the session at the cut is kept complete).
    """
    if len(frame) <= max_rows:
        return frame, 0
    frame = frame.sort_index()
    times = frame.index.get_level_values("time_index")
    kept = frame[times <= times[max_rows - 1]]
    return kept, len(frame) - len(kept)


class HunchDailyBars(AssetIndexedUpdater):
    """Daily bars of the whole Hunch universe, written at the XNYS session close.

    Construct it without arguments (the identity must stay constant) and call ``configure`` to
    narrow the asset list, choose the provider or cap the end date.
    """

    # Rows must be later than this; the first bar is the first session of 2024.
    OFFSET_START = dt.datetime(BARS_START.year - 1, 12, 29, tzinfo=UTC)

    def __init__(self) -> None:
        self._asset_identifiers: list[str] | None = None
        self._provider: BarsProvider | None = None
        self._end: dt.date | None = None
        self._restate_after: dt.datetime | None = None
        self._rows_pending = 0
        self.provenance: dict[str, Any] = {}
        from hunch.series import daily_bars_storage

        # Hunch's own instance of the ExternalPricesTS contract (ADR 0006); the output table does
        # not enter the updater's identity.
        super().__init__(
            config=AssetIndexedUpdaterConfiguration(), output_table=daily_bars_storage()
        )

    def configure(
        self,
        *,
        asset_identifiers: Sequence[str] | None = None,
        provider: BarsProvider | None = None,
        end: dt.date | None = None,
        restate_after: dt.datetime | None = None,
    ) -> HunchDailyBars:
        """``restate_after`` rewrites the stored bars of these instruments after that moment.

        The run then treats each instrument as stored up to ``restate_after``; its write replaces
        the stored rows in the window it covers (a MetaTables write overwrites per instrument).
        """
        if asset_identifiers is not None:
            self._asset_identifiers = sorted(dict.fromkeys(asset_identifiers))
        self._provider = provider or self._provider
        self._end = end or self._end
        self._restate_after = restate_after or self._restate_after
        return self

    def _set_update_statistics(self, update_statistics: Any) -> Any:
        scoped = super()._set_update_statistics(update_statistics)
        if self._restate_after is not None:
            progress = dict(scoped.index_progress or {})
            for figi in self.get_asset_list():
                progress[figi] = self._restate_after
            scoped.index_progress = progress
        return scoped

    def _fetch_start(self) -> dt.date:
        """The first date an incremental provider is asked for: the earliest last stored bar."""
        progress = getattr(self.update_statistics, "index_progress", None) or {}
        moments = [
            pd.Timestamp(progress[figi]) for figi in self.get_asset_list() if figi in progress
        ]
        if not moments:
            return BARS_START
        earliest = min(moment.tz_convert("UTC") if moment.tzinfo else moment for moment in moments)
        return max(BARS_START, earliest.date())

    @property
    def rows_pending(self) -> int:
        """Rows the last run left for a further run (see ``BARS_MAX_ROWS_PER_RUN``)."""
        return self._rows_pending

    @classmethod
    def _required_output_table(cls) -> type[ExternalPricesStorage]:
        return ExternalPricesStorage

    def get_asset_list(self) -> list[str]:
        if self._asset_identifiers is not None:
            return list(self._asset_identifiers)
        return universe_figis()

    def dependencies(self) -> dict[str, Any]:
        return {}

    def update(self) -> pd.DataFrame:
        provider = self._provider or bars_provider_instance()
        end = self._end or dt.datetime.now(UTC).date()
        # The synthetic series is defined from BARS_START; a venue is asked only for what is new.
        start = self._fetch_start() if getattr(provider, "incremental", False) else BARS_START
        frame = provider.daily_bars(self.get_asset_list(), start, end)
        self.provenance = {"source": provider.name, "rows": 0}
        if frame.empty:
            return frame
        normalized = _normalize_bars(frame)
        # Keep only the bars of completed sessions.
        now = pd.Timestamp.now(tz="UTC")
        normalized = normalized[normalized.index.get_level_values("time_index") <= now]
        new_rows = self.update_statistics.filter_df_by_latest_value(normalized)
        bounded, self._rows_pending = bound_to_sessions(new_rows)
        self.provenance = bars_provenance(provider.name, bounded)
        return bounded


def bars_provenance(source: str, frame: pd.DataFrame) -> dict[str, Any]:
    """What one run wrote: its provider, rows, sessions, and which instruments are synthetic."""
    if frame.empty:
        return {"source": source, "rows": 0}
    flat = frame.reset_index()
    times = pd.to_datetime(flat["time_index"], utc=True)
    synthetic = flat["interpolated"].astype(bool)
    return {
        "source": source,
        "rows": len(flat),
        "first": times.min().to_pydatetime(),
        "last": times.max().to_pydatetime(),
        "observed_instruments": sorted(set(flat.loc[~synthetic, "asset_identifier"].astype(str))),
        "synthetic_instruments": sorted(set(flat.loc[synthetic, "asset_identifier"].astype(str))),
    }


def universe_figis() -> list[str]:
    """Every instrument of the Hunch universe, sorted."""
    from hunch.instruments.services import list_instruments

    return sorted(row.figi for row in list_instruments())


def last_stored_bars(figis: Sequence[str]) -> dict[str, dt.datetime]:
    """The time of the last stored bar of each instrument, in one read of Hunch's bars instance.

    The table's identity is the instrument, so the last-observation read answers one row for each
    instrument that has bars. It reads the instance itself, which needs no registered update.
    """
    from hunch.portfolios.graph import external_prices_ref

    unique = list(dict.fromkeys(figis))
    if not unique:
        return {}
    frame = external_prices_ref().get_last_observation(
        dimension_filters={"asset_identifier": unique}
    )
    if frame is None or frame.empty:
        return {}
    flat = frame.reset_index()
    times = pd.to_datetime(flat["time_index"], utc=True)
    return {
        str(figi): moment.to_pydatetime()
        for figi, moment in zip(flat["asset_identifier"], times, strict=True)
    }


def daily_bars_current(figis: Sequence[str], *, end: dt.date | None = None) -> bool:
    """Whether every instrument has the bar of the last session completed through ``end``."""
    moment = dt.datetime.now(UTC)
    if end is not None:
        moment = min(moment, dt.datetime.combine(end, dt.time.max, tzinfo=UTC))
    target = last_completed_session_close(moment)
    try:
        stored = last_stored_bars(figis)
    except Exception as exc:  # the check only spares a run; the updater decides without it
        logger.warning("Reading the stored bars failed: %s", type(exc).__name__)
        return False
    return all(figi in stored and stored[figi] >= target for figi in figis)


def ensure_daily_bars(
    figis: Sequence[str] | None = None,
    *,
    end: dt.date | None = None,
    provider: BarsProvider | None = None,
) -> HunchDailyBars | None:
    """Bring the daily bars of these instruments (default: the whole universe) up to date.

    One read checks the stored bars first, and nothing runs when every instrument already has the
    last completed session: an updater run costs about fifteen MetaTables round trips even when it
    writes nothing, about a minute on development. Otherwise a run writes at most
    ``BARS_MAX_ROWS_PER_RUN`` rows, so a backfill takes several runs; each starts from the table's
    statistics, which the previous run advanced. Returns the last node that ran, if any.
    """
    figis = list(figis) if figis is not None else universe_figis()
    if daily_bars_current(figis, end=end):
        return None
    for _attempt in range(BARS_MAX_RUNS):
        node = HunchDailyBars().configure(asset_identifiers=figis, provider=provider, end=end)
        error, _ = node.run(update_tree=False)
        if error:
            raise RuntimeError("Writing the daily bars failed.")
        _log_provenance(node)
        if not node.rows_pending:
            return node
    raise RuntimeError("Writing the daily bars did not finish within the allowed runs.")


def _log_provenance(node: Any) -> None:
    provenance = getattr(node, "provenance", None) or {}
    if provenance.get("rows"):
        logger.info(
            "Daily bars: %s rows from %s, %s to %s; synthetic instruments: %s.",
            provenance["rows"],
            provenance["source"],
            provenance.get("first"),
            provenance.get("last"),
            len(provenance.get("synthetic_instruments") or []),
        )


def restate_daily_bars(
    figis: Sequence[str],
    *,
    provider: BarsProvider | None = None,
    since: dt.date = BARS_START,
    end: dt.date | None = None,
) -> dict[str, Any]:
    """Replace the stored bars of these instruments from ``since`` with the provider's bars.

    Moving an Environment from synthetic to venue bars must not splice real bars onto a synthetic
    history, so the history is rewritten once. The provider is read once; an instrument is
    rewritten only when the provider observed it (not a synthetic fallback) through its last
    stored bar, so no stored bar is left after the rewritten ones; the others keep their bars and
    are reported. The writes go in bounded runs of whole sessions, as ``ensure_daily_bars``'s do.
    """
    from hunch.market_data.venue import FrameBarsProvider

    provider = provider or bars_provider_instance()
    wanted = list(dict.fromkeys(figis))
    end = end or dt.datetime.now(UTC).date()
    frame = provider.daily_bars(wanted, since, end)
    report: dict[str, Any] = {"source": provider.name, "restated": [], "kept": {}, "rows": 0}
    if frame.empty:
        report["kept"] = {figi: "no bars from the provider" for figi in wanted}
        return report
    normalized = _normalize_bars(frame.copy())
    normalized = normalized[
        normalized.index.get_level_values("time_index") <= pd.Timestamp.now(tz="UTC")
    ]
    flat = normalized.reset_index()
    observed = flat[~flat["interpolated"].astype(bool)]
    venue_last = observed.groupby("asset_identifier")["time_index"].max().to_dict()
    stored = last_stored_bars(wanted)
    restated: list[str] = []
    for figi in wanted:
        last = venue_last.get(figi)
        if last is None:
            report["kept"][figi] = "not observed by the provider"
        elif figi in stored and pd.Timestamp(stored[figi]) > last:
            report["kept"][figi] = (
                f"provider ends {last.date().isoformat()}, stored bars end "
                f"{pd.Timestamp(stored[figi]).date().isoformat()}"
            )
        else:
            restated.append(figi)
    if not restated:
        return report
    source = FrameBarsProvider(flat[flat["asset_identifier"].isin(restated)], name=provider.name)
    after = dt.datetime.combine(since, dt.time.min, tzinfo=UTC) - dt.timedelta(microseconds=1)
    first: dt.datetime | None = None
    for _attempt in range(BARS_MAX_RUNS):
        node = HunchDailyBars().configure(
            asset_identifiers=restated, provider=source, end=end, restate_after=after
        )
        error, _ = node.run(update_tree=False)
        if error:
            raise RuntimeError("Restating the daily bars failed.")
        _log_provenance(node)
        written = node.provenance
        report["rows"] += int(written.get("rows") or 0)
        first = first or written.get("first")
        if not node.rows_pending or not written.get("last"):
            report.update(restated=restated, first=first, last=written.get("last"))
            return report
        after = written["last"]
    raise RuntimeError("Restating the daily bars did not finish within the allowed runs.")


def recent_bars(figis: Sequence[str], *, days: int = 400) -> pd.DataFrame:
    """Stored bars of these instruments over the trailing window, indexed by time and asset."""
    unique = list(dict.fromkeys(figis))
    node = HunchDailyBars().configure(asset_identifiers=unique)
    start = dt.datetime.now(UTC) - dt.timedelta(days=days)
    frames = [
        node.get_df_between_dates(
            start_date=start,
            dimension_filters={"asset_identifier": unique[index : index + BARS_READ_BATCH]},
            columns=["close", "volume"],
            page_size=BARS_READ_PAGE_SIZE,
        )
        for index in range(0, len(unique), BARS_READ_BATCH)
    ]
    filled = [frame for frame in frames if not frame.empty]
    if not filled:
        return frames[0] if frames else pd.DataFrame()
    return pd.concat(filled).sort_index()


def latest_closes(figis: Sequence[str]) -> dict[str, tuple[dt.datetime, float]]:
    """The last stored close per instrument."""
    frame = recent_bars(figis, days=30)
    if frame.empty:
        return {}
    last = frame.reset_index().sort_values("time_index").groupby("asset_identifier").tail(1)
    return {
        str(row.asset_identifier): (row.time_index.to_pydatetime(), float(row.close))
        for row in last.itertuples()
    }


def quantitative_facts(figis: Sequence[str]) -> dict[str, dict[str, float]]:
    """Trailing average daily volume, annualised volatility and one-year return per instrument."""
    frame = recent_bars(figis, days=400)
    facts: dict[str, dict[str, float]] = {}
    if frame.empty:
        return facts
    for figi, group in frame.reset_index().groupby("asset_identifier"):
        series = group.sort_values("time_index")
        closes = series["close"].astype(float)
        returns = closes.pct_change().dropna()
        facts[str(figi)] = {
            "average_daily_volume": float(series["volume"].tail(60).mean()),
            "annualised_volatility": float(returns.tail(252).std() * np.sqrt(252)),
            "one_year_return": float(closes.iloc[-1] / closes.iloc[max(0, len(closes) - 253)] - 1),
        }
    return facts


__all__ = [
    "BARS_START",
    "BAR_COLUMNS",
    "BarsProvider",
    "HunchDailyBars",
    "SyntheticBarsProvider",
    "bars_provenance",
    "bars_provider_instance",
    "bound_to_sessions",
    "daily_bars_current",
    "ensure_daily_bars",
    "last_completed_session_close",
    "last_stored_bars",
    "latest_closes",
    "quantitative_facts",
    "recent_bars",
    "restate_daily_bars",
    "session_schedule",
    "universe_figis",
]
