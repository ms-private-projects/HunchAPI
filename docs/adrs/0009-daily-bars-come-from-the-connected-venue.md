# ADR 0009: Daily bars come from the connected venue

- **Status:** Accepted
- **Date:** 2026-11-04
- **Scope:** Where Hunch's daily prices come from, how they reach Hunch's bars instance, what a
  run records about them, and how an Environment moves from synthetic to venue prices

## Context

Every price Hunch uses (portfolio values, the Performance tab, the leaderboard, the daily review's
drift, proposal sizing) is read from one series: `HunchDailyBars`, Hunch's own instance of the
ms-markets `ExternalPricesTS` contract (ADRs 0002 and 0006). Its rows came only from the
synthetic provider, a deterministic geometric Brownian motion per FIGI. That kept tests and
offline development reproducible, but it made every return Hunch shows synthetic, and it sized
real orders from synthetic closes (the demo take's BIL close was 639 dollars; the fund trades
near 92).

The Alpaca connector (`alpaca-connectors`) already stores Alpaca's daily bars and serves them
read-only to any authenticated caller, Hunch's runtime grant included:

- `GET /v1/market-data/datasets` lists one dataset per (frequency, feed, adjustment). On the
  Production release (2026-11-04) `1d/sip/all` holds 1,067,616 rows from 2018-01-02 for the 510
  assets of its IVV universe; `1d/iex/raw` is empty.
- `GET /v1/market-data/datasets/{uid}/observations` filters by `asset_identifier` (repeatable,
  the connector's `ALPACA::<uuid>`), `start` and `end`, orders by `time_index`, and pages with
  `limit` at most 1,000 and an `offset` that is a multiple of it. A row carries
  `time_index` (the scheduled 16:00 New York close, UTC), `open_time`, OHLC, `volume`,
  `trade_count` and `vwap`. A hosted call answers in 10 to 30 seconds.
- The connector's assets carry no FIGI, so Hunch maps them by ticker (`resolve_assets`).

## Decisions

1. **The provider is selectable.** `HUNCH_BARS_PROVIDER` is `synthetic` (the default: tests,
   offline development, any Environment without a connector) or `alpaca`. Both write the same
   instance through the same updater, so valuation, the review and the leaderboard read the same
   table and change in nothing.
2. **The Alpaca provider reads the connector's REST API.** `AlpacaConnector.daily_bars` resolves
   the instruments by ticker, finds the `1d/sip/all` dataset (split- and dividend-adjusted, so a
   close-to-close change is the total return) and pages the observations, 40 identifiers and
   1,000 rows a request. It goes through `ReleaseHTTPClient` (or a local URL), never an Alpaca
   SDK or key. `hunch.market_data.venue.AlpacaBarsProvider` restamps each bar at the XNYS session
   of its New York date (the connector stamps 16:00 even on early-close days) and drops a bar on
   a non-session date or without a close. Bars are market data, so the provider reads the
   connector even when `HUNCH_CONNECTOR_MODE=simulated`.
3. **A venue is asked only for what is new.** A provider marked `incremental` is asked from the
   earliest instrument's last stored bar; the synthetic provider still generates from
   `BARS_START`, since its series is defined from there. A run still writes at most 6,000 rows of
   whole sessions (`BARS_MAX_ROWS_PER_RUN`).
4. **Instruments the venue does not list keep synthetic bars, flagged.** For such an instrument
   (BIL: the connector's catalog is the IVV universe) the Alpaca provider serves the synthetic
   series. Leaving it without bars would stop more than that instrument: the portfolio graph
   values a session only when every held instrument has a price, so one ETF without bars freezes
   its take's performance, and a proposal cannot size a leg without a close. The rows say what
   they are: `interpolated` (the contract's "synthetically interpolated" flag) is `true` on every
   synthetic bar and `false` on every venue bar. An instrument the venue lists but has no bars for
   is not given synthetic bars: it lags until the connector has them.
5. **Each run records its provenance.** `HunchDailyBars.provenance` holds the source, the rows,
   the first and last session and which instruments were observed or synthetic;
   `ensure_daily_bars` logs it. `GET /v1/project-state/configuration` reports the provider.
6. **Moving to venue bars restates history once.** Appending venue bars after synthetic ones
   would splice two price paths. `restate_daily_bars(figis, provider=..., since=...)` reads the
   provider once, then rewrites the stored bars of each instrument the venue observed through the
   instrument's last stored bar: the updater treats them as stored up to `since` and its write
   overwrites the window per instrument. An instrument the venue does not reach that far keeps
   its bars and is reported, so a restatement never leaves synthetic bars after venue bars.
7. **Hosted stays synthetic for now.** The hosted Jobs that write bars (take build and research,
   portfolio refresh) would need `HUNCH_BARS_PROVIDER=alpaca`, the connector release UID and a
   `reader` grant on `alpaca-connectors`; grants need the owner's approval, so the workflow is
   unchanged by this ADR.

## The connector's bars stopped on 2026-09-04

The Production connector's stored bars end at 2026-09-04. Its nightly `Alpaca Stored Bar
Configuration` Job fails every run (23 runs, the latest 2026-11-04 00:00 UTC) with
"ALPACA_BARS_CONFIGURATION_UID must identify an enabled stored bar configuration": the workflow
does not set that variable, and the one enabled configuration is `Daily IVV Update`
(`d0a3c211-1485-4732-8814-f0ec78de1a54`, last updated 2026-09-05). No connector code change is
needed:

- set `ALPACA_BARS_CONFIGURATION_UID=d0a3c211-1485-4732-8814-f0ec78de1a54` on that Job in
  `.mainsequence/workflows/daily-stock-bars-holdings-ivv.yaml`, and
- catch up once with `POST /v1/market-data/bar-configurations/d0a3c211-.../actions/update`
  (it starts the `Alpaca Bars Update` Job).

BIL needs the connector to list it and store its bars: a bar configuration with explicit assets
(`asset_source: assets`) that includes it. Until the connector reaches the last completed
session, a restatement keeps every stored bar it cannot replace and an `alpaca` refresh writes
nothing new for the instruments it lists.

## Consequences

- With the connector current, a take's returns, its review and its leaderboard rank come from
  observed closes, and proposals size legs at real prices.
- A refresh on `alpaca` costs a few connector calls (tens of seconds each) instead of none; it
  still runs only when an instrument lacks the last completed session.
- Synthetic bars written before this ADR carry `interpolated = false`; the flag is reliable for
  rows written since, and a restatement rewrites the history it replaces.
- A process that still writes with `synthetic` after a restatement appends synthetic bars to venue
  history: every process of an Environment (API, Jobs, local scripts) must use the same provider.
- Checked on development (2026-11-04): a restatement of two instruments over 24 sessions
  overwrote 48 rows in one run, leaving one row per session and the row count unchanged.
