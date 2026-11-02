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

## Incomplete research answers (2026-11-02)

On development the research of take `3cfdd6d6` (research `a037d2e2`) on Muse Wonder 1.0 came
back schema-valid but empty: no candidate had a `case`, the brief had no `claims`, and two
electric utilities (DUK, NEE) were tagged `pure_play` on a water-utilities thesis. The schema put
no lower bound on those fields and the prompt never described them. Since then:

- The research schema requires at least one claim and a non-empty `case` on every candidate
  (`minItems`, `minLength`). The system prompt describes every field of the answer and every
  role. `pure_play` means the thesis is the instrument's business: a company in a neighbouring
  industry, or a diversified one with one exposed division, is not a pure play, and when the
  universe holds none no candidate takes the role.
- Code checks the same fields, because a provider's strict mode may accept these keywords
  without enforcing them (ADR 0007: Meta's documented strict subset does not mention the size
  keywords). Blank claims are dropped and cases are trimmed. An answer with no claim, or with a
  candidate without a case, is **retried once**: a second recorded request whose prompt names the
  empty fields, with `attempt: 2` in its metadata and the idempotency prefix
  `hunch-take-<uid>-research-<n>-retry`. The research keeps both request UIDs. A second
  incomplete answer fails the research with a `ResearchError` (502 `research_unavailable` through
  the API, exit 1 in the Job) and stores no row. An answer that does not match the contract still
  fails at once, without a retry.
- A retry rather than an immediate refusal, because an empty field is a lapse of one answer, not
  of the configuration: refusing would only make the person start the same research again. One
  retry costs at most one more call (the first Wonder research answered in 31 seconds) inside the
  Job's 30-minute limit. Only one, because a model that leaves the fields empty twice points at
  the model or the prompt, and that should surface as a failure.
- Research stored before this change may have empty cases or claims; it reads back and builds as
  before. Roles cannot be checked in code: the prompt is their only control, and the guardrails
  still size by role.
- Meta accepts `minLength` as well as `maxLength`, `maxItems` and `minItems`. A local run of Muse
  Wonder 1.0 with the stricter schema and the field descriptions, before the role definitions
  were added, filled five claims and all eleven cases on its first call (33.6 seconds). It still
  tagged NEE and DUK `pure_play`, so the role definitions are not yet verified on Wonder.

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
