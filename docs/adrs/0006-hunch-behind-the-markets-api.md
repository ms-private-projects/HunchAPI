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
   does not change its identity. After every graph run the take registers its values, weights and
   signal instances in the Markets catalog (`PortfolioDatasets.register`, an upsert that
   reconciles), so other readers get the take's frames from Markets.
3. **Remote backend.** `start_markets_engine` selects the Markets API for every Markets row class
   in every process and attaches only Hunch's 21 tables; Hunch row classes require only Hunch
   tables. Locally the runtime now attaches in about a second. The workflow grants `reader` on the
   `MainSequenceMarkets` branch to the API and the nine Jobs that start the engine, not to the
   migration Job or the Agent. The schema gate checks only Hunch's provider: the Markets revision is
   the Markets deployment's concern, and reading it needs a grant Hunch no longer holds. The
   hosted Markets API scales to zero; the backend's client (`hunch.runtime.markets_api_client`)
   waits up to 600 s for it to wake, because the first development build failed after the
   client's own 30 s while the API was still waking (2026-10-28).
4. **Reads.** Hunch reads its own values and weights instances directly (`TimeIndexTableRef`).
   The Markets read services join core tables in compiled SQL and would need Markets grants.
5. **Registries and series, per primitive.**
   - Instruments: Hunch keeps creating its FIGI-keyed assets and OpenFIGI details through the API
     (plan decision 1); snapshots go through `AssetSnapshots.publish`.
   - Prices: a Hunch-owned bars instance, synthetic locally (plan decision 2).
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

`hunch-migrate` keeps `editor` on `mainsequence.markets` for its first U2 run only: moving a table
out of a namespace needs `tables.update` there.

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

## Consequences

- Hunch holds no grant on `mainsequence.markets` once the grants above are done, and Markets sees
  Hunch's portfolios through its catalog.
- Takes built locally before this change keep their history in the Markets core tables, which Hunch
  no longer reads; rebuild them, or move them with `msm series move`. The hosted Environments had
  no takes.
- A Markets API outage stops Hunch's registry reads and writes; Hunch's own tables stay readable.
