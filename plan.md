# plan.md: what changed, and how to adapt

A running log of changes the rest of the team needs to know about. **Newest entry first.**

**Adding an entry:** in the same PR as the change, add a section at the top of "Entries" with
the date, who made it (and which agent, if any), what changed, and **what others have to do
differently**. Keep it short; link to the docs instead of repeating them.

---

## Current state (keep this up to date)

| | |
|---|---|
| Repo | https://github.com/MaC-aroni/deployed-on-a-prayer (public, org `MaC-aroni`) |
| Live app | https://deployed-on-a-prayer.fly.dev: the MaC console at `/`. Anyone can watch; the buttons need **Sign in with GitHub** and write access to this repo. Real AWS, Jira and Confluence behind it. Run history on the Fly volume `mac_data` |
| Stack | FastAPI backend (`backend/`), React + Vite frontend (`frontend/`), one Fly.io app |
| MaC runner | `backend/mac/`, spec `mac/v0.3`, rules in [`docs/runner.md`](docs/runner.md) |
| Runner API (for the UI) | `/api/mac/...` in `backend/app/mac_api.py`, contract in [`docs/api.md`](docs/api.md) |
| Demo pipeline | [`examples/claims-adjudication/migration.yaml`](examples/claims-adjudication/migration.yaml): 8 steps, 4 repos, 3 approvals |
| Demo repos | `claims-service-iac`, `claims-db-migrate`, `claims-mcp-server`, `claims-smoke-tests` on GitHub in `MaC-aroni`, protected and reviewed |
| How to ship | branch → PR → CI passes → merge (no review). Deploy to Fly is manual and maintainers-only |
| Knowledge base | 14 Confluence pages for the fictional Prayerwell Health in [`demo-data/confluence/`](demo-data/confluence/); publish with `mise run mac publish-knowledge demo-data/confluence` |
| Migrations repo | `MaC-aroni/mac-migrations`: AI-generated `migration.yaml` PRs that engineers review |
| Agents | Knowledge graph, planner, guide writer, code writer: [`docs/agents.md`](docs/agents.md) (tested with a scripted LLM; not yet run against real Nemotron or Confluence) |
| UI | `frontend/`: the console at `/` (Build → Migrate · Pipelines, live DAG, step logs, approvals, Build report, runs), mock pitch page at `/demo`; rules in [`UI.md`](UI.md) |
| Planning API | `/api/mac/services`, `/plan`, `/ingest`, `/plans/...` in `backend/app/planning_api.py`, contract in [`docs/planning-api.md`](docs/planning-api.md) |
| Not built yet | API endpoints for the guide and code writers; the Diagnostician behind Explain · Report · Auto-fix |

---

## Entries

### 2026-11-08: Migration flow with agents: Learn, detect-or-plan, breakpoints, investigate (Elathius, with Claude Code)

#### What changed
- **Sidebar:** Build → **Migration** and **Pipelines (count)** are the two big items; pipelines
  only exist once a migration started, and the empty Pipelines page says so.
- **Migration page:** every service and every repo has two doors, **Confluence** (the page, or
  the console's copy at `/knowledge/<page>` until it's published) and **GitHub**. One primary per
  service: **Launch agent** (learn if needed → detect an existing `migration.yaml` or write one →
  render the pipeline → start Build) or **Open pipeline** when one exists. Undocumented repos get
  **Learn**: an agent writes the knowledge page from the repository, merges the graph and raises
  a Jira review ticket; the service then shows "under review · MAC-n".
- **Agent view** at `/agents/<run>`: the hierarchy (Director → Readers / References / … →
  Compiler) with each agent's observation → reasoning → action → outcome and model. Every
  running agent shows the working-agent icon (`frontend/src/assets/greenloading.gif`); clicking
  it opens this page. `/agents/demo` replays a mock Learn for the pitch.
- **Pipeline:** `when: manual` steps are drawn as breakpoints; the primary button reads
  **Continue · <step>** while the run waits there. On a failed run **Investigate** launches the
  Diagnostician (Logs · Code · Fixer → Compiler raises the approval ticket); its card shows the
  root cause and the proposed fix with **Approve fix**, which opens the pull request. Nothing
  merges by itself.
- **Planning API** (`backend/app/planning_api.py`, own module, nothing in `mac_api.py` touched):
  `POST /learn`, `GET /knowledge/{page}`, `POST /runs/{id}/investigate`,
  `POST /runs/{id}/approve-fix`; `POST /plan` takes `reuse` and `build`; `GET /services` adds
  `page_url`, `generated`, `review`, `migration`. Every run emits `agent` events (JSON message:
  agent, parent, role, model, phase, status, text). Contract: `docs/planning-api.md`.
- Fixed: status dots were grey everywhere (the `.status` default outranked the tone classes).
- [`docs/ui-data-needs.md`](docs/ui-data-needs.md) rewritten: screen by screen, what renders
  from what and when, what's still a gap (auto-diagnosis wiring, `needs`, failure tail, agent
  events from the runner's own agents, Confluence URLs on Fly), plus the Endpoints card to come.

#### How to adapt
- Generated knowledge pages live in `<MAC_DATA_DIR>/knowledge/` (`/data` on Fly), proposed fixes
  in `<MAC_DATA_DIR>/fixes/`; both survive deploys with the volume.
