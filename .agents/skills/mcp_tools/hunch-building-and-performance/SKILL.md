---
name: hunch-building-and-performance
description: Build a take's basket from its thesis, activate it as a practice take, and read its revisions, weights and performance through Hunch MCP tools.
---

# Building A Take And Reading Its Portfolio

Discover current schemas with `hunch__list_tools`, then use `hunch__call_tool` with `tool` and
`arguments`. The API verifies caller/requester identity; never supply a person's UID.

## Build

`hunch_build_take` operation `build` researches the take's thesis, applies the person's
constraints (cash buffer, single-name cap, position count, exclusions, leveraged products), publishes
the basket as the take's weight signal and computes its portfolio. Tell the person what a build does
before starting one, and build only owned takes.

- Locally the build runs inline and the answer carries the new revision: weights, cash, the
  rationale and the guardrail notes that explain every dropped or capped name.
- Hosted, the build is a platform Job: the answer carries `job_run_uid`. Report it and follow it
  with `hunch_get_job_run_status`; do not wait inside a turn. Then read the revision with
  `hunch_query_portfolio`.
- A rebuild adds a revision and rebalances the portfolio to the new basket; the history stays.
- `research_mode` overrides the configured mode: `inference` (a recorded model call) or
  `heuristic` (deterministic theme matching, no model). Use the default unless the person asks.

```json
{"tool":"hunch_build_take","arguments":{"operation":"build","take_uid":"TAKE_UID"}}
```

## Activate and refresh

`activate_practice` starts the performance record of a built take without investing money
(status `active_practice`); the take can then be published. `refresh` brings prices up to date and
extends the values; the daily refresh Job does this for every built take.

## Read

`hunch_query_portfolio`:
- `revisions`: every basket revision with weights, cash weight, candidates with roles and
  conviction, rationale and guardrail notes.
- `weights`: the latest portfolio weights by instrument, heaviest first, with the invested and
  cash fractions.
- `performance`: a tabular frame of values since activation, rebased to 1.0, with daily returns.
  Values are simulated until the take is funded; say so when quoting them.

```json
{"tool":"hunch_query_portfolio","arguments":{"operation":"weights","take_uid":"TAKE_UID"}}
```

## Instruments

`hunch_query_instruments` lists or searches the universe Hunch can hold (ticker, name, sector,
themes, flags such as etf, leveraged, inverse). Hunch never trades instruments outside it.

## Disclosures

Hunch is not an investment adviser and the person decides; research is an input, not a
recommendation. Returns are measured from activation and past performance does not predict future
results.
