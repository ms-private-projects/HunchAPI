# ADR 0003: Funding and execution through the venue connectors

- **Status:** Accepted
- **Date:** 2026-10-25
- **Scope:** Linked accounts, funded takes, proposals, approvals, autopilot, execution sync,
  withdrawal, daily reviews, leaderboard and notifications (stages C and D)

## Context

A funded take puts real money behind a basket inside the person's own brokerage account. The plan
(docs/planning/0001 §3.3, §3.8, §3.11) fixes the shape: Hunch owns the logic (targets, proposals,
approvals, autopilot limits, state) and delegates the exact orders to the connector of the venue
the account belongs to; the Agent and the model never touch a connector. ms-markets supplies the
money-side records (``Account``, holdings, ``VirtualFund``, target positions, ``OrderManager``,
``OrdersTS``, ``TradesTS``) but no execution service. The two connectors, as they stand today:

- `alpaca-connectors` registers accounts over HTTP (keys or Secret names), captures holdings and
  resolves assets (`ALPACA::<uuid>`, FIGI as enrichment); it has **no order surface** and its
  routes accept any authenticated caller, recording the person as
  `credentials_updated_by_user_uid`.
- `interactivebrokersbackend` is read-only (reports and Flex, end of day), is not deployed as an
  API yet, registers no owner on an account and keeps executions in a project table.

## Decisions

1. **A venue connector port** (`hunch.connectors.base.VenueConnector`): accounts, holdings,
   asset resolution by FIGI, `submit_orders`, `sync_orders`, `cancel_orders`, and
   `execution_capability()` (`automatic`, `manual`, `unavailable`). Three implementations:
   `AlpacaConnector` and `IBKRConnector` (typed REST clients over the connectors' Command Center
   contracts; the Alpaca client already targets the execution routes of plan §6.1 and reports
   `unavailable` until the release ships them), and `SimulatedConnector` for local development and
   tests, which fills every market order at the last stored close and writes the same ms-markets
   rows a connector would (`Account` with the owner in `metadata_json`, `AccountHoldingsSet` +
   `AccountHoldingsTS`, `OrderManager` + `OrdersTS` + `TradesTS`). `HUNCH_CONNECTOR_MODE` selects
   `live` (URLs per venue) or `simulated`.
2. **Interactive Brokers executes manually.** An approved proposal for an IBKR account is an order
   list the person places at IBKR; the next holdings capture reconciles the fund. Links to IBKR
   accounts carry `ownership_verified: false` because the connector reports no owner; the site and
   the Agent say so. Automatic execution follows the connector's OAuth work (plan §6.2).
3. **Ownership lives in Hunch.** `HunchUserProfileAccount` is the only place that says whose
   account a connector `Account` is. A link is accepted when the connector reports the acting
   user as the credential owner (Alpaca, simulated) and refused when another Hunch user already
   linked the account. Credentials never pass through Hunch: live linking points the person at the
   connector's own registration flow.
4. **Funding records.** `HunchFunding` (one per take: linked account, target notional, status
   `planned → pending_initial → active → withdrawing → closed | failed`, autopilot policy as JSON
   on the funding rather than a separate table) backed by an ms-markets `VirtualFund`
   (`HUNCH_FUND__<take>__<account>`, account × take portfolio) whose `VirtualFundHoldingsTS` is
   Hunch's ledger of the take's slice of the account (positions and its cash, positive quantities
   with direction). Each funding also publishes the intent as an account target: allocation model
   `hunch`, `AccountTargetAllocation`, `PositionSet`, one `TargetPositionsTS` portfolio row with
   `constant_notional_exposure`. ms-markets' allocation planner is not used: it needs exact-time
   holdings, targets and a valuation resolver Hunch would have to supply anyway, and Hunch's legs
   are a direct function of weights × notional ÷ last close netted against the fund.
5. **Proposals are the state machine.** `HunchRebalanceProposal` holds the legs (side, quantity,
   estimated price and notional, reason), the trigger (`initial`, `drift`, `thesis`, `user`,
   `withdrawal`), the status (`proposed`, `approved`, `rejected`, `expired`, `submitted`,
   `partially_filled`, `filled`, `failed`), the autopilot check, the deciding person and the
   `OrderManager` batch (`HUNCH_BATCH__<proposal>`). Legs are computed in code
   (`compute_legs`): sells before buys, whole shares when the venue is not fractionable, buys
   scaled to the available cash with a note, a one-dollar minimum per leg. Proposals expire after
   the next session close.
6. **Approval and autopilot.** In approval mode the person approves (API, site or Agent tool); the
   service re-checks expiry and submits. In autopilot, `autopilot_check` enforces the funding's
   policy (turnover per day, per-order notional, single-name weight, new instruments, trading
   window) and submits within it, otherwise the proposal waits for approval with the reasons.
   Withdrawal is approved by the request itself.
7. **Execution sync** books fills into the fund (`applied_fills` on the proposal keeps the sync
   idempotent), settles the proposal, activates or closes the funding, moves the take between
   `funding`, `active_funded` and back to `active_practice`, and notifies. The `hunch-execution-sync`
   Job runs it every 15 minutes during US sessions and expires stale proposals.
8. **Daily review** (`hunch.reviews`): for every active take, drift of the current weights (the
   fund's weights when funded, the model portfolio's otherwise) against the basket, a thesis check
   (recorded completion with a schema, or the deterministic reviewer), an outcome (`hold`,
   `flagged`, `proposed`, `executed`) and a notification. Funded takes above the drift thresholds
   get a proposal through the review hook. The `hunch-daily-review` Job runs on session days before
   the open.
9. **Leaderboard** ranks published, activated takes by the model portfolio's return since
   activation (consistent across practice and funded; `is_simulated` labels practice periods),
   snapshotted nightly by `hunch-leaderboard` and computed live when no snapshot exists.
   **Notifications** are rows created by services and Jobs and read by the site and the Agent.
10. **Agent surface.** Six more tools (`hunch_accounts`, `hunch_funding`, `hunch_proposals`,
    `hunch_reviews`, `hunch_leaderboard`, `hunch_notifications`) over the same services, two
    published skills, and a prompt that makes funding, approving and withdrawing explicit-consent
    actions.

## Consequences

- Locally (`scripts/dev_stack.sh`, `HUNCH_CONNECTOR_MODE=simulated`) the whole funded loop runs
  against the MetaTables runtime: link → fund → approve or autopilot → fills → review → withdraw,
  with every record in ms-markets tables.
- Hosted, Alpaca accounts can be linked and read today; automatic execution waits for the
  connector's execution capability (plan §6.1), after which no Hunch change is needed beyond
  setting `HUNCH_ALPACA_CONNECTOR_URL`. IBKR is manual until its OAuth work lands.
- The service-to-service call path from the Hunch workload to a connector release (caller
  assertion, release URL) is implemented as a bearer/`X-Resource-Release-UID` client and still
  needs the Phase 0 spike against a hosted release before the first live funding.
- The `OrderEventsTS` table is not written (its asset-index contract is defective in ms-markets
  2.2.12); order state lives on the proposal and in `OrdersTS`.
