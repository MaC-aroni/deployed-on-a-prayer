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
| Live app | https://deployed-on-a-prayer.fly.dev (placeholder pages, plus `/excuses`) |
| Stack | FastAPI backend (`backend/`), React + Vite frontend (`frontend/`), one Fly.io app |
| MaC runner | `backend/mac/`, spec `mac/v0.3`, rules in [`docs/runner.md`](docs/runner.md) |
| Runner API (for the UI) | `/api/mac/...` in `backend/app/mac_api.py`, contract in [`docs/api.md`](docs/api.md) |
| Demo pipeline | [`examples/claims-adjudication/migration.yaml`](examples/claims-adjudication/migration.yaml): 8 steps, 4 repos, 3 approvals |
| Demo repos | `claims-service-iac`, `claims-db-migrate`, `claims-mcp-server`, `claims-smoke-tests` (built and tested; waiting to be created on GitHub) |
| How to ship | branch → PR → CI passes → merge (no review). Deploy to Fly is manual and maintainers-only |
| Not built yet | AWS account and state bucket (Zafeer), Atlassian site, UI, the remaining agents |

---

## Entries

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