- Review and fix-approval tickets go through the runner's Jira integration (`ATLASSIAN_*`); with
  it unset the runs say "not raised" and finish anyway.
- The Confluence doors open Confluence only where `publish-knowledge` ran (it records the URLs
  in the store); otherwise they open the console's page view.
- Frontend: `follow()` now also streams `agent`, `approval` and `failure` event kinds.

### 2026-11-08: The console at `/`, the Migrate flow, planning endpoints (Elathius, with Claude Code)

#### What changed
- **`/` is the full console** (`frontend/src/pages/`, `components/`), replacing the consoles from
  #12 and #16, which stay in `frontend/src/mac/` unrouted as a reference until the team agrees to
  remove them. Their step info panel is adopted here as the pipeline's step inspector. It keeps the rules in `UI.md`: every call goes through
  `frontend/src/mac/api.js`, `409` reasons are shown as they are, sign-in is the server's cookie
  (`GET /api/auth/me` drives the Sign-in button), the server decides.
  - Sidebar **Build → Migrate · Pipelines**, then Runs and a mock Pitch demo (`/demo`).
  - Pipeline lines are one chain in the runner's execution order (a failure skips the rest),
    plus explicit `needs`. Clicking a step opens a panel with live logs, repo and locked commit,
    undo, ▶ for manual steps. Tabs: Approvals, Build report, Activity, History.
- **Migrate flow:** `/migrate` lists the services in the knowledge graph with their repos;
  "Migrate to AWS" runs the Planner and shows each attempt live (`/migrate/<run>`), then
  "Open pipeline" lands on the generated plan (`/plans/<run>`) where Build / Rehearse / Deploy
  work as for a reviewed spec.
- **Planning endpoints** in a module of their own, `backend/app/planning_api.py`, mounted by
  one line in `backend/app/main.py`: `GET /api/mac/services`, `POST /api/mac/plan`,
  `POST /api/mac/ingest`, `GET /api/mac/plans`, `GET /api/mac/plans/{run}`,
  `POST /api/mac/plans/{run}/build|rehearse|deploy`. Plans and ingests are ordinary runs
  (modes `plan`, `ingest`), so `/runs/{id}`, `/events` and `/stream` follow them unchanged.
  Contract: [`docs/planning-api.md`](docs/planning-api.md). It's separate from `mac_api.py`
  (not what `UI.md` says) so the UI team's additions never touch the runner API's module;
  it imports `mac_api`, `auth` and `mac.agents_cli` and changes none of them.
- `backend/.env.example` says, for every variable, what it is and where to get it.
- [`docs/ui-data-needs.md`](docs/ui-data-needs.md): what the console wants from the API that it
  doesn't get yet (real `needs`, failure details, timings, agent reasoning events, approval
  events). Requests, not changes; for the backend team to pick up.
- Look: dark, calm dashboard with one purple accent; tokens in `frontend/src/styles.css` only.
  One primary action per page (the next step), everything else in the ··· menu.
- Frontend dependency: `lucide-react` (icons).

#### How to adapt
- Run the knowledge-graph ingest once before a demo (`/migrate` → Ingest, or `mise run mac
  ingest`); it's 14 LLM calls. The API and CLI share `.mac/` at the repo root.
- **Nemotron track:** the live site's `MAC_LLM_BASE_URL` / `MAC_LLM_MODEL` currently point at
  Grok. Point them at NVIDIA NIM (and set `NVIDIA_API_KEY`) before the pitch.
- New step states or run statuses need a colour in `frontend/src/status.js`.

### 2026-11-08: Cancel, and tickets that survive plan changes (ob1-can-obi, with Claude Code)

#### What changed
- **Tickets are raised once.** Editing `migration.yaml` no longer raises fresh Jira tickets: the
  existing ticket keeps its status and gets a comment that the plan was updated (the design
  page is rewritten in place). Re-running Build never duplicates anything.
- **Cancel:** `POST /api/mac/runs/{id}/cancel` stops any running or waiting run and undoes
  everything it did; a running script is killed, a running Terraform command finishes first.
  New run status **`cancelled`** (terminal, everything undone). A cancelled Build just stops.
- Reminder: only **Deploy** waits for approvals. Rehearse never does.

#### What you need to do
- **Elathius (UI):** add a **Cancel** button on active runs (`running`, `waiting`), with a
  confirmation ("stop and undo everything this run did"), and colour the new `cancelled`
  status like `undone` (purple). `docs/api.md`.

### 2026-11-08: AI help is connected; region bug; undo retries (ob1-can-obi, with Claude Code)

#### What changed
- **The first real Rehearse on prod failed at `db_migrate` with `NoRegionError`:** the runner set
  `AWS_REGION` but boto3 reads `AWS_DEFAULT_REGION`. Both are set now; no script needs to know
  the region. Terraform had already undone the table and roles, so AWS was left clean.
- **Explain · Report · Auto-fix work for real** (`mac/aihelp.py`, on the configured LLM):
  Explain puts a grounded diagnosis on the run; Report reads the step's code at the commit that
  ran and writes `GET /runs/{id}/report.md`; Auto-fix pushes guardrail-checked changes to
  `mac/autofix/<run>` and re-runs Build + Rehearse up to 3 times, opening the PR when it passes.
