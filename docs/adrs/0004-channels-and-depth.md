# ADR 0004: Channels and depth

- **Status:** Accepted
- **Date:** 2026-10-25
- **Scope:** Performance metrics, grounded research sources with citations, the email digest
  channel, and what the platform does not offer for inbound channels (plan phase 4)

## Context

Phase 4 of the plan asks for status updates and replies by email "through A2A", research that
cites sources, and risk metrics. A survey of the installed SDKs (mainsequence 9.0.32, ms-tau-sdk
2.0.26) found: a platform `Notification.send(..., include_email=True, target_user_uid=...)` whose
email delivery the backend performs (its sender, template and authorisation are undocumented);
`User.get_by_uid(uid).email` for a person's address; A2A messaging from a Job to a deployed Agent
(`Agent.get_or_create_session`, `AgentSession.send_a2a_message`) that carries only the Job's
workload identity, never a person (`acts_for_requester` covers only `fastapi` and `harness_agent`
resources); and no inbound email, webhook or push channel for a Harness Agent (A2A push
notifications are explicitly rejected; `public_ingress` exists only for `fastapi` releases).

## Decisions

1. **Metrics are computed from the value series, in code** (`hunch.portfolios.metrics`): total
   and annualised return, annualised volatility, Sharpe (zero rate), maximum drawdown, best and
   worst day, session count; null until two sessions. They ride on the performance frame's
   `source.context.metrics` and on leaderboard entries.
2. **Research sources are a port** (`hunch.research.sources`): `quant` (facts from the stored
   bars, always on) and `finnhub` (company news and basic financials, `HUNCH_FINNHUB_API_KEY`).
   `collect_evidence` numbers the items (`E1..En`), the researcher cites them (`[E3]` in the
   rationale and `citations` per candidate; the schema requires the field so the model always
   answers it), the revision stores them (`research_json.evidence`), and the daily thesis check
   receives the last three days of news. Without a configured news source the rationale says so.
   No source is ever simulated or invented, so there is no fixture news provider.
3. **Email is an outbound digest, not a conversation.** `hunch.channels` composes one
   deterministic Markdown digest per opted-in person from their notifications not yet delivered by
   email plus their pending proposals, and sends it through a sender port: `platform` (the
   Main Sequence Notification with `include_email`, the hosted default), `outbox` (`.eml` files,
   the local default), `smtp` (Secrets-mapped environment), `none`. Delivery is recorded on the
   notification (`delivered_channels_json`), so reruns never repeat. The `hunch-email-digest` Job
   runs after the daily reviews. Preferences (`email_digest`, optional `email_address` overriding
   the platform user's email) live on the profile.
4. **Replies by email are out of scope until the platform offers an inbound channel.** The digest
   points the person to the Assistant and the site. Composing the digest with the Agent over A2A
   was rejected: a Job-owned session carries no person, so the Agent's Hunch tools would see
   nothing of that person's takes; a deterministic composition is both correct and cheaper.

## Consequences

- Locally: `HUNCH_EMAIL_SENDER=outbox` writes the digest to `.hunch-outbox/` (git-ignored); the
  Job accepts `--dry-run` and `--user-uid`.
- Hosted: the platform sender needs confirmation that a Job workload may send notifications with
  email to a person and what the message looks like; `HUNCH_SITE_URL` must be set for links.
- Open: an inbound email or chat channel for the Agent waits on the platform; risk metrics could
  move to a nightly analytics snapshot if the leaderboard grows.
