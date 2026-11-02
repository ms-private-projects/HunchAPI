# ADR 0006: Hunch behind the Markets API boundary

- **Status:** Accepted
- **Date:** 2026-10-27
- **Scope:** The `hunch` catalog namespace, Hunch's time-series instances, the remote row backend,
  venue and fund state, the local stack and the hosted grants (plan
  `docs/planning/0002-hunch-under-the-markets-api-boundary.md`, step U2)

## Context

ms-markets 3.0 ships its ADR 0047: the Markets API is the application boundary for registries,
providers own their time series in their own namespace, and Markets catalogues them. Until this
change every Hunch process attached 61 Markets tables, wrote Markets core time series, held
`data_writer` on `mainsequence.markets`, and registered the Hunch tables there. The hosted API
needed five to six minutes to start because it attached all of them.

## Decisions

1. **Namespace.** The Hunch mixins declare `__metatable_namespace__ = "hunch"`, so every Hunch table
   is catalogued in `hunch` with a namespaced identifier (`hunch.HunchUserProfile`). The tables
   registered before are moved in place: the migration Job patches each catalog entry
   (`hunch.migrations.namespace_move`) before the upgrade. A table keeps its uid, physical name,
   rows and Alembic binding, so nothing is recreated (the plan expected a recreate). The move is
   idempotent and touches only tables bound to this provider.
2. **Series instances.** `hunch.series` declares Hunch's own instances of the ms-markets contracts,
   created by revision `0004`: the take graph's values, weights, signal weights, rebalance state and
   calendar events (`hunch__portfoliosts__takes` and four more), the daily bars
   (`hunch__externalpricests__daily`), each funded take's fund holdings and target positions, and
   the simulated venue's account holdings and fills. Each keeps the contract's columns, grain index
   and foreign keys to the Markets registries. Every updater is bound with `output_table=`, which
   does not change its identity. The rebalance, weights and values updaters hash their whole
   portfolio configuration, so the take graph's configuration holds only what builds the
   portfolio (signal, rebalance strategy, valuation source, fees) and is named by the portfolio's
   unique identifier: every build and every refresh of a take reaches the same three updaters.
   The description travels as `portfolio_description`, outside the identity. Until 2026-11-01 the
   take's title and the build's rationale were in it, so each build registered three new updaters
   (about twenty MetaTables round trips each) and left the old ones behind, and the refresh used
   a third set. After every graph run the take registers its values, weights and
   signal instances in the Markets catalog (`PortfolioDatasets.register`, an upsert that
   reconciles), so other readers get the take's frames from Markets.
3. **Remote backend.** `start_markets_engine` selects the Markets API for every Markets row class
   in every process and attaches only Hunch's 21 tables; Hunch row classes require only Hunch
   tables. Locally the runtime now attaches in about a second. The workflow grants `reader` on the
   `MainSequenceMarkets` branch to the API and the nine Jobs that start the engine, not to the
   migration Job or the Agent. The schema gate checks only Hunch's provider: the Markets revision is
   the Markets deployment's concern, and reading it needs a grant Hunch no longer holds. The
   hosted Markets and MetaTables APIs scale to zero. Every process resolves each with a 600 s
   wake budget (`hunch.runtime.markets_api_client`, `wait_for_metatables_api`, also in the schema
   gate and the migration Job), because the first development builds and a migration run failed
   after the clients' own 30 s while the APIs were still waking (about 130 s, 2026-10-28). Markets
   calls may take 300 s: an 85 s snapshot publish outlived the 60 s default and was reported
   failed after the Markets API had written it. Seeding writes the Markets registries first and
   Hunch's instrument rows last, so a failed seed is retried by the next build.
4. **Reads.** Hunch reads its own values and weights instances directly (`TimeIndexTableRef`).
   The Markets read services join core tables in compiled SQL and would need Markets grants.
