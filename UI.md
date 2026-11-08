# MaC console UI: guide for building on it

The console is the app at `/`: a GitLab-style pipeline view for MaC migrations. It's a
starting point. Build on it freely, but keep the rules at the end of this file.

## Run it

```
mise run dev-local      # backend (with the runner) on :8000 + frontend on http://localhost:5173
```

Locally nothing needs a sign-in. For real GitHub calls, run it with your GitHub login:
`GITHUB_TOKEN=$(gh auth token) mise run dev-local`. The other secrets come from
`backend/.env`; see `docs/cloud-setup.md`. Run history is in `.mac/` at the repo root, shared
with `mise run mac ...`.

Live: https://deployed-on-a-prayer.fly.dev. Anyone can watch; to press buttons, click **Sign in
with GitHub** (you need write access to this repo). Pressing buttons on the live site makes
**real** AWS, Jira and Confluence changes, so use your local copy while developing.

## Files

| File | What it is |
|---|---|
| `frontend/src/mac/api.js` | **Every** call to the backend: `api.*` and `follow()` (the live stream). Nothing else calls `fetch` |
| `frontend/src/mac/Console.jsx` | The screens: `Console` (the page), `Pipeline`, `JobCard`, `LogPanel`, `Approvals` |
| `frontend/src/mac/console.css` | Styles. Colours are CSS variables on `.mac`, with a dark mode in `prefers-color-scheme` |
| `frontend/src/App.jsx` | Routing: the console at `/`; the old pages at `/hello` and `/excuses` |
| `docs/api.md` | **The API contract**: every endpoint, field and status. Read this first |

## How the page works

1. **Load:** `GET /migrations` fills the sidebar. Picking one loads `GET /migrations/{name}`
   (stages, steps, approvals, design page, latest runs) and `GET /runs?migration=` (history).
2. **Which run is shown:** the active run, if there is one; otherwise the newest. Clicking a
   history row switches to it.
3. **Pipeline:** the stages come from the migration detail, in run order. Each card's state
   comes from the shown run's `steps[step_id]`. A card with no state didn't run in that run;
   Build only previews some steps.
4. **Live updates:** for the shown run, `GET /runs/{id}/events` loads the history, then
   `follow()` streams new events. On any non-`log` event the page re-fetches the run, so the
   cards update. `end` arrives when the run stops moving.
5. **Buttons** call `POST`s that answer at once with `202` (it started) or `409`, whose
   `detail` is the reason. **Show `409` details exactly as they are**: they're written for
   people ("Run Build first", "Changed since the last Rehearse: …").

## What the states mean (colour them consistently)

| Step state | Meaning | Card |
|---|---|---|
| `pending` | hasn't run yet | grey ○ |
| `running` | running now | blue spinner |
| `succeeded` | done | green ✓ |
| `failed` | failed; everything is being or was undone | red ✕ |
| `waiting` | manual step: show ▶ (`POST /runs/{id}/steps/{step}/play`) | orange ▶ |
| `blocked` | waiting for an approval; the run's `reason` says which | orange 🔒 |
| `rolled_back` | was undone (always, at the end of a Rehearse) | purple ↺ |
| `rollback_failed` | undo failed: **needs a person** | red ! |
| `skipped` | never reached, because an earlier step failed | grey » |

Run statuses: `running`, `waiting`, `rolling_back`, `succeeded`, `failed`, `rollback_failed`, `undone`.

## Ideas worth building next

- **A step detail drawer:** repo, path or entrypoint, verify, rollback, `codegen`, and its
  `sources` (knowledge-base citations), all from `GET /migrations/{name}`.
- **A Build report view:** `run.report.guardrails` (per repo: CI, protected branch,
  reviewed), `report.approvals`, `report.design_page`.
- **The AI diagnosis:** show `diagnosis` events as a card when a run fails, and a
  "Download report (.md)" button once the Report mode exists.
- **Approvals timeline:** manager → MCP team → Tech Risk, with the chain from `after`.
- **Agents:** buttons for Plan (opens a PR in `mac-migrations`) and Write guide (the
  Confluence tree). They're CLI-only today (`docs/agents.md`); ask ob1-can-obi to add API
  endpoints.
- **Diffs:** the Terraform plan for each `iac` step is in that step's log during Build.

## Rules

- **The server decides.** Grey out buttons as a hint (the console does, from
  `latest.*.status`), but never re-implement runner rules in the UI. The `409` is the truth.
- **All backend calls go through `api.js`.** A new endpoint goes in `backend/app/mac_api.py`,
  with a test in `backend/tests/test_api.py` and a line in `docs/api.md`.
- **No secrets in the frontend.** Sign-in is a cookie the server sets; the UI only reads
  `GET /api/auth/me` to show who's signed in and to grey out buttons.
- Branch → PR → CI → merge (`AGENTS.md`). Add a `plan.md` entry if your change affects others.
