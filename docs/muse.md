# How Hunch uses Muse

Every model call in Hunch runs on Meta's Muse models, through the Meta Model API. Muse runs in two
places:

- **The Hunch Agent's conversation.** It talks with the person and acts through Hunch's MCP tools.
- **Hunch's own model calls.** Research, the daily review and the thesis critique run as
  recorded-inference requests: each is bounded, constrained by a schema and recorded by the
  platform.

The model reasons and proposes. Code decides the weights, the limits and the orders.

## Where Muse runs

| Role | Model and thinking level | What it does | Code | Declared in the workflow file |
| --- | --- | --- | --- | --- |
| Hunch Agent | Muse Spark 1.3, `medium` | Talks with the person about their takes and acts through Hunch's MCP tools | [`api/agent/main.py`](../api/agent/main.py), [`.tau/SYSTEM.md`](../.tau/SYSTEM.md), [`src/hunch/agent_tools.py`](../src/hunch/agent_tools.py) | [lines 135–137](../.mainsequence/workflows/hunch-api.yaml#L135-L137) |
| `research` | Muse Wonder 1.0, `medium` | Researches a take against the instrument universe. It returns the claims, the beneficiaries and losers, and 3 to 20 candidates, each with a role, a case, risks, a conviction and cited evidence | [`inference_research`](../src/hunch/research/inference.py#L291) | [lines 221–222](../.mainsequence/workflows/hunch-api.yaml#L221-L222) |
| `review` | Muse Spark 1.3, `medium` | The daily thesis check of each active take. It returns `hold`, `rebalance` or `thesis_change` with its reasoning, the triggered "change my mind" conditions and a confidence. Its evidence includes the last 3 days of news when a news source is configured | [`inference_thesis_check`](../src/hunch/reviews/services.py#L148) | [lines 335–336](../.mainsequence/workflows/hunch-api.yaml#L335-L336) |
| `analysis` | Muse Spark 1.3, `low` | The thesis critique the Agent offers while a take is written. It returns the claims and their strength, the assumptions, counterarguments, risks, suggested conditions and questions | [`inference_critique`](../src/hunch/analysis/services.py#L200) | [lines 108–109](../.mainsequence/workflows/hunch-api.yaml#L108-L109) |

[ADR 0007](adrs/0007-model-roles-and-analysis-tools.md) explains why each role has its own model:

- **Research** is the one step where the strongest model pays, so it gets Muse Wonder 1.0.
- **The analysis role** answers a person synchronously inside the API's deadline, so it reasons at
  `low`.
- **The Agent and the review** stay on Muse Spark 1.3.

A role is configuration, not code: `HUNCH_MODEL_<ROLE>` sets `model=… thinking=…` over a shared
selection (`HUNCH_INFERENCE_*`). A malformed setting fails the call; it never silently falls back to
another model ([`hunch.settings.model_role`](../src/hunch/settings.py#L195)).
`GET /v1/project-state/configuration` reports every role.

## How one model call is made

All three roles go through [`recorded_completion`](../src/hunch/research/inference.py#L231), which
sends one request to the platform's recorded inference with:

- a system prompt and a user prompt;
- a JSON schema the answer must match;
- the role's model, thinking level and credential (`custom_id: meta`);
- metadata naming the operation, the role and the take;
- a request key naming the operation and the take (for research, also its number), with a random
  suffix, so every call, a retry included, is its own recorded request and traces back to its take.

The platform holds the Meta Model API key (the `meta` credential), sends the request to the Meta
Model API (`https://api.meta.ai/v1`, Chat Completions) and records the request and the answer.
The Hunch Agent reaches Muse the same way, through the platform's `meta` provider. Hunch holds no
provider client and no key. Each workload declares the credential it may use under
`access.model_providers` in the workflow file:
- the `hunch` API, for the critique;
- `hunch-take-research`;
- `hunch-daily-review`.

The build Job holds none: it calls no model ([ADR 0008](adrs/0008-research-and-construction-are-separate-steps.md)).
Every stored research keeps the provider, the model and the recorded request UIDs that produced it.

## The research contract

The [system prompt](../src/hunch/research/inference.py#L28) tells the model to:
- pick instruments only from the universe it is given, by exact ticker;
- cite the evidence ids it relies on (`[E3]`) and never invent a source;
- respect the person's constraints;
- never promise returns.

It defines each role precisely. `pure_play`, for example, means the thesis is the instrument's
business, and the prompt describes every field of the answer.

The evidence it cites is a numbered list:
- price facts computed from Hunch's daily bars. With `HUNCH_BARS_PROVIDER=alpaca` these are the
  Alpaca connector's stored bars ([ADR 0009](adrs/0009-daily-bars-come-from-the-connected-venue.md));
  every run below used synthetic bars, a deterministic series per instrument;
- news and fundamentals, when a Finnhub key is configured.

The [response schema](../src/hunch/research/inference.py#L97) bounds the answer:

| Field | Bound |
| --- | --- |
| Claims | 1 to 10 |
| Candidates | 3 to 20 |
| Each candidate's case | at least 1 character, at most 600 |

Strict mode on Muse accepts `minItems`, `maxItems`, `minLength` and `maxLength`. We checked this
on 2 November.

Code checks the answer again, because strict mode may accept a keyword without enforcing it. An
answer with no claim, or with a candidate that has no case, is retried once, and the retry prompt
names the empty fields. A second incomplete answer fails the research rather than storing it. The
research keeps both request UIDs.

## The model proposes, code decides

- **Research sets no weight.** [`construct_basket`](../src/hunch/research/__init__.py#L63) turns the
  candidates into weights with no model call. It enforces the take's exclusions, tradability,
  leveraged products, the position count, the single-name cap and the cash buffer, and reports
  every decision.
- **No model touches money.** The Agent's tools and the model never call a broker connector. Only
  `hunch.funding.services` submits orders, and only for one of three reasons:
  - a proposal the person approved;
  - a proposal that passed [`autopilot_check`](../src/hunch/funding/services.py#L316) inside limits
    the person set;
  - a withdrawal.
- **The Agent cannot overreach.** Its tools take no credentials and no UIDs of people. Archives and
  deletes need the exact text `DELETE <uid>`. Long work starts a Job and returns its run UID.

## What we measured on Muse

A full real answer, with the basket the guardrails built from it and the platform's record of the
request, is in [docs/examples](examples/README.md); `uv run scripts/check_example_research.py`
checks it against the code with no credentials.

These are dated, so they can be checked against ADRs 0007 and 0008 and the platform's recorded
requests.

| Date | What happened |
| --- | --- |
| 1 Nov 2026 | The platform accepted Meta in recorded inference. The same day a build (JobRun `4c8c75e8`, request `2e564635`; builds still ran research until ADR 0008 split them later that day) and a critique (request `0d665f6c`) completed on Muse Spark 1.3, with Hunch's schemas unchanged. The Hunch Agent moved to Muse Spark 1.3. |
| 2 Nov 2026 | Research moved to Muse Wonder 1.0. The first research on Spark 1.3 had returned 4,102 output tokens in 29 seconds; Wonder's first took 31 seconds. |
| 2 Nov 2026 | A Wonder research on development came back schema-valid but empty (no cases, no claims). It also tagged two electric utilities as pure plays on a water thesis. The fix: tighter schema bounds, every field and role described in the prompt, the code check and the one retry. |
| 2 Nov 2026 | A local Wonder run on the stricter schema filled five claims and all eleven cases on its first call, in 33.6 seconds. The role definitions were added after that run. |
| 3 Nov 2026 | A local Wonder research with the role definitions in its prompt filled seven claims and eight cases on its first call: 30.2 seconds from request to answer in the platform's record (request `3ac2815c`, [exported](examples/muse-wonder-recorded-request.json)). |
| 4 Nov 2026 | For the film's take on the local stack: the critique answered in 27.7 seconds, research 1 in 42.3 seconds (request `126463af`; 6 claims, 8 candidates) and the daily review in 17.5 seconds ("hold"). |
| 4 Nov 2026 | The 2 Nov water thesis (take `3cfdd6d6`'s title, thesis and constraints), run again on the local stack with the role definitions: request `63879db7`, 49.0 seconds in the platform's record, seven claims and six cases on the first call. The mis-tag is gone: no candidate is a `pure_play`, and the rationale says the universe holds no water utility and that an electric utility is not a pure play on water. |

Per role, from the platform's recorded requests in Hunch's development and Production Environments
(listed through `GET /api/v1/inference/conversations/` at 13:12 UTC on 4 Nov, plus the 17:08 water
re-run). Latency is the platform's time from request to answer:

| Role (model) | Calls | Complete on the first call | Retried | Median latency (range) |
| --- | --- | --- | --- | --- |
| `research` (Wonder 1.0) | 7 | 5; the 2 incomplete answers came on 2 Nov, before the code check and the retry existed | 0 | 32.4 s (26.7 to 49.0) |
| `research` (Spark 1.3, until 2 Nov) | 2 | 2 | n/a | 19.1 and 28.4 s |
| `analysis`, the critique (Spark 1.3) | 5 | 5; a critique is one call with no retry | n/a | 22.5 s (13.3 to 27.9) |
| `review` (Spark 1.3) | 5 | 5; a review is one call with no retry | n/a | 18.9 s (13.5 to 26.6) |
| Hunch Agent (Spark 1.3) | not measured | | | |

Every research answered inside the platform's 60-second transport limit.

**What is verified, and what is not.**
- **Role definitions:** verified on two theses. The 3 Nov research ran with them (the check script
  confirms its recorded prompt is the code's), and the water re-run no longer calls an electric
  utility a pure play.
- **The retry:** it has not fired in a recorded run. No recorded research request carries
  `attempt: 2`, and all four since the retry existed were complete on the first call. Only the
  tests in [`test_research_inference.py`](../tests/test_research_inference.py) exercise it.
- **Scale:** seven Wonder research calls are a log, not a sample, so there is no failure rate yet.

The platform's limits shaped the design:
- **Thinking level:** one request gets 60 seconds of transport, which is why research stays at
  `medium`.
- **Concurrency:** an Organization can run four recorded requests at once. The scheduled sweep
  therefore runs at most three reviews at a time, which keeps a slot free for a person's own
  critique.

## Next: Hunch inside Muse

The film ends on Hunch plugged into the Muse app as an agent. This is **coming soon** and not
available today. Hunch already has the pieces an assistant needs to call it:
- its operations served as MCP tools at `/mcp`;
- skills published from [`.agents/skills/mcp_tools/`](../.agents/skills/mcp_tools/);
- an [agent card](../.agents/agent_card.json).

Every action keeps the same guardrails, whichever assistant calls it.
