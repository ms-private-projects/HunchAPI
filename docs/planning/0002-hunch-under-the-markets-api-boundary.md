# 0002. Hunch On ms-markets 3.x And The Markets API Boundary

- **Status:** Analysis, 2026-10-27. Supersedes the 2026-10-26 draft written against the 2.2.13
  development branch. No Hunch code changed.
- **Inputs:** ms-markets 3.0.1 (PyPI, `main` at `c7cf0a1`) and the `development` head `d629e77`
  (3.0.2), the 3.0 upgrade guide, ADR 0047 (application boundary) and ADR 0048 (time-index rename),
  the `msm.client` knowledge page, the changelog, and the unmerged branches
  `rename/phase-3-read-new-columns` (3.1.0), `rename/phase-4-remove-old-names` (4.0.0) and
  `rename/phase-5-drop-old-columns` (4.1.0).
- **Checks run:** a scratch environment with ms-markets 3.0.1, MetaTables 0.1.59 and SDK 9.0.33;
  the Hunch test suite in it; `msm rename-preflight scan` over Hunch; the remote-dispatch registry;
  and the hosted schema revisions in both Environments.

## 1. What 3.x changes

3.x moves along two axes at once.

**ADR 0048, the breaking rename.**

- `msm.data_nodes`, `msm_portfolios.data_nodes` and `msm_pricing.data_nodes` become `*.time_index`.
- `*DataNode` classes become `*Updater`, and `*DataNodeConfiguration` becomes
  `*UpdaterConfiguration`.
- The UID fields are renamed after the identity they hold: `portfolio_*_data_node_uid` becomes
  `*_table_update_uid`, `holdings_data_node_uid` becomes `holdings_storage_table_uid`, and so on.
- Old names keep working through 3.x with a `DeprecationWarning`. 4.0 removes them.
- Every producer built from a moved ms-markets class gets a new MetaTables `update_hash` once.
  `signal_uid`, portfolio configuration hashes and strategy revisions do not change.
- The UID columns move in four releases, each gated on every Environment having upgraded:

| Release | Revision | Gate |
| --- | --- | --- |
| 3.0.0 | `0022` | Adds the new columns; writes both, reads the old |
| 3.1.0 | `0023` | Only when no 2.x writer remains in any Environment |
| 4.0.0 | `0024` | Only when no project older than 3.1 reads these tables |
| 4.1.0 | `0025` | Only when no project older than 4.0 uses them; drops the old columns |

**ADR 0047, the boundary, now shipped as code.**

- `msm.client` with a remote row backend. Under `MSM_API_BACKEND=remote` (or
  `use_remote_backend(...)`), every public class method of a Markets row class runs through the
  Markets API (`POST /api/v1/rows/{resource}/{operation}/`). The client discovers the FastAPI
  release named `api` of the `MainSequenceMarkets` repository in the caller's Environment and
  authenticates with its release token.
- Since 3.0.1, any workload whose workflow grants it `reader` on the `MainSequenceMarkets` branch
  may write registries through the API. Each write records the acting identity.
- Provider-owned instances for every time series the portfolio engine writes: values, weights,
  signal weights, rebalance state, calendar events and event ledger. There is also a generic
  `msm.storage_instances.configured_time_index_instance` for any other Markets time-index storage.
- `PortfolioDatasets.register/reconcile/get` through the remote backend.
- `AccountHoldingsSnapshots.publish` and `AssetSnapshots.publish`, so an application needs no grant
  on those tables.
- Set-based row calls under both backends: `upsert_many`, `count`, and `filter` with `order_by`,
  `offset`, `__in` and range bounds.
- Series-move tooling to copy existing history into provider instances: `msm series move|rollback`,
  `PortfolioSeriesMove`, `SignalSeriesMove`.
- Under the remote backend, `start_engine` no longer attaches a Markets table that is only a
  foreign-key target of a provider's table.

Not shipped: the separate `ms-markets-contracts` package. A consumer still installs `ms-markets`
(with QuantLib), even though it uses no table grant. Per-service ownership and Team scoping in the
Markets API are also still open.

## 2. What the checks found