- **Undo can be retried** on a `rollback_failed` run (only what wasn't undone). After a restart,
  a cut-off Rehearse/Deploy gets its undo queued, not just a label. Fly waits up to 5 minutes
  for the app to exit on deploy or stop.

#### What you need to do
- **Elathius (UI):** `diagnosis` events are now Markdown (render them); show a "Download report"
  button when the run view's `ai_report` is true (`GET /runs/{id}/report.md`); show
  `run.autofix` (branch, attempt, PR link) on auto-fix runs; enable **Undo** on `rollback_failed`
  runs ("Retry undo"). `docs/api.md`.
- Everyone: the AI mode's answers now take 10–60 s after a failure (LLM calls); the run is
  already final by then, so nothing waits on them.

### 2026-11-08: Step outputs and probes: show the service answering from AWS (ob1-can-obi, with Claude Code)

#### What changed
- **Spec:** steps can declare `outputs` (e.g. the deployed service's `url`) with `probes` (signed
  requests that prove it answers). The planner is told to declare them for anything callable.
  A declared output that isn't produced fails the step and undoes everything. `docs/runner.md`.
- **The demo plan** now declares `provision_storage.table_name`, `deploy_mcp_server.url`, and
  `deploy_service.url` with two probes: `GET /health` and `POST /adjudicate {claim_id: CLM-1001}`.
  This changes the spec's digest, so **the next Build raises fresh Jira tickets** and rewrites
  the design page (approvals cover an exact plan).
- **API:** runs carry `outputs`; `GET /migrations/{name}` has `endpoints` (latest URL per
  environment, and whether it should still be live); `POST /runs/{id}/outputs/{step}/{output}/probes/{probe}`
  sends the signed request and returns AWS's answer (status, body, Lambda request id, timing,
  an equivalent `curl`); `GET /runs/{id}/probes` is the history. Open to viewers, no sign-in.
- Lambda URLs here only take SigV4-signed requests, so a plain curl gets 403. AWS also answers
  **403 for a URL that doesn't exist**: that's the "before" (and the "after undo").

#### What you need to do
- **Elathius (UI):** add an "Endpoints" card (from `endpoints`) with a button per probe that
  calls the probe endpoint and shows status, `request_id`, `elapsed_ms` and the JSON body; and a
  before/after list from `GET /runs/{id}/probes`. Show the `curl` with a copy button.
  `docs/api.md` → "Outputs and probes" has the shapes.

### 2026-11-08: Instant approvals through a Jira webhook (ob1-can-obi, with Claude Code)

#### What changed
- `mise run mac-jira-webhook` sets `MAC_JIRA_WEBHOOK_SECRET` on Fly and registers a Jira webhook
  (issue updated, project `MAC`) that calls MaC. Approving a ticket now reaches the console in
  about a second; the 30 s poller stays on as a safety net.
- The access log masks `token=`, `code=` and `state=` in URLs, so the webhook secret and GitHub
  sign-in codes never land in `fly logs`.

#### What you need to do
- Nothing. **Elathius:** no API change; approvals just update sooner.

### 2026-11-08: Approvals follow Jira on their own (ob1-can-obi, with Claude Code)

#### What changed
- **No more "Check approvals".** The server asks Jira about every outstanding approval every 30 s
  (`MAC_APPROVAL_POLL_SECONDS`), and Jira can push changes instantly to
  `POST /api/mac/jira/webhook?token=<MAC_JIRA_WEBHOOK_SECRET>`. When a ticket is approved, MaC
  raises the **next ticket in the `after` chain** by itself (manager approved → the MCP team's
  ticket appears), and any Deploy waiting on that approval continues. A rejection fails the
  Deploy and undoes everything.
- `GET /api/mac/migrations/{name}` now carries the **live** state per approval: `status`,
  `detail`, `checked`, plus `approvals_checked` and `approvals_live`. These no longer depend on
  the last Build.
- `POST /api/mac/migrations/{name}/approvals/sync` checks Jira right now.
- The migration's latest run gets a log line when Jira changes: `approvals changed in Jira: …`.
- Docs: `docs/api.md` (Migrations), `docs/runner.md` (Approvals), `docs/cloud-setup.md` (the
  webhook setup, 1 minute in Jira).

#### What you need to do
- **Elathius (UI):** read `approvals[].status` / `detail` / `checked` from the migration detail
  instead of the Build report, and re-fetch the detail on a timer (the console already polls
  every 30 s when idle). Show `checked` as "as of …". The "Check approvals" button can call
  `POST /migrations/{name}/approvals/sync` and is now a convenience, not a necessity. When a
  run's log says `approvals changed in Jira`, re-fetch the detail too.
- **ob1-can-obi:** optionally set `MAC_JIRA_WEBHOOK_SECRET` on Fly and create the Jira webhook
  (`docs/cloud-setup.md`); without it, changes arrive within 30 s instead of instantly.

### 2026-11-08: Prod latency fixed: disk, SQLite, health check (ob1-can-obi, with Claude Code)

#### What changed
- **The cause:** every `iac` step downloaded its own ~700 MB AWS provider into a fresh checkout
  and nothing was ever deleted (11 GB locally after three Builds). On Fly the 1 GB volume filled
  during the first Build, Terraform crawled, the health check timed out and the proxy refused
  requests. Fly then auto-stopped the only machine mid-run because `primary_region` wasn't set.
