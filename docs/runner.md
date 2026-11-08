# MaC runner and `migration.yaml` (schema `mac/v0.3`)

The runner is deterministic: no model is in the execution path. The only LLM call MaC makes
is during Build, to write the design page's prose (see below); nothing it writes is executed.
Code: `backend/mac/`. Example: `examples/claims-adjudication/migration.yaml`.

## The three buttons

| | What it does | Changes anything? | Allowed when |
|---|---|---|---|
| **Build** | Validates the spec, locks every repo's `main` to a commit, checks guardrails on GitHub, writes the design page, raises the approval tickets that are due, runs `terraform plan` for `iac` steps and runs `check` steps that come before any change | Nothing in AWS (it does write to Confluence and Jira) | Always |
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
**An undo is verified, not trusted:** after each `terraform destroy`, the runner runs
`terraform state list` for that step; anything still in state fails the undo with the leftovers
named. A clean undo ends with a `run` event "Undo verified: N step(s) undone and checked empty";
an incomplete one with "Undo NOT complete: …" (press Undo to retry).
The runner keeps undoing the other steps either way. `rollback_failed` means a person has to look.
If the runner itself crashes or restarts mid-run, a Rehearse or Deploy ends `rollback_failed`
(what it left behind is unknown), but a Build just ends `failed`: it only reads and plans.
**Undo** does the same for a finished Deploy, or for a run that's waiting.

**Cancel** stops any active run and undoes everything it did: a waiting run is undone at once;
a run mid-step finishes that step first (a running script is killed on the spot, a Terraform
command is left to finish, because a half-applied state is worse than a finished step that gets
destroyed a moment later). The run ends `cancelled`. A Build that's cancelled just stops.

## Stages, manual steps and approvals

- `stages` are the pipeline's columns, run left to right. Within a stage, `needs` decides the
  order, then the order in the file. `needs` can't point at a later stage.
- `when: manual` makes a step wait until someone presses **play**, in Rehearse and Deploy.
- `requires_approval` makes a step wait in **Deploy** until those approvals' Jira tickets are
  approved. A rejected ticket fails the run, which undoes everything. Rehearse doesn't wait for
  approvals, since it only touches the rehearsal environment.
- A waiting run continues with `play` (manual step) or `resume` (approvals checked again).

## Approvals: tickets raised by MaC

MaC raises the Jira tickets itself, in plain code from the spec (summary, justification, the
steps each approval unblocks), never written by a model. Rules:

- **One ticket per approval, kept across plan versions.** Re-running never duplicates a ticket,
  and editing the plan doesn't raise new ones either: the existing ticket gets a Jira comment
  saying the plan was updated (the design page is rewritten in place), and keeps whatever
  status the approver gave it. Approvers judge the plan on the design page, not a version hash.
- **Chains:** an approval with `after: [X]` isn't requested until X is approved. If X is
  rejected, it counts as rejected too. Demo: the MCP team is only asked after the manager.
- **`design_doc: true`:** the ticket links the design page and isn't raised until the page
  exists for this version of the plan.
- Tickets are raised when Build runs, and when Deploy (or `resume`) reaches a step that needs
  them. Statuses map by name: `Approved` or `Done` approves; `Rejected`, `Declined` or
  `Won't Do` rejects; anything else is pending.
- Build's report lists every approval with its status, ticket and why it's waiting.
- **Approvals follow Jira on their own.** The server asks Jira about every outstanding approval
  every `MAC_APPROVAL_POLL_SECONDS` (default 30, 0 turns it off), and Jira can push changes to
  `POST /api/mac/jira/webhook?token=<MAC_JIRA_WEBHOOK_SECRET>`. Either way `Runner.sync_approvals`
  records the new statuses, raises the next ticket of an `after` chain the moment its
  predecessor is approved, and continues every Deploy that was waiting (a rejection fails it and
  undoes everything). Nobody has to press "Check approvals".

## The design page (the one LLM call)

During Build, MaC sends the migration's facts (every step, repo, locked commit, undo and
approval, assembled by code) to an LLM (Nemotron on NVIDIA NIM by default), gets a design
document back in Markdown, and publishes it to Confluence. The Tech Risk ticket links to it.

- The model's output is only ever text on that page. Code converts it with everything escaped,
  and appends an appendix generated from the spec, so the steps listed are exactly what runs.
- The page is rewritten only when the spec changes, updating the same page in place.
- If the LLM or Confluence fails or isn't configured, **Build still passes**. The design-doc
  tickets just wait, and Build tries again next time.

## The cost estimate (code only)

At the end of a passing Build, MaC works out what the migration will cost on AWS each month,
and every number in it has a source:

