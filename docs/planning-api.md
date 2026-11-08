# Planning API (for the UI)

The knowledge graph, the Planner and the Diagnostician over HTTP, for the console's
**Build → Migration** flow. Code: `backend/app/planning_api.py`; tests:
`backend/tests/test_planning_api.py`. It sits beside the runner API ([`api.md`](api.md)) in its
own module and imports it; it changes nothing there.

Everything is under **`/api/mac`**, same access rules as the runner API: every `GET` is open,
every `POST` needs the GitHub sign-in on Fly. Plans, ingests, learns and investigations are
**ordinary runs** (modes `plan`, `ingest` and `diagnose`), so you follow them with
`GET /runs/{id}`, `GET /runs/{id}/events` and the `/stream`, exactly like a Build.

## Agent events: the hierarchy

Every agent here narrates itself. Each narration is an event with `kind: "agent"` whose `message`
is a JSON object:

```json
{"agent": "reader:50-claims-service", "parent": "director", "role": "Reader",
 "model": "nvidia/nemotron-3-ultra-550b-a55b", "phase": "action", "status": "running",
 "text": "compressing 50-claims-service into facts and relations, each cited"}
```

- `agent` is a stable id within the run; `parent` is the agent that directed it (absent on the
  Director). `role` and `model` come with an agent's first event.
- `phase` is one of `observation`, `reasoning`, `action`, `outcome`: the trace the brief asks for.
- `status`, when present, moves the agent's card: `pending` → `running` → `succeeded` | `failed`.
- `step` is the virtual step the event belongs to (`knowledge`, `detect`, `attempt-n`, `plan`,
  `diagnose`), so the same events also drive the step cards.

The console draws them at `/agents/{run id}`: Director → workers → Compiler, with each
agent's trace on click. The working-agent icon on any running agent card opens that page.

Every run here has a Director; the workers differ per run:

| run | workers | compiler does |
|---|---|---|
| ingest (`POST /ingest`) | one `reader:<page>` per page · `references` (pages vs graph) | saves `graph.json` |
| learn (`POST /learn`) | `reader` (the repository) · `references` (what the pages already say) | writes the page, merges the graph, **raises the review ticket**, publishes to Confluence when configured |
| plan (`POST /plan`) | `detect` · `knowledge` · `planner` (one event per attempt) · `validator` | writes `migration.yaml`, opens the PR, hands the pipeline to Build when asked |
| investigate (`POST /runs/{id}/investigate`) | `logs` · `code` · `fixer` | records the proposal, **raises the approval ticket** |

The LLM is whatever the runner's is configured with (`MAC_LLM_API_KEY` or `NVIDIA_API_KEY`,
`MAC_LLM_BASE_URL`, `MAC_LLM_MODEL`). Without one, `POST /plan` and `POST /ingest` answer `409`
with the reason. The knowledge base is `MAC_KNOWLEDGE_DIR` (default `demo-data/confluence`);
the graph is `<MAC_DATA_DIR>/graph.json`, shared with `mise run mac ingest`.

## Services

`GET /api/mac/services`: what can be migrated. Always answers, graph or not.
```json
{"ingested": false, "graph_updated": null, "knowledge": {"pages": 15, "dir": "confluence", "generated": 1},
 "services": [{"name": "ClaimsAdjudicationService", "page": "service-claims-adjudication",
               "page_title": "Services: ClaimsAdjudicationService", "page_url": "https://….atlassian.net/wiki/…",
               "team": "claims-platform", "description": "ClaimsAdjudicationService decides medical claims…",
               "repos": ["MaC-aroni/claims-db-migrate", "MaC-aroni/claims-service-iac"],
               "learned": false, "generated": false, "review": null, "approvers": [], "sources": [],
               "plans": [], "migration": "claims-adjudication-onprem-to-aws"}],
 "repos": [{"name": "claims-service-iac", "full_name": "MaC-aroni/claims-service-iac", "url": "https://github.com/…",
            "description": "…", "pushed_at": 1794100000.0, "archived": false,
            "service": "ClaimsAdjudicationService", "page": "service-claims-adjudication", "page_url": null}],
 "repos_error": null}
```
- `services` come from the knowledge base without any model call: pages whose `labels` include
  `service`, with the repos each page mentions. Once the graph exists (`ingested: true`) each
  service is enriched from it and `learned` turns true; `approvers` and `sources` come from the
  graph. `plans` are the ids of generated plans for that service; `migration` is the reviewed
  `migration.yaml` in `examples/` for it, if one exists (the pipeline already exists then).
