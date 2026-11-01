# Hunch: Supertake product analysis and build proposal

- **Status:** Proposal for discussion (2026-10-25)
- **Scope:** Replicate Supertake's functionality as "Hunch" on Main Sequence. Backend as a
  Main Sequence FastAPI application in this repository (`hunchapi`), the agent as a TAU Harness
  Agent built with `ms-tau-sdk`, every market primitive on `ms-markets`, brokerage execution in
  Alpaca or Interactive Brokers through the existing connector repositories.
- **Out of scope for this document:** the Command Center frontend (sibling `hunch` repository,
  currently an empty Vite scaffold). It is referenced where the backend contract depends on it.

---

## 1. What Supertake is

Sources: the USV announcement (2026-09-28), supertake.com, and launch coverage (see Appendix A).

### 1.1 Positioning

"AI that turns your ideas into investments." A user states a belief about the world in natural
language. AI agents turn it into a diversified portfolio of US-listed equities, place the trades in
the user's own brokerage account, manage it daily, and talk to the user about it. The product is
non-custodial (assets stay at the user's broker), invite-only, free during beta, and explicitly not
a registered investment adviser: the user is the one giving instructions, and displayed returns
"may be simulated or unaudited".

### 1.2 Vocabulary

| Term | Meaning in Supertake |
| --- | --- |
| **Take** | The user's thesis, stated in natural language ("humanoid robots are coming to every home"). It is the unit of identity, sharing and ranking. |
| **Portfolio** | The basket the agents build from a take and hold in the user's brokerage. One take, one portfolio. |
| **Agent(s)** | Research, construct, execute, monitor daily, rebalance on drift or new information, explain decisions, answer questions. |
| **Autopilot / Approval** | Two execution modes. Approval: the user signs off on every trade. Autopilot: the agents trade automatically, within limits. |
| **Practice Mode** | Builds the identical portfolio and runs the identical rebalancing logic, but sends no orders. Results are labelled simulated. |
| **Fork** | Any user copies a published take and invests in it immediately. The fork is an independent portfolio under the forker's control; the rationale travels with it and the leaderboard credits the origin. |
| **Leaderboard** | Public, continuously updated ranking of takes by return measured from each take's activation date. Practice takes are flagged as simulated. |
| **Agentic account** | A sub-account at the broker (Robinhood, Coinbase) that the agents are authorized to read positions from and send orders to. Access is OAuth-style and revocable. |

### 1.3 What a take contains

The public leaderboard shows the artefact the agents produce from a thesis. Every entry has:

- a title and author handle;
- a written rationale (the thesis and why these holdings express it);
- a basket described by roles, not only tickers: pure plays, "choke-point suppliers", "secondary
  enablers", sometimes an inverse or leveraged ETF as a hedge;
- weighting guidance: heavier and lighter sleeves, explicit avoidance of single-name
  concentration;
- a cash buffer (8 to 10 percent in the examples);
- a holding horizon (quarters to five-plus years);
- "what would change my mind" conditions, which the daily monitoring evaluates.

### 1.4 The user journey

1. Join (waitlist, sign in with X). Optionally start in Practice Mode.
2. Write a take.
3. Agents research it (companies, competitive dynamics, market cap, liquidity, history) and build
   a weighted basket with a cash buffer. The user sees rationale and weights.
4. Link a brokerage (OAuth-style). Choose Approval or Autopilot. Fund the take with an amount.
5. Agents place the orders.
6. Daily: the agents re-read the thesis against new information, check drift, and either propose a
   rebalance (Approval) or execute it (Autopilot). They send proactive status updates.
7. The user talks to each portfolio in the app or by email (iMessage and SMS planned): ask for
   explanations, request changes.
8. The user publishes the take. Others fork it. Both appear on the leaderboard with returns since
   activation.

### 1.5 Operating rules we must replicate

- One agent conversation per portfolio, with full context of that take.
- Non-custodial. Credentials and assets stay at the broker; access is revocable.
- Approval is the default; Autopilot is bounded by limits that the user can see.
- Practice and funded takes share one construction and rebalancing engine. Only order
  transmission differs.
- Returns are measured from activation, include rebalancing, and are labelled simulated when no
  money was invested.
- Forks keep attribution. Authors can edit or unpublish; forks become independent.
- Assets today: public US equities. Planned: crypto, derivatives, prediction markets.

### 1.6 Capability inventory derived from the product

| Capability | What it must do |
| --- | --- |
| Identity and tenancy | Users own takes, brokerage links, conversations, notifications. Public takes are readable by all. |
| Brokerage linking | Register a paper or live account per venue, prove the user owns it, revoke it. |
| Thesis capture | Store the take text, structured constraints (horizon, cash buffer, exclusions, risk appetite), and revisions. |
| Research | Turn a thesis into candidates with roles, evidence and risks. |
| Construction | Produce weights under deterministic guardrails (liquidity, concentration, tradability at the venue, cash buffer). |
| Model portfolio | Hold the weights as a time series, rebalance on a policy, compute NAV and returns from activation. |
| Funding and execution | Map weights to target quantities for a funded amount, generate orders, transmit, track fills, reconcile holdings. |
| Approval and Autopilot | Proposal objects with an explicit state machine; autopilot limits enforced server-side. |
| Daily review | Drift check, thesis check against new information, proposal or execution, status update. |
| Conversation | Per-take agent sessions with tools for reads and bounded writes. |
| Social | Publish, fork with lineage, leaderboard snapshots, disclaimers. |
| Notifications | In-app feed first; email later. |
| Practice mode | Same engine, no transmission, labelled. |

---

## 2. What we already have

### 2.1 ms-markets primitives Hunch will use

`ms-markets` 2.2.12 (`mainsequencemarkets` repository, `src/msm`, `src/msm_portfolios`). Everything
below is reused as-is; Hunch writes through the row APIs and DataNodes and never defines parallel
market tables.

| Hunch concept | ms-markets primitive | Notes |
| --- | --- | --- |
| Tradable instrument | `Asset`, `AssetType` (`equity`, `currency`), `OpenFigiAssetDetails`, `AssetSnapshotsTS` | `Asset.unique_identifier` is the join key of every time-indexed table. Connectors register provider-native identities (Alpaca UUID, `IBKR::<conid>`), so the same stock is a different `Asset` per venue (see 3.5). |
| Basket universe | `AssetCategory` + `AssetCategoryMembership` | One category per take revision ("HUNCH_TAKE_<uid>_R<n>") and one global "HUNCH_UNIVERSE" category for price coverage. |
| Brokerage account | `Account` (`is_paper`, `account_is_active`, `metadata_json`), `AccountHoldingsSet`, `AccountHoldingsTS` | Created and refreshed by the connectors. No owner column exists; Hunch owns the user-to-account link (3.4). |
| Cash | A `currency` Asset (`USD`) position row | No cash field exists on accounts; the connectors already model cash this way. |
| Take weights | `SignalMetadata` + `SignalWeightsTS` via `msm_portfolios.contrib.signals.FixedWeights` | One signal per take; each agent revision publishes a new observation of `AUIDWeight` rows. |
| Model portfolio | `Portfolio` (needs `calendar_uid`), `PortfolioMetadata`, `PortfolioWeightsTS`, `PortfolioRebalanceStateTS`, `PortfoliosTS` (`close`, `return_`), `PortfolioAnalyticsTS` | Hunch extends `Portfolio` one-to-one with its own `HunchPortfolio` table (3.4). The weight-return engine (`PortfoliosDataNode`) is the "take performance since activation" series for practice and funded takes alike. |
| Rebalance policy | `CalendarEventSignal` (NYSE regular session, market_open/close, every_session or weekly) or `ImmediateSignal` | Calendar events come from `PortfolioCalendarEvents` on an XNYS `Calendar` created with `Calendar.create_from_pandas_calendar`. |
| Prices | `InterpolatedPrices` over the Alpaca connector's daily bars table (`alpaca_stock_bars_1d_sip_all`) | Same source for every take regardless of execution venue (3.5). Portfolios require an explicit price source (ADR 0030/0031). |
| Several takes in one account | `VirtualFund` (`account_uid`, `target_portfolio_uid`), `VirtualFundHoldingsSet`, `VirtualFundHoldingsTS`, planner `plan_account_virtual_fund_allocations` / `apply_...` | A funded take is a virtual fund inside the user's agentic account. The planner needs a `ValuationResolver` that Hunch supplies from bars. |
| Account targets | `AccountAllocationModel`, `AccountTargetAllocation`, `PositionSet`, `TargetPositionsTS` (`target_type="portfolio"`) + `expand_portfolio_target_positions` | Records "this account targets these portfolios with these notionals"; the audit trail for what the executor was asked to reach. |
| Orders and fills | `OrderManager` (batch per proposal), `OrdersTS`, `OrderEventsTS`, `TradesTS` | Pass-through writers; the connector execution capability publishes them. `OrderManager.status` carries the batch state. |
| Calendars | `Calendar`, `CalendarSession`, `CalendarDate` | Session times drive rebalance windows and the daily review schedule. |
| HTTP contracts | `msm.api.http`: `ResourceCollection`, discovery, bulk preflight, `TabularFrameResponse`, `api_http_error` | Command Center wire contracts for the frontend, identical to the connectors. |
| Migrations | `build_metatable_migration_provider` for a `hunch` namespace with FKs into `AssetTable`, `AccountTable`, `PortfolioTable` | Hunch never applies `msm_migrations:migration`; the ms-markets deployment owns that schema. Hunch needs `data_viewer`/`data_writer` on `mainsequence.markets` and table `editor` on the tables its DataNodes write. |

### 2.2 What ms-markets does not provide (Hunch builds it)

- Users, ownership, sharing, visibility, forks and lineage, leaderboards.
- Natural-language thesis storage, agent provenance, research evidence.
- An LLM-to-weights signal (we subclass or feed `FixedWeights`).
- Broker connectivity, venue registry, credential binding, provider asset-ID mapping.
- Order generation, target-quantity calculation, approval workflow, autopilot limits,
  execution-error storage, fill-to-holdings reconciliation.
- Scheduled operations store (`InMemoryOperationStore` is not durable; Jobs and JobRuns are).
- Risk and performance metrics beyond resampled close and return (Sharpe, drawdown, benchmark).
- Fundamentals, news, sector classification, market capitalisation.

### 2.3 Alpaca connector (`alpaca-connectors` 0.1.41)

Exists and deployed: account registration from Secret names or site-based key entry (keys never
pass through chat), paper/live identity, `AlpacaAccountDetails` sidecar, holdings capture into
`AccountHoldingsTS`, asset registration by Alpaca UUID with optional OpenFIGI enrichment, daily SIP
bars in a migrated asset-indexed table, interpolated prices, analytical ETF portfolios on
`msm_portfolios`, a FastAPI with `/mcp` and six published skills, and a TAU Harness Agent that
uses them. It is the reference architecture for Hunch's API, MCP, agent and workflows.

Missing for Hunch:

- **No order placement.** Only read methods of `alpaca-py` are called; the repository tests that
  no order tool exists. Execution must be added (6.1).
- **No scheduled holdings capture.** Capture runs synchronously on demand (registration, API,
  MCP). Hunch needs a nightly capture Job.
- **No per-user visibility.** Accounts are Environment-wide; the only person recorded is
  `credentials_updated_by_user_uid`.

### 2.4 Interactive Brokers connector (`interactivebrokersbackend` 0.1.3)

Exists: contracts registered as `IBKR::<conid>` with `IBKRContractDetails`, accounts
`<id>__IBKR[_PAPER]` with `IBKRAccountDetails`, end-of-day holdings and an executions ledger from
IBKR's reporting feed and Flex, NAV and P&L series, a capability API, CLI and Jobs. Credentials are
Secret names on `main`; a branch moves them to sealed encrypted columns (ADR 0011).

Constraints for Hunch:

- **Read-only toward IBKR by policy.** Order placement is explicitly excluded by `AGENTS.md`,
  ADR 0001 and the roadmap. Nothing calls the Trading Web API today.
- **Trading Web API access depends on IBKR approving a third-party OAuth 1.0a consumer**, an
  8 to 14 week legal review that has not started. Sessions are read-only and paced (10 req/s,
  429 is terminal).
- Holdings arrive once a day (previous business day). No bars.
- No MCP server, no agent.

Consequence: IBKR funded takes ship after Alpaca, in two steps: a manual-execution mode on the
existing read-only connector, then automated execution when OAuth is approved (6.2).

### 2.5 Main Sequence SDK 9 capabilities Hunch relies on

- `mainsequence.server.fastapi.install_request_identity` and `install_mcp`: platform-signed caller
  assertions; `User.get_logged_user()` is the caller, `User.get_requester()` the person an Agent
  acts for. Routes never read headers.
- `mainsequence.server.mcp_skills.skills_extension`: publish Agent Skills from the API's MCP.
- `Job.run_job(command_args=...)` and `JobRun` status for long work; workflow API 3.0.0 for
  declarations, schedules, access and execution steps.
- `InferenceClient.complete(...)` with `response_schema`, `thinking_level`, `conversation_uid`,
  `idempotency_key`: recorded, replayable model calls with no application-side provider key.
  This is how the backend runs research and daily reviews without an agent turn.
- `Agent.get_or_create_session`, `AgentSession.send_a2a_message`, `wait_for_a2a_task`: how a Job
  can hand work to the Hunch Agent (for example an inbound email).
- Secrets with `value_reader` policies; workflows declare `access.secrets`, `access.branches`
  (another repository's releases and Jobs in the Environment), `access.resources`,
  `access.agents`, `access.model_providers`.

### 2.6 TAU agent model (`ms-tau-sdk` 2.0.23)

- `api/agent/main.py` is `app = create_app()`; nothing else. Behaviour comes from `.tau/SYSTEM.md`,
  `.tau/skills`, `.tau/extensions`, and the MCP applications declared in the workflow
  (`mcp_applications: [{resource: hunch}]`), which Tau exposes as `hunch__list_tools`,
  `hunch__call_tool`, `hunch__list_resources`, `hunch__read_resource`.
- `TAU_EXCLUDE_BASE_TOOLS=true` and `TAU_EXCLUDE_MAINSEQUENCE_MCP=true` leave only skill reading,
  the application tools and the A2A task controls.
- `acts_for_requester: true` makes every tool call run in the Hunch API as the person served, with
  their permissions; the platform checks it on every call for at most 24 hours.
- Limits: a direct A2A Message gets 90 seconds; an MCP tool gets 60 seconds unless it declares
  `mainsequence.ai/timeout-seconds/v1`. Anything longer is a Job that returns a JobRun UID.

---

## 3. Target architecture

### 3.1 Principles

1. **ms-markets is the market ledger.** Assets, accounts, holdings, signals, portfolios, orders and
   trades live only in ms-markets tables. Hunch tables reference them by foreign key and add the
   product layer: people, theses, proposals, lineage, notifications.
2. **The connectors are the brokerage boundary, and Hunch talks to them deterministically.**
   Credentials, provider clients, holdings capture and order transmission stay in
   `alpaca-connectors` and `interactivebrokersbackend`. Hunch services and Jobs call their REST
   APIs through typed clients; the agent and the model never call a connector. Everything about
   an Alpaca account (registration, holdings, orders) goes through the Alpaca API, and the same
   for IBKR.
3. **Hunch owns portfolio and execution logic; connectors execute.** Hunch turns a basket into a
   `HunchPortfolio`, computes target quantities and proposals, enforces approvals and autopilot
   limits, and hands the exact orders to the connected venue API, which places them and reports
   fills.
4. **One agent.** Hunch has exactly one TAU Harness Agent, for conversation and bounded actions
   on behalf of the person, with one session per take. Research, construction and the daily
   review are deterministic service code in Jobs that call recorded inference
   (`InferenceClient`); they are not agents.
5. **Deterministic guardrails around the model.** The model proposes candidates, roles and
   weights; code enforces tradability, liquidity, concentration, cash buffer and autopilot limits.
6. **One engine for practice and funded takes.** Practice is a `HunchPortfolio` without a
   virtual fund; funding adds a virtual fund, target positions and execution. The performance
   series is the same object.
7. **Copy the connector conventions.** `src/<package>` wheel, `api/app/main.py` and
   `api/agent/main.py` outside the wheel, `src/jobs/*` launchers with a schema gate,
   configuration-selected Jobs plus dispatchers, migration Job gating the API deploy, ADRs,
   strict MkDocs, contract tests.

### 3.2 Components

```text
                     Command Center (hunch static site)
                       |  delegated fetch (person)        | chat (person), one session per take
                       v                                   v
   +-------------------------------+        +------------------------------+
   | hunch API (FastAPI, /mcp)     | <----- | Hunch Agent: the one TAU     |
   | routes, services, skills      |  MCP   | harness, acts_for_requester, |
   | identity: caller / requester  |        | tools = hunch API only       |
   +---------------+---------------+        +------------------------------+
                   | Job.run_job / JobRun
                   v
   +-------------------------------+   InferenceClient (recorded)   +------------------+
   | Hunch Jobs (deterministic)    | -----------------------------> | model provider   |
   | take-build, portfolio-refresh |                                +------------------+
   | daily-review, execution-sync  |
   +------+------------------------+-------------------------------------------+
          | ms-markets row APIs + DataNodes               typed REST clients   |
          v                                                                   v
   +----------------------------------------+   +--------------------------------------------+
   | ms-markets: Asset, Account, HoldingsTS, |   | connector APIs (deterministic, per venue)  |
   | Portfolio + HunchPortfolio extension,   |   |  alpaca-connectors: accounts, holdings,    |
   | SignalWeightsTS, Portfolio*TS,          |<--|    bars, NEW execution capability          |
   | VirtualFund*, TargetPositionsTS,        |   |  interactivebrokersbackend: accounts,      |
   | OrderManager, OrdersTS, TradesTS        |   |    holdings, executions; later execution   |
   +----------------------------------------+   +---------------------+----------------------+
                                                                      |
                                                       Alpaca    Interactive Brokers
```

| Component | Repository | Deployable |
| --- | --- | --- |
| Hunch API | `hunchapi` (this repo) | `fastapi` resource `hunch`, `mcp_enabled: true` |
| Hunch Agent | `hunchapi` | `harness_agent` resource `hunch-agent` |
| Hunch Jobs | `hunchapi` | `job` resources (5.3) |
| Hunch site | `hunch` | `static_site`, consumes the API's Command Center contracts and the Agent |
| Alpaca brokerage | `alpaca-connectors` | existing `alpaca` API, Jobs, Agent; new execution capability |
| IBKR brokerage | `interactivebrokersbackend` | existing API and Jobs; later OAuth and execution |
| Market ledger | `mainsequencemarkets` | existing MetaTables deployment; no change required |

### 3.3 Decision (confirmed 2026-10-25): Hunch owns execution logic, the connected venue API executes

Hunch decides what to trade (target quantities, proposals, approvals, autopilot limits). The
connector of the venue the account belongs to places and reports the exact orders, through a new
`execution` capability that the Hunch API and Jobs call release-to-release with typed clients.

- Credentials and provider clients already live there; nothing new learns a broker key.
- The connectors already own the account registry, provider asset identity and holdings capture,
  which an executor needs for pre-trade checks and post-trade reconciliation.
- Each connector exposes the same contract (`POST .../orders/actions/submit` with an
  `OrderManager` batch of target quantities, `GET .../orders`, `POST .../orders/actions/sync`,
  `POST .../holdings/actions/capture`), so Hunch's executor is venue-agnostic.
- The Hunch workload declares `access.branches: [{repository: <connector>, policy: user}]` and
  calls the connector release as itself. The Hunch API has already authorised the person
  (owner of the take and of the brokerage link); the connector authorises the Hunch workload.
  A delegated person identity cannot be forwarded application-to-application, so this is the
  only correct shape.

Alternative considered: Hunch depends on the connector packages as libraries and runs their
services in-process. Rejected because the managed Secrets are per-account and created by the
connector workload, so Hunch would need dynamic `value_reader` grants on each, and because two
deployables would then write the connector's sidecar tables.

Phase 0 verifies the mechanics with a spike: the SDK call path from a FastAPI workload to another
release, the cross-repository `access.branches` grant, and paper order placement with `alpaca-py`.

### 3.4 Hunch domain model (namespace `hunch`, FKs into ms-markets)

| Table | Key columns | Purpose |
| --- | --- | --- |
| `HunchUserProfile` | `user_uid` (PK, the Main Sequence user), `handle`, `display_name`, `created_at` | The Hunch user. It is not an ms-markets `Account`; it owns takes and links to the venue accounts the connectors create for it. |
| `HunchUserProfileAccount` | `uid`, `user_uid` FK `HunchUserProfile`, `venue` (`alpaca`, `ibkr`), `account_uid` FK `AccountTable` (the row that venue's connector created), `status` (`pending`, `active`, `revoked`), `is_paper`, `linked_at` | One profile, many venue accounts. The user-to-account ownership that ms-markets lacks; verified at creation against the connector's `credentials_updated_by_user_uid`. |
| `HunchPortfolio` | `portfolio_uid` (PK and FK `PortfolioTable.uid`), `take_uid`, `owner_user_uid`, `basket_revision_uid`, `activated_at`, `is_simulated`, `metadata_json` | Hunch's portfolio type: the ms-markets `Portfolio` row plus Hunch columns, built from the take's basket by Hunch's own construction logic. All portfolio time series stay keyed on the base `Portfolio.unique_identifier`. |
| `Take` | `uid`, `owner_user_uid`, `title`, `thesis_text`, `constraints_json` (horizon, cash buffer, exclusions, risk level, allow_leveraged_etf), `visibility` (`private`, `public`), `status` (3.6), `execution_mode` (`practice`, `approval`, `autopilot`), `forked_from_take_uid`, `origin_take_uid`, `signal_uid` FK `SignalMetadata`, `hunch_portfolio_uid` FK `HunchPortfolioTable`, `activated_at`, `published_at` | The product object. |
| `TakeRevision` | `uid`, `take_uid`, `revision`, `kind` (`initial`, `rebalance`, `user_edit`, `thesis_check`), `rationale_md`, `weights_json`, `research_json` (candidates, roles, evidence, risks), `inference_request_uids`, `created_by` (`agent`, `job`, `user`), `signal_time_index` | Every change of weights with its evidence; the `SignalWeightsTS` observation it produced. |
| `Instrument` | `figi` (PK), `ticker`, `name`, `exchange_code`, `security_type`, `sector` (nullable) | Venue-neutral instrument used in theses (3.5). |
| `InstrumentVenueAsset` | `figi`, `venue`, `asset_uid` FK `AssetTable`, `tradable`, `fractionable` | Resolution to the venue's `Asset`. |
| `Funding` | `uid`, `take_uid`, `user_account_uid` FK `HunchUserProfileAccount`, `virtual_fund_uid` FK `VirtualFundTable`, `account_target_allocation_uid`, `target_notional`, `currency`, `status` | Funded take inside an account. |
| `RebalanceProposal` | `uid`, `take_uid`, `funding_uid`, `revision_uid`, `order_manager_uid` FK `OrderManagerTable`, `legs_json` (instrument, side, quantity, est. notional, reason), `trigger` (`initial`, `drift`, `thesis`, `user`), `status` (`proposed`, `approved`, `rejected`, `expired`, `submitted`, `partially_filled`, `filled`, `failed`), `autopilot_check_json`, `expires_at`, `decided_by_user_uid`, `decided_at` | Approval and autopilot state machine. |
| `AutopilotPolicy` | `take_uid`, `max_turnover_per_day`, `max_notional_per_order`, `max_single_name_weight`, `allow_new_instruments`, `trading_window` | Server-enforced autopilot limits shown to the user. |
| `DailyReview` | `uid`, `take_uid`, `review_date`, `drift_json`, `thesis_check_json`, `outcome` (`hold`, `proposed`, `executed`), `proposal_uid`, `inference_request_uids`, `summary_md` | Audit of the daily loop and source of status updates. |
| `LeaderboardSnapshot` | `snapshot_date`, `take_uid`, `return_since_activation`, `days_active`, `is_simulated`, `rank` | Nightly ranking. |
| `Notification` | `uid`, `user_uid`, `take_uid`, `kind`, `payload_json`, `created_at`, `read_at`, `delivered_channels_json` | In-app feed, later email. |
| `ResearchSource` (phase 2) | provider, config, Secret name | Pluggable fundamentals and news providers. |

Hunch tables carry `owner_user_uid` and are the only place authorisation is decided. ms-markets
rows are never returned to a person without passing through a Hunch ownership or visibility
check.

**Why `HunchPortfolio` is an extension table.** ms-markets extends a model by relational
composition: a one-to-one table whose primary key is the base row's uid, as `OpenFigiAssetDetails`
and the connectors' detail tables do (`examples/msm/platform/custom_asset_details_extension.py`,
skill `asset_model_extension`). There is no SQLAlchemy inheritance in ms-markets.
`HunchPortfolioTable` follows that convention in the `hunch` namespace, attached through
`msm_portfolios.start_engine(models=[...])`, and a `HunchPortfolio` row API (a
`MarketsMetaTableRow` subclass) creates the base `Portfolio` and the extension row in one
operation. The base `Portfolio` table keeps only what `msm_portfolios` needs; every Hunch
attribute lives on the extension.

### 3.5 Asset identity across venues

The connectors register provider-native `Asset` rows (Alpaca UUID identity, `IBKR::<conid>`), and
the IBKR ADR states the same instrument stays a separate `Asset` per venue. A take must be
venue-neutral so it can be practiced, funded at Alpaca, forked into an IBKR account, and priced
from one source. Therefore:

- Theses and revisions name instruments by FIGI (`Instrument`), the identity ms-markets itself
  recommends. Resolution uses `msm.services.assets.openfigi` (Secret `OPEN_FIGI_API_KEY`).
- `InstrumentVenueAsset` maps a FIGI to the venue `Asset` (Alpaca: from the connector's asset
  registration with OpenFIGI enrichment; IBKR: from `IBKRContractDetails` when IBKR supplies the
  FIGI, otherwise by ISIN or ticker plus exchange through OpenFIGI).
- Prices for every take come from the Alpaca daily SIP bars of the Alpaca `Asset`, through
  `InterpolatedPrices`. Hunch maintains one Alpaca bars configuration (`asset_source: assets`)
  whose membership is the union of all take constituents; the connector's existing daily bars
  Job updates it. The model `Portfolio` therefore always runs on Alpaca-identified assets, and
  the funded leg translates to the venue asset at order time.
- Trading eligibility is per venue (`tradable`, `fractionable`, shortable); construction rejects
  instruments that the target venue cannot trade.

### 3.6 Take lifecycle

```text
draft --build--> built --(practice)--> active_practice --fund--> funding --filled--> active_funded
  ^                |                         |                                      |
  |                +--rebuild (user edit)----+                                      |
  +-----------------------------------------------------------------------<--------+ archive
```

| Step | Hunch writes | ms-markets writes |
| --- | --- | --- |
| Create | `Take(status=draft)` | none |
| Research (Job `hunch-take-research`, ADR 0008) | `TakeResearch(number=1)`: candidates, roles, conviction, evidence; no weights | none |
| Build (Job `hunch-take-build`, from a stored research) | `TakeRevision(initial)` with the weights and a copy of the research | `Instrument`/`InstrumentVenueAsset` resolution; `AssetCategory` for the revision; `SignalMetadata` + `FixedWeights` observation into `SignalWeightsTS`; `Portfolio` (calendar XNYS, `signal_uid`) with its `HunchPortfolio` extension row, `PortfolioMetadata`; graph run → `PortfolioWeightsTS`, `PortfoliosTS` from `activated_at` |
| Activate practice | `status=active_practice`, `activated_at` | the `PortfoliosTS` series starts |
| Fund (Alpaca) | `Funding` against a `HunchUserProfileAccount`, `RebalanceProposal(trigger=initial)` | `VirtualFund(account, portfolio)`, `AccountAllocationModel`, `AccountTargetAllocation`, `PositionSet`, `TargetPositionsTS(target_type=portfolio, constant_notional_exposure)`, `OrderManager` |
| Execute (approved or autopilot) | proposal `submitted` → `filled` | connector publishes `OrdersTS`, `OrderEventsTS`, `TradesTS`; Hunch `execution-sync` updates `VirtualFundHoldingsTS` and asks the connector to capture `AccountHoldingsTS` |
| Daily review (Job) | `DailyReview`, optional `TakeRevision(rebalance|thesis_check)` and `RebalanceProposal` | new `SignalWeightsTS` observation; `PortfolioRebalanceStateTS`; graph refresh |
| Publish / fork | `visibility`, new `Take` with lineage, copied latest `TakeRevision` | new `SignalMetadata`, `Portfolio` for the fork with its own activation |
| Archive / revoke | `status=archived`, `HunchUserProfileAccount.revoked` | `Account` untouched (connector-owned); virtual fund closed by a final proposal that liquidates to cash |

### 3.7 Research and construction pipeline

Runs in the `hunch-take-build` and `hunch-daily-review` Jobs with `InferenceClient` (recorded,
`response_schema`, one `conversation_uid` per take, idempotency key per step). The Hunch Agent
can trigger a build, read its results and explain them; it does not do the research itself in a
60-second tool call. This pipeline is deterministic service code owned by Hunch; the model is
called as a recorded function with a schema, and the pipeline is not a second agent.

1. **Parse** the thesis into a structured brief: claims, time horizon, beneficiaries, losers,
   explicit constraints, the user's "what would change my mind" conditions.
2. **Candidate generation** from the brief: instruments with a role (`pure_play`, `supplier`,
   `enabler`, `hedge`), a one-paragraph case, and risks. Phase 1 grounds this in the Alpaca
   tradable asset list (names, tickers, exchanges) plus quantitative facts from bars (average
   daily volume, realised volatility, 1y return) that code computes and feeds to the model.
   Phase 2 adds pluggable fundamentals and news sources.
3. **Guardrails (code, not model):** tradable and active at the target venue; minimum average
   daily volume; maximum single-name weight (default 15 percent); maximum weight in leveraged or
   inverse products (default 0 unless the user allows it); cash buffer from the constraints;
   weights sum to one; fractional eligibility for the funded notional.
4. **Weighting:** the model proposes sleeves and relative sizes; code normalises, applies caps,
   and redistributes. The result is the `TakeRevision.weights_json` and the `FixedWeights`
   observation.
5. **Rationale:** the model writes the public rationale and the per-position reasons, which the
   leaderboard and the agent show.
6. **Daily review:** compute drift from `PortfolioWeightsTS` versus target; ask the model to
   evaluate the thesis conditions against the quantitative facts (and, in phase 2, news); decide
   `hold`, `rebalance` or `thesis_change`; produce a `RebalanceProposal` or execute under
   autopilot; write the `DailyReview` summary that becomes a status notification.

### 3.8 Execution, approvals and autopilot

1. The daily review or the initial funding creates a `RebalanceProposal` with legs computed from
   target weights × funding notional ÷ last price, netted against `VirtualFundHoldingsTS`, rounded
   per venue rules, with an `OrderManager` row in `pending_approval`.
2. **Approval mode:** the user approves in the app or through the agent (`hunch_manage_proposal
   approve`). The API requires the proposal owner, checks expiry (end of the next session), and
   re-validates prices and holdings before submission.
3. **Autopilot:** the Job applies `AutopilotPolicy` (turnover, per-order notional, new
   instruments, trading window). Within limits it submits; outside them it degrades to a
   proposal and notifies.
4. **Submission:** the Hunch executor (service code, never the agent) calls the execution
   capability of the connector that owns the account, through its typed REST client, with the
   `OrderManager` identifier and legs (`client_order_id = <proposal uid>:<leg>`, idempotent).
   The connector places the orders, writes `OrdersTS`, and returns the broker order IDs.
5. **Sync:** `hunch-execution-sync` asks the connector to sync order states (`OrderEventsTS`,
   `TradesTS`), updates `VirtualFundHoldingsTS` from fills, moves the proposal to
   `partially_filled`/`filled`/`failed`, requests a holdings capture, and notifies.
6. **IBKR before OAuth approval (manual execution mode):** the proposal is presented as an order
   list the user executes at IBKR; the connector's executions ledger and next-day holdings
   reconcile the virtual fund, and the proposal closes when the holdings match within tolerance.

### 3.9 Practice mode, forks, leaderboard, notifications

- **Practice:** `execution_mode=practice`, no `Funding`. The identical build, graph and daily
  review run; `DailyReview.outcome` is recorded without orders. Converting to funded keeps the
  take and its series; the leaderboard shows `is_simulated` for the period before funding.
- **Forks:** copy the latest revision, create a new signal and portfolio, set
  `forked_from_take_uid` and `origin_take_uid`. The origin's author can edit or unpublish their
  take; forks continue independently. Leaderboard entries carry origin attribution.
- **Leaderboard:** nightly Job ranks public takes by `PortfoliosTS.close` relative to the close at
  `activated_at`, with days active and the simulated flag. Disclaimers are part of the API
  response, not only the UI.
- **Notifications:** created by Jobs and services; the feed endpoint and an agent tool read them.
  Email delivery (and the email channel into the agent through A2A) is phase 4.

### 3.10 Multi-tenancy and security

- The Hunch API installs `install_request_identity`; `acting_user_uid()` is the requester when an
  Agent acts for a person, else the caller. No route or tool accepts a person's UID.
- Every read and write on a `Take`, `Funding`, `Proposal`, `HunchUserProfileAccount` or `Notification`
  checks `owner_user_uid` (or `visibility=public` for reads of takes and leaderboard).
- The Hunch workload holds no Secrets. Broker keys are entered on the connector's site flow (or
  the Hunch site posting to the connector with the person's delegated identity), never in chat.
- Writes are idempotent and confirm-before-destroy (`DELETE <uid>` for archive of a funded take;
  revocation liquidates only on explicit instruction).
- Proposal approval, autopilot limits and venue eligibility are enforced in services, never in the
  prompt.
- The agent prompt states the regulatory posture: the user instructs, Hunch is not an adviser,
  returns may be simulated.

### 3.11 Decisions confirmed on 2026-10-25

1. Connector interaction is deterministic. Hunch services and Jobs call the Alpaca and IBKR
   connector APIs through typed clients. Account management, holdings and orders for an Alpaca
   account go through the Alpaca API; the same for IBKR. The agent and the model never call a
   connector.
2. Hunch owns portfolio construction from the basket. Portfolios are `HunchPortfolio` rows, an
   ms-markets extension table keyed one-to-one on `Portfolio.uid`, never bare `Portfolio` rows.
3. `HunchUserProfile` is the Hunch user, distinct from an ms-markets `Account`. It links
   one-to-many to the venue accounts the connectors create for that user
   (`HunchUserProfileAccount`).
4. Hunch owns execution logic (targets, proposals, approvals, autopilot limits) and delegates the
   exact trades and their execution to the connected venue API.
5. Hunch has exactly one agent.

---

## 4. The Hunch Agent (the one agent)

### 4.1 Role

"Hunch Agent": helps the signed-in person write and refine takes, understand research and weights,
link a brokerage, fund a take, approve or reject proposals, read performance and daily reviews,
publish and fork. It speaks as the portfolio's manager for the take the conversation is about. It
has no shell, file, SQL or platform tools. Long work (build, daily review, execution sync) returns
a JobRun UID that it reports and follows up on.

Hunch has exactly one agent. Many conversations, one agent: the per-take context comes from the
session, not from separate agents, and every tool call goes to the Hunch API, never to a
connector.

### 4.2 Tool catalogue served by the Hunch API `/mcp`

Operation-discriminated schemas as in the Alpaca connector; read tools run in parallel, mutations
sequentially; results carry only business fields.

| Tool | Operations | Notes |
| --- | --- | --- |
| `hunch_project_state` | readiness, capabilities, disclaimers | first call when readiness is unknown |
| `hunch_query_takes` | `list` (mine, public, leaderboard), `get`, `revisions`, `research`, `performance`, `holdings`, `drift`, `daily_reviews` | performance = `PortfoliosTS` since activation |
| `hunch_manage_take` | `create`, `update_thesis`, `build` (→ JobRun), `activate_practice`, `publish`, `unpublish`, `fork`, `archive` | `archive` needs `DELETE <uid>` |
| `hunch_query_accounts` | `list`, `get`, `holdings` | the profile's linked venue accounts; holdings read from `AccountHoldingsTS` |
| `hunch_manage_account_link` | `start_link` (returns the connector's key-entry URL), `complete_link`, `revoke` | never accepts credentials; the Hunch API talks to the connector, not the agent |
| `hunch_manage_funding` | `plan` (dry run: legs, notional, eligibility), `fund`, `set_execution_mode`, `set_autopilot_policy`, `withdraw` | `fund` creates the initial proposal |
| `hunch_query_proposals` | `list`, `get`, `orders`, `fills` | from Hunch tables plus `OrdersTS`/`TradesTS` |
| `hunch_manage_proposal` | `approve`, `reject`, `request_change` | approval re-validates server-side |
| `hunch_query_notifications` | `list`, `mark_read` | |
| `hunch_get_job_run_status` | by JobRun UID | |

Tool time limits: `plan` and `research` reads declare `mainsequence.ai/timeout-seconds/v1: 120`;
everything heavier is a Job.

### 4.3 Published skills (`.agents/skills/mcp_tools/`)

`hunch-take-authoring`, `hunch-practice-mode`, `hunch-brokerage-linking`,
`hunch-funding-and-proposals`, `hunch-monitoring-and-rebalancing`,
`hunch-sharing-forks-leaderboard`. Each records trigger, inputs, tools, preconditions, side
effects, completion criteria and escalation, and is listed in `.agents/agent_card.json`.

### 4.4 Conversation model

- The site opens one AgentSession per take (`handle_unique_id = take uid`), so "talk to each
  portfolio" is literal and the history stays per take. A general session handles authoring.
- The first message of a take session carries the take UID; tools default to it.
- Channels: Command Center chat now; email in phase 4 (inbound mail → Job → `send_a2a_message`
  on the take's session; outbound through notifications); iMessage and SMS are not planned.

### 4.5 Deployment declaration (sketch)

```yaml
- key: hunch-agent
  kind: harness_agent
  acts_for_requester: true
  access:
    resources:
      - key: hunch
        policy: user
  spec:
    source_path: api/agent/main.py
    llm_provider: <provider>
    llm_model: <model>
    llm_thinking: medium
    mcp_applications:
      - resource: hunch
    env_vars:
      - {name: TAU_EXCLUDE_BASE_TOOLS, value: 'true'}
      - {name: TAU_EXCLUDE_MAINSEQUENCE_MCP, value: 'true'}
    cpu_request: 250m
    memory_request: 512Mi
    automatic_deployment: true
    automatic_redeployment: {enabled: true, tag_regex: null}
    revision_retention_count: 3
```

---

## 5. The Hunch API and Jobs (this repository)

### 5.1 Layout

```text
hunchapi/
├── api/app/main.py          # re-exports hunch.api.app.main:app (discovery contract)
├── api/agent/main.py        # app = ms_tau_sdk.create_app()
├── src/hunch/
│   ├── instruments/         # FIGI resolution, venue mapping, universe category, bars membership
│   ├── takes/               # Take, TakeRevision, lifecycle services
│   ├── research/            # InferenceClient pipeline, schemas, guardrails, quantitative facts
│   ├── portfolios/          # HunchPortfolio extension, FixedWeights signal, graph build/run, performance
│   ├── profiles/            # HunchUserProfile, HunchUserProfileAccount (venue account links)
│   ├── funding/             # Funding, virtual funds, target positions, ValuationResolver
│   ├── execution/           # proposals, autopilot policy, venue executor port
│   ├── connectors/          # typed REST clients for the alpaca and ibkr connector APIs (deterministic)
│   ├── review/              # daily review
│   ├── social/              # publish, fork, leaderboard
│   ├── notifications/
│   ├── api/app/             # routers, schemas, services, identity, errors, capabilities, mcp_server
│   ├── agent_tools.py
│   ├── migrations/          # metatables provider `hunch.migrations:migration`, schema_gate
│   ├── runtime.py           # single msm_portfolios.start_engine with explicit model sets
│   └── cli/
├── src/jobs/                # launchers (schema gate first, JSON summary, exit 1 on failure)
├── .tau/SYSTEM.md
├── .agents/agent_card.json, .agents/skills/mcp_tools/*
├── .mainsequence/workflows/hunch-api.yaml
├── docs/ (MkDocs, ADRs), tests/
└── pyproject.toml           # mainsequence[mcp]>=9.0.30,<10; ms-markets>=2.2.12,<3;
                             # mainsequence-metatable>=0.1.51,<0.2; ms-tau-sdk>=2.0.23,<3
```

This repository currently pins `mainsequence==8.1.10`, which `ms-markets` 2.x does not support;
phase 0 moves it to SDK 9 and the `uv` lock convention of the connectors.

### 5.2 Routes (Command Center contracts via `msm.api.http`)

| Prefix | Operations |
| --- | --- |
| `/health`, `/v1/project-state/{capabilities,configuration}` | readiness, capability catalogue, Agent UID for the site |
| `/v1/takes` | list (mine/public), get, create, patch, `/discovery`, `/{uid}/revisions`, `/{uid}/performance` (tabular frame), `/{uid}/holdings`, `/{uid}/daily-reviews`, actions `build`, `activate-practice`, `publish`, `unpublish`, `fork`, `archive` (+preflight) |
| `/v1/profile`, `/v1/profile/accounts` | profile get and patch; linked venue accounts list, get, actions `start-link`, `complete-link`, `revoke`, `/{uid}/holdings` |
| `/v1/fundings` | list, get, actions `plan`, `create`, `set-execution-mode`, `set-autopilot-policy`, `withdraw` |
| `/v1/proposals` | list, get, `/{uid}/orders`, `/{uid}/fills`, actions `approve`, `reject` |
| `/v1/leaderboard` | current snapshot, `/discovery` |
| `/v1/notifications` | list, mark-read |
| `/v1/operations/job-runs/{uid}` | JobRun polling |
| `/mcp` | tools and published skills |

### 5.3 Jobs and schedules (workflow API 3.0.0)

| Job | Selector | Schedule | Work |
| --- | --- | --- | --- |
| `hunch-migrate` | none | execution step before API deploy | apply `hunch.migrations:migration` |
| `hunch-take-research` | `--take-uid` | on demand (API/agent) | research of the target universe, stored per take (ADR 0008) |
| `hunch-take-build` | `--take-uid`, `--research-uid` | on demand (API/agent) | construction from a stored research, signal, portfolio graph |
| `hunch-portfolio-refresh` | `--take-uid` | dispatcher daily 01:30 UTC (after the Alpaca bars Job at 00:00 UTC) | graph refresh → `PortfoliosTS`, analytics |
| `hunch-daily-review` | `--take-uid` | dispatcher on NYSE session days, 13:00 UTC | drift, thesis check, proposal or autopilot execution, notifications |
| `hunch-execution-sync` | `--proposal-uid` or `--scheduled` | every 15 minutes during sessions | order state sync, fills → virtual fund holdings, holdings capture |
| `hunch-leaderboard` | none | daily 02:30 UTC | ranking snapshot |
| `hunch-instrument-sync` | none | weekly | refresh venue eligibility, bars membership |

Dispatchers follow the connector pattern (a Job cannot hold `runner` on itself). Access per
workload: MetaTables reader on the shared repository, `data_writer` on `mainsequence.markets`,
table `editor` on the TS tables Hunch DataNodes write, `user` on the connector releases they call,
`access.model_providers` for the Jobs that run inference.

### 5.4 Migrations and roles

- Provider `hunch.migrations:migration` with its own `hunch` namespace; FKs to `AssetTable`,
  `AccountTable`, `PortfolioTable`, `OrderManagerTable`, `VirtualFundTable`.
- Local: `metatables --local migrations upgrade --provider msm_migrations:migration head` (dev
  database only) then the Hunch provider. Hosted: only `hunch-migrate` runs, against the schema the
  ms-markets deployment owns.
- Every launcher calls the schema gate first.

---

## 6. Changes required in the other repositories

### 6.1 `alpaca-connectors` (new ADR: execution capability)

- `src/alpaca_connectors/execution/`: submit an `OrderManager` batch (market and limit, notional
  or fractional where eligible, `client_order_id` idempotency), cancel, sync order status and
  fills; write `OrdersTS`, `OrderEventsTS`, `TradesTS`; publish a holdings snapshot after fills.
- Routes `POST /v1/accounts/{uid}/orders/actions/submit|cancel|sync` (+preflight),
  `GET /v1/accounts/{uid}/orders`, matching MCP tools and a skill; capability key `execution`.
- A scheduled holdings capture Job (nightly, all active accounts).
- Pre-trade checks: account active, buying power, asset tradable/fractionable, pattern-day-trade
  and market-hours rules reported as structured errors.
- Workload authorisation for an external caller (the Hunch release) and the `AGENTS.md`, prompt
  and tests that currently assert "no trading" updated to the new boundary (the Alpaca Agent may
  still be kept out of execution; the API capability is what Hunch needs).

### 6.2 `interactivebrokersbackend`

- Phase 3a (no IBKR dependency): expose holdings and executions reads to the Hunch workload;
  that is enough for manual-execution mode and for IBKR-linked practice takes.
- Phase 3b (after IBKR approves the OAuth 1.0a consumer): implement `src/ibkr/auth` and
  `src/ibkr/web_api` (roadmap phase 1b), a brokerage session with `compete=false`, and the same
  execution contract as Alpaca under a new ADR superseding the read-only decision. Fractional
  shares and pacing differ; the Hunch executor's venue rules cover them.

### 6.3 `mainsequencemarkets`

No change required. Nice-to-haves to propose upstream later: a performance-metrics service
(Sharpe, drawdown) so projects stop recomputing it, and a documented approval state vocabulary
for `OrderManager.status`.

---

## 7. Delivery plan

Effort is indicative, for one engineer plus agent assistance, and excludes IBKR's approval lead
time.

| Phase | Deliverable | Acceptance | Effort |
| --- | --- | --- | --- |
| **0. Foundation** | SDK 9 upgrade of this repo, `uv` lock, package layout, migration provider, workflow file with API, agent, migrate Job; spikes: release-to-release call, cross-repo access, Alpaca paper order via `alpaca-py` | API deploys with identity; agent answers in Command Center with `hunch_project_state`; spikes documented as ADRs | 1 week |
| **1. Practice takes** | Instruments and FIGI resolution; Take and revisions; research pipeline with guardrails; `FixedWeights` signal; Portfolio graph on Alpaca bars; performance; agent tools for authoring and reading; publish, fork, leaderboard | A thesis typed in chat becomes a built take with rationale and weights, runs daily, shows returns since activation, can be published and forked | 3 to 4 weeks |
| **2. Alpaca funded takes** | Profile account links; typed Alpaca client; virtual funds and target positions; proposals; Alpaca execution capability (6.1); approval mode; autopilot with policy; daily review; execution sync; in-app notifications | A paper Alpaca account holds a funded take; approval and autopilot both place and reconcile orders; drift triggers a proposal | 3 to 4 weeks |
| **3. IBKR** | 3a manual-execution mode on the read-only connector; 3b automated execution after OAuth approval | 3a: an IBKR-linked take reconciles from the executions ledger; 3b: parity with Alpaca | 3a: 1 week; 3b: 2 to 3 weeks after approval |
| **4. Channels and depth** | Email channel through A2A; fundamentals and news research sources; risk metrics; frontend polish in the `hunch` site | Status updates and replies by email; research cites sources | 2 to 3 weeks |

Phase 1 and the Alpaca execution capability (6.1) can run in parallel in different repositories.

---

## 8. Risks and open questions

1. **IBKR execution timing** depends on an 8 to 14 week approval that has not started. Decide
   whether to file the OAuth consumer request now so phase 3b is not blocked later.
2. **Research grounding.** ms-markets and the connectors carry no fundamentals, news or sector
   data. Phase 1 relies on model knowledge plus bar-derived facts and says so in the rationale.
   Choose the phase 2 data provider early (it needs a Secret and a `ResearchSource`).
3. **Leaderboard return basis.** Model-portfolio series (consistent across practice and funded)
   versus realised virtual-fund NAV (truthful for funded). Proposal: rank on the model series,
   show realised next to it, label simulated periods.
4. **Account visibility across users.** Connector accounts are Environment-wide. Hunch's
   `HunchUserProfileAccount` plus the connector's `credentials_updated_by_user_uid` check is the gate;
   confirm this is acceptable or add an owner column to the connector sidecars.
5. **Model provider and cost.** Research and daily reviews are recorded inference per take per
   day; pick provider, model and thinking level, and batch reviews for inactive takes.
6. **Alpaca connector policy change.** Its prompt, docs and tests currently assert "no trading".
   Adding execution to the API is a deliberate boundary change that needs an ADR and owners'
   agreement.
7. **Regulatory posture.** Mirror Supertake: not an adviser, user instructs, Approval default,
   Practice first, disclaimers in API responses. Legal review before public access.
8. **Frontend.** The `hunch` scaffold must implement take authoring, chat per take, proposal
   approval and brokerage key entry (posting to the connector with the person's delegated
   identity). It is not covered by this document.

---

## Appendix A: sources

- USV, "Introducing Supertake" (Michael Mignano, 2026-09-28):
  https://www.usv.com/writing/introducing-supertake
- Supertake landing page and leaderboard: https://supertake.com
- Coverage: KuCoin blog "USV Partner Michael Mignano Launches Supertake" and Runtime Wire
  "Supertake turns investing theses into portfolios, starting with Robinhood".
- Repositories inspected (workbench `code-repositories/`): `mainsequencemarkets` (ms-markets
  2.2.12), `alpaca-connectors` 0.1.41, `interactivebrokersbackend` 0.1.3 and its frontend
  `interactivebrokersam`, `binance-connectors`, `hunch` (frontend scaffold), and the CRM API
  project as a second TAU integration reference.
