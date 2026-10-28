# Hosted deploy

How Hunch reaches the platform: what deploys from which branch, which values each Environment
needs, and the order that makes the pieces find each other. Nothing here holds a credential.

## Environments and branches (checked 2026-10-25)

| Environment | Branch | UID |
| --- | --- | --- |
| development | `development` | `58218213-5e4e-43de-a5bd-6757f4e1c8f6` |
| Production | `main` | `18595d12-f92a-4960-84cd-0c6798a1ad25` |

The platform deploys from pushes to an Environment's branch. `phase-0-foundation` (backend) and
`command-center-site` (site) are feature branches: pushing them deploys nothing. A deploy starts
when they are merged (or fast-forwarded) into `development`, then `main`.

Platform repository names: `HunchAPI` (this repository), `Hunch` (the site), `alpaca-connectors`,
`InteractiveBrokersBackend`, `MetaTables`.

## What each workflow declares

`HunchAPI/.mainsequence/workflows/hunch-api.yaml` (one unscoped file, both Environments):

- `hunch` FastAPI (`/mcp` enabled), `hunch-agent` Harness Agent, Jobs `hunch-migrate`,
  `hunch-take-build`, `hunch-portfolio-refresh` (+dispatcher), `hunch-daily-review`
  (+dispatcher), `hunch-execution-sync`, `hunch-leaderboard`, `hunch-email-digest`.
- Execution steps: image → migrate → deploy API; agent image → deploy Agent.

`Hunch/.mainsequence/workflows/hunch-site.yaml`: the `hunch-site` static site whose
`build_environment.VITE_HUNCH_API_RELEASE_UID` names the API release by repository and key
(`HunchAPI` / `hunch`), so each Environment's build gets its own release UID without a pinned value.

## Values to fill per Environment

| Where | Variable | Value | When |
| --- | --- | --- | --- |
| `hunch` API | `HUNCH_CORS_ORIGINS` | `https://*.site-dev.main-sequence.app` (development); the production site origin on `main` | before the first push |
| `hunch` API | `HUNCH_BUILD_EXECUTION` | `job` | set |
| `hunch` API | `HUNCH_CONNECTOR_MODE` | `live` | set |
| `hunch` API, review and sync Jobs | `HUNCH_ALPACA_CONNECTOR_RELEASE_UID` | the `alpaca` FastAPI release UID in that Environment | after the Alpaca connector API is deployed there (not yet, 2026-10-25) |
| same | `HUNCH_IBKR_CONNECTOR_RELEASE_UID` | the IBKR API release UID | after that repository publishes its API (today only Jobs) |
| `hunch` API, build and review Jobs (dispatcher included) | `HUNCH_RESEARCH_MODE` | `heuristic`; `inference` once the provider's recorded-inference adapter is confirmed there | set |
| `hunch` API, build and review Jobs | `HUNCH_RESEARCH_SOURCES` | `quant`, or `quant,finnhub` with the Secret below | optional |
| `hunch-email-digest` Job | `HUNCH_EMAIL_SENDER` | `platform` | set |
| `hunch-email-digest` Job | `HUNCH_SITE_URL` | the site's Command Center link in that Environment (`.../app/links/<site uid>`) | after the first site deploy |
| `hunch-agent` | provider / model / thinking | the Environment's model-provider credential | before the first push |

Find release UIDs with the Environment filter, never by name alone:

```bash
curl -H "Authorization: Bearer $(.venv/bin/mainsequence auth token)" \
  "$MAINSEQUENCE_ENDPOINT/api/v1/resource-releases/?name=alpaca&release_kind=fastapi&organization_environment_uid=<env uid>"
```

## Namespace roles (done by hand, per Environment)

Hunch tables live in the MetaTables namespace `hunch` (until revision 0004 the product tables were
catalogued in `mainsequence.markets`; ADR 0006). Workflow files cannot grant namespace roles, so
after the first push of a branch (which creates the workload Users) an owner of the namespace, or
an Organization admin, grants from their own session with the MetaTables client
(`Namespace.filter(search=...)[0].grant_role(workload_user_uid, role)`, or `MetaTable.grant_role`
for one table), the checkout on that Environment's branch so the client resolves that
Environment's MetaTables API. The role table is under "MetaTables roles in each Environment".

Workload User UIDs come from `GET /api/v1/jobs/?code_repository_branch_uid=<branch>`
(`workload_user_uid`) and from the releases (`workload_user_uid`). A recreated Job or release gets a
new User and needs the grant again; a Team holding the roles avoids that.

First-deploy findings (development, 2026-10-25): the migration Job first timed out because the
development MetaTables runtime was asleep (its `/runtime-context/` call exceeded the SDK's 120 s read
timeout); warming the runtime (`ResourceRelease.wait_for_runtime_access`) and re-running the Job
fixed that. The second run failed with `namespace_access_required` until the grants above existed.
A failed migrate step blocks the API and Agent deploys (`workflow_prerequisite_failed`); after the
fix, an empty commit on the branch re-runs the whole pipeline. The site build fails with
`invalid_configuration` until the API release exists in the Environment and is rebuilt afterwards.

## Access to declare when the pieces exist