- `page_url` is the Confluence page: from the publish record (`mise run mac publish-knowledge`),
  or, when Confluence is configured and there is no record, found by title in the space (asked at
  most every 10 minutes per page, then remembered). Null when Confluence isn't configured; the
  console then links a Confluence search when `health.confluence_site` is set, else its own
  `GET /knowledge/{page}` view. `generated` marks a page MaC wrote itself (`POST /learn`);
  `review` is then `{repo, ticket, ticket_url, run_id, …}`.
- `repos` is every repository in the org (`MAC_GITHUB_REPO`'s owner, via GitHub, cached for a
  minute; `GITHUB_TOKEN` lifts the anonymous rate limit). `service`, `page` and `page_url`
  point at the documented service that uses the repo, or are null: the Planner only plans with
  documented repos, and the console offers **Learn** for the rest. If GitHub can't be reached,
  `repos` is empty and `repos_error` says why.

`GET /api/mac/knowledge/{page}`: one page, `{id, title, body (Markdown), parent, owner, labels,
source, url, generated, review}`; `404` for an unknown id.

## Learn a repository

`POST /api/mac/learn` with `{"repo": "MaC-aroni/eligibility-sync"}` (or just the name) → `202`
plus the run (mode `ingest`, migration `knowledge/<repo name>`), `409` without an LLM or while
the same repo is being learned, `422` for something that isn't `owner/name`.

The Reader fetches the repository's README, file list and metadata from GitHub and asks the
model for the facts (name, summary, runtime, data, dependencies, owner, unknowns). References
lists the knowledge pages that already mention the repo. The Compiler writes
`<MAC_DATA_DIR>/knowledge/generated-<repo>.md` with labels `service, generated, needs-review`,
extracts its facts into the graph (merging with the existing one), **raises a Jira review
ticket** through the runner's approvals integration (`ATLASSIAN_*`; without it the run says so
and goes on), and publishes the page to Confluence when `CONFLUENCE_SPACE_KEY` is set. The
sidecar `generated-<repo>.json` holds `{repo, page, service, ticket, ticket_url, run_id}`.

The run's `report`: `repo, service, page, title, path, nodes, edges, dropped, ticket, ticket_url,
confluence_url, mentions`. The new service appears in `GET /services` at once, `generated: true`,
with the repo matched to it; the Planner may use its repos from then on.

## Ingest

`POST /api/mac/ingest` → `202` plus the run (mode `ingest`, migration `knowledge`), or `409`
(no LLM, or an ingest is already running). One LLM call per knowledge page; every page is a
`log` event on the virtual step `knowledge`, and the `step` events on `knowledge` summarise.
The run's `report` has `nodes`, `edges`, `dropped` and `services`.

## Plan

`POST /api/mac/plan` with `{"service": "ClaimsAdjudicationService"}` or `{"goal": "Migrate … to
AWS"}`, plus any of:

| field | default | meaning |
|---|---|---|
| `pr` | false | also open a PR into `MAC_MIGRATIONS_REPO` |
| `reuse` | true | a reviewed `migration.yaml` for the service (in `examples/`) **is** the plan: detected, not generated. `false` always generates a fresh one |
| `build` | false | once the plan is ready, start **Build** on it; `report.build_run` is its id |

Answers `202` plus the run (mode `plan`, migration `plan/<goal-slug>`), `409` without an LLM or
while the same goal is still planning, `422` with neither field. The console's **Launch agent**
sends `{service, build: true}`: learn if needed → detect or write → render → Build.

The run's events use virtual steps, so they can be drawn as cards:

| step | events |
|---|---|
| `detect` | `step`: "found reviewed migration.yaml <name>" or "no migration.yaml for this goal, generating one" |
| `knowledge` | `step`: "graph loaded, N facts…" or, when there's no graph yet, the ingest's pages as `log` lines |
| `attempt-1` … `attempt-4` | `step`: "running, asking the model…", then "valid" or "k problems"; each problem is a `log` line on that attempt |
| `plan` | `step`: "migration.yaml written, N steps and M approvals in k attempt(s)", then "opened <PR url>" with `pr: true`, then "Build <id> started" with `build: true` |

When the plan is valid the run ends `succeeded`; `spec_text` holds the YAML and `report` has
`plan` (the run id), `name`, `service`, `iterations`, `steps`, `approvals`, `breakpoints` (the
steps with `when: manual`) and, with a PR, `pr_url`. When a reviewed spec was detected, `report`
has `detected` (its name) and `iterations: 0`, nothing is written, and the pipeline is
`GET /migrations/{detected}`. Otherwise it ends `failed` with the problems as `log` lines on the
last attempt.

**Breakpoints.** A step with `when: manual` is a pause point: the runner stops there with the
step `waiting` and the run `waiting` until someone presses **Continue**
(`POST /runs/{id}/steps/{step}/play`, [`api.md`](api.md)). Approvals (`requires_approval`) pause
the same way, with the step `blocked`, until Jira says approved.

The file lands at `<MAC_DATA_DIR>/plans/<run id>/migration.yaml`. It is **not** listed under
`GET /migrations` (those are the reviewed specs in `examples/`); use the endpoints below.

## Generated plans

- `GET /api/mac/plans`: every generated plan, newest first: `run_id`, `name`, `service`,
  `owner_team`, `stages`, `created`, `goal`, `iterations`, `pr_url`, `valid`, and `latest`
  (`build`/`rehearse`/`deploy` summaries, as in `GET /migrations`).
- `GET /api/mac/plans/{run_id}`: the same shape as `GET /migrations/{name}` (stages and steps
  in run order, approvals with tickets, design page, issues, latest, active_run) plus
  `source: "generated"`, `plan_run`, `goal`, `pr_url` and `yaml`.
- `POST /api/mac/plans/{run_id}/build|rehearse|deploy`: the three buttons on a generated plan.
  Same bodies, same `202`/`409` answers, same rules as the runner API's; the runs they start
  are ordinary runs.

A generated plan usually keeps the reviewed spec's `metadata.name`, so `latest` and run history
by name include runs of both files. The runner's "exact same `migration.yaml`" checks (by
digest) still apply, so nothing unsafe follows from that.

