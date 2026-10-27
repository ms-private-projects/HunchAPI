# AGENTS.md

## CodeRepository-Specific Instructions

This repository is the Hunch backend for Main Sequence: takes (theses), Hunch portfolios built from
them, the Hunch users and their linked brokerage accounts, and later funding, proposals and
execution. The installable `hunch` package (`src/`) backs the FastAPI application with its MCP
server, the one Hunch Agent and the workflow Jobs. The plan is
`docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md`; decisions are ADRs under
`docs/adrs/`.

Repository rules:

- Every market primitive is an ms-markets table (`msm`, `msm_portfolios`): assets, accounts,
  holdings, signals, portfolios, orders, trades. Never add a parallel market table. Hunch tables
  live in the `hunch` namespace, use `hunch.metatables` mixins, and reference ms-markets rows by
  foreign key. `HunchPortfolio` extends `Portfolio` one-to-one (`portfolio_uid` is its primary key);
  never write a bare `Portfolio` for a take.
- `HunchUserProfile` is the Hunch user, keyed by the Main Sequence user UID. It is not an ms-markets
  `Account`; `HunchUserProfileAccount` links it to the `Account` rows the venue connectors create.
  Authorisation is decided on Hunch tables (`owner_user_uid`, `visibility`), never on ms-markets
  rows alone.
- Connectors (`alpaca-connectors`, `interactivebrokersbackend`) are the brokerage boundary. Hunch
  services and Jobs call their REST APIs through the typed clients in `hunch.connectors`
  (`VenueConnector` port; `SimulatedConnector` for local development and tests), deterministically.
  No broker credential, Secret name or provider client belongs in this repository. The Agent and
  the model never call a connector; `hunch.funding.services` is the only module that submits
  orders, and only from an approved proposal, an autopilot check that passed, or a withdrawal.
- Hunch owns portfolio construction and execution logic (targets, proposals, approvals, autopilot
  limits) and delegates the exact trades to the connected venue API.
- Frozen identities: the migration provider `hunch.migrations:migration` keeps catalog key
  `package="hunch"` and namespace `hunch`. Never change either.
- Only `.mainsequence/workflows/*.yaml` creates Jobs and sets their schedules. `src/jobs/`
  launchers run by path; every launcher except the migration Job starts with
  `skip_if_schema_behind`. Hosted schema changes come only from the `hunch-migrate` Job; never run
  `metatables migrations upgrade` against a hosted environment. Revisions add first and drop later.
- Each process attaches the ms-markets runtime once through `hunch.runtime.start_markets_engine`.
- Money moves only through `HunchRebalanceProposal` rows: fund, rebalance and withdraw create a
  proposal; approval mode needs the person's decision, autopilot needs `autopilot_check` to pass.
  Ownership of a venue account is decided by `HunchUserProfileAccount` alone.
- The ms-markets shims in `hunch.compat` are documented in ADRs 0002 and 0005; remove each when
  ms-markets fixes the call site, never add behaviour there.

FastAPI surface:

- Routes stay thin over `hunch.api.app.services`, one `/v1/<capability>` group per capability, on
  the `msm.api.http` Command Center contracts.
- `create_app()` installs `install_request_identity` once after the routers, then `install_mcp`.
  Routes and tools read the caller only through `hunch.api.app.identity`; no header,
  `request.state` or process-user fallback. No route is public. Call a local API with
  `Authorization: Bearer $(mainsequence auth token)`.
- Ownership follows the acting user: the requester on an Agent's call, otherwise the caller, never
  both. No UID comes from a body, header or tool argument.
- The workflow key `hunch` is the Agent's MCP tool prefix (`^[a-z][a-z0-9_]{0,39}$`).
  `GET /v1/project-state/configuration` returns `agent_uid` and `organization_environment_uid`
  from `api.app.site_agent`; never put either in a site build.

Project-to-agent boundary:

- One Harness Agent: `.agents/agent_card.json`, the skills under `.agents/skills/mcp_tools/`, and
  the tools `hunch.api.app.mcp_server` serves from `hunch.agent_tools`. Add no second agent, no
  separate agent runtime and no `.tau/extensions` tools.
- The API publishes only `.agents/skills/mcp_tools/` through `skills_extension`. Never publish the
  whole `.agents/skills/` tree or copy skills into `.tau/skills`.
- The `harness_agent` in `hunch-api.yaml` serves `api/agent/main.py` (`ms_tau_sdk.create_app()`)
  with `acts_for_requester: true` and `mcp_applications: [{resource: hunch}]`. It deploys after the
  API, the two hold `user` on each other, and `TAU_EXCLUDE_BASE_TOOLS` and
  `TAU_EXCLUDE_MAINSEQUENCE_MCP` stay `true`.
- Tool invariants: results and errors never quote arguments; deletes and archives need exact
  `DELETE <uid>`; long work submits Jobs and returns JobRun UIDs; reads run in parallel and
  mutations in sequence; no tool takes credentials, UIDs of persons or an Environment selector.

Validate with `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check api src tests`,
`.venv/bin/ruff format --check api src tests` and `.venv/bin/msm rename-preflight scan src tests api
scripts` (ms-markets 3.x names only; ADR 0005).

## The Hunch Agent

This repository also deploys the Hunch Agent. Its runtime instructions are `.tau/SYSTEM.md`; this
file is for developers. Tau loads this file into the Agent's context too, so keep it short and never
put runtime-only instructions here.
