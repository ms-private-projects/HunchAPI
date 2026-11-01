# hunchapi

Hunch turns a person's investment thesis, their *take*, into a portfolio of US-listed equities that
Hunch builds, monitors and, when the person authorises it, trades through their own brokerage
account at Alpaca or Interactive Brokers. This repository is the backend: the Main Sequence FastAPI
application, the one Hunch Agent (a TAU Harness Agent) and the Jobs.

The product analysis and the build plan are in
[docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md](docs/planning/0001-supertake-analysis-and-hunch-build-proposal.md).
Architecture decisions live under [docs/adrs/](docs/adrs/).

## Principles

- **ms-markets is the market ledger, reached through the Markets API.** Assets, accounts,
  calendars, portfolios, signals and funds are Markets registries that Hunch reads and writes only
  through the Markets API (ADR 0006). The time series Hunch produces live in Hunch's own instances
  of the ms-markets contracts (`hunch.series`), which Markets catalogues. Hunch tables reference
  Markets rows by foreign key; `HunchPortfolio` extends the ms-markets `Portfolio` one-to-one.
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
  market_data/           # HunchDailyBars (Hunch's ExternalPricesTS instance) and the bar providers
  research/              # thesis -> candidates (recorded inference or heuristic) -> guardrails
  takes/                 # HunchTake, HunchTakeRevision and the take lifecycle
  portfolios/            # HunchPortfolio, the basket signal, the ms-markets portfolio graph, builds
  connectors/            # the venue connector port: Alpaca and IBKR HTTP clients, simulated venue
  funding/               # HunchFunding, HunchRebalanceProposal, fund and target ledger, execution
  reviews/               # HunchDailyReview and the daily review
  community/             # leaderboard snapshots and notifications
  channels/              # email digest: composition, delivery, outbox/platform/smtp senders
  operations/            # build/review orchestration (inline locally, Jobs hosted)
  migrations/            # `hunch.migrations:migration`, schema gate, namespace move, 0001-0004
  series.py              # Hunch's instances of the ms-markets time-series contracts
  api/app/               # routers, services, schemas, identity, errors, capabilities, mcp_server
  agent_tools.py         # the tool catalog the API serves at /mcp
  compat.py              # shims for ms-markets and SQLite (see ADRs 0002, 0005 and 0006)
  runtime.py             # Markets API backend and the single engine start per process