| Input | Where it comes from |
|---|---|
| What gets created | Terraform's own plan: Build runs `terraform plan -out`, then `terraform show -json`, and keeps each resource's type and a few non-sensitive attributes (`memory_size`, `billing_mode`, ...) in `report.resources` |
| How much it's used | the usage reader's figures (`docs/agents.md`), each with its Confluence section and quote, saved in `<data dir>/usage/<migration>.json` |
| What AWS charges | AWS's public Price List offer files for the target region, with each price's SKU, rate code and dates; the saved copy `backend/mac/prices_snapshot.json` if AWS can't be reached |
| Pricing rules | the AWS rules the formulas use (read and write units per KB, 100 bytes of item overhead, GB-seconds), each linked to AWS's docs |

`mac/cost.py` multiplies them and writes each line's formula, for example `1,261,330
invocations × 60 ms ÷ 1,000 × 256 MB ÷ 1,024 = 18,919.9 GB-seconds`. Tiered prices (the
DynamoDB storage free tier, Lambda's duration tiers) are applied to the total per price, as AWS
bills them. IAM, function URLs and Lambda permissions are listed as no charge, with AWS's page
saying so. Resource types it can't price yet are listed, never left out silently.

- A figure the docs don't give leaves its line **unpriced**, with the Jira question asking for it,
  and the estimate is `partial`. No saving is claimed against a partial total.
- With the finance page's figures, it compares with today's on-prem cost.
- The estimate goes in `report.cost`. When it changes, the design page is republished with a
  code-generated "Cost estimate" section (formulas, prices with SKUs, quotes linking to
  Confluence), and each design-page approval's ticket (Tech Risk) gets one comment with the
  summary. Building again with the same estimate repeats neither.
- No model is called: the usage reader ran before. A cost problem (no figures yet, AWS down
  and no snapshot) **never fails a Build**; it only shows in the report.

The order: Build (its plans list the resources), then `mise run mac usage <spec>` (or
`POST /api/mac/migrations/{name}/usage`), then Build again. `mise run mac cost <spec>`
recalculates the estimate from the last Build without running one.

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
  - id: APPR-MGR-001
    type: access_request_manager
    approver: manager # who signs off; mapped to a Jira assignee by MAC_JIRA_ASSIGNEES
    summary: "Manager approval: the service needs the Claims MCP tool" # the ticket title
    justification: ... # the ticket body
  - id: APPR-MCP-001
    type: access_request_owner
    approver: claims-mcp-team
    summary: ...
    after: [APPR-MGR-001] # not requested until the manager approves
  - id: APPR-TR-001
    type: tech_risk_cloud_migration
    approver: tech-risk
    summary: ...
    design_doc: true # link the design page; wait for it to exist
steps:
  - id: db_migrate
    stage: data
    type: db_migration # check | script | iac | db_migration
    needs: []
    requires_approval: [APPR-TR-001]
    when: manual # auto (default) | manual
    codegen: engineer # engineer (default) | llm: who writes this step's code from the migration guide
    run: { repo: github.com/MaC-aroni/claims-db-migrate, entrypoint: migrate.py }
    verify: { entrypoint: verify.py } # optional repo:, defaults to run.repo
    rollback: { entrypoint: rollback.py }
guardrails: { require_ci_green: true, require_protected_branch: true, require_review: true }
diagnostics: { mode: explain } # default AI help; a run can override it
```

**Outputs and probes.** A step can declare what it hands back, and how to check it:

```yaml
    outputs:
      - name: url                      # Terraform: the output of that name; scripts: written to $MAC_OUTPUTS
        description: The service's AWS Lambda URL
        probes:                        # signed requests anyone can trigger from the console
          - {name: health, method: GET, path: /health}
          - {name: adjudicate, method: POST, path: /adjudicate, body: {claim_id: CLM-1001}, expect: 200}
```

After a step runs, the runner records each declared output on the run (`run.outputs[step][name]`)
and logs `output url = …`. **A declared output that wasn't produced fails the step**, which undoes
everything: the planner promised it. Terraform outputs come from `terraform output -json` after
apply (sensitive ones are never read); scripts write a JSON object or `NAME=value` lines to the
file named by `$MAC_OUTPUTS`. Probes send a SigV4-signed request (the landing zone only allows
signed calls) and keep AWS's answer; see `docs/api.md`.

Rules `mac validate` enforces:
- `repo` is `github.com/<owner>/<repo>`, optionally `@<branch>`. It defaults to `main`.
- `iac` steps have `run.path`, a Terraform directory, and roll back with `terraform destroy`.
- `script` and `db_migration` steps have a `rollback.entrypoint`. `check` steps have no rollback.
- `db_migration` steps need `verify`, and get a warning if they aren't `when: manual`.
- Approvals have an `approver` and a `summary`. `after` names other approvals, with no loops.
- No duplicate ids, no unknown references, no loops.
- Output and probe names are unique per step; probe paths start with `/`; only POST probes have a body.

