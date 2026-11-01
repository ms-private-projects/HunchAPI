# ADR 0007: Model roles and analysis-only tools

- **Status:** Accepted
- **Date:** 2026-11-01
- **Scope:** Which model each kind of model call in Hunch runs on, how a deployment mixes models,
  and the shape of the analysis-only tools the Hunch Agent offers (first: the thesis critique)

## Context

Hunch calls a model in two places. The Hunch Agent runs a conversation on the one provider, model
and thinking level its Harness Agent declaration names in `.mainsequence/workflows/hunch-api.yaml`
(`llm_provider`, `llm_model`, `llm_thinking`); Tau gives a session exactly one model and no
per-tool override. Hunch's own code calls a model through the platform's recorded inference
(`InferenceClient.complete`, ADR 0002): one bounded, schema-constrained, idempotent request whose
provider, model, thinking level and credential are chosen per call, whose credentials the platform
holds, and whose history the platform records. Until now every such call used one shared
selection (`HUNCH_INFERENCE_PROVIDER`, `HUNCH_INFERENCE_MODEL`, `HUNCH_INFERENCE_THINKING`).

The product wants a mix: a conversational model for the Agent, and specific models for specific
kinds of analysis. The platform facts that bound the design (read from the backend on
2026-11-01):

- Recorded inference has adapters for the `openai` (Responses and Chat Completions), `anthropic`
  (Messages), `openrouter` (Chat Completions) and Ollama families and for any Organization custom
  endpoint speaking an OpenAI protocol. It refuses `openai-codex` (the subscription OAuth
  credential the Jobs declared until 2026-11-01, which is why research ran in `heuristic` mode).
  It refused the new built-in `meta` provider (Muse Spark 1.1 to 1.3, Muse Wonder 1.0, published
  2026-10-28) until backend commit 4f844bdf8 of 2026-11-01 added Meta as a Chat Completions
  family.
- A recorded request has a 60-second transport timeout and a 90-second deadline, and an
  Organization may have four requests active at once.
- A workload calls recorded inference as itself: the credential must be shared with that workload's
  User through `access.model_providers` in the workflow file. The API's workload holds none today;
  the two Jobs hold `openai-codex`.
- The Hunch Agent can run on Meta once `ms-tau-sdk` is at least 2.0.28 (it reads the hydrate
  field `catalog_definition` that carries Meta's address) and a Meta key is stored in the target
  Environment; Production holds one, development does not.

## Decisions

1. **Model roles.** Each kind of recorded model call is a role: `research` (a take build),
   `review` (the daily thesis check) and `analysis` (analysis-only tools). `hunch.settings.model_role`
   resolves a role to a `ModelSelection` (provider, model, thinking, credential): the shared
   `HUNCH_INFERENCE_*` values, then the role's `HUNCH_MODEL_<ROLE>` override as space-separated
   `key=value` pairs (`provider`, `model`, `thinking`, `credential`), so model identifiers may
   contain `/` and `:`. A malformed override fails the call with a `ResearchError`, never silently
   falls back. `recorded_completion` takes the role, passes the credential as `custom_id` and
   records the role in the request metadata. `GET /v1/project-state/configuration` reports every
   role under `research.models`.
2. **The Agent keeps one model.** Mixing happens below the Agent: it converses on its declared
   model and calls tools; the tools that need a model call recorded inference on their role. No
   second Agent, no per-tool model override in Tau, no provider client in Hunch.
3. **Analysis-only tools.** An analysis reads Hunch tables, makes one bounded recorded completion
   on the `analysis` role, validates the answer against a JSON schema in code, and returns it to
   the person. It never changes Hunch state, never trades, and is not persisted (the platform's
   recorded conversation is the audit trail; the response carries the request UID). It runs
   synchronously in the API within the platform's deadline, so prompts stay small and heavy work
   stays in Jobs. In `heuristic` research mode a deterministic reading answers instead and says
   so in `mode`, so the local stack and the tests need no provider. The first tool is the thesis
   critique (`hunch_analyze_take` operation `critique_thesis`, `POST
   /v1/takes/{uid}/actions/critique-thesis`): summary, clarity, claims with their strength,
   assumptions, counterarguments, risks, suggested change-my-mind conditions, constraint notes
   and questions. Later analyses (explain a basket, compare takes, summarise a review) follow the
   same shape in `hunch.analysis`.
4. **Declared access follows the role.** A workload that runs a role declares the role's
   credential under `access.model_providers`. The API therefore needs the analysis role's
   credential before `HUNCH_RESEARCH_MODE=inference` is set on it; the workflow file documents
   this and leaves the share to an explicit decision, because every push keeps it and the
   credential's owner pays for its use.
5. **The scheduled sweep dispatches instead of holding a credential.** The review dispatcher
   Job owns the schedule but no model credential. With `HUNCH_REVIEW_DISPATCH=job` its launcher
   starts one `Hunch Daily Review` Job run per active take (`hunch.operations.reviews.dispatch_reviews`),
   three at a time, and follows each batch to its end before starting the next, because the
   platform admits four recorded model calls per Organization at once and a person's own review
   or critique must keep a slot. A run that cannot start, fails or is still pending after half an
   hour is reported and the sweep goes on; the exit code is 1 when any take failed. Locally
   (`inline`) the sweep reviews in its own process as before. The portfolio refresh dispatcher
   still refreshes in its own process: it calls no model.

## Development declaration (2026-11-01)

With the owner's approval, the `hunch` API, `hunch-take-build` and `hunch-daily-review` declare
the Environment's Meta credential (`provider: meta`, `custom_id: meta`, `policy: user`) and run
with `HUNCH_RESEARCH_MODE=inference`: the shared selection is `meta` / `muse-spark-1.3` /
`medium`, the research and review roles keep it, and the analysis role reasons at `low` because it
answers a person synchronously. Meta offers no `off` level. An OpenRouter share declared earlier
the same day was replaced once the backend accepted Meta; it never completed a call, because that
key had no credit. The review dispatcher holds no share: since decision 5 it starts review Job
runs, which hold it. Every later push keeps the share, and usage is billed to the credential's
owner. Verified the same day: a build (JobRun 4c8c75e8, recorded request 2e564635) and a critique
(request 0d665f6c) completed on `muse-spark-1.3` with Hunch's schemas unchanged.

## Consequences

- One deployment can research on one model, review on another and analyse on a third, from the
  workflow file alone.
- Which credential a workload runs on is a declared-access decision, not a code change: the
  roles only name what the Environment shares with the workload.
- Hunch's schemas use `maxItems` and `maxLength`, which Meta's documented strict subset does not
  mention; the first recorded call on Meta decides whether those keywords stay.