- Terraform providers now go to one shared cache (`TF_PLUGIN_CACHE_DIR` under `MAC_DATA_DIR`);
  each action's checkout is deleted when it finishes; finished runs' work dirs are pruned at
  startup.
- SQLite runs in WAL mode, so the API reads history while a run writes logs; the live stream's
  database reads moved off the event loop; `/api/health` is async.
- Fly: `primary_region = "lax"`, 1 GB memory, health check timeout 10 s, grace 30 s. The
  `mac_data` volume was extended to 3 GB.

#### What you need to do
- Nothing. If you ran Builds locally before this, `rm -rf .mac/work` frees the space.

### 2026-11-08: Console v2, GitLab-style (ob1-can-obi, with Claude Code)

#### What changed
- The console was rebuilt to look and work like GitLab's pipeline pages: a job graph with stage
  columns and status icons, tabs (**Pipeline · Jobs · Build report · Approvals · Runs**), a dark
  job trace with line numbers and Terraform diff colouring, a job sidebar with deep links to the
  locked commit, an approvals timeline that draws the `after` chain, and a runs table with stage
  mini-graphs. Rehearse, Deploy and Undo open a confirmation dialog that states what will happen.
- `frontend/src/mac/` is now split into `components/` plus `util.js`; see `UI.md` for the map.
- The URL carries `?m=&run=&step=&tab=`, so a view can be shared or reloaded.
- A rollback in progress shows a progress bar ("undoing 6 finished steps, newest first · 3 / 6").
- Durations per step and per run come from the event timestamps; "requested by" is parsed from
  the run log until the API has a field for it.

#### What you need to do
- **Elathius:** pull `main` and build on this structure. New screens go in `components/`; new
  helpers in `util.js`; new API calls only in `api.js`. The long plan (screens, build order, API
  gaps) is in the "MaC UI Plan" document.

### 2026-11-08: Default Nemotron model changed to the 550B (Zafeer-R, with Claude Code)

#### What changed
- The default model is now `nvidia/nemotron-3-ultra-550b-a55b`. The old default,
  `nvidia/nemotron-3-super-120b-a12b`, is listed by NIM's `/v1/models` but returns **HTTP 404**
  on `/v1/chat/completions` (tested 2026-11-08 with a real key), so every default-model call
  failed: the agents, and the design page, which then silently never appeared.
- Tested through `NIMDesignWriter` with the 550B: 200 in about 9 seconds, all 7 design-page
  headings, no `<think>` text.
- `cli.py` no longer has its own copy of the default: it uses `DEFAULT_MODEL` and
  `DEFAULT_BASE_URL` from `mac/llm.py`, the one place to change them.
- `.env.example` now lists `MAC_LLM_MODEL` and `MAC_LLM_BASE_URL`.

#### What you need to do
- Nothing, if you already set `MAC_LLM_MODEL` (the live app uses Grok through it).
- If you use Nemotron and had no override, pull `main`; the new default applies.
- **ob1-can-obi:** to run Nemotron on Fly, set the secrets `NVIDIA_API_KEY` and
  `MAC_LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b`, and clear `MAC_LLM_API_KEY` and
  `MAC_LLM_BASE_URL` if they point at Grok (`MAC_LLM_API_KEY` wins over `NVIDIA_API_KEY`).
- The 550B is larger than the old default, so expect slower calls and watch the rate limits.

### 2026-11-08: Sign in with GitHub replaces the MaC API token (ob1-can-obi, with Claude Code)

#### What changed
- The live console has a **Sign in with GitHub** button instead of the token box. Anyone can
  open the site and watch runs; pressing a button (Build, Rehearse, Deploy, ▶, Check
  approvals, Undo) needs a GitHub account with write access to `MaC-aroni/deployed-on-a-prayer`.
- `MAC_API_TOKEN` is gone. Every `GET` under `/api/mac` is now open; every `POST` needs the
  sign-in on Fly. New endpoints under `/api/auth` (`docs/api.md`, Access).
- Each run's log says who started it: `requested by @login`.
- Locally nothing changes: `mise run dev-local` needs no sign-in.

#### What you need to do
- Nothing locally. On the live site, click **Sign in with GitHub** once; it lasts 7 days.
- UI work: read `GET /api/auth/me` for who's signed in. Don't add tokens or headers.

### 2026-11-08: The console is live on Fly (ob1-can-obi, with Claude Code)

#### What changed
- https://deployed-on-a-prayer.fly.dev now serves the MaC console, backed by the real runner:
  AWS (account …5238), Jira project `MAC`, Confluence space `CLAIMS`, Grok for the design page.
- Run history, tickets and page ids live on a Fly volume (`MAC_DATA_DIR=/data`), so deploys keep them.
- A crashed Build now ends `failed`, not `rollback_failed` (a Build changes nothing).
- The console's AI setting (Explain / Report / Auto-fix) moved off the action row, and Rehearse
  and Deploy now ask for confirmation.

#### What you need to do
- **Elathius:** build the UI on top of this; read `UI.md` first. Develop against your local copy
  (`mise run dev-local`): buttons on the live site make real AWS, Jira and Confluence changes.
- Ask ob1-can-obi for the MaC API token to use the live console.

### 2026-11-08: The MaC console UI, and Grok for testing (ob1-can-obi, with Claude Code)

