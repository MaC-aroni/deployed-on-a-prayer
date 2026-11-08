# MaC runner and `migration.yaml` (schema `mac/v0.2`)

The runner is deterministic: no model is in the execution path. AI only reads what happened.
Code: `backend/mac/`. Example: `examples/claims-adjudication/migration.yaml`.

## The three buttons

| | What it does | Changes anything? | Allowed when |
|---|---|---|---|
| **Build** | Validates the spec, locks every repo's `main` to a commit, checks guardrails on GitHub, reads approval status, runs `terraform plan` for `iac` steps and runs `check` steps that come before any change | No | Always |
| **Rehearse** | Runs every step in the **rehearsal** environment, then undoes all of it | Yes, then undone | The latest Build passed, on this exact `migration.yaml` |
| **Deploy** | Runs every step in **production** | Yes | The latest Rehearse passed on this exact `migration.yaml`, and no repo's `main` has moved since |

Deploy runs exactly the commits the passing Rehearse ran. If a repo's `main` moved since,
Deploy refuses: run Build and Rehearse again. Only one Rehearse or Deploy per migration can be
in progress at a time.

## Failure means undo everything

If any step fails, or its `verify` fails, the runner:

1. undoes the failed step's own half-finished work, for `iac` and `db_migration` steps;
2. undoes every finished step, newest first (`check` steps have nothing to undo);
3. marks steps that never ran as `skipped`;
4. asks the AI for help, in the run's mode (see below).

The run ends `failed` if everything was undone, or `rollback_failed` if an undo itself failed.
The runner keeps undoing the other steps either way. `rollback_failed` means a person has to look.
**Undo** does the same for a finished Deploy, or for a run that's waiting.

## Stages, manual steps and approvals

- `stages` are the pipeline's columns, run left to right. Within a stage, `needs` decides the
  order, then the order in the file. `needs` can't point at a later stage.
- `when: manual` makes a step wait until someone presses **play**, in Rehearse and Deploy.
- `requires_approval` makes a step wait in **Deploy** until its Jira tickets are approved.
  A rejected ticket fails the run, which undoes everything. Rehearse doesn't wait for approvals,
  since it only touches the rehearsal environment. Build reports their status.
- A waiting run continues with `play` (manual step) or `resume` (approvals checked again).

## The spec

```yaml
apiVersion: mac/v0.2
kind: Migration
metadata: { name: claims-adjudication-onprem-to-aws, service: ..., owner_team: ... }
target:
  provider: aws
  account: "123456789012"
  region: us-east-1
  rehearsal: { account: "...", region: ... } # optional; defaults to the same account
stages: [check, infrastructure, data, release, verify]
approvals:
  - { id: APPR-TR-001, type: tech_risk_cloud_migration, jira: MAC-1, justification: ... }
steps:
  - id: db_migrate
    stage: data
    type: db_migration # check | script | iac | db_migration
    needs: []
    requires_approval: [APPR-DBA-001]
    when: manual # auto (default) | manual
    run: { repo: github.com/MaC-aroni/claims-db-migrate, entrypoint: migrate.py }
    verify: { entrypoint: verify.py } # optional repo:, defaults to run.repo
    rollback: { entrypoint: rollback.py }
guardrails: { require_ci_green: true, require_protected_branch: true, require_review: true }
diagnostics: { mode: explain } # default AI help; a run can override it
```

Rules `mac validate` enforces:
- `repo` is `github.com/<owner>/<repo>`, optionally `@<branch>`. It defaults to `main`.
- `iac` steps have `run.path`, a Terraform directory, and roll back with `terraform destroy`.
- `script` and `db_migration` steps have a `rollback.entrypoint`. `check` steps have no rollback.
- `db_migration` steps need `verify`, and get a warning if they aren't `when: manual`.
- No duplicate ids, no unknown references, no loops.

Changes from the design doc's v0.1: `stages` and `when` are new; `approvals[].blocks` is gone
(use `requires_approval` on steps); repos follow `main` instead of pinned SHAs (Build locks
them); `run.action` is gone (the button decides plan, apply or destroy); `on_failure` is gone
(failure always undoes everything); there's no `approval_gate` step type.

## Contract for the repos a pipeline runs

Each action is a fresh checkout of the repo at the locked commit. `.py` entrypoints run with
Python; anything else must be executable. Exit code 0 means success. Everything printed
becomes the step's log. The runner sets these environment variables:

| Variable | Value |
|---|---|
| `MAC_ENV` | `rehearsal` or `production`. **Name resources with it**, so a rehearsal never touches production |
| `MAC_MODE` | `build`, `rehearse` or `deploy` |
| `MAC_ACTION` | `run`, `verify`, `rollback` or `plan` |
| `MAC_RUN_ID`, `MAC_STEP_ID`, `MAC_MIGRATION` | identifiers |
| `MAC_RUN_DIR` | a directory kept for the whole run, for passing artifacts between steps |
| `MAC_TARGET_ACCOUNT`, `MAC_TARGET_REGION`, `AWS_REGION` | the target for this environment |

Rollback scripts must be safe to run when the step only partly happened.

**Terraform** (`iac` steps): the runner writes `mac_backend_override.tf` into the Terraform
directory, so state always lives in the S3 bucket at
`mac/<migration>/<rehearsal|production>/<step>.tfstate`, with S3 locking. The module receives
`TF_VAR_mac_env` and `TF_VAR_mac_run_id`. Declare `variable "mac_env" {}` and use it in
resource names.

## AI help when a run fails

One selector: **Explain · Report · Auto-fix**. Each includes the one before it.

- **Explain**: reads the logs and says what went wrong and the likely cause.
- **Report**: also reads the failing repo's code and produces a `.md` report for the
  developer's own coding agent.
- **Auto-fix**: also changes code on a branch `mac/autofix/<run-id>` and re-runs Build and
  Rehearse with that branch, up to 3 attempts. Then it opens a PR into `main`.

Auto-fix guardrails, enforced in code (`mac/diagnostics.py`), not by the model:
- It only acts on Rehearse. A Deploy asking for auto-fix gets Report.
- Builds and rehearsals of an auto-fix branch report that branch's guardrails without blocking
  on them. **Deploy refuses any rehearsal that used a branch**: the fix has to be merged into
  `main` through the repo's normal PR rules first.
- It can't change check or verify scripts, tests, `.github/`, `CODEOWNERS` or `.env` files,
  and it can only touch repos the pipeline uses.

The Nemotron agents plug in behind `Diagnostician` in `mac/diagnostics.py`. Until they do,
failures record that AI help isn't connected yet.

## CLI

```
mise run mac validate examples/claims-adjudication/migration.yaml
mise run mac build    <spec> [--branch github.com/o/r=branch]
mise run mac rehearse <spec> [--ai explain|report|autofix]
mise run mac deploy   <spec> [--ai explain|report]
mise run mac play <run-id> <step>   |  resume <run-id>  |  undo <run-id>
mise run mac status <run-id>        |  logs <run-id> [--step id]  |  runs
```

Configuration comes from environment variables:

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | read access to the pipeline's repos |
| `JIRA_SITE`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | approvals. Without them, approval steps wait |
| `MAC_TF_STATE_BUCKET`, `MAC_TF_STATE_REGION` | the S3 bucket for Terraform state |
| AWS credentials | the usual `AWS_PROFILE`, or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `MAC_DATA_DIR` | run history and logs (default `./.mac`) |
