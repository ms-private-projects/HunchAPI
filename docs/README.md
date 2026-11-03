# Hunch documentation

New readers should start with the repository [README](../README.md): what Hunch is, the
hackathon timeline, the judge's guide, the demo film and how to run it. This folder holds the
rest.

## Start here

| Document | What it covers |
| --- | --- |
| [How Hunch uses Muse](muse.md) | Where Meta's Muse models run (the Hunch Agent and the research, review and analysis roles), how each call is bounded and recorded, the research contract, and the dated runs on Muse |
| [A take, end to end](walkthrough.md) | A sequence diagram of a take from a sentence to traded orders, the code behind every step, the guardrails and the tests by area |
| [A real research on Muse Wonder 1.0](examples/README.md) | One stored research, its claims, candidates and cited evidence, the basket the guardrails built from it, and screenshots of both in the site |

## Plans

| Document | What it covers |
| --- | --- |
| [0001 Hunch product and build proposal](planning/0001-hunch-product-and-build-proposal.md) | What Hunch is, its ontology (section 1), the architecture and the delivery plan |
| [0002 Hunch under the Markets API boundary](planning/0002-hunch-under-the-markets-api-boundary.md) | Moving Hunch to ms-markets 3.x and behind the Markets API |

## Decisions (ADRs)

| ADR | Decision |
| --- | --- |
| [0001](adrs/0001-phase-0-foundation.md) | The foundation: Hunch tables over ms-markets, the API, the one Agent and the workflow |
| [0002](adrs/0002-building-takes-on-ms-markets.md) | Building takes on ms-markets: the basket signal and the portfolio graph, recorded inference, rebuilding in the same session |
| [0003](adrs/0003-funding-and-execution-through-connectors.md) | Funding and execution through the Alpaca and Interactive Brokers connectors |
| [0004](adrs/0004-channels-and-depth.md) | Notifications, the email digest and channel depth |
| [0005](adrs/0005-ms-markets-3.md) | Hunch on ms-markets 3.x |
| [0006](adrs/0006-hunch-behind-the-markets-api.md) | Hunch reaches every market registry through the Markets API |
| [0007](adrs/0007-model-roles-and-analysis-tools.md) | Model roles (research, review, analysis), the Agent's model and the thesis critique |
| [0008](adrs/0008-research-and-construction-are-separate-steps.md) | Research and portfolio construction are separate steps and Jobs |

## Operations

| Document | What it covers |
| --- | --- |
| [Hosted deploy runbook](operations/hosted-deploy.md) | Environments and branches, release tags, the values and grants each workload needs, first-deploy findings and validation |

## Elsewhere in the repository

- [`.tau/SYSTEM.md`](../.tau/SYSTEM.md): the Hunch Agent's runtime instructions.
- [`.agents/skills/mcp_tools/`](../.agents/skills/mcp_tools/): the skills the API publishes for the
  Agent.
- [`.mainsequence/workflows/hunch-api.yaml`](../.mainsequence/workflows/hunch-api.yaml): every
  release, Job, schedule, model and grant the platform deploys.
- [`films/hunch-demo-video/`](../films/hunch-demo-video/): the demo film.