#### What changed
- **`/` is now the MaC console** (`frontend/src/mac/`), a GitLab-style pipeline view on
  `/api/mac`:
  - migrations listed on the left
  - Build / Rehearse / Deploy, with the Explain · Report · Auto-fix selector
  - stages as columns and steps as cards, with live status icons, ▶ for manual steps, 🔒
    approval counts, and an "AI" badge for `codegen: llm`
  - a live log per step, streamed from the server
  - approvals with their Jira links, the design page link, and run history
  - Check approvals and Undo buttons
- The old pages moved to `/hello` and `/excuses`.
- **Any OpenAI-compatible LLM:** set `MAC_LLM_API_KEY`, `MAC_LLM_BASE_URL` and
  `MAC_LLM_MODEL` (we test with xAI `grok-4.7`). `NVIDIA_API_KEY` still works.
- The API now keeps run history in `.mac/` at the repo root, the same history as `mise run mac`.
- **Fixed:** LLM calls were capped at 30 seconds, and a timeout crashed the Build. Now the
  timeout is honoured, and no LLM or Confluence failure can fail a Build.
- **Tested for real** through a headless browser against GitHub, AWS, Jira, Confluence and Grok:
  - a Build started from the UI passed
  - Grok wrote the design page into Confluence
  - MaC raised Tech Risk MAC-5 after the page existed

#### How to adapt
- **Elathius:** this is the base to build on. All API calls are in `frontend/src/mac/api.js`;
  the screens are in `Console.jsx` and `console.css`. Colours are CSS variables, with a dark
  mode.
- Run it with `mise run dev-local`. On Fly, paste the MaC API token in the box top right.

### 2026-11-07: The four agents (ob1-can-obi, with Claude Code)

#### What changed
- **Knowledge graph** (`mise run mac ingest`): facts from every knowledge page, each citing its
  section. Code drops anything uncited or made up.
- **Planner** (`mise run mac plan "<goal>" --pr`): writes `migration.yaml` and checks it in a
  loop: `mac validate`, real citations, only documented repos and approvers. It opens a PR
  into `mac-migrations`.
- **Guide writer** (`mise run mac guide <spec>`): a Confluence page tree, one page per stage.
  **Every paragraph must cite a source, enforced by code** (retried, then ungrounded text is
  removed). Citations are links.
- **Code writer** (`mise run mac codegen <spec> <step> --pr`): only for `codegen: llm` steps,
  only inside the step's folder, never tests, CI or lock files. Delivered as a PR.
- Spec: steps and approvals have optional `sources:` (knowledge-base section ids). The demo
  spec cites its sources, and a test checks every citation exists.
- 164 tests. The agents are tested with a scripted LLM that misbehaves on purpose.

#### How to adapt
- Read [`docs/agents.md`](docs/agents.md). The agents need `NVIDIA_API_KEY`; the guide also
  needs Confluence.
- **UI:** these are CLI commands for now. API endpoints for them are next; ask if you need
  them sooner.

### 2026-11-07: Company knowledge base, codegen setting, migrations repo (ob1-can-obi, with Claude Code)

**Where this is going:**
1. The agents read the company's Confluence docs and build a knowledge graph, with the source
   page of every fact.
2. They generate the `migration.yaml`, with approvals and citations, as a PR into
   `mac-migrations`.
3. An LLM writes a migration guide page tree in Confluence: every step, how to write and run
   its code, citations on everything.
4. For steps marked `codegen: llm`, an LLM writes the code from the guide, as a reviewed PR.

This entry is the groundwork for that.

#### What changed
- **Knowledge base:** 14 Confluence pages for the *fictional* **Prayerwell Health** in
  `demo-data/confluence/`:
  - Platform: landing zone, Terraform, naming and tagging, Lambda, MCP tools
  - Access: requesting MCP access (manager, then owner)
  - Tech Risk: migration policy (needs a design doc)
  - Data: claims migration, which says Oracle `DD-MON-YY` dates must become ISO 8601, so the
    planted bug breaks a documented rule
  - Engineering: change management and MaC
  - Services: the claims service and the Claims MCP tool
  - QA: smoke testing
  - The teams and approvers directory

  They match what's built. **`test_knowledge.py` fails if the docs and the demo pipeline
  disagree** (repos, approvers, approval types, stage order, paths, the date rule).
- **`mise run mac publish-knowledge <dir>`** publishes them as one Confluence page tree and
  records each page's URL for citations. Re-running updates the same pages in place.
- **Spec: per-step `codegen: engineer | llm`** (default `engineer`) says who writes that step's
  code. The demo trusts the LLM with `provision_storage`.
- **The `mac-migrations` repo** (set up locally, waiting to be created on GitHub):
  - CI runs MaC's own validator, checked out from this repo, so the rules never drift.
  - `main` will need one approving review.
- The four demo repos' first PRs are merged, and **Build's GitHub guardrails pass for real on
  all four** (CI green, protected branch, approved PR).

#### How to adapt
1. **Changing the pipeline or a demo repo?** Update `demo-data/confluence/` to match. The
   tests will tell you if you forgot.
2. **Atlassian (Zafeer):** once the site and space exist, set `ATLASSIAN_SITE`,
   `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` and `CONFLUENCE_SPACE_KEY`, then run
   `mise run mac publish-knowledge demo-data/confluence`.
