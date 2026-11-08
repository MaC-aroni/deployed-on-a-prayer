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
| MaC runner | `backend/mac/`, spec `mac/v0.2`, rules in [`docs/runner.md`](docs/runner.md) |
| Demo pipeline | [`examples/claims-adjudication/migration.yaml`](examples/claims-adjudication/migration.yaml) |
| How to ship | branch → PR → CI passes → merge (no review). Deploy to Fly is manual and maintainers-only |
| Not built yet | AWS account and state bucket, the 3 demo repos, HTTP API for the UI, UI, Jira, agents |

---

## Entries

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
