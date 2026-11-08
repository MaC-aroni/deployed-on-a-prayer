# Planning API (for the UI)

The knowledge graph and the Planner over HTTP, for the console's **Build → Migrate** flow.
Code: `backend/app/planning_api.py`; tests: `backend/tests/test_planning_api.py`. It sits beside
the runner API ([`api.md`](api.md)) in its own module and imports it; it changes nothing there.

Everything is under **`/api/mac`**, same access rules as the runner API: every `GET` is open,
every `POST` needs the GitHub sign-in on Fly. Plans and ingests are **ordinary runs** (modes
`plan` and `ingest`), so you follow them with `GET /runs/{id}`, `GET /runs/{id}/events` and the
`/stream`, exactly like a Build.

The LLM is whatever the runner's is configured with (`MAC_LLM_API_KEY` or `NVIDIA_API_KEY`,
`MAC_LLM_BASE_URL`, `MAC_LLM_MODEL`). Without one, `POST /plan` and `POST /ingest` answer `409`
with the reason. The knowledge base is `MAC_KNOWLEDGE_DIR` (default `demo-data/confluence`);
the graph is `<MAC_DATA_DIR>/graph.json`, shared with `mise run mac ingest`.

## Services

`GET /api/mac/services`: what can be migrated. Always answers, graph or not.
```json
{"ingested": false, "graph_updated": null, "knowledge": {"pages": 15, "dir": "confluence"},
 "services": [{"name": "ClaimsAdjudicationService", "page": "service-claims-adjudication",
               "team": "claims-platform", "description": "ClaimsAdjudicationService decides medical claims…",
               "repos": ["MaC-aroni/claims-db-migrate", "MaC-aroni/claims-service-iac"],
               "learned": false, "approvers": [], "sources": [], "plans": []}],
 "repos": [{"name": "claims-service-iac", "full_name": "MaC-aroni/claims-service-iac", "url": "https://github.com/…",
            "description": "…", "pushed_at": 1794100000.0, "archived": false, "service": "ClaimsAdjudicationService"}],
 "repos_error": null}
```
- `services` come from the knowledge base without any model call: pages whose `labels` include
  `service`, with the repos each page mentions. Once the graph exists (`ingested: true`) each
  service is enriched from it and `learned` turns true; `approvers` and `sources` come from the
  graph. `plans` are the ids of generated plans for that service.
- `repos` is every repository in the org (`MAC_GITHUB_REPO`'s owner, via GitHub, cached for a
  minute; `GITHUB_TOKEN` lifts the anonymous rate limit). `service` names the documented service
  that uses the repo, or is null: the Planner only plans with documented repos. If GitHub can't
  be reached, `repos` is empty and `repos_error` says why.

## Ingest

`POST /api/mac/ingest` → `202` plus the run (mode `ingest`, migration `knowledge`), or `409`
(no LLM, or an ingest is already running). One LLM call per knowledge page; every page is a
`log` event on the virtual step `knowledge`, and the `step` events on `knowledge` summarise.
The run's `report` has `nodes`, `edges`, `dropped` and `services`.

## Plan

`POST /api/mac/plan` with `{"service": "ClaimsAdjudicationService"}` or `{"goal": "Migrate … to
AWS"}`, optionally `"pr": true` to also open a PR into `MAC_MIGRATIONS_REPO`. Answers `202` plus
the run (mode `plan`, migration `plan/<goal-slug>`), `409` without an LLM or while the same goal
is still planning, `422` with neither field.

The run's events use virtual steps, so they can be drawn as cards:

| step | events |
|---|---|
| `knowledge` | `step`: "graph loaded, N facts…" or, when there's no graph yet, the ingest's pages as `log` lines |
| `attempt-1` … `attempt-4` | `step`: "running, asking the model…", then "valid" or "k problems"; each problem is a `log` line on that attempt |
| `plan` | `step`: "migration.yaml written, N steps and M approvals in k attempt(s)", then "opened <PR url>" with `pr: true` |

When the plan is valid the run ends `succeeded`; `spec_text` holds the YAML and `report` has
`plan` (the run id), `name`, `service`, `iterations`, `steps`, `approvals` and, with a PR,
`pr_url`. Otherwise it ends `failed` with the problems as `log` lines on the last attempt.

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