3. **UI:** steps now have `codegen` in `GET /migrations/{name}`. Show it on the card (for
   example a small "AI writes this" badge).

### 2026-11-07: MCP tool, MaC-raised approvals, LLM design page, demo repos (ob1-can-obi, with Claude Code)

#### What changed
- **Spec `mac/v0.3`.** Approvals drop `jira:` and gain `approver`, `summary`, `after` and
  `design_doc`. v0.2 files fail validation; see the example and `docs/runner.md`.
- **MaC raises the Jira tickets itself**, in plain code from the spec:
  - once per approval per version of the plan, never duplicated
  - editing the plan raises fresh ones
  - `after` chains them: the MCP team's ticket only appears once the manager approves, and
    a manager rejection fails the run and undoes everything
- **The design page (the one LLM call).** Build sends the migration's facts to Nemotron
  (`nvidia/nemotron-3-super-120b-a12b` on NVIDIA NIM), publishes the returned document to
  Confluence, and the Tech Risk ticket links it.
  - The model only writes prose: its output is escaped, never executed, and followed by a
    code-generated appendix of exactly what runs.
  - If the LLM is down, Build still passes, and only the Tech Risk ticket waits.
- **The demo pipeline** (`examples/claims-adjudication/migration.yaml`):

  | Stage | Step | What it does |
  |---|---|---|
  | check | `preflight` | Right AWS account, AWS reachable |
  | infrastructure | `provision_storage`, `provision_iam` | Create the claims table (DynamoDB) and the two roles |
  | data | `db_migrate` | ✋ manual. Copy the Oracle export in and verify the counts |
  | release | `deploy_mcp_server`, `deploy_service` | Put the Claims MCP tool and the claims service on Lambda (AWS-signed URLs only) |
  | access | `grant_mcp_access` | Let the service's role call the MCP tool |
  | verify | `smoke_test` | Adjudicate a real migrated claim through the service and the MCP tool |

  The approvals: **Tech Risk** covers every production change. **Manager, then MCP team**
  covers the access grant.
- **The database is DynamoDB, created by the pipeline itself**, not a pre-made Postgres
  database. That means no networking to break on stage, nothing for Zafeer to pre-build, and
  undo deletes the table, which proves rollback end to end.
- **The four demo repos are built and tested** (see "How to adapt" for where they are).
  - Each has CI: tests, plus `terraform fmt` and `validate` against the real AWS provider v6.
  - Each resource is named per environment (`mac-claims-<env>-...`) and tagged with the
    deployment ID (`mac:deployment-id`).
  - **The planted bug:** `claims-db-migrate` copies Oracle dates like `01-JAN-24` as they are,
    so the smoke test fails with `time data '01-JAN-24' does not match format '%Y-%m-%d'`.
    Converting the date in `to_item` fixes it.
- **Deployment IDs:** every run's ID reaches each script (`MAC_RUN_ID`) and Terraform
  (`TF_VAR_mac_run_id`), and is on every AWS resource as the `mac:deployment-id` tag.
- `boto3` is now in the backend dependencies, because pipeline scripts run with the
  runner's Python.
- Tests: 123 in MaC, plus 24 across the demo repos. Jira, Confluence, NIM and GitHub are
  tested against a local HTTP server that checks the exact requests.

#### How to adapt
1. Pull `main`, then `mise run setup` (boto3 is new).
2. **Writing or generating specs:** use `mac/v0.3` approvals (`approver`, `summary`, optional
   `after` and `design_doc`). Don't put Jira keys in specs.
3. **UI:**
   - `GET /migrations/{name}` now has `approvals[].ticket` and `design_page`.
   - Build's `report.approvals` values are objects (`{status, detail, ticket, url}`), not
     strings, and Build's report has `design_page`. See `docs/api.md`.
   - Show each approval's `detail` (for example "not requested until APPR-MGR-001 is
     approved") so people know why it's waiting.
4. **Demo repos:** they're waiting to be created on GitHub. Until they're on GitHub they're on
   ob1-can-obi's laptop in `~/Desktop/mac-demo-repos/`. Unlike this repo, their `main`
   **requires one approving review**, because Build checks that every commit it runs was
   reviewed. So Elathius or Zafeer-R must approve their first PRs.
5. **Zafeer (AWS):** the runner's credentials need, in one account and region:
   - DynamoDB (create, delete, read and write tables)
   - IAM (create and delete roles and their policies; `iam:PassRole` on `mac-claims-*`)
   - Lambda (functions, function URLs, permissions, `InvokeFunctionUrl`)
   - S3 on the state bucket
   - `sts:GetCallerIdentity`

   Then set `MAC_TF_STATE_BUCKET`, the AWS credentials, and the account ID in the example spec.
6. **Atlassian (anyone, about 10 minutes):** a free site with a Jira project `MAC` and a
   Confluence space. Set the `ATLASSIAN_*` and `CONFLUENCE_SPACE_KEY` variables listed in
   `docs/runner.md`. Add a "Rejected" status to the Jira workflow, or use "Won't Do".

### 2026-11-07: Cloud setup, corrected for what's built (ob1-can-obi, with Claude Code)

This replaces Zafeer-R's earlier cloud-setup entry and its Confluence pages, which were written
against the morning's plan (VPC/ECS/RDS, DBA and Security approvals, hand-made Jira tickets).

