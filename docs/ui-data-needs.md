# What the console needs from the backend, and when it renders what

A running list from the UI side (Elathius) of the data the screens render, where it comes from
today, what is still missing or guessed, and the moment each thing should appear. Everything
here is a request, not a change: the backend team decides where it lands (`mac_api.py`, the
runner's events, `planning_api.py`) and the UI adapts. New fields are additive; the UI ignores
what it doesn't know.

Legend: **have** = exists in `docs/api.md` or `docs/planning-api.md` · **gap** = missing ·
**guess** = the UI infers it and would rather be told · **own** = lives in `planning_api.py`
(UI-owned module) and is already in place.

## 0. The flow the console tells, screen by screen

| # | Screen | What the person sees | Rendered from | Appears when |
|---|---|---|---|---|
| 1 | **Migration** (`/migrate`) | Every service in the knowledge base and every repo in the org; two doors each (Confluence · GitHub); Learn / Plan / Build stepper; one primary: **Launch agent**, or **Open pipeline** when a `migration.yaml` already exists | `GET /services` (own), `GET /plans` (own) | on load; re-fetched after every action |
| 2 | **Agents** (`/agents/{run}`) | Director → workers → Compiler hierarchy with each agent's observation / reasoning / action / outcome; the working-agent icon on running agents | `agent` events (own) via `/runs/{id}/events` + `/stream` | opens from any working-agent icon; live while the run is active |
| 3 | **Planning run** (`/migrate/{run}`) | Detect → Knowledge → Planner attempts → Pipeline; "Open pipeline · Build running" | `step` + `log` events on virtual steps (own) | as events arrive |
| 4 | **Pipeline** (`/migrations/{name}`, `/plans/{run}`) | Stages as columns, steps as cards, lines = dependencies, red "failed here" stage, dimmed never-run steps; breakpoints (amber bar, ▌▌); **Continue** on the waiting step; **Investigate** on a failed run; the Diagnostician's root cause + **Approve fix** | `GET /migrations/{name}` · `GET /runs/{id}` · events | run detail on load; cards move on every non-`log` event |
| 5 | **Knowledge page** (`/knowledge/{page}`) | The page body, labels, owner, review ticket for generated pages, "Open in Confluence" | `GET /knowledge/{page}` (own) | from a Confluence door when the page has no Confluence URL yet |
| 6 | **Pipelines** (`/`) | Count in the sidebar, table of reviewed + generated pipelines; empty state says "start a migration" | `GET /migrations`, `GET /plans` | every 5 s (list), every 10 s (sidebar count) |

## 1. The pipeline graph: logical connectors

Lines are drawn from every step a step depends on. The reviewed spec has `needs: []` on every
step, so the UI falls back to "each step depends on the one before it in execution order",
which hides the real reasons (data before release, both infrastructure steps before data).

| Need | Status | Ask |
|---|---|---|
| `needs` per step | guess | Planner and demo spec state real `needs`, or `GET /migrations/{name}` and `GET /plans/{id}` add a computed `depends_on` per step |
| Approval → step dependency | have | `requires_approval` draws the lock and the line from the approval |
| Breakpoints | have | `when: manual` is drawn as a breakpoint (amber bar, pause mark). **Ask the Planner to emit `when: manual` for PHI/data and cutover steps**, so generated plans pause where the docs say a person decides |
| Stage order | have | `stages` in run order |

**Render timing.** The graph is drawn from the migration detail before any run exists (all
cards pending). Card states come from `run.steps[id]`; they move on every `step` event. A
breakpoint's card turns `waiting` and the run `waiting`; the primary button becomes **Continue ·
<step>** and posts `/runs/{id}/steps/{step}/play`.

## 2. Where a run broke, and what it took down

| Need | Status | Ask |
|---|---|---|
| `failed_step` | have | keep |
| Skipped steps | have | `steps[id] == "skipped"` |
| Rollback progress | gap | `rollback: {total, done, current}` on the run while `rolling_back`, so the UI shows "undoing 4 finished steps, newest first · 2 / 4" |
| Failing output tail | gap | a `failure` event with `step`, `exit_code`, `duration` and the last ~20 stderr lines, so the inspector opens on the error |
| Investigation | own | `POST /runs/{id}/investigate` → a `diagnose` run with `report.root_cause / fix / files / ticket`; `POST /runs/{id}/approve-fix` opens the PR. Listed by `GET /runs?migration=` beside the failed run |
| **Auto-launch on failure** | gap | the runner already calls its Diagnostician at failure time (`ai` mode) but it is `NotConfigured`. Two options: wire the runner's Diagnostician to the same `/investigate` logic, or have the runner emit `diagnosis` events the way `/investigate` does (`root cause: …`, `fix: …`) so the console shows one card either way |

**Render timing.** The red stage and dimmed steps appear as soon as `failed_step` is set, while
rollback is still running. The Investigate button appears when the run is no longer active. The
fix card appears under the graph once a `diagnose` run with `based_on == run.id` exists, follows
it live, and shows **Approve fix** when it succeeds with files.

## 3. Timing and provenance

| Need | Status | Ask |
|---|---|---|
| Per-step started / finished | guess (from `step` event timestamps) | `timing[step] = {started, finished}` on `GET /runs/{id}` |
| Run duration | guess (`updated - created`) | `started` / `finished` on the run |
| Who pressed the button | guess (parsed from the "requested by @x" log line) | `requested_by` on the run |

## 4. The agents (the part the judges score)

The planning module's runs (`plan`, `ingest`, learn, `diagnose`) already emit `agent` events
(`docs/planning-api.md` → "Agent events"): `{agent, parent, role, model, phase, status, text}`.
The console renders the hierarchy from them. Two asks so the whole product speaks the same way:

| Need | Status | Ask |
|---|---|---|
| Agent events from the runner's own agents | gap | the design-page writer, the guide writer and the code writer (`codegen: llm`) emit the same `agent` events on their step, so a Deploy with LLM-written steps shows the working-agent icon and opens the hierarchy too |
| Reasoning content | gap (nice to have) | when NIM returns `reasoning_content`, put it in a `phase: "reasoning"` event; today the reasoning events are the agent's stated plan |
| Streaming tokens | gap (nice to have) | partial events with `partial: true` so the panel types the text out |
| Which knowledge sections the planner read | gap | `sources` per attempt, to list on the Knowledge card |
| Diagnostician output | own | `diagnosis` events plus the structured `report`; see §2 |

**Render timing.** An agent card appears on its first event (`pending` or `running`), turns to
the working-agent icon while `running`, and settles on its `outcome`. The Readers collapse into
one card when there are more than six. When the run stops, agents still `running` are shown
`failed`, `pending` ones `skipped`.

## 5. Approvals

| Need | Status | Ask |
|---|---|---|
| Ticket, live status, detail, checked | have | `approvals[].status / detail / checked` on the migration detail (poller + webhook) |
| Who approved and when | gap | `approved_by`, `approved_at` on the entry |
| Approval change as an event | gap | an `approval` event `{id, status, ticket}` on the migration's latest run, so the open pipeline unblocks without a poll (the UI already listens for `approval` on the stream) |
| Review ticket for a generated knowledge page | own | `services[].review.ticket` from `POST /learn`; shows as "under review · MAC-21" on the service card |

## 6. Migration page

| Need | Status | Ask |
|---|---|---|
| Services before the graph exists | have (own) | knowledge pages with the `service` label |
| Repositories in the org | have (own) | GitHub, cached a minute; an outage shows one line, the list fills when GitHub recovers |
| Confluence URL per page | have (own) | from the published-knowledge table; null until `mise run mac publish-knowledge` ran on that deployment. **Ask: run it on Fly once**, so the Confluence doors open Confluence instead of the console's copy |
| Existing `migration.yaml` per service | have (own) | `services[].migration`; the card says "yaml found" and opens the pipeline |
| Knowledge-base freshness | gap | `knowledge.updated` (newest page mtime or Confluence version) to say "learned before the docs changed" |

## 7. Endpoints and probes (new on main, not drawn yet)

`GET /migrations/{name}` now has `endpoints` with probes, and `POST /runs/{id}/outputs/…/probes/…`
answers with AWS's response. The UI will add an **Endpoints** card (one button per probe:
status, `request_id`, `elapsed_ms`, body, the `curl` with copy) and a before/after list from
`GET /runs/{id}/probes`. Nothing further needed from the backend for it.

