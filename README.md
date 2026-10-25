# hunchapi

Hunch turns a person's investment thesis, their *take*, into a portfolio of US-listed equities that
Hunch builds, monitors and, when the person authorises it, trades through their own brokerage
account at Alpaca or Interactive Brokers. This repository is the backend: the Main Sequence FastAPI
application, the one Hunch Agent (a TAU Harness Agent) and the Jobs.

The product analysis and the build plan are in
[docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md](docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md).
Architecture decisions live under [docs/adrs/](docs/adrs/).

## Principles

- **ms-markets is the market ledger.** Assets, accounts, holdings, signals, portfolios, orders and
  trades live only in ms-markets tables. Hunch tables reference them by foreign key and add the
  product layer. `HunchPortfolio` extends the ms-markets `Portfolio` one-to-one.
- **Connectors are the brokerage boundary, called deterministically.** Hunch services and Jobs call
  the Alpaca and IBKR connector APIs through typed clients; the Agent and the model never call a
  connector. Hunch never holds a broker credential.
- **Hunch owns portfolio and execution logic; the connected venue API executes the trades.**
- **One agent.** The Hunch Agent converses and performs bounded actions through the API's MCP tools.
  Research, construction and the daily review are deterministic service code in Jobs.

## Repository layout

```text
api/app/main.py          # deployed FastAPI entry point (re-exports hunch.api.app.main:app)
api/agent/main.py        # the Hunch Agent: app = ms_tau_sdk.create_app()
src/hunch/               # the installable package
  profiles/              # HunchUserProfile, HunchUserProfileAccount, account linking (accounts.py)
  instruments/           # HunchInstrument universe (FIGI keyed) over ms-markets Assets
  market_data/           # HunchDailyBars (ExternalPricesTS) and the bar providers
  research/              # thesis -> candidates (recorded inference or heuristic) -> guardrails
  takes/                 # HunchTake, HunchTakeRevision and the take lifecycle
  portfolios/            # HunchPortfolio, the basket signal, the ms-markets portfolio graph, builds
  connectors/            # the venue connector port: Alpaca and IBKR HTTP clients, simulated venue
  funding/               # HunchFunding, HunchRebalanceProposal, ms-markets ledger, execution flow
  reviews/               # HunchDailyReview and the daily review
  community/             # leaderboard snapshots and notifications
  operations/            # build/review orchestration (inline locally, Jobs hosted)
  migrations/            # `hunch.migrations:migration` provider, schema gate, revisions 0001-0003
  api/app/               # routers, services, schemas, identity, errors, capabilities, mcp_server
  agent_tools.py         # the tool catalog the API serves at /mcp
  compat.py              # shims for ms-markets 2.2.12 (see ADR 0002)
  runtime.py             # the single msm.start_engine per process
src/jobs/                # Job launchers run by path (not in the wheel)
scripts/dev_stack.sh     # local stack: MetaTables, loopback API, local Tau, the site
.tau/SYSTEM.md           # the Agent's runtime instructions
.agents/                 # agent_card.json and the published skills (.agents/skills/mcp_tools)
.mainsequence/workflows/ # API, Agent and migration Job declarations (workflow API 3.0.0)
docs/                    # planning documents and ADRs
tests/
```

## Install

Python 3.13 and `uv`. Dependency ranges live in `pyproject.toml`; `uv.lock` records the
reproducible resolution and `requirements.txt` is exported from it for the deployment image.

```bash
uv sync
```

Refresh `requirements.txt` after changing dependencies:

```bash
uv export --locked --no-dev --no-hashes --format requirements-txt -o requirements.txt
```

## Validate

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check api src tests
.venv/bin/ruff format --check api src tests
```

## Run everything locally

`scripts/dev_stack.sh` starts the local MetaTables API (SQLite), the loopback Hunch API on
127.0.0.1:8601 (it presents your SDK sign-in on every request, so the browser and `curl` need no
header), the local Tau runtime of the Hunch Agent on 127.0.0.1:8602 and the Command Center site on
127.0.0.1:5601 (the sibling `hunch` repository). Prepare the runtime once:

```bash
mainsequence login
.venv/bin/metatables init --local && .venv/bin/metatables serve --local --no-open-browser &
.venv/bin/metatables --local migrations upgrade --provider msm_migrations:migration head
.venv/bin/python scripts/local_prepare_runtime.py
.venv/bin/metatables --local migrations upgrade --provider hunch.migrations:migration head
```

```bash
scripts/dev_stack.sh all      # or: api | tau | site
```

Local defaults: builds run inline with heuristic research (`HUNCH_RESEARCH_MODE`), and the venue
connectors are simulated (`HUNCH_CONNECTOR_MODE=simulated`: a paper venue inside Hunch that fills
orders at the last stored close and writes the same ms-markets rows a connector would). Set
`HUNCH_CONNECTOR_MODE=live` with `HUNCH_ALPACA_CONNECTOR_URL` / `HUNCH_IBKR_CONNECTOR_URL` to call
the connector releases, and `HUNCH_RESEARCH_MODE=inference` with `HUNCH_INFERENCE_ENVIRONMENT_UID`
to research through recorded inference (ADR 0002 explains the local finding).

```bash
curl http://127.0.0.1:8601/v1/project-state/capabilities
curl -X POST http://127.0.0.1:8601/v1/profile/accounts/actions/link \
  -H 'content-type: application/json' -d '{"venue":"alpaca"}'
```

The hosted entry point `api.app.main:app` verifies the platform's caller assertion instead.

## Schema

The `hunch` MetaTables live in the `hunch` namespace and are applied only by this repository's
provider. The ms-markets schema they reference is owned by the ms-markets deployment.

```bash
# local development database only; hosted environments run the hunch-migrate Job
metatables --local migrations upgrade --provider msm_migrations:migration head
metatables --local migrations upgrade --provider hunch.migrations:migration head
```

Workloads need `data_viewer` or `data_writer` on the `mainsequence.markets` namespace from its
owner; the workflow file declares the branch, MetaTables and Agent access.

## Deployment

`.mainsequence/workflows/hunch-api.yaml` declares the `hunch` FastAPI release (with `/mcp`), the
one `hunch-agent` Harness Agent (acting for the requester, tools from the `hunch` MCP only) and the
`hunch-migrate` Job that gates the API rollout. The Agent's provider and model are set there.

## Status

Phases 0 to 3 of the plan run locally end to end: a thesis becomes a built take with a basket, a
model portfolio and a performance record; it can be practiced, published, forked and ranked; a
linked account can fund it in approval or autopilot mode, proposals execute through the venue
connector (simulated locally), the daily review watches drift and the thesis, and notifications
report every step. Hosted execution waits for the Alpaca connector's execution capability (plan
§6.1); Interactive Brokers executes manually (ADR 0003). Email channels and external research
sources (phase 4) are not started.