#### What changed
- **[`docs/cloud-setup.md`](docs/cloud-setup.md) rewritten:**
  - **one AWS account**, because of the budget. Rehearsal and production are separated by
    name and state
  - the runner's **exact IAM policy**, scoped to `mac-claims-*` and the state bucket
  - the Jira `MAC` project with `Approved`/`Rejected` statuses, and **no hand-made
    tickets**, since MaC raises them
  - the Confluence space **`CLAIMS`**
  - the NVIDIA key
  - every variable, and the checks in order
- **Removed** `examples/claims-adjudication/confluence/` (the 10 pages from the design doc's
  first list), `scripts/load_confluence.py` and the `load-confluence` task. **The one
  knowledge base is `demo-data/confluence/`,** published with `mise run mac publish-knowledge
  demo-data/confluence`, which builds the page tree and records page URLs for citations.

#### How to adapt
- **Zafeer:** follow the new `docs/cloud-setup.md`:
  - one account
  - the policy as written
  - space key `CLAIMS`
  - don't create tickets by hand; if `MAC-1` to `MAC-3` already exist, close them as
    "Won't Do"

  Send the account ID, state bucket, runner keys, the Atlassian site URL, email, API token
  and the NVIDIA key to ob1-can-obi privately.
- If you loaded the old 10 pages into Confluence already, delete them from the `CLAIMS` space
  so the agents only read the current knowledge base.

### 2026-11-07: Runner API for the UI (ob1-can-obi, with Claude Code)

**For Elathius and the UI agent: build the pipeline screens against [`docs/api.md`](docs/api.md).**

#### What changed
- **New HTTP API at `/api/mac`** over the runner:
  - list and show migrations, with stages and steps in run order, ready to draw as columns
  - Build / Rehearse / Deploy with the AI selector (`ai: explain | report | autofix`)
  - ▶ play, resume and undo on runs
  - run details, history and event logs
  - a **live stream** (server-sent events) of every log line and state change
- **Buttons answer at once:** `202` plus the run when it starts, `409` plus a plain-English
  reason when the runner refuses (e.g. "Run Build first"). The work runs in the background,
  so long runs never block a request.
- **Locked on Fly:** in production every `/api/mac` endpoint needs the `MAC_API_TOKEN` Fly
  secret, and answers 503 until it's set. That's because the app is public and Deploy
  changes real AWS. Locally it's open.
- The runner now splits each action into a quick rule check (`start_*` / `request_*`) and the
  slow work (`execute`). After a restart it re-queues work that never started, and marks runs
  that were cut off mid-work as `rollback_failed`, so nothing looks active forever.
- The Docker image now includes `examples/`, so the API on Fly lists the demo migration.
- Test client: `httpx2` in the dev lockfile. Tests: 76, all passing.

#### How to adapt
1. **UI work:**
   - run `mise run dev-local` (not `mise run dev`); `/api/mac` works locally without a token
   - put a `GITHUB_TOKEN` in `backend/.env` if you want Builds to reach GitHub
   - until the demo repos exist, Builds fail with "repo or branch not found"; those are
     real runs with real events, good for building screens
2. **Follow the contract in `docs/api.md`:**
   - step states for card colours
   - run statuses
   - which buttons to enable
   - show `409` reasons as they are
   - use `EventSource` on `/runs/{id}/stream` for live cards
3. **Don't re-implement runner rules in the UI**, like "can I deploy?". Ask the server and show
   its answer. The UI can grey buttons out as a hint, but the server decides.
4. **Need a field or endpoint that isn't there?** Add it in `backend/app/mac_api.py`, with a
   test in `backend/tests/test_api.py` and the change in `docs/api.md`, or ask ob1-can-obi.
5. **ob1-can-obi:** set `MAC_API_TOKEN` as a Fly secret before using the API on Fly, and add
   a Fly volume for `MAC_DATA_DIR` so run history survives deploys.

### 2026-11-07: Everything up to the runner (ob1-can-obi, with Claude Code)

The first entry, so it covers everything set up so far.

#### What changed

