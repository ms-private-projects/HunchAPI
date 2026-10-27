# ADR 0005: Hunch on ms-markets 3.x

- **Status:** Accepted
- **Date:** 2026-10-27
- **Scope:** The ms-markets dependency range, the ADR 0048 names, the compat shims, the one-time
  `update_hash` rotation, and the order of the ms-markets column releases (plan
  `docs/planning/0002-hunch-under-the-markets-api-boundary.md`, step U1)

## Context

ms-markets 3.0 renames its time-index vocabulary (its ADR 0048): `msm.data_nodes`,
`msm_portfolios.data_nodes` and `msm_pricing.data_nodes` become `*.time_index`, and `*DataNode`
classes become `*Updater`. The old paths warn through 3.x and disappear in 4.0. The hosted
databases of both Environments were migrated to ms-markets revision `0022` by the Markets
deployment while Hunch still ran 2.2.12. Markets cannot release 3.1.0 (revision `0023`) while any
2.x writer remains, so Hunch on 2.x blocked it.

## Decisions

1. **Dependencies.** `ms-markets[portfolios]>=3.0.1,<4` (3.0.2 resolved) and
   `mainsequence-metatable>=0.1.57,<0.2` (0.1.59 resolved). Hunch imports
   `pandas_market_calendars` itself, so it declares `pandas-market-calendars>=5.4.0` directly
   instead of relying on the extra.
2. **Names.** Every import uses the 3.0 path and class name (`AssetIndexedUpdater`,
   `AssetIndexedUpdaterConfiguration`, `PortfoliosUpdater`, `msm.time_index.*`,
   `msm_portfolios.time_index.*`, `msm_pricing.time_index.*`). `msm rename-preflight scan src tests
   api scripts` is part of validation and exits 1 on any pre-3.0 name, so 4.0 stays a dependency
   bump.
3. **Shims.** The three `hunch.compat` shims were re-checked on 3.0.2 and all are still needed: the
   calendar-session search still passes `calendar_uid` as a string, several call sites still bind
   UUID strings (SQLite only), and the rebalance, weights and values updaters still fall back to the
   table-wide latest time index for a portfolio with no progress entry. The third shim now patches
   `msm_portfolios.time_index.portfolios.PortfoliosUpdater`; its behaviour is unchanged.
4. **Rotation.** Every take's rebalance, weights and values updaters get a new MetaTables
   `update_hash` on their first 3.x run, as ADR 0048 states. `HunchDailyBars` keeps its hash: it is
   a Hunch class that takes no constructor arguments. Signals, portfolio configuration hashes and
   strategy revisions keep their identities. Locally, refreshing the five
   takes built on 2.2.12 rotated all three updaters of each, continued from the last stored value,
   and left every earlier value unchanged with no duplicate time index. Run history in MetaTables
   splits at the upgrade; nothing in Hunch reads it.
5. **Release order.** Hunch deploys 3.x to development, then Production. Once both run 3.x, Markets
   may ship 3.1.0. Hunch moves to 4.0 before Markets ships 4.1.0 (revision `0025`), which drops the
   old columns that every 3.x model still maps.

## Consequences

- No Hunch schema change: the Hunch provider stays at `0003` and `hunch-migrate` only re-checks the
  ms-markets head, which both Environments already have.
- The local MetaTables needs `metatables --local migrations upgrade --provider
  msm_migrations:migration head` once (to `0022`); the README steps already run it.
- The boundary work (Hunch namespace, remote backend, registries) is U2 and is not part of this
  change.