## Investigate a failure, then a person approves the fix

`POST /api/mac/runs/{run_id}/investigate` (optional body `{"mode": "explain" | "report" |
"autofix"}`) on a run that `failed` or `rollback_failed` with a `failed_step` → `202` plus a new
run (mode `diagnose`, same migration, `based_on` the failed run, the failed run's `spec_text`
and `shas` copied so it renders on the same pipeline), `409` while the run is still active, has
no failed step, or an investigation of that migration is already running.

Logs reads the failed step's output (last 40 lines); Code reads the failing repository at the
commit the run locked (`GITHUB_TOKEN`), the entrypoint's folder first; the Fixer asks the model
for `{root_cause, fix, confidence, files}`; the Compiler stores the proposed files under
`<MAC_DATA_DIR>/fixes/<run id>/` and **raises a Jira approval ticket**. The run's `report`:
`investigated, step, repo, sha, entrypoint, root_cause, fix, confidence, files (paths), ticket,
ticket_url, mode, approved`. Two `diagnosis` events carry the root cause and the fix as text.

`POST /api/mac/runs/{run_id}/approve-fix` is the manual command: on a finished `diagnose` run it
puts the proposed files on branch `mac/autofix/<failed run id>` of the failing repository and
opens a pull request against `main`; `report.pr_url`, `approved`, `approved_by`, `approved_at`
are set. `409` when it isn't a finished investigation, when no code change was proposed, when
it was already approved, or when `GITHUB_TOKEN` is missing. Nothing merges by itself.

Investigations are listed by `GET /runs?migration=<name>` beside the runs they explain, so the
pipeline page can show "fix proposed" under a failed run.

## Health, run index, active services

- `GET /api/mac/health` → `{llm, model, llm_provider, llm_providers, github, jira, confluence, confluence_site, aws, approvals_live}`: what this
  deployment has configured, names only. The console greys Launch agent, Learn and Investigate
  when `llm` is false and says why. `llm_providers` is `[{id, label, model, active}]`, the models
  that can be switched between (`nemotron` from `NVIDIA_API_KEY`/`MAC_LLM_*`, `grok` from
  `GROK_API_KEY`); `llm_provider` and `model` are the one in use.
- `POST /api/mac/settings/llm {"provider": "grok"}` (sign-in) switches every agent, the design
  page, AI help and Chat to that provider from their next call; kept in `MAC_DATA_DIR/settings.json`.
  Returns the health object; `409` for a provider that isn't configured.
- **Cancel an agent run:** the runner API's `POST /api/mac/runs/{id}/cancel` also takes plan,
  ingest/learn/describe and investigate runs. The agent stops before its next model call and the
  run ends `cancelled` (nothing to undo: agents change nothing until their last step). The run
  gets a `Cancel requested` event; `409` when it has already finished.
- `GET /api/mac/run-index?migration=&limit=`: `GET /runs` plus `migration`, `based_on`,
  `diagnostics_mode`, `autofix` and `active` per run, so lists can link a run to its pipeline and
  the pipeline page can find the investigation of a failed run.