**Repo and workflow**
- The repo moved from `ob1-can-obi/...` to the **`MaC-aroni` org** and is public. Old links redirect.
- **Every change goes through a branch and a PR** (hard rule, from Zafeer-R's #2). No review
  is needed; merge once CI passes. `CODEOWNERS` was removed, so nobody gets auto-requested.
- **CI runs on every push to every branch**: backend lint, tests and `mac validate` of the
  examples; frontend build; a gitleaks scan of the full history. It must pass to merge.
- **Deploy to Fly** is Actions → Deploy → Run workflow on `main`, for ob1-can-obi, Elathius
  and Zafeer-R only. Merging doesn't deploy.
- **API keys** live in Fly secrets, which only ob1-can-obi can set. Send values to them
  privately, and add the key name to `backend/.env.example`.

**Local development** (same commands on macOS, Linux and Windows)
- **`mise.toml` pins the tools**: Node 22.23.4, Python 3.12.16, uv 0.10.2, Terraform 1.17.1.
- Commands: `mise run setup`, `mise run dev` (frontend against the live backend),
  `mise run dev-local` (both locally), `mise run test`, `mise run mac ...`, `mise run lock`.
- **Python packages are locked.** Edit `backend/requirements.in` (or `requirements-dev.in`),
  then run `mise run lock`. Never hand-edit the `.txt` files.
- Scripts are Python (`scripts/`), not bash. Cross-platform rules are in `AGENTS.md`.

**Removed**, so don't look for them
- Hosting on a laptop: the self-hosted GitHub runner, pm2, Tailscale and `prayer-host`.
- `scripts/setup.sh` and `scripts/dev.sh`. Use the `mise run` commands.
- `CODEOWNERS`, required reviews, and the gitleaks GitHub Action (it needs a license for orgs).

**The MaC runner** (PR #1). Details in [`docs/runner.md`](docs/runner.md).
- **Build** checks everything and changes nothing. It locks each repo's `main` to a commit,
  checks guardrails on GitHub (CI green, protected branch, merged through an approved PR),
  reads Jira approvals, runs `terraform plan` and the early checks.
- **Rehearse** runs every step in the rehearsal environment, then undoes all of it. It needs a
  passing Build of the same `migration.yaml`.
- **Deploy** runs in production with exactly the rehearsed commits. It refuses if a repo's
  `main` moved since the Rehearse.
- **Any failure undoes every finished step, newest first.** Steps that never ran are
  skipped. A failed undo is reported as `rollback_failed`, and the runner keeps undoing the rest.
- GitLab-style **stages**, `when: manual` steps (press play), and approvals (Deploy only).
- **AI help selector: Explain · Report · Auto-fix.** The auto-fix guardrails are enforced in
  code: it only acts on Rehearse, it can't edit checks, tests, CI or CODEOWNERS, and a branch
  rehearsal can never be deployed.
- It uses real connectors only (GitHub API, git, Jira, Terraform with S3 state). Stand-ins
  exist only inside unit tests. **We do real AWS deployments.**

#### Decisions behind the runner (agreed 2026-11-07)

| Decision | Instead of (design doc v0.1) |
|---|---|
| Steps point at a repo's `main`; Build locks the commit; Deploy reuses the rehearsed commits | Pinned SHAs in the spec |
| Rehearse is required before Deploy, and is always undone | Build, then Deploy |
| Any failure always undoes the whole run | `on_failure: rollback_all` on some steps |
| GitLab-style `stages` and `when: manual` | `gate: manual` |
| Approvals only through `requires_approval` on steps | `approvals[].blocks` as well |
| No `approval_gate` step type, no `run.action`, no `pin_commits` | Those v0.1 fields |
| "Migrated properly" means data and checks pass; behaviour may differ from the old system | Behaviour parity |
| Terraform state in S3 with S3 locking | S3 plus DynamoDB |
| Steps run one at a time, in order | Parallel where independent (stretch goal) |

#### How to adapt

1. **Pull `main`, then run `mise install` and `mise run setup`.** Terraform, pytest and ruff
   are new.
2. **Write specs in `mac/v0.2`.** v0.1 fields like `action`, `gate`, `on_failure` and
   `@<sha>` refs fail validation. Check with `mise run mac validate <file>`.
3. **Writing a repo the runner runs** (the demo repos)? Follow "Contract for the repos" in
   `docs/runner.md`:
   - name resources with `MAC_ENV`, so rehearsal and production never collide
   - declare `variable "mac_env" {}` in Terraform
   - make rollback scripts safe to re-run
   - merge changes through approved PRs, so Build's review check passes
4. **Building the UI?** Show what the runner records:
   - stages as columns
   - the step states (`pending`, `blocked`, `waiting`, `running`, `succeeded`, `failed`,
     `rolled_back`, `rollback_failed`, `skipped`)
   - the run actions: play, resume and undo
   - the AI selector

   There's no HTTP API yet; tell ob1-can-obi which endpoints you need.
5. **Changing the runner?** It must stay deterministic: no model calls in `runner.py` or
   `executors.py`. Add tests (`mise run test`).

#### Conflicts with `MAC.md` on `elathius/ui` (not merged yet)

`MAC.md` was written before these decisions. Where they differ, the code follows the table
above. Let's settle these before more is built on either:

- **Spec version:** `MAC.md` §2.2–2.3 describe v0.1 (pinned SHAs, `gate: manual`,
  `on_failure`, `approval_gate`, CODEOWNERS review, DynamoDB locks). The runner implements v0.2.
- **Failure handling:** `MAC.md` §5 lists "hold vs rollback on failure" as an engineer's
  choice. The runner always rolls back.
- **Demo target:** `MAC.md` §6 lists the demo target as an OPEN decision (Online Boutique
  GKE→EKS, or Spring PetClinic). The runner's example and the planted Oracle-date failure
  assume the claims-adjudication scenario from the design doc.
- **Knowledge graph:** `MAC.md` decides on a JSON graph in the repo instead of Neo4j. This
  doesn't affect the runner, but the agents will need it.

#### Next

- AWS account ID, region and runner credentials → S3 state bucket (ob1-can-obi).
- The demo repos `claims-service-iac`, `claims-db-migrate` and `claims-smoke-tests` in
  `MaC-aroni`, with real Terraform and the planted Oracle-date bug. These depend on the demo
  target decision above.
- An HTTP API over the runner for the UI.
- A Jira site and project `MAC`; Nemotron agents; the Confluence corpus.