5. **Registries and series, per primitive.**
   - Instruments: Hunch keeps creating its FIGI-keyed assets and OpenFIGI details through the API
     (plan decision 1); snapshots go through `AssetSnapshots.publish`.
   - Prices: a Hunch-owned bars instance, synthetic locally (plan decision 2). A build or a
     refresh first reads the last stored bar of each instrument (one read) and runs the bars
     updater only when one lacks the last completed session; a build writes the take's names
     again only when one has left the universe.
   - Funds and targets: VirtualFund, holdings sets, allocation models, target allocations and
     position sets are Markets rows written through the API; the fund holdings and target positions
     series are Hunch instances (plan decision 3, second option). Markets' by-fund views do not show
     them.
   - Execution: Hunch creates no `OrderManager` batch. The batch id lives on the proposal, and a
     live connector keeps its whole ledger.
   - The simulated venue behaves like a connector. Its Account and each AccountHoldingsSet are
     Markets rows whose `holdings_storage_table_uid` and `source_storage_table_uid` name its holdings
     instance, and its fills go to its `TradesTS` instance. It keeps no `OrdersTS` instance: that
     contract keys every order to a Markets order batch (the updater writes `""`, never `NULL`).
6. **Local stack.** `scripts/dev_stack.sh` starts (or reuses) a loopback Markets API from the
   sibling ms-markets checkout, with that checkout's interpreter (`scripts/local_markets_api.py`,
   port 8603), and gives the Hunch API `MARKETS_API_URL`. The launcher reuses each verified identity
   until its token expires and retries a failed verification, because the local backend is slow; it
   installs Hunch's SQLite shims, which the Markets API now hits.
7. **Shims.** Two SQLite-only shims join `hunch.compat`: expanded `IN` parameters that skip the
   UUID bind processors (MetaTables), and ISO-string timestamps written into DateTime columns by the
   dataset catalog's reconcile (ms-markets). Both are no-ops on PostgreSQL. A third applies on
   every dialect: compiled SQL declares `json` for parameters bound to JSON columns, because
   MetaTables sends PostgreSQL parameters raw and the server binds an undeclared list as an
   array, which failed the first hosted build (`HunchInstrument.themes_json`, 2026-10-28).

## Grants

| When | Principal | Grant |
| --- | --- | --- |
| Before the first U2 deploy | `hunch` API and every Hunch Job | `data_writer` on `hunch` (they held `data_viewer`) |
| After it | the Markets API workload | `data_viewer` on the three catalogued tables only (`hunch__portfoliosts__takes`, `hunch__portfolioweightsts__takes`, `hunch__signalweightsts__takes`), for catalog verification and reconcile; never on the namespace, which holds the profiles |
| After it | every Hunch workload | revoke the roles on `mainsequence.markets` |
| Before the first hosted build | `hunch` API, Hunch Take Build, Hunch Portfolio Refresh, Hunch Daily Review and Hunch Execution Sync | table-level `editor` on the ten series instances (`hunch__externalpricests__daily`, `hunch__signalweightsts__takes`, `hunch__portfoliosts__takes`, `hunch__portfolioweightsts__takes`, `hunch__portfoliorebalancestatets__takes`, `hunch__portfoliocalendareventsts__takes`, `hunch__targetpositionsts__takes`, `hunch__virtualfundholdingsts__takes`, `hunch__accountholdingsts__simulated`, `hunch__tradests__simulated`) |

`hunch-migrate` keeps `editor` on `mainsequence.markets` for its first U2 run only: moving a table
out of a namespace needs `tables.update` there.

Registering, configuring and running an updater is `tables.operate_updaters` on its output table,
which only `editor` holds; `data_writer` covers row writes, not updaters. A workload without it
gets 404 "TimeIndexMetaTable not found." from `time-index-table-updates/get-or-create/`, which
stopped the first hosted take build at the daily bars (development, 2026-10-28). `editor` is
granted per series table, not on the namespace, so the profile, take and funding tables stay at
`data_writer` and these workloads cannot create tables in `hunch`. The dispatchers, Hunch
Leaderboard and Hunch Email Digest run no updater and keep `data_writer`.

## Upstream reports (ms-markets 3.0.2 and the 3.0.3 development branch)

- `OrderManager.create_batch` through the Markets API fails: the API's runtime does not attach
  `OrderManagerTable`.
