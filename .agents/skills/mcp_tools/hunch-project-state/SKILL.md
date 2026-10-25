---
name: hunch-project-state
description: Inspect what this Hunch deployment can do, which venues it supports and its disclaimers, and read the takes of the person served through Hunch MCP tools.
---

# Hunch Project State And Takes

Discover current schemas with `hunch__list_tools`, then use `hunch__call_tool` with `tool` and
`arguments`. Direct MCP clients use those inner names and arguments with `tools/call`. The API
verifies caller/requester identity; never supply a person's UID. No shell, SQL or direct table
access exists.

## Readiness

Call `hunch_project_state` with empty arguments when readiness is unknown. It returns the
capability catalog (each capability's availability, contents and actions), the supported venues,
the deployed Agent and Environment, the person the call runs for, and the disclaimers Hunch shows.
A capability marked `partial` has its tables but not yet its actions; say so instead of promising
the action.

```json
{"tool":"hunch_project_state","arguments":{}}
```

## Reading takes

`hunch_query_takes` supports `list` (the person's own takes, newest first) and `get` (one take the
person owns or that is public). Limits are 1–100; offsets must be multiples of the limit.

```json
{"tool":"hunch_query_takes","arguments":{"operation":"list","limit":25,"offset":0}}
```

```json
{"tool":"hunch_query_takes","arguments":{"operation":"get","take_uid":"TAKE_UID"}}
```

A take carries its title, thesis text, structured constraints, status (`draft`, `built`,
`active_practice`, `funding`, `active_funded`, `archived`), execution mode (`practice`, `approval`,
`autopilot`), visibility and fork lineage. The basket, weights and performance come from the take's
Hunch portfolio and are not exposed by this release.

## What this release does not do

Creating or building takes, linking accounts, funding, proposals and execution are not available
yet. Tell the person plainly and explain what Hunch will do once they are.
