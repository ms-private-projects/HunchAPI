---
name: hunch-accounts-and-funding
description: Link a person's Alpaca or Interactive Brokers account, fund a take into it, and handle the trade proposals, approvals, autopilot limits and withdrawals through Hunch MCP tools.
---

# Linked Accounts, Funding And Execution

Discover current schemas with `hunch__list_tools`, then use `hunch__call_tool` with `tool` and
`arguments`. The API verifies caller/requester identity; never supply a person's UID. You never
talk to a brokerage: Hunch's services call the venue connectors deterministically and you record
the person's decisions.

## Linked accounts (`hunch_accounts`)

- `list`: the person's linked accounts with venue, paper/live, status, cash and equity.
- `linkable`: accounts the venue connector registered for the person that are not linked yet.
- `link`: link one account (`venue`, optional `account_uid`). Brokerage keys are entered on the
  connector's site, never in chat; when a person has none registered, send them there. In the
  simulated local mode `link` without `account_uid` creates a paper account with cash.
- `holdings`: the latest holdings snapshot of a linked account (`capture: true` asks the
  connector for a fresh one).
- `revoke`: stop using the account; funded takes in it must be withdrawn first.

A link whose `ownership_verified` is false (Interactive Brokers today) was accepted on the
person's word because that connector reports no owner; say so when it matters.

## Funding (`hunch_funding`)

- `fund`: fund a built or practice take into a linked account with `request`
  `{profile_account_uid, target_notional, execution_mode: approval|autopilot, autopilot_policy?}`.
  Hunch creates the ms-markets virtual fund and the initial proposal. In **approval** mode the
  trades wait for the person; in **autopilot** they execute at once when the policy allows
  (turnover, per-order notional, single-name weight, new instruments, trading window), otherwise
  they become a proposal. The answer carries the funding and the proposal.
- `withdraw`: sell the funded positions back to cash. The person's request is the approval; the
  take continues in practice mode.
- `list`, `get`, `for_take`: fundings with NAV, cash, invested amount, positions and return on the
  funded notional.

Before `fund` or `withdraw`, show the person the target, the account and the effect, and get their
go-ahead in their own words. Funding needs the account to hold at least the target notional in cash.

## Proposals (`hunch_proposals`)

- `list` (`status`, `take_uid`, `open_only`), `get`: the legs (side, ticker, quantity, estimated
  price and notional, reason), the trigger (initial, drift, thesis, user, withdrawal), the status
  (proposed, approved, rejected, expired, submitted, partially_filled, filled, failed), the
  autopilot check and the order states.
- `approve`: submit the trades to the venue connector. Only after the person approves in their
  own words. Proposals expire after the next session close.
- `reject` (optional `reason`).
- `sync`: refresh order states and book fills; the scheduled sync Job does this too.

Interactive Brokers executes manually: an approved proposal is an order list the person places at
IBKR, and the next holdings capture reconciles the take. Say so.

```json
{"tool":"hunch_proposals","arguments":{"operation":"approve","proposal_uid":"PROPOSAL_UID"}}
```

## Daily reviews (`hunch_reviews`)

- `run`: review the take now (drift against the basket, thesis check, proposal when funded).
- `list`: past reviews with verdict, drift and summary.

## Disclosures

Hunch is not an investment adviser; the person instructs. Estimates use the last stored close and
fills happen at market prices. Funded results are real money in the person's own account.