Changes in v0.3: approvals lost `jira:` (MaC raises the tickets) and gained `approver`,
`summary`, `after` and `design_doc`. Steps gained `codegen`: the engineers decide, step by step
and in review, which parts of the pipeline the LLM may write code for. LLM-written code always
arrives as a pull request a person reviews.

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
| `MAC_OUTPUTS` | (run action only) a file to write the step's declared outputs to: JSON, or `NAME=value` lines |
| `MAC_TARGET_ACCOUNT`, `MAC_TARGET_REGION`, `AWS_REGION` | the target for this environment |

Rollback scripts must be safe to run when the step only partly happened. Entrypoints run with
the runner's Python, which has `boto3`; anything else they need has to come from the stdlib.

**Terraform** (`iac` steps): the runner writes `mac_backend_override.tf` into the Terraform
directory, so state always lives in the S3 bucket at
`mac/<migration>/<rehearsal|production>/<step>.tfstate`, with S3 locking. The module receives
`TF_VAR_mac_env` and `TF_VAR_mac_run_id`. Declare `variable "mac_env" {}` and use it in
resource names.

Build's `terraform plan` runs with `-lock=false` (it's read-only), so a Build never waits on
or leaves a state lock. If a Rehearse or Deploy is killed mid-command (the server restarted),
its S3 lock stays behind and the next apply fails with "Error acquiring the state lock"; when
nothing is running, `mise run mac-unlock` removes stale locks.

Each action's checkout is deleted as soon as it finishes (the log is in the store), and
finished runs' work dirs are pruned when the server starts. Terraform providers are downloaded
once into `<MAC_DATA_DIR>/tf-plugin-cache` (`TF_PLUGIN_CACHE_DIR`) and shared by every step and
run; without that, each `iac` step pulled its own ~700 MB AWS provider.

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

The AI behind the selector is `mac/aihelp.py`, on whatever LLM `MAC_LLM_API_KEY` (or
`NVIDIA_API_KEY`) points at; without a key, failures record that AI help is off. What it does:
- **Explain** sends the step, the last log lines and the company standards the step cites
  (numbered sources) to the model, and puts its answer on the run as a `diagnosis` event: what
  went wrong, likely cause, where, what to do.
- **Report** also reads the step's code **at the exact commit that ran** (only the step's own
  files; never data, tests or CI) and writes a Markdown report for a coding agent:
  `GET /api/mac/runs/{id}/report.md`.
- **Auto-fix** also asks for the changed files, keeps only what the guardrails above allow,
  pushes them to `mac/autofix/<run-id>` in the failing repo, and re-runs Build and Rehearse with
  that branch (`autofix` on those runs: parent, branch, attempt). A passing rehearsal opens the
  pull request; after 3 failed attempts the branch is handed over in a PR for a person. When a check
  (`smoke_test`) fails, the model picks which earlier step's code caused it (code accepts only a
  step that ran and isn't a check), and that step's code is read and fixed. Checks themselves are
  never patched: they're what prove a fix.

**Undo retries and restarts.** `undo` also works on a `rollback_failed` run: it redoes only the
steps that weren't undone (and the failed step's own cleanup). After a server restart, a Rehearse
or Deploy that was cut off mid-work is settled and its undo is queued automatically.

## CLI

```
mise run mac validate examples/claims-adjudication/migration.yaml
mise run mac build    <spec> [--branch github.com/o/r=branch]
mise run mac rehearse <spec> [--ai explain|report|autofix]
mise run mac deploy   <spec> [--ai explain|report]
mise run mac play <run-id> <step>   |  resume <run-id>  |  undo <run-id>
mise run mac status <run-id>        |  logs <run-id> [--step id]  |  runs
mise run mac usage <spec>           # the usage reader (LLM): the figures the cost estimate needs
mise run mac cost <spec>            # the cost estimate from the last Build, with every source
mise run mac prices [--refresh]     # AWS's prices it uses; --refresh saves them as the snapshot
```

Configuration comes from environment variables:

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | read access to the pipeline's repos |
| `ATLASSIAN_SITE`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | one Atlassian site for Jira and Confluence, e.g. `https://<your-site>.atlassian.net`. Without them, approval steps wait |
| `JIRA_PROJECT` (default `MAC`), `JIRA_ISSUE_TYPE` (default `Task`) | where tickets go |
| `MAC_JIRA_ASSIGNEES` | optional JSON, approver name → Jira accountId, e.g. `{"manager": "712020:…"}` |
| `CONFLUENCE_SPACE_KEY` | the space for design pages. Without it, no page (Build still passes) |
| `NVIDIA_API_KEY`, `MAC_LLM_MODEL` (default `nvidia/nemotron-3-ultra-550b-a55b`), `MAC_LLM_BASE_URL` | the LLM that writes the design page |
| `MAC_TF_STATE_BUCKET`, `MAC_TF_STATE_REGION` | the S3 bucket for Terraform state |
| AWS credentials | the usual `AWS_PROFILE`, or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `MAC_DATA_DIR` | run history, logs, the Terraform provider cache and work dirs (default `./.mac`) |