- `AccountHoldingsSnapshots.publish` is a PostgreSQL-only statement (data-modifying CTEs), so a
  Markets API on the local SQLite runtime cannot serve it.
- The dataset catalog's reconcile writes `min`/`max` of an untyped column (text on SQLite) into
  DateTime columns.
- On SQLite, the multi-portfolio values read looks portfolios up by hyphenated uid strings and finds
  none. Hunch reads its own instances, so it does not depend on this.
- MetaTables: expanded `IN` parameters skip the SQLite bind processors.
- MetaTables: `compile_sqlalchemy_statement` declares only temporal `parameter_types`, so a JSON
  list column write fails on PostgreSQL (`invalid input syntax for type json`).
- The per-portfolio progress fallback (ADR 0002, shim 3) is still present.
- `MarketsClient.from_environment` waits a fixed 30 s for the Markets API to wake, with no setting;
  a scaled-to-zero API takes minutes. Hunch builds its client with a longer discovery timeout.
- The Markets client's 60 s request timeout is shorter than a snapshot publish on a cold
  Environment (85 s); the client reports a failure for a write that succeeded.
- The hosted Markets API image installs `requirements.txt`, exported without extras, so it lacks
  `pandas-market-calendars` (the `portfolios` extra) and `Calendar.create_from_pandas_calendar`
  answers 500 (`ModuleNotFoundError`). Hunch builds the XNYS dates and sessions itself and
  writes them with `Calendar.upsert` and `upsert_many`, extending the calendar's horizon last
  (development, 2026-10-28).
- MetaTables transfers have one 60 s deadline per upload and per read, and a read pages 500 rows
  by default while the server allows 10,000. On development (a page or chunk takes seconds) the
  first build's 40k-row bars backfill and the 18k-row evidence read both ran out of it. Hunch
  bounds a bars run to 6,000 rows of whole sessions and runs again, and reads bars per 20
  instruments at the largest page (`hunch.market_data`, 2026-10-29).
- The MetaTables SDK fetches `runtime-context` before every operation and caches it nowhere by
  design (an API restart or a fork must never reuse a source), so each read costs two round
  trips on the hosted API, about 3 s each on development. Hunch's read paths therefore spend
  operations, not rows: one catalog lookup per series table per process, the instrument rows
  cached for five minutes, the weights snapshot in one last-observation read (the physical
  reader ranks rows per identity coordinate), and the last closes only for rows the graph
  stored without an execution price (2026-10-30: the take weights fell from ten operations to
  two on a warm process).
- Platform: the gateway admits every request to a hosted FastAPI release (MetaTables, Markets)
  through the backend's `/fastapi/jwt/validate/`. Its 60 s reuse is keyed on the full URI, so SDK
  calls almost never reuse it. On development that backend is the Django `runserver` on the
  developer's machine behind ngrok: it runs sync views one at a time and reads Cloud SQL in
  europe-west1 at 22 ms a query, so a validation takes 0.3 s alone and 2.6-4 s on average under
  a build's own traffic (136 validations, 351 s, in the 18-minute build of 2026-10-29). This sets
  the seconds per MetaTables round trip noted above.
- FastAPI releases scale to zero after about 60 s idle (no scale-down delay; Harness Agents keep
  15 minutes), and a Markets API cold start takes 60-110 s, 40-50 s of it attaching its runtime.
  A take build calls Markets before its graph and registers the datasets after it, so on
  development it paid that wake twice (three times before the graph identity was fixed). The
  build Job now starts the first wake right after its schema gate (`wake_markets_api`, a
  background resolve of the lazy backend's client), so it overlaps the runtime attachment and
  the construction; the wake after the graph's MetaTables-only stretch remains.

## Consequences

- Hunch holds no grant on `mainsequence.markets` once the grants above are done, and Markets sees
  Hunch's portfolios through its catalog.
- Takes built locally before this change keep their history in the Markets core tables, which Hunch
  no longer reads; rebuild them, or move them with `msm series move`. The hosted Environments had
  no takes.
- A Markets API outage stops Hunch's registry reads and writes; Hunch's own tables stay readable.
