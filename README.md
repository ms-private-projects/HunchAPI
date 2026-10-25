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
  profiles/              # HunchUserProfile, HunchUserProfileAccount (linked venue accounts)
  takes/                 # HunchTake
  portfolios/            # HunchPortfolio (ms-markets Portfolio extension) and its services
  migrations/            # `hunch.migrations:migration` provider, schema gate, revisions
  api/app/               # routers, services, schemas, identity, errors, capabilities, mcp_server
  agent_tools.py         # the tool catalog the API serves at /mcp
  runtime.py             # the single msm.start_engine per process
src/jobs/                # Job launchers run by path (not in the wheel)
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

## Run the API locally

Every request needs a caller the Main Sequence SDK request identity verifies. Sign in once with the
SDK CLI, then send your session's token:

```bash
mainsequence login
uv run uvicorn api.app.main:app --host 127.0.0.1 --port 8001
```

```bash
curl -H "Authorization: Bearer $(.venv/bin/mainsequence auth token)" \
  http://127.0.0.1:8001/v1/project-state/capabilities
```

The API attaches the ms-markets runtime at startup, so the MetaTables must be migrated first.

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

Phase 0 of the plan: dependencies on SDK 9, ms-markets 2.2 and ms-tau-sdk; the four foundation
tables with their first migration; the API with project state and the MCP server; the Agent with
one published skill; the workflow. Takes cannot be created, built, funded or traded yet.
