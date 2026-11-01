---
name: hunch-take-authoring
description: Help a person write, refine, publish, fork and archive their takes (investment theses) and keep their Hunch profile through Hunch MCP tools.
---

# Writing And Managing Takes

Discover current schemas with `hunch__list_tools`, then use `hunch__call_tool` with `tool` and
`arguments`. The API verifies caller/requester identity; never supply a person's UID. When
readiness is unknown, call `hunch_project_state` first.

## What a take is

A take is the person's thesis about where the world is headed, in their own words, plus the
constraints Hunch must respect when it builds the basket: horizon in months, cash buffer, maximum
single-name weight, maximum number of positions, exclusions, whether leveraged or inverse products
are allowed, risk level, and the conditions that would change their mind. Help the person say the
thesis clearly before creating it; do not invent constraints they did not express. Defaults are
a 12-month horizon, 5% cash, 15% maximum per name and 15 positions.

## Create and edit

`hunch_manage_take` operation `create` takes a `request` with `title`, `thesis_text`,
optional `constraints` and `execution_mode` (`practice` by default). Show the person what you will
send, then send it once. `update` changes `title`, `thesis_text` or `constraints` of an owned take.
`set_execution_mode` switches between `practice`, `approval` and `autopilot`; explain that
approval and autopilot only matter once the take is funded, and that autopilot runs within the
person's limits.

```json
{"tool":"hunch_manage_take","arguments":{"operation":"create","request":{"title":"Robots at home","thesis_text":"Humanoid robots are coming to every home within the decade.","constraints":{"cash_buffer":0.08,"max_single_name_weight":0.12}}}}
```

## Read

`hunch_query_takes` operation `list` returns the person's takes (`scope` `mine`) or everyone's
published takes (`scope` `public`), newest first, with optional `status` and `search`. `get` reads
one take they own or that is public. Limits are 1–100 and offsets are multiples of the limit.

## Critique the thesis

`hunch_analyze_take` operation `critique_thesis` reads a take the person owns or a published one
and answers with an analysis only: a summary, how clearly the thesis is stated, each claim with
the weight it can carry, the assumptions, counterarguments, risks, conditions that would show the
thesis wrong, tensions with the constraints, and questions that would sharpen it. Nothing changes.
The call runs on the analysis model and can take a minute. Offer it before a research or before
publishing, relay the questions and the suggested conditions in the person's words, and let them
decide what to edit. When the answer's `mode` is `heuristic`, it is a deterministic reading of the
structure only: say so, and do not present it as a judgement of the claims.

```json
{"tool":"hunch_analyze_take","arguments":{"operation":"critique_thesis","take_uid":"<take uid>"}}
```

## Publish, fork, archive

- `publish` needs a built take; a draft has nothing to show. `unpublish` makes it private again.
- `fork` copies a published take (or one of the person's own) into their independent private
  draft and records the lineage; the original author keeps their take.
- `archive` needs the exact confirmation `DELETE <take uid>` typed by the person. Never supply it
  for them. Archiving keeps the record but hides it everywhere.

## Profile

`hunch_profile` operation `get` returns the person's handle, display name and email digest
preferences, created on first contact; `update` changes them. Handles are 3 to 32 lower-case
letters, digits and underscores and must be unique. `email_digest: true` opts the person into the
daily email digest (reviews, executions, proposals waiting for them); `email_address` overrides the
platform account's email, and an empty value clears the override. Set them only when the person
asks, and confirm the address back to them.

## Beyond authoring

Research and building (two independent steps: research the target universe, then construct the
basket from a stored research), performance, linked accounts and funding, proposals, reviews, the
leaderboard and notifications have their own skills; read the matching one before those workflows.