- Connector calls: `access.branches: [{repository: alpaca-connectors, policy: reader}]` on the
  `hunch` API, `hunch-daily-review` and `hunch-execution-sync` (branch `reader` makes the workload
  a release `viewer`, which may call the release). The runtime then resolves the release's RPC URL
  and token through `resolve-runtime-access` (`hunch.connectors.http.ReleaseHTTPClient`).
- Finnhub: `access.secrets: [{name: HUNCH_FINNHUB_API_KEY, policy: value_reader}]` on the API and
  the build and review Jobs, and the Secret's value exported as `HUNCH_FINNHUB_API_KEY`.
- Email: the `platform` sender calls `Notification.send(include_email=True)` as the Job workload;
  confirm with the platform team that a workload may notify a person by email.
- Recorded inference: the Jobs declare `model_providers` for `openai-codex`; the provider must have
  a recorded-inference adapter on the target backend (the development backend had none on
  2026-10-25, ADR 0002). Set `HUNCH_RESEARCH_MODE=heuristic` on the API and Jobs to deploy without
  it.

## MetaTables roles in each Environment

Workflow entries grant no MetaTables roles; an owner of each namespace grants them (MetaTables
Admin, namespace or table **Access**, or `grant_role`). Since revision 0004 (ADR 0006) every Hunch
table is catalogued in `hunch`, and Hunch reaches the Markets registries only through the Markets
API, which the workflow's `MainSequenceMarkets` branch grant lets each workload discover.

| Principal (workload User) | `hunch` | `mainsequence.markets` |
| --- | --- | --- |
| `hunch-migrate` | `editor` (automatic) | `editor` until its first 0004 run has moved the tables, then none |
| `hunch` API and every other Hunch Job, dispatchers included | `data_writer` | none |
| the Markets API workload | `data_viewer` on `hunch__portfoliosts__takes`, `hunch__portfolioweightsts__takes` and `hunch__signalweightsts__takes` only (catalog reconcile) | owner side |
| a person or a Team of people | `owner` | as before |

Before 0004 the Hunch product tables were catalogued in `mainsequence.markets` (the inherited
mixins), so the API and the Jobs held `data_writer` there and `data_viewer` on `hunch`. Without
`editor` the migration fails with 403 `namespace_access_required` naming its workload User, which
blocks the API and the Agent and, through them, the site build. Workload User UIDs are on each Job
(`GET /api/v1/jobs/?code_repository_branch_uid=<branch uid>`) and each release
(`workload_user_uid`). A recreated Job or release gets a new workload User and needs its grant
again. First granted in development on 2026-10-25.

## Moving onto the Markets API boundary (revision 0004)

1. Grant `data_writer` on `hunch` to the API and every Hunch Job (they held `data_viewer`).
2. Push. `hunch-migrate` moves the product tables to `hunch` in place, then applies 0004, which
   creates the series instances; the API and the Agent deploy after it. The new API attaches only
   the Hunch tables, so its cold start no longer waits on the Markets tables.
3. Grant the Markets API workload `data_viewer` on the three catalogued instances above, so the
   catalog can verify and reconcile the takes.
4. Revoke every Hunch workload's role on `mainsequence.markets`.

## Order of operations

1. Grant the MetaTables roles above in the Environment, then merge `phase-0-foundation` into
   `development` and push. The platform builds the image, runs `hunch-migrate` (ms-markets
   schema must already be at its head in that Environment), deploys the `hunch` API, then the
   Agent. Confirm with `mainsequence code-repository resources list` and the release logs. The
   first push creates the Jobs and their workload Users, so their grants can follow it; push
   again after granting.
2. Only once the `hunch` release has an active revision, merge `command-center-site` into the
   site's `development` and push: the site resolves `HunchAPI/hunch` at build time and fails
   with `invalid_configuration` while that release does not exist (2026-10-25: the site built 41 s
   before the API workflow created it). The next push to the site's branch builds it again.
3. Open the site in Command Center; create, build and activate a practice take; publish it; check
   the leaderboard, notifications and the Assistant (the configuration endpoint reports the Agent).
4. Set `HUNCH_SITE_URL` from the site's link and push; opt a profile into the digest; run
   `hunch-email-digest --user-uid <uid> --dry-run` from the Jobs page, then for real.
5. When the Alpaca connector API ships its execution capability: set
   `HUNCH_ALPACA_CONNECTOR_RELEASE_UID`, add the branch access, push, link an account from the
   connector's site, fund a take with a small notional in approval mode, approve, sync.
6. Repeat on `main` with production values; production research mode stays `inference` only once
   the provider adapter is confirmed.

## Validation

Validated on 2026-10-25 against each repository's registered branch (`main`, Production):
`hunch-site.yaml` is valid; `hunch-api.yaml` reports only `source_not_indexed` for the Agent's
`api/agent/main.py` (and the `resource_uid` the validator then asks for), because `main` does not
carry the file yet. Both clear once the branch that holds the code is registered. Re-run the
validation against the `development` branch UID right after the merge.

Validate every workflow change before committing:

```bash
POST /api/v1/code-repository-branches/<branch uid>/validate-workflow/  {"path": ".mainsequence/workflows/hunch-api.yaml", "content": "..."}
```

The branch UID comes from `GET /api/v1/code-repository-branches/?code_repository_uid=<repo uid>`.
