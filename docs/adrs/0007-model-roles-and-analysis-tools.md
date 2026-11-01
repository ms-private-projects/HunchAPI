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
  credential the Jobs declare today, which is why research runs in `heuristic` mode) and the new
  built-in `meta` provider (Muse Spark 1.1 to 1.3, Muse Wonder 1.0, published 2026-10-28).
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

## Consequences

- One deployment can research on one model, review on another and analyse on a third, from the
  workflow file alone.
- The Jobs' `openai-codex` declaration cannot serve recorded inference; the switch to a provider
  with an adapter (for example the Environment's `openrouter` credential) is a deliberate access
  change, not a code change.
- Meta's models are reachable only as the Agent's conversation model until the platform adds a
  recorded-inference adapter for `meta`; a custom endpoint pointing at Meta's host would pass the
  adapter but sidesteps that refusal and is not taken without the platform owner's agreement.