| Check | Result |
| --- | --- |
| Hunch tests on 3.0.1 | 92 passed, 2 skipped, 1 failed, with 12 deprecation warnings |
| The failure | `hunch.compat` looks up `PortfoliosDataNode` on the renamed module. Old class names resolve only from the old import paths, so the lookup raises `AttributeError`. `start_markets_engine` installs the shims, so every Hunch process fails to start on 3.x until the shim is rewritten |
| `msm rename-preflight scan src tests` | 30 pre-3.0 names in 7 files: `compat.py`, `funding/ledger.py`, `instruments/services.py`, `market_data`, `portfolios/graph.py`, `portfolios/signal.py`, `runtime.py`, plus `tests/test_compat.py`. All are import paths and class names, none are UID field names, and no silent-default findings |
| Remote-dispatch registry | 34 resources. It covers every registry Hunch writes: Asset, AssetType, OpenFigiDetails, AssetCategory (with `replace_memberships`), AssetSnapshots, Calendar (with `create_from_pandas_calendar`), Account, AccountHoldingsSet, AccountHoldingsSnapshots, AccountAllocationModel, AccountTargetAllocation, PositionSet, VirtualFund, VirtualFundHoldingsSet, OrderManager (with `create_batch`), Portfolio, SignalMetadata, PortfolioDatasets |
| Remote ownership rule | `is_markets_owned` reads the table's catalog namespace. Hunch's tables are registered in `mainsequence.markets`, so under the remote backend they would be dispatched to the Markets API, which has no such resources, and every Hunch row call would fail. The namespace move is a hard prerequisite of the remote backend |
| Hosted Markets | Deployed today: 3.0.1 in Production (`c7cf0a1`) and `d629e77` in development. Both databases are at revision `0022`, so a 3.x project may now run in either Environment |
| Hosted Hunch | Still on 2.2.12 in both Environments. 2.2.12 writes `Portfolio` and `Account` rows through the old columns, so Hunch is now one of the 2.x writers that block Markets 3.1.0 |
| Shim 3 (per-portfolio progress fallback) | The bug is still in 3.x: `PortfolioRebalance._latest_transition_time_index_value` still falls back to the table-wide `max_time_index_value`. It still matters with Hunch-owned instances, because all of a provider's takes share one instance. The shim must be kept under the new names and reported upstream |
| Shims 1 and 2 (SQLite UUID binds, calendar search) | Under the remote backend those code paths run inside the Markets API, not in Hunch, so Hunch drops them. A local Markets API on SQLite would hit the same bugs; that is upstream's to fix |
| Dependencies | 3.0.1 requires `mainsequence-metatable>=0.1.57`, while Hunch declares `>=0.1.51`. `pandas-market-calendars` comes with the `portfolios` extra, so keep `ms-markets[portfolios]` (Hunch imports it and should declare it directly) |

Not verified: the identity-rotation report (`msm rename-preflight rotation`) and a local build on
3.x. Both need a runtime attached to a database at revision `0022`, and the local MetaTables
database is still at `0020`. Getting there means running
`metatables --local migrations upgrade --provider msm_migrations:migration head` with 3.x
installed, a schema change I did not make. The rotation expectations below follow the upgrade
guide's stated rules.

## 3. Every Hunch touchpoint under 3.x

