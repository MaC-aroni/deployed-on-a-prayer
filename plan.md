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
| Not built yet | Real credentials (Zafeer), UI, API endpoints for the agents |

---

## Entries

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