## 8. Found while building ui_v2 (2026-11-08, afternoon)

| Need | Status | Ask |
|---|---|---|
| `GET /runs` summaries lack `migration` and `based_on` | own workaround | the console uses `GET /run-index` (planning API) for now; adding `migration`, `based_on`, `autofix` to `_summary` in `mac_api.py` would let it drop that |
| `expected_live` on a cancelled Deploy | gap | `_endpoints` treats only finished Rehearse and `undone` as gone; a `cancelled` Deploy was undone too and should report `expected_live: false`. The UI treats `run_status == "cancelled"` as off meanwhile |
| `GET /plans/{id}` had no `endpoints` or live approval status | own (endpoints) · gap (approvals) | `endpoints` added in the planning API; live `approvals[].status/detail/checked` for generated plans still needs the same lookup `get_migration` does |
| Health | own | `GET /health` exists in the planning API; fine to move into `mac_api.py` |

## 9. Smaller things

- `GET /runs` could accept `mode=` to list only agent runs (`plan`, `ingest`, `diagnose`).
- `GET /migrations` could include `failed_step` and `requested_by` in each `latest.*` summary.
- A `GET /api/mac/health` that says which integrations are configured (`llm`, `github`, `jira`,
  `confluence`, `aws`) so the UI can explain a `409` before the person clicks, and grey the Learn
  and Investigate buttons when there is no model.

## How the UI uses the API

Every call is in `frontend/src/mac/api.js`. The pipeline page reads `GET /migrations/{name}` or
`GET /plans/{id}`, `GET /runs?migration=`, `GET /runs/{id}`, `GET /runs/{id}/events` and the SSE
stream (kinds `log`, `step`, `run`, `diagnosis`, `agent`, `approval`, `failure`). The Migration
page reads `GET /services`, `GET /plans` and posts `/learn`, `/ingest` and `/plan`. The agents
page reads one run's events and draws the `agent` ones. The sidebar count is
`GET /migrations` + `GET /plans` every 10 s.
