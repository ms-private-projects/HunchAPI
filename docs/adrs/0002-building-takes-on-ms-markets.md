# ADR 0002: Building takes on ms-markets

- **Status:** Accepted
- **Date:** 2026-10-25
- **Scope:** Instruments, daily prices, research, the take's weight signal, the portfolio graph,
  and how builds run locally and hosted

## Context

A take becomes a basket and a portfolio with a performance record. The plan requires every market
primitive to be an ms-markets table and Hunch to own the construction logic. ms-markets 2.2.12
supplies the portfolio graph (signal weights → calendar-event rebalances → weights → values), an
external daily price table, FIGI-keyed assets and a persisted trading calendar; it supplies no
price producer, no research and no thesis storage. Local development runs on the MetaTables
SQLite runtime.

## Decisions

1. **Instrument identity is the FIGI.** `HunchInstrument` (FIGI primary key) points at the
   canonical ms-markets `Asset` whose `unique_identifier` is the FIGI, with OpenFIGI details and a
   snapshot; the `HUNCH_UNIVERSE` category holds the price-coverage set. The packaged universe
   (`src/hunch/instruments/universe.json`) carries FIGIs resolved through OpenFIGI's mapping API,
   plus the sector and theme tags research matches on. Venue mappings (Alpaca UUID, IBKR conid)
   come with funding.
2. **Prices live in `ExternalPricesTS`.** One asset-indexed DataNode, `HunchDailyBars`, writes
   daily bars at the XNYS session close into ms-markets' external prices table, which the portfolio
   graph values directly (`TimeIndexTableRef`, staleness 5 days). Its identity is constant: the
   MetaTables updater hashes constructor arguments into the node identity, so the node takes none,
   reads its asset list from the universe and receives options after construction; a growing
   universe therefore keeps one updater and its per-asset statistics. Bars come from a provider
   port; `synthetic` (deterministic geometric Brownian motion per FIGI) serves local development
   and tests, an Alpaca market-data provider is a later phase.
3. **Research proposes, code decides.** `research_take` runs either a recorded completion through
   the platform's `InferenceClient` (one call with a JSON schema whose tickers are the universe) or
   the deterministic theme matcher (`heuristic`, for tests and as the fallback). `apply_guardrails`
   then enforces, in code, tradability, exclusions (ticker, name, sector or theme), the leveraged or
   inverse rule, the position count, the single-name cap with redistribution and the cash buffer,
   and reports every decision in notes stored on the revision.
4. **One signal per take with a history.** `HunchBasketSignal` is a `SignalWeights` subclass whose
   configuration is only the take UID, so its `signal_uid` is stable while baskets change. Each
   build publishes one observation at the last completed session close, with every instrument the
   take ever held (dropped names at 0). `FixedWeights` was rejected because its configuration is
   the weights, so it cannot keep a history. The class path is part of every take's signal UID and
   must never move.
5. **The portfolio graph is ms-markets'.** `PortfolioGraph` builds `PortfolioCalendarEvents`
   (XNYS, market_close), `CalendarEventSignal` (every session), `PortfoliosDataNode` with a fixed
   resolver returning Hunch's `Portfolio` row, zero commission, and runs events, rebalance, weights
   and values with `OFFSET_START` one day before the first signal. Performance since activation is
   read from `PortfoliosTS` and rebased to the last value at or before activation.
6. **Revisions are evidence.** `HunchTakeRevision` stores weights, candidates with roles and
   conviction, the rationale, the guardrail notes, the recorded inference request UIDs and the
   signal observation time.
7. **Builds run inline locally and as Jobs hosted.** `HUNCH_BUILD_EXECUTION` selects it; the API
   starts the `Hunch Take Build` Job with `--take-uid`, and the Agent follows the JobRun. A daily
   dispatcher refreshes every built take after the US close. The build MCP tool declares a
   300-second limit.

## Local SQLite findings (compat shims and preparation)

- SQLite's foreign-key enforcement reads child tables on a parent-key insert, and the local API's
  authorizer grants only registered tables. ms-markets' migration 0018 creates
  `ms_markets__interpolatedpricests` but never registers it, which blocks every asset insert
  locally. `scripts/local_prepare_runtime.py` registers that relation in the catalog (namespace
  `hunch-local`); hosted PostgreSQL needs nothing.
- Assets are created with a lookup plus insert, never an upsert on the asset key, for the same
  reason.
- ms-markets passes several UUIDs as strings into compiled SQL; SQLAlchemy's non-native `Uuid`
  bind processor (SQLite) refuses strings. `hunch.compat` coerces UUID strings for SQLite in the
  process and patches the calendar-session search; both are no-ops on PostgreSQL and should be
  removed when ms-markets fixes the call sites.
- Not SQLite-specific: the rebalance, weights and values nodes of every portfolio share one storage
  table, and a portfolio with no entry yet in the per-portfolio progress map falls back to the
  table-wide latest time index. The second take ever built therefore started its window after its
  only rebalance event and produced no weights or values. `hunch.compat` treats a missing entry in a
  populated progress map as a new portfolio (start from `OFFSET_START`) for the three nodes; this
  one matters on PostgreSQL too and should be reported upstream.

## Local inference finding

Recorded inference is a platform service: the backend needs a recorded-inference adapter for the
provider and the Environment needs a funded credential. On the development backend `openai-codex`
has no adapter (`400 {"provider": "This provider/API has no recorded-inference adapter."}`), the
`openrouter` credential answered `402` (no credit) and the Ollama provider was unreachable, so the
local stack (`scripts/dev_stack.sh`) builds with `HUNCH_RESEARCH_MODE=heuristic` and reports the
mode in `GET /v1/project-state/configuration` (`research.mode`). The hosted default stays
`inference`; a local checkout can opt in through `.env` once a provider with an adapter has credit.
The inference path is covered by tests with a fake client.

## Consequences

- Phase 1 is complete locally: a thesis becomes a built, activated practice take with weights and a
  value series in about two seconds in heuristic mode.
- Funding (stage C) adds the venue mappings and virtual funds on top of these tables.
- `tests/` has pure tests for research, guardrails, bars and routes; the build itself is covered by
  the runtime-gated tests (`HUNCH_LOCAL_RUNTIME_TESTS=1`) against the local MetaTables API.