src/jobs/                # Job launchers run by path (not in the wheel)
scripts/dev_stack.sh     # local stack: MetaTables, Markets API, loopback API, local Tau, the site
scripts/local_markets_api.py  # loopback Markets API, run with the ms-markets checkout's interpreter
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
.venv/bin/msm rename-preflight scan src tests api scripts   # exits 1 on any pre-3.0 ms-markets name
```

## Run everything locally

`scripts/dev_stack.sh` starts the local MetaTables API (SQLite), a loopback Markets API on
127.0.0.1:8603 (the sibling `mainsequencemarkets-*` checkout, run with its own `.venv`, which
`uv sync --all-extras` creates there), the loopback Hunch API on 127.0.0.1:8601 (it presents your
SDK sign-in on every request, so the browser and `curl` need no header), the local Tau runtime of
the Hunch Agent on 127.0.0.1:8602 and the Command Center site on 127.0.0.1:5601 (the sibling
`hunch` repository). Hunch reaches every Markets registry through the Markets API
(`MARKETS_API_URL`); scripts and tests run outside the stack need the same variable. Prepare the
runtime once:

```bash
mainsequence login
.venv/bin/metatables init --local && .venv/bin/metatables serve --local --no-open-browser &
.venv/bin/metatables --local migrations upgrade --provider msm_migrations:migration head
.venv/bin/python scripts/local_prepare_runtime.py
PYTHONPATH=src .venv/bin/python -m hunch.migrations.namespace_move --local
.venv/bin/metatables --local migrations upgrade --provider hunch.migrations:migration head
```

```bash
scripts/dev_stack.sh all      # or: markets | api | tau | site
```

Local defaults: builds run inline with heuristic research (`HUNCH_RESEARCH_MODE`), and the venue
connectors are simulated (`HUNCH_CONNECTOR_MODE=simulated`: a paper venue inside Hunch that fills
orders at the last stored close and keeps its records as a connector does, Markets rows through
the Markets API and its holdings and fills in its own instances). Set
`HUNCH_CONNECTOR_MODE=live` with `HUNCH_ALPACA_CONNECTOR_URL` / `HUNCH_IBKR_CONNECTOR_URL` to call
the connector releases, and `HUNCH_RESEARCH_MODE=inference` with `HUNCH_INFERENCE_ENVIRONMENT_UID`
to research through recorded inference (ADR 0002 explains the local finding).

Model roles (ADR 0007): in `inference` mode each kind of recorded model call selects its own
provider, model, thinking level and credential, so one deployment mixes models: `research`
(builds), `review` (daily reviews) and `analysis` (the analysis-only tools, such as the thesis
critique). Every role starts from `HUNCH_INFERENCE_PROVIDER`, `HUNCH_INFERENCE_MODEL`,
`HUNCH_INFERENCE_THINKING` and `HUNCH_INFERENCE_CREDENTIAL` (a configured credential's
`custom_id`); `HUNCH_MODEL_<ROLE>` overrides any of them with space-separated `key=value` pairs,
for example `HUNCH_MODEL_ANALYSIS="provider=openrouter model=anthropic/claude-haiku-4.5
thinking=low"`. The Hunch Agent's own conversation model is the Harness Agent declaration in the
workflow file, not a role. `GET /v1/project-state/configuration` reports every role. The
scheduled review sweep (`run_hunch_daily_review.py --scheduled`) reviews in its own process by
default; with `HUNCH_REVIEW_DISPATCH=job` (the hosted dispatcher) it starts one review Job run per
active take, three at a time, so the reviews run on that Job's credential and in parallel.

Research sources: `HUNCH_RESEARCH_SOURCES` (default `quant`; add `finnhub` with
`HUNCH_FINNHUB_API_KEY` for news and fundamentals). Email digests: `HUNCH_EMAIL_SENDER` (`outbox`
locally, writes `.hunch-outbox/*.eml`; `platform` hosted), `HUNCH_SITE_URL` for links; run
`src/jobs/run_hunch_email_digest.py --scheduled` after opting in on the profile.

```bash
curl http://127.0.0.1:8601/v1/project-state/capabilities
curl -X POST http://127.0.0.1:8601/v1/profile/accounts/actions/link \
  -H 'content-type: application/json' -d '{"venue":"alpaca"}'
```

The hosted entry point `api.app.main:app` verifies the platform's caller assertion instead.

## Schema

The `hunch` MetaTables (the product tables and the series instances) live in the `hunch` namespace
and are applied only by this repository's provider. The ms-markets schema they reference is owned
by the ms-markets deployment. Tables catalogued before revision 0004 move to `hunch` in place
(`hunch.migrations.namespace_move`), which the `hunch-migrate` Job runs before every upgrade.

```bash
# local development database only; hosted environments run the hunch-migrate Job
metatables --local migrations upgrade --provider msm_migrations:migration head
PYTHONPATH=src .venv/bin/python -m hunch.migrations.namespace_move --local
metatables --local migrations upgrade --provider hunch.migrations:migration head
```

Workloads need `data_writer` (the Migrations Job `editor`) on the `hunch` namespace from its owner
and no role on `mainsequence.markets`; the workflow file declares the branch, MetaTables, Markets
API and Agent access (`docs/operations/hosted-deploy.md`).

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
§6.1); Interactive Brokers executes manually (ADR 0003). Phase 4 adds risk metrics, research
grounded in cited evidence (bar facts, Finnhub news and fundamentals) and the daily email digest;
inbound email replies wait on a platform channel (ADR 0004).
