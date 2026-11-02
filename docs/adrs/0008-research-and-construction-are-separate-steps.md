# ADR 0008: Research and portfolio construction are separate steps

- **Status:** Accepted
- **Date:** 2026-11-01
- **Scope:** How a thesis becomes a basket: the research of the target universe, the
  construction of the portfolio from it, what each step stores, which Job runs it, and how the
  API and the Hunch Agent expose them

## Context

Until this decision a build was one chain in one Job: research the thesis against the universe,
apply the constraints, publish the weights, run the portfolio graph. The research output lived
only inside the revision it produced. A person or the Agent could not research without building,
could not read the candidates before weights existed, and could not build again from a research
they kept. The one model call Hunch makes for a build (the `research` role, ADR 0007) and the
deterministic construction therefore shared a Job, a credential and a timeout.

The product treats them as two different things. Researching the target universe is the model's
work: which instruments express the thesis, in which role, with what conviction and evidence.
Constructing the portfolio is Hunch's work: exclusions, tradability, leveraged products, the
position count, the single-name cap and the cash buffer, enforced by rules that report every
decision. The strongest model belongs to the first; no model belongs to the second.

## Decisions

1. **Research is its own step and its own record.** `hunch.research.runs.run_take_research`
   reads the universe and the evidence, calls the configured researcher (the `research` role's
   recorded completion, or the deterministic heuristic) and stores the answer as a
   `HunchTakeResearch` row (`hunch.takes.research`): the brief, the candidates with roles,
   cases, risks, conviction and citations, the rationale, the evidence consulted, the provider
   and model that answered and the recorded request UIDs. Research rows are numbered per take
   (`number`, unique with `take_uid`); the recorded call is idempotent per research
   (`hunch-take-<uid>-research-<n>`) and carries `research_number` in its metadata. A research
   decides no weight.
2. **Construction starts from a stored research.** `hunch.portfolios.build.build_take` takes a
   `research_uid` (the take's latest research by default), re-reads the research as a
   `ResearchOutput`, applies the take's constraints through `hunch.research.construct_basket`
   (the guardrails, no model), publishes the basket and (re)builds the portfolio. A take that was
   never researched cannot be built (`TakeStateError`, 409 through the API). The revision records
   `research_uid` (revision 0005 adds the table and the nullable column, SET NULL on delete) and
   keeps a copy of what it was constructed from in `research_json`, so a revision reads on its
   own and the site's revision view is unchanged. The research may be older than the universe:
   the guardrails drop a candidate that is no longer tradable or in the universe, and say so.
3. **Two Jobs, one credential.** `Hunch Take Research` (`src/jobs/run_hunch_take_research.py`,
   `--take-uid`, optional `--research-mode`) holds the research role's model share under
   `access.model_providers`; `Hunch Take Build` (`--take-uid`, optional `--research-uid`) calls
   no model and holds no share. The API holds `runner` on both. `HUNCH_BUILD_EXECUTION` decides
   for both steps whether they run inline (local) or as the Job (hosted), as before. The new Job
   is a new workload User: it needs `data_writer` on `hunch` and `editor` on the series tables it
   writes (the daily bars), granted by the namespace owner after the first push creates it.
4. **The API and the Agent expose both steps.** `POST /v1/takes/{uid}/actions/research` starts a
   research (the owner only; inline answer or `job_run_uid`), `GET /v1/takes/{uid}/research`
   lists the take's research latest first and `GET .../research/{research_uid}` reads one (anyone
   who can read the take). `POST .../actions/build` takes `research_uid` instead of a research
   mode. The Agent gets `hunch_research_take` (`run`, `list`, `get`); `hunch_build_take`'s
   `build` takes `research_uid`. Neither tool takes a person's UID or a credential.
5. **The review and the critique are unchanged.** The daily review's thesis check (the `review`
   role) and the thesis critique (the `analysis` role) are their own calls and read no research
   row.

## Consequences

- The research role can run on the strongest model and the build Job needs no model at all;
  each step has its own Job timeout and its own JobRun to follow.
- A person can research again without rebuilding, compare research runs, and build from the one
  they prefer; the Agent can show the candidates before any weight exists.
- The site keeps working on `actions/build` and `/revisions`, but a take must be researched
  before it is built: the site needs a research step before its build button, and until then a
  build of a never-researched take answers 409 `action_conflict`.
- Revisions built before revision 0005 have no `research_uid`; their `research_json` copy stays
  readable.
