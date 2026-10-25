# ADR 0001: Phase 0 foundation

- **Status:** Accepted
- **Date:** 2026-10-25
- **Scope:** Dependencies, package layout, the first four tables, the API and Agent skeleton

## Context

The plan in `docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md` fixes five
decisions: connectors are called deterministically by Hunch services, portfolios are
`HunchPortfolio` rows extending ms-markets, `HunchUserProfile` is the Hunch user and not an
ms-markets account, Hunch owns execution logic but delegates trades to the connected venue API, and
there is exactly one agent. This repository was a scaffold on SDK 8.1.10, which ms-markets 2.x does
not support.

## Decisions

1. **Dependencies.** `mainsequence[mcp]>=9.0.30,<10`, `mainsequence-metatable>=0.1.51,<0.2`,
   `ms-markets[portfolios]>=2.2.11,<3`, `ms-tau-sdk>=2.0.23,<3`, managed with `uv` and exported to
   `requirements.txt` for the deployment image, as the Alpaca connector does.
2. **Layout.** One wheel package `hunch` under `src/`, capability packages (`profiles`, `takes`,
   `portfolios`), `api/app` and `api/agent` entry points outside the wheel, `src/jobs` launchers
   run by path, workflow declarations under `.mainsequence/workflows/`.
3. **Namespace and names.** Project tables use the `hunch` app segment (`hunch__<table>`), the
   `hunch` MetaTables migration namespace and the catalog key `package="hunch"`. These are frozen.
4. **Extension by composition.** ms-markets extends models with one-to-one detail tables whose
   primary key is the base row's uid; there is no SQLAlchemy inheritance. `HunchPortfolioTable`
   therefore has `portfolio_uid` as primary key and foreign key to `PortfolioTable.uid`
   (`CASCADE`), and a `HunchPortfolio` row API creates both rows in one service. Portfolio time
   series stay keyed on the base `Portfolio.unique_identifier`.
5. **Ownership direction.** `HunchPortfolioTable.take_uid` references the take (unique, `CASCADE`);
   the take does not reference the portfolio, which avoids a circular foreign key. A take has at
   most one current portfolio.
6. **Linked accounts.** `HunchUserProfileAccountTable.account_uid` references the connector-created
   `AccountTable.uid` with `RESTRICT` and a unique index: one connector account links to one Hunch
   user, and the link must be removed in Hunch before the account row could ever be deleted.
   `user_uid` columns are strings (the Main Sequence user UID), as in the connectors.
7. **Fork lineage.** `forked_from_take_uid` and `origin_take_uid` are indexed take UIDs without
   a database foreign key. The ms-markets runtime orders MetaTables by their foreign-key graph and
   rejects a self-referencing table as a dependency cycle (`resolve_markets_meta_table_models`),
   so the take services validate the lineage targets instead. A separate lineage table was
   considered and rejected as an extra join for two nullable columns.
8. **Migrations.** Provider `hunch.migrations:migration` with its own Alembic version table
   `hunch__alembic_version`; revision 0001 creates the four tables with the constraint names the
   models derive. The gate `skip_if_schema_behind` waits for both `msm_migrations:migration` and
   the Hunch provider. Hosted schema changes come only from the `hunch-migrate` Job.
9. **API and MCP.** `create_app()` mirrors the Alpaca connector: exception handlers, routers,
   `install_request_identity`, `install_mcp` with the `hunch` MCP server serving the
   `hunch.agent_tools` catalog and the skills under `.agents/skills/mcp_tools`, CORS last.
10. **Agent.** `api/agent/main.py` is `create_app()`; `.tau/SYSTEM.md` carries the runtime role;
    the workflow declares `acts_for_requester: true`, `mcp_applications: [{resource: hunch}]` and
    both TAU exclusions, so the Agent's only tools are the Hunch API's.

## Observations from the installed versions

- `uv` resolved mainsequence 9.0.32, ms-markets 2.2.12, mainsequence-metatable 0.1.56 and
  ms-tau-sdk 2.0.26, all inside the declared ranges.
- Since ms-tau-sdk 2.0.24 the hosted runtime admits project resources from `.tau` alone;
  `.agents/skills` is a development resource. The published skills under
  `.agents/skills/mcp_tools` therefore reach the Agent only through the API's MCP
  (`hunch__list_resources`, `hunch__read_resource`), which is the intended path. The hosted tool
  catalog test confirms the Agent keeps exactly the skill-scoped `read`, the four `hunch__*` tools
  and the two A2A task controls.
- After `install_mcp`, `app.routes` no longer enumerates the API routes; tests enumerate the
  routers `create_app` mounts instead.

## Consequences

- Phase 1 adds the take build pipeline, the `FixedWeights` signal and the portfolio graph on top
  of these tables without changing their keys.
- The connector execution capability and the typed connector clients (`hunch/connectors`) are
  Phase 2 work and need their own ADRs here and in the connector repositories.
- The Agent's provider and model in the workflow file are placeholders to confirm before the first
  push.
