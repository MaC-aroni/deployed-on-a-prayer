# What the console needs from the backend

A running list from the UI side (Elathius) of data the screens want to render and don't get
yet, or get in a form that forces the UI to guess. Everything here is a request, not a change:
the backend team decides where it lands (`mac_api.py`, `planning_api.py`, the runner's events)
and the UI adapts. Items are ordered by how much they matter for the pitch demo.

Legend: **have** = exists in `docs/api.md` or `docs/planning-api.md` today · **gap** = missing ·
**guess** = the UI infers it and would rather be told.

## 1. The pipeline graph: logical connectors

The graph draws a line from every step a step depends on. Today the reviewed spec has
`needs: []` on every step, so the UI falls back to "each step depends on the one before it in
execution order", which is true for the runner but hides the real reasons (data before
release, both infrastructure steps before data, approvals before the gated steps).

| Need | Status | Ask |
|---|---|---|
| `needs` per step | guess | Have the planner (and the demo spec) state real `needs`, or add a computed `depends_on` per step to `GET /migrations/{name}` and `GET /plans/{id}`: the steps that must finish first, as the runner orders them |
| Approval → step dependency | have | `requires_approval` is enough to draw a lock and a line from the approval; keep it |
| Stage order | have | `stages` in run order; keep it |

## 2. Where a run broke, and what it took down

The UI highlights the failed step red, tints its stage, and dims and dashes everything after it.

| Need | Status | Ask |
|---|---|---|
| `failed_step` | have | keep |
| Which steps were skipped because of the failure | have | `steps[id] == "skipped"` works |
| Rollback progress | gap | a `rollback: {total, done, current}` on the run while `rolling_back`, so the UI can show "undoing 4 finished steps, newest first · 2 / 4" |
| The failing line of output | gap | an event `kind: "failure"` with `step` and the exact stderr tail (last ~20 lines), so the panel can open on the error instead of the whole log |
| Exit code and duration of the failed step | gap | fields on the `failure` event |

## 3. Timing

| Need | Status | Ask |
|---|---|---|
| Per-step started / finished | guess (from `step` event timestamps) | `timing[step] = {started, finished}` on `GET /runs/{id}` |
| Run duration | guess (`updated - created`) | `started`/`finished` on the run |
| Who pressed the button | guess (parsed from the "requested by @x" log line) | `requested_by` on the run |

## 4. The Nemotron agents (the part the judges score)

The planning run already emits virtual steps `knowledge`, `attempt-n`, `plan`. To show the
reasoning instead of just the outcome, the UI wants the trace the brief describes:
`observation → reasoning → action → outcome`, with the model name.

| Need | Status | Ask |
|---|---|---|
| Attempt result and problems | have | `step` + `log` events on `attempt-n` |
| Model name and reasoning per call | gap | an event `kind: "agent"` with `{agent: "planner" \| "ingest" \| "diagnostician", model, phase: "observation" \| "reasoning" \| "action" \| "outcome", text}`; reasoning may be the model's thinking when the API returns it, else the prompt summary |
| Streaming tokens for the reasoning | gap (nice to have) | partial `agent` events with `partial: true`, so the panel can type it out live |
| Which knowledge sections the planner read | gap | `sources` used per attempt, so the Knowledge card can list them |
| Ingest per-page facts | have (log lines) | a `step` event per page with `{page, nodes, edges, dropped}` would let the UI draw a page-by-page bar |
| Diagnostician output | stub | when connected: `diagnosis` events with `{root_cause, fix, pr_url}` fields, not one message string |

## 5. Approvals

| Need | Status | Ask |
|---|---|---|
| Ticket, status, detail per approval | have | from Build's `report.approvals`; keep |
| Approval status changes while a Deploy waits | gap | an event `kind: "approval"` with `{id, status, ticket}` so the card unblocks live without polling `resume` |
| Who approved and when | gap | `approved_by`, `approved_at` on the report entry |

## 6. Migrate page

| Need | Status | Ask |
|---|---|---|
| Services before the graph exists | have | `GET /services` reads the knowledge base pages (`planning_api.py`) |
| Repositories in the org | have | from GitHub, cached a minute |
| Which service a repo belongs to | guess (repo named in a service page) | fine for the demo; the graph's `has_repo` edges take over once learned |
| Knowledge-base freshness | gap | `knowledge.updated` (newest page mtime or Confluence version) next to `graph_updated`, to say "learned before the docs changed" |

## 7. Smaller things

- `GET /runs` could accept `mode=` to list only plans/ingests.
- `GET /migrations` could include `failed_step` and `requested_by` in each `latest.*` summary.
- A `GET /api/mac/health` that says which integrations are configured (`llm`, `github`,
  `jira`, `confluence`, `aws`) so the UI can explain a 409 before the user clicks.

## How the UI uses the API

Every call is in `frontend/src/mac/api.js`. The pipeline page reads `GET /migrations/{name}`
or `GET /plans/{id}`, `GET /runs?migration=`, `GET /runs/{id}`, `GET /runs/{id}/events` and the
SSE stream. The Migrate page reads `GET /services`, `GET /plans` and posts `/ingest` and `/plan`.
New fields are additive; the UI ignores what it doesn't know.