| Hunch code | Today (2.2.12) | Under 3.x and the boundary | Status |
| --- | --- | --- | --- |
| 11 product tables (`hunch.metatables` mixins) | Registered in `mainsequence.markets` | Declare `__metatable_namespace__ = "hunch"`; FKs to core by physical name and `uid` (`msm.storage_instances.markets_reference_table`) | Hunch work; prerequisite of everything below |
| Instruments: Asset, AssetType, OpenFigiDetails, AssetSnapshot, AssetCategory | Direct writes | Same calls under the remote backend (`Asset.upsert_many`, `OpenFigiDetails.upsert_many`, `AssetSnapshots.publish`, `AssetCategory.replace_memberships`) | Ready |
| XNYS calendar | `Calendar.create_from_pandas_calendar` | Same call, remote. It should find the shared calendar first | Ready |
| Portfolio per take, pointer updates | `Portfolio.upsert`, `update_pointers=True` | Same calls, remote. Pointers move to the renamed `*_table_update_uid` columns | Ready |
| Signal metadata and weights | `SignalWeights` writes core tables | `SignalMetadata` remote; weights into `configured_signal_weights_storage` in `hunch` | Ready |
| Portfolio engine outputs | Core values, weights, rebalance state, calendar events | `configured_portfolios_storage`, `..._weights_`, `..._rebalance_state_`, `..._calendar_events_` (plus the event ledger if used); bound with `output_table=`, `weights_output_table=`, `rebalance_output_table=`; then `PortfolioDatasets.register` and `.reconcile` | Ready |
| Daily bars | `HunchDailyBars` into core `ExternalPricesTS` | `configured_time_index_instance(ExternalPricesStorage, instance_key="hunch", namespace="hunch", storage_app="hunch", base=...)`, or Alpaca's bars by uid. The valuation source is already a `TimeIndexTableRef` | Ready |
| Portfolio reads | Compiled SQL over core tables | `MarketsClient.portfolio_values/portfolio_weights`, or Hunch reading its own instances by uid | Ready |
| Funding target | AllocationModel, TargetAllocation, PositionSet rows plus a `TargetPositions` updater into core `TargetPositionsTS` | Rows remote. `TargetPositionsTS` has no remote publish; `POST /account/{uid}/add-target-positions/` exists but creates one default allocation per account | Gap: decision 3 |
| Fund state | `VirtualFund`, `VirtualFundHoldingsSet` rows plus a `VirtualFundHoldings` updater into core `VirtualFundHoldingsTS` | Rows remote. Holdings have no remote publish (the allocate helper takes an updater and is not dispatched); a Hunch-owned instance via `configured_time_index_instance` would be invisible to Markets' by-fund views | Gap: decision 3 |
| Execution ledger | `OrderManager` rows plus `Orders` and `Trades` into core tables | The executing connector owns it. The Alpaca connector's execution capability (merged 2026-10-26) writes its own ledger | Hunch stops writing |
| Simulated venue | Account rows, holdings updater, orders and trades | `Account.upsert` and `AccountHoldingsSnapshots.publish` remote; its own ledger in `hunch`, or retire it for Alpaca paper accounts | Ready |
| `msm.api.http` contracts | Collections, frames, errors | Unchanged; tests pass | Ready |
| `hunch.compat` | Three shims | Shim 3 rewritten for `PortfoliosUpdater` and kept in producer Jobs; shims 1 and 2 dropped | Hunch work, blocking on 3.0 |
| `hunch.runtime` | Attaches 61 models in every process | API: remote backend, attaches only Hunch's tables. Producer Jobs: runtime backend for Hunch's instances, remote for registries, in the same process | Ready after the namespace move |

Compared with the 2026-10-26 draft, the gaps it listed against ms-markets are closed. That covers
Portfolio and Asset writes, VirtualFund and OrderManager writes, instance factories for every engine
output, bars instances, the client, and the deployment of step 1. What remains is funding facts (two
time series without a remote publish), the progress-fallback bug, and requester forwarding.

## 4. Breaking points and ordering constraints

1. **Startup break on 3.0.** `hunch.compat` fails at engine start. It is the only change Hunch
   cannot defer past the dependency bump.
2. **4.0 removes the old names.** The 30 scanned names must move before Hunch accepts 4.x.
   Renaming them now costs nothing and keeps CI clean (`msm rename-preflight scan` exits 1 while any
   remain, so it can gate the build).
3. **Identity rotation, once.** `HunchDailyBars` uses an ms-markets configuration class directly
   (`AssetIndexedDataNodeConfiguration`). The portfolio graph uses ms-markets updaters directly
   (`PortfolioCalendarEvents`, `PortfolioRebalance`, `PortfolioWeights`, `PortfoliosUpdater`). All
   of them get a new `update_hash` on their first 3.x run and continue from their output table's last
   observation; the old `TimeIndexTableUpdate` records keep the history, and portfolios rewrite their
   pointer columns on the next run. `HunchBasketSignal` has its own configuration class, so its
   update hash should stay, and its `signal_uid` stays either way. Moving the engine to Hunch-owned
   instances (section 5) creates new identities anyway, so the two changes are best done together.
4. **Environment order.** A 3.x Hunch may run only where revision `0022` is applied, which is now
   true in both hosted Environments but not in the local database. Hunch on 2.2.12 blocks Markets
   3.1.0. Hunch must reach at least 3.1 before Markets ships 4.0, and at least 4.0 before 4.1, after
   which every 3.x model fails because it still maps the dropped columns. The branches for 3.1, 4.0
   and 4.1 already exist, so this is a near-term schedule, not a theoretical one.
5. **The remote backend needs the namespace move.** Section 2 explains why.
6. **One backend choice per process.** `MSM_API_BACKEND=remote` is process-wide for Markets-owned
   rows. A producer Job can write its own instances with MetaTables and Markets registries through
   the API in the same process, but no process may use the runtime backend for Markets tables once
   Hunch drops its grants on `mainsequence.markets`.
7. **Local development.** Under the remote backend the local stack needs a Markets API. The
   ms-markets checkout ships one (`api/main.py`), started on loopback against the local MetaTables
   and selected with `MARKETS_API_URL`. The local database must first move to revision `0022`.

## 5. Target shape

1. **Hunch API.** Remote backend for every Markets row; owns the `hunch` namespace; attaches only its
   own tables at startup, which also removes the cold-start problem. It reads portfolio frames
   through `MarketsClient` or its own instances.