- `GET /api/mac/services/active`: one row per declared output of every pipeline (reviewed and
  generated), `{migration, service, owner_team, source, href, step, name, description, probes,
  production?, rehearsal?}` where each environment entry is the runner API's
  (`run_id, value, run_status, expected_live`) plus `last_probe` (the newest probe answer for
  that output, or null). The Services tab; Ping calls the runner API's probe endpoint.
- `GET /plans/{id}` now carries `endpoints` like `GET /migrations/{name}`.

## Repositories added by URL

`POST /api/mac/repos {"url": "https://github.com/owner/name"}` → `202` plus a run (mode
`ingest`, migration `repo/<name>`), `422` for anything that isn't a GitHub repository URL. The
Reader fetches the repository and its LICENSE from GitHub (a private or missing repo fails the
run); the Licence checker asks the model to classify it for internal use and modification
(`{spdx, category, risk: ok | review | confirm | blocked, reason}`), or, without an LLM, applies
an SPDX rule (permissive → ok, copyleft → review, no licence → confirm); the Compiler records the
repository in `<MAC_DATA_DIR>/repos.json` and **raises a Jira review ticket** for `review` and
`blocked`. `confirm` (no licence file) is the adder's own call: `POST /api/mac/repos/{owner}/{name}/accept`
`{note?}` records `licence.accepted`, `accepted_by`, `accepted_at` (it also works on `review` and
`blocked`: "proceed anyway", the ticket stays for the record). `GET /services` lists the repo in
`repos[]` with `custom: true`, `licence` and `page_title`; `DELETE /api/mac/repos/{owner}/{name}`
removes it.

## Create a Confluence page

`POST /api/mac/knowledge/{page}/publish` creates or updates that one page in Confluence
(`state.runner.pages`; the parent is linked when it was published before) and records the URL,
so `page_url` is set from then on. `409` when Confluence isn't configured; `404` for an unknown
page. For a repository with no page at all, `POST /learn` is the agent that writes and
publishes one.

## Describe: the Confluence page that introduces a migration

`POST /api/mac/migrations/{name}/page` (sign-in on Fly) starts an agent run (`mode: "ingest"`,
`migration: "page/<name>"`) and answers `202` with the run; follow it like Learn
(`GET /runs/{id}`, `/events`, `/stream`, the console's `/agents/{id}`). `404` for an unknown
migration, `409` while a Describe for it is still running.

What it does, in agent events (`step: "describe"`): the **Director** states the facts (steps,
approvals, repositories); the **Reader** reads each repository's README on GitHub and the
knowledge-base sections the spec cites (`sources:` on steps and approvals, `metadata.source_docs`);
the **Writer** (the LLM) turns those facts into the page, with the headings Summary · What moves
and why · How it runs · Approvals · Risks and rollback; code appends the authoritative appendix
(exactly what will run, from `migration.yaml`) and publishes.

The page is saved as `migration-<name>.md` in the generated-pages folder with labels
`migration, generated`, so `GET /knowledge/migration-<name>` shows it, and published to
Confluence under the knowledge base's root page when Confluence is configured (updating the
same page on a rerun). Without an LLM the page is the facts alone; without Confluence it stays
in the console. Either way the run succeeds and `GET /migrations` shows it as `page`
(`url`, `local`, `generated`, `written`, `model`, `summary`); `report` has `page`, `title`,
`confluence_url`, `summary`, `model`, `repos`, `sections`.

## Review of a page MaC wrote

A generated page carries the label `needs-review` until a person signs it off. Its review state
is on `services[].review.status` and `GET /knowledge/{page}.review.status`:
`pending | approved | rejected`. When Learn raised a Jira ticket, the state follows the ticket
(asked at most every 30 s; Approved/Done → `approved`, Rejected/Declined/Won't Do → `rejected`),
and the page's labels are rewritten (`needs-review` → `reviewed`). Without a ticket the review
happens in the console: `POST /api/mac/knowledge/{page}/review {"status": "approved" |
"rejected", "note"?}` (sign-in) records `reviewed_by` / `reviewed_at`, rewrites the labels and
returns the page view; `409` for a hand-written page, `404` for an unknown one.

## Chat transcripts

The assistant itself is the runner API's `POST /api/mac/chat` ([`api.md`](api.md) → "The
assistant": a streaming, tool-using agent over Confluence, Jira and MaC's records). That server
keeps no history, so the console stores each conversation here: `PUT /api/mac/chats/{id}`
`{title, turns}` (sign-in; id is 6–40 of `[A-Za-z0-9_-]`, the client mints it),
`GET /api/mac/chats` (newest first), `GET /api/mac/chats/{id}`, `DELETE /api/mac/chats/{id}`.
Files under `<MAC_DATA_DIR>/chats/`.
