---
name: hunch-community
description: Read the Hunch leaderboard of published takes and the person's notification feed through Hunch MCP tools.
---

# Leaderboard And Notifications

Discover current schemas with `hunch__list_tools`, then use `hunch__call_tool`.

## Leaderboard (`hunch_leaderboard`)

`get` returns published takes ranked by return since activation, with days active, whether the
period is simulated (practice) or funded, the owner's handle and fork attribution. Quote the
snapshot date and say that practice results are simulated. A person can fork a leaderboard take with
`hunch_manage_take` operation `fork`.

## Notifications (`hunch_notifications`)

- `list` (`unread_only`): build results, daily review summaries, proposals awaiting approval,
  executions, funding and account events, newest first, with the unread count.
- `mark_read` (`uids` optional): mark some or all notifications read.

When a notification says a proposal awaits approval, offer to show it with `hunch_proposals`.