2. **Hunch producer Jobs** (take build, refresh, daily review). They run the engine bound to
   Hunch-owned instances in `hunch` (values, weights, signal weights, rebalance state, calendar
   events, bars), create Portfolio, SignalMetadata and Calendar rows through the remote backend,
   register the instances with `PortfolioDatasets.register` on the first build, and reconcile after
   every run. Shim 3 stays here.
3. **Venues.** Connectors own accounts, holdings and the execution ledger. Hunch links accounts in
   its own table, reads them through `Account.get_many_by_unique_identifier` or the by-uid route
   with `include=` of the connector sidecar, and reads holdings through
   `AccountHoldingsSnapshots.get`.

Grants in the end state:

| Principal | Grant |
| --- | --- |
| Hunch Team (Migrations `editor`; API and Jobs `data_writer`) | `hunch` namespace only |
| Hunch API and Jobs (workflow) | `access.branches: [{repository: MainSequenceMarkets, policy: reader}]` |
| Markets workload | `data_viewer` on Hunch's portfolio and signal instances (catalog reads and reconcile) and on `hunch__portfolio` (sidecar hydration) |
| Hunch, on `mainsequence.markets` | nothing; revoke the grants made on 2026-10-25 and 26 |

Identity: the client authenticates with the Hunch workload's release token, so Markets records
Hunch as the actor. Neither the 3.0 client nor Hunch's API resource offers requester forwarding
today, so person-level authorization of registry writes stays inside Hunch.

## 6. Plan

**U1: upgrade to 3.x, behaviour unchanged.** Do this now; it unblocks Markets 3.1.0.

1. Require `ms-markets[portfolios]>=3,<4` and `mainsequence-metatable>=0.1.57,<0.2`, declare
   `pandas-market-calendars` directly, regenerate `uv.lock` and `requirements.txt`.
2. Apply the 30 renames and rewrite `hunch.compat` shim 3 for `PortfoliosUpdater`. Add
   `msm rename-preflight scan src tests` to the validation commands.
3. Upgrade the local MetaTables to revision `0022`. Run the suite and the runtime-gated tests and
   the funded loop locally.
4. Deploy to development, then Production. Both databases are already at `0022`.

**U2: the boundary.** Hunch-only work; nothing waits on ms-markets except decision 3.

1. Move the Hunch tables to the `hunch` namespace. Hosted data is one profile per Environment, so a
   recreate is simpler than a namespace move. Reference core tables by physical name and `uid`.
2. Declare the Hunch time-series instances and bind the engine and bars to them; register and
   reconcile them through `PortfolioDatasets`. Hosted has no take data, so nothing moves; locally,
   `msm series move` can carry the existing takes over, or they can be rebuilt.
3. Switch the API and Jobs to the remote backend, split the runtime per role, and add
   `MainSequenceMarkets` branch access to the workflow.
4. Stop writing the execution ledger. Route the simulated venue through `Account.upsert` and
   `AccountHoldingsSnapshots.publish`. Implement decision 3 for the fund state and targets.
5. Add a loopback Markets API to `scripts/dev_stack.sh`.
6. Revoke every Hunch grant on `mainsequence.markets` in both Environments, and grant the Markets
   workload `data_viewer` on Hunch's instances.

**U3: follow the column releases.** Move to 3.1 when Markets releases it and to 4.0 before Markets
ships 4.1. With the scan clean after U1, these are dependency bumps.

## 7. Decisions to make

1. **Instrument identity.** The remote backend now lets Hunch keep FIGI-keyed canonical Assets
   (`Asset.upsert_many` and `OpenFigiDetails.upsert_many` through the API), so the 2026-10-26 blocker
   is gone. The open choice is whether Hunch remains the creator of those assets or adopts the assets
   the connectors register.
2. **Price source.** A Hunch-owned bars instance (synthetic locally), or Alpaca's bars read by uid
   with a `data_viewer` grant from the Alpaca Team.
3. **Fund state and targets.** Three options:
   - ask Markets for remote publish calls for `TargetPositionsTS` and `VirtualFundHoldingsTS`, like
     `AccountHoldingsSnapshots.publish`, plus a per-take target allocation;
   - keep each take's slice of the account in Hunch-owned tables, which Markets' by-fund views then
     do not show;
   - keep target positions only through `add-target-positions`, with one allocation per account.
4. **Upstream reports.** Report the per-portfolio progress fallback (shim 3) and the SQLite UUID bind
   issues to ms-markets with the Hunch reproduction from ADR 0002.
