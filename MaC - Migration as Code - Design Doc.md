# MaC — Migration as Code
### Agentic legacy-modernization pipelines, generated from the knowledge your company already has

**Hackathon:** 8090 (Legacy System Modernization) × NVIDIA (Nemotron Beyond a Chatbot)
**Status:** Design v1 — 2026-11-07

---

## 1. One-paragraph pitch

Legacy modernization is slow not because the code is hard to move, but because the *coordination* is: undocumented dependencies, Tech Risk approvals, DBA sign-offs, security reviews, and a dozen repos that each have to run in the right order. All of that knowledge exists — in Confluence pages, Jira history, and Git repos — but no one can act on it. **MaC** uses Nemotron agents to read that knowledge, generate a complete **migration pipeline as code** (a reviewable DAG in a Git repo), draft and raise every required approval in Jira with business justification, compose the pipeline from the company's *existing* production repos, and execute it with a deterministic runner that supports step-by-step runs, manual gates, and full rollback. Engineers stop herding approvals and start shipping migrations.

**8090 fit:** makes decades-old, poorly understood systems *actionable* — the documentation becomes an executable plan.
**NVIDIA fit:** Nemotron runs a multi-agent, multi-step, tool-heavy workflow (Confluence, Jira, GitHub, AWS) that plans, raises tickets, reviews, diagnoses failures and self-corrects. It is not a chatbot.

---

## 2. The core concept: Migration as Code

Just as IaC made infrastructure a versioned, reviewable artifact, **MaC makes the migration itself one.** The agent's output is a `migration.yaml` DAG committed to a MaC repo as a pull request. Everything downstream falls out of that:

| Property | Because the pipeline is code |
|---|---|
| Reviewable | It lands as a PR; engineers review it like any code |
| Editable | Add a manual gate, reorder steps, swap a repo ref |
| Versioned | Every migration attempt has a commit SHA |
| Executable | A deterministic runner executes the DAG |
| Auditable | Approvals, runs, and rollbacks are linked to the SHA |
| Reusable | Pipelines become templates for the next team |

**Design principle:** *LLMs plan, review and diagnose. A boring state machine executes.* No LLM is in the execution path of Deploy.

---

## 3. System architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  KNOWLEDGE SOURCES                                                       │
│  Confluence (Tech Risk policies, landing-zone standards, service docs)   │
│  GitHub (existing prod repos: IaC, DB migrations, smoke tests)           │
│  Jira (approval history, open tickets)                                   │
└───────────────┬──────────────────────────────────────────────────────────┘
                │  tools (MCP / REST)
┌───────────────▼──────────────────────────────────────────────────────────┐
│  NEMOTRON AGENT LAYER  (LangGraph, Nemotron via NVIDIA NIM)              │
│                                                                          │
│   1. Ingestion agent   Confluence → Knowledge Graph (Neo4j)              │
│   2. Planner agent     KG + target KG → migration.yaml DAG               │
│   3. Compliance agent  policy → required approvals → Jira tickets        │
│   4. Reviewer agent    lints DAG vs. standards & best practices          │
│   5. Diagnostician     failed run → root cause → proposed fix PR         │
└───────────────┬──────────────────────────────────────────────────────────┘
                │  opens PR
┌───────────────▼──────────────────────────────────────────────────────────┐
│  MaC REPO  (GitHub)                                                      │
│  migrations/<service>/migration.yaml  +  approvals.lock  +  runs/        │
│  Branch protection, CODEOWNERS, CI = `mac validate`                      │
└───────────────┬──────────────────────────────────────────────────────────┘
                │  merged spec
┌───────────────▼──────────────────────────────────────────────────────────┐
│  MaC RUNNER  (deterministic state machine, Python)                       │
│  Build  → pre-flight checks, guardrail verification, approval status     │
│  Deploy → saga execution w/ compensating rollback                        │
│  Run step / Manual gates / Rollback                                      │
│  Executes: pinned repo entrypoints, Terraform, DB migrations             │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│  TARGET: AWS (real account)   +   UI: React DAG console (FastAPI API)    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. The Knowledge Graph

### 4.1 Source: Confluence pages (unstructured)
The "KG" is **built, not assumed**. The ingestion agent reads Confluence spaces and extracts entities and relationships into Neo4j. Two sub-graphs:

- **Legacy graph** — services, databases, dependencies, data classification, owning teams, runbooks, known issues.
- **Target graph** — approved cloud services, Terraform modules, network/landing-zone standards, security baselines, *who approves what*.

### 4.2 Node & edge schema (Neo4j)
```
(:Service {name, env, owner_team, criticality, doc_url})
(:Database {name, engine, version, size_gb, pii: bool, doc_url})
(:Team {name, jira_project, approver_role})
(:Policy {name, trigger_condition, approval_type, approver_team, sla_days, doc_url})
(:CloudService {name, provider, approved: bool, terraform_module, doc_url})
(:Repo {url, purpose, entrypoint, protected_branch})

(:Service)-[:DEPENDS_ON]->(:Service)
(:Service)-[:USES]->(:Database)
(:Service)-[:OWNED_BY]->(:Team)
(:Service)-[:HAS_REPO]->(:Repo)
(:Database)-[:MIGRATES_TO]->(:CloudService)
(:Policy)-[:REQUIRES_APPROVAL_FROM]->(:Team)
(:Policy)-[:TRIGGERED_BY {condition}]->(:Database|:CloudService|:Service)
```

### 4.3 Agent tool contract
The agents **query** the graph via tools; they never receive the whole graph in context.
- `kg.search(text) -> [nodes]` (vector + keyword)
- `kg.neighbors(node_id, depth) -> subgraph`
- `kg.cypher(query) -> rows` (read-only)
- `kg.policies_for(subgraph) -> [Policy]`

### 4.4 Demo corpus (Claude to draft, ~10 Confluence pages)
Medicare-claims flavored, realistic tone:
1. `ClaimsAdjudicationService — Architecture Overview` (on-prem, Java 8, Oracle 12c)
2. `ClaimsAdjudicationService — Runbook`
3. `CLAIMS_DB — Data Dictionary & Classification` (contains PHI)
4. `Eligibility Service — Interface Contract` (downstream dependency)
5. `Tech Risk — Cloud Migration Approval Policy`
6. `Tech Risk — PHI/PII Data Handling Standard`
7. `Platform — AWS Landing Zone Standards` (approved services, VPC layout)
8. `Platform — Approved Terraform Modules`
9. `DBA — Database Migration Sign-off Procedure`
10. `Security — IAM Role Review Process`

---

## 5. The `migration.yaml` spec (MaC schema v0.1)

```yaml
apiVersion: mac/v0.1
kind: Migration
metadata:
  name: claims-adjudication-onprem-to-aws
  service: ClaimsAdjudicationService
  owner_team: claims-platform
  generated_by: nemotron-planner@<run-id>
  source_docs: [confluence:12345, confluence:12346]

target:
  provider: aws
  account: sandbox-123456789012
  region: us-east-1

approvals:                      # drafted & raised by Compliance agent
  - id: APPR-TR-001
    type: tech_risk_cloud_migration
    jira: MAC-14
    justification: >            # written by agent
      Migrating ClaimsAdjudicationService to AWS reduces ...
    blocks: [provision_network, deploy_service]
  - id: APPR-DBA-001
    type: dba_db_migration
    jira: MAC-15
    blocks: [db_migrate]
  - id: APPR-SEC-001
    type: iam_role_review
    jira: MAC-16
    blocks: [provision_iam]

steps:
  - id: preflight
    type: check
    run:
      repo: github.com/org/claims-smoke-tests@a1b2c3d
      entrypoint: checks/preflight.py
    rollback: none

  - id: provision_network
    type: iac
    needs: [preflight]
    requires_approval: [APPR-TR-001]
    run:
      repo: github.com/org/claims-service-iac@9f8e7d6
      path: terraform/network
      action: apply
    rollback:
      action: destroy

  - id: provision_iam
    type: iac
    needs: [provision_network]
    requires_approval: [APPR-SEC-001]
    run: { repo: github.com/org/claims-service-iac@9f8e7d6, path: terraform/iam, action: apply }
    rollback: { action: destroy }

  - id: db_migrate
    type: db_migration
    needs: [provision_network]
    requires_approval: [APPR-DBA-001]
    gate: manual                 # engineer must click "Run" — recommended for DB
    run:
      repo: github.com/org/claims-db-migrate@4c5d6e7
      entrypoint: migrate.py
    verify:
      repo: github.com/org/claims-db-migrate@4c5d6e7
      entrypoint: verify.py      # row counts, checksums
    rollback:
      entrypoint: rollback.py

  - id: deploy_service
    type: script
    needs: [provision_iam, db_migrate]
    requires_approval: [APPR-TR-001]
    run: { repo: github.com/org/claims-service-iac@9f8e7d6, entrypoint: deploy.py }
    rollback: { entrypoint: undeploy.py }

  - id: smoke_test
    type: check
    needs: [deploy_service]
    run: { repo: github.com/org/claims-smoke-tests@a1b2c3d, entrypoint: checks/smoke.py }
    on_failure: rollback_all

guardrails:                      # inherited from source repos; verified at Build
  require_ci_green: true
  require_protected_branch: true
  require_codeowners_review: true
  pin_commits: true
```

### Step types
| type | Build does | Deploy does | Rollback |
|---|---|---|---|
| `check` | runs it (read-only) | runs it; fail → stop/rollback | none |
| `script` | verifies repo guardrails, dry-run if supported | runs entrypoint | runs rollback entrypoint |
| `iac` | `terraform plan`, shows diff | `terraform apply` | `terraform destroy` (scoped to state) |
| `db_migration` | validates connectivity, runs plan | runs migrate + verify | runs rollback script |
| `approval_gate` | checks Jira status | blocks until Approved | n/a |
| `manual` (gate flag) | n/a | pauses for human click | n/a |

---

## 6. The agents (Nemotron via NVIDIA NIM)

Orchestrated in **LangGraph**. Model routing: large Nemotron for Planner/Compliance/Reviewer reasoning; a smaller Nemotron for high-volume ingestion/extraction calls (cost-aware routing — mention in pitch).

### 6.1 Ingestion agent
- **Input:** Confluence space keys.
- **Loop:** list pages → fetch → extract entities/relations (structured output) → upsert to Neo4j → resolve duplicates → attach `doc_url` provenance.
- **Output:** Legacy + Target graphs.

### 6.2 Planner agent
- **Input:** "Migrate `<service>` from on-prem to AWS."
- **Loop:** `kg.neighbors(service, 2)` → identify DBs, dependencies, repos → for each legacy component, `kg.search` target equivalent (Oracle → RDS Oracle / Aurora Postgres; on-prem VM → ECS/EKS per landing-zone standard) → order steps by dependency → emit `migration.yaml` steps + guardrails.
- **Output:** draft DAG (no approvals yet).

### 6.3 Compliance agent
- **Input:** draft DAG + `kg.policies_for(subgraph)`.
- **Loop:** for each policy whose trigger matches (PHI DB → DBA + Tech Risk; new IAM → Security) → write business justification (template: what/why/risk/mitigation/rollback) → `jira.create_issue(project, type, summary, description, assignee=approver_team)` → attach to `approvals[]` and wire `requires_approval` on affected steps.
- **Output:** DAG with approvals; Jira tickets raised.

### 6.4 Reviewer agent
- **Input:** full DAG + Target standards.
- **Checks:** approved-services only, modules from approved list, PHI steps have manual gate, every mutating step has rollback, commits pinned, DAG acyclic. Emits review comments on the PR.
- **Output:** PR review (approve / request changes) — a human still merges.

### 6.5 Diagnostician agent
- **Trigger:** runner reports failed step.
- **Loop:** fetch step logs + repo entrypoint source → root-cause → propose fix (patch to script or spec) → open fix PR → (optionally) re-trigger Build.
- **Output:** PR with explanation. Human approves.

---

## 7. The MaC runner (deterministic)

State machine per step: `pending → blocked(approval|manual) → ready → running → succeeded | failed → rolled_back`.

**Build** (safe, repeatable):
1. Parse & validate spec (schema, acyclic).
2. Guardrail verification per repo ref via GitHub API: CI checks green on pinned SHA, SHA reachable from protected branch, CODEOWNERS review present.
3. Approval status via Jira API → mark blocked steps.
4. `terraform plan` for `iac` steps; run `check` steps.
5. Produce Build report (what will run, what's blocked, planned diff).

**Deploy** (saga):
- Execute ready steps in topological order (parallel where independent).
- Pause at `gate: manual` and at unresolved approvals.
- On failure: run compensating rollbacks in reverse order of completed steps; mark run `rolled_back`; hand logs to Diagnostician.
- **Run step** executes one node (with the same guardrail + approval checks); UI warns "not recommended — use full Deploy for end-to-end test."

Execution sandbox: each repo ref cloned fresh at pinned SHA into an isolated workdir/container; AWS creds via short-lived assumed role; Terraform state in S3+DynamoDB lock.

---

## 8. External integrations (tool contracts)

| System | Used by | Calls |
|---|---|---|
| **Confluence Cloud** (real, free site) | Ingestion | `GET /wiki/api/v2/spaces/{id}/pages`, `GET /pages/{id}?body-format=storage` |
| **Jira Cloud** (same site) | Compliance, Runner | `POST /rest/api/3/issue`, `GET /issue/{key}` (status), webhook → runner on transition |
| **GitHub** | Planner, Runner, Reviewer, Diagnostician | contents, checks (`/commits/{sha}/check-runs`), branch protection, PR create/review |
| **AWS** (real sandbox acct) | Runner | Terraform (AWS provider), boto3 for verification |
| **Neo4j** (Aura free or Docker) | Ingestion, Planner, Compliance | Cypher |
| **NVIDIA NIM** (build.nvidia.com) | all agents | OpenAI-compatible chat completions |

---

## 9. Repositories to create

| Repo | Role |
|---|---|
| `mac-platform` | Agents (LangGraph), runner, FastAPI, React UI |
| `mac-migrations` | **The MaC repo.** `migrations/<service>/migration.yaml`; CI runs `mac validate`; branch protection + CODEOWNERS |
| `claims-service-iac` | "Existing prod" Terraform: network, IAM, ECS service; `deploy.py` / `undeploy.py` |
| `claims-db-migrate` | "Existing prod" `migrate.py`, `verify.py`, `rollback.py` (Oracle→RDS; demo may use Postgres→RDS Postgres) |
| `claims-smoke-tests` | `checks/preflight.py`, `checks/smoke.py` |

Each "existing prod" repo gets GitHub Actions CI, a protected `main`, and a CODEOWNERS file so guardrail verification has real signals to check.

---

## 10. UI (React console)

- **Migrations list** → one migration.
- **DAG view**: nodes colored by state; approval badges linking to Jira; manual-gate icon.
- **Node drawer**: repo ref, entrypoint, last logs, guardrail check results, `Run this step`, `Edit in MaC repo` (deep link to file/PR).
- **Top bar**: `Build` · `Deploy` · `Rollback` · agent activity feed (what the agents are doing, live).
- **Approvals panel**: each approval with Jira status + agent-written justification.

---

## 11. Demo script (~5 min)

1. **Problem (30s):** Medicare's $28.8B in improper payments runs on code nobody fully understands; every migration drowns in approvals and tribal knowledge.
2. **Ingest (45s):** point MaC at the Confluence space → graph builds live in Neo4j; show `ClaimsAdjudicationService → CLAIMS_DB (PHI) → Eligibility Service`.
3. **Plan (60s):** "Migrate ClaimsAdjudicationService to AWS." Planner traverses graph; Compliance agent identifies 3 required approvals, writes justifications, **Jira tickets appear**. PR opens in `mac-migrations` with `migration.yaml`. Reviewer agent comments.
4. **Approve (30s):** a judge/teammate approves the Tech Risk ticket on their phone → DAG node unblocks live.
5. **Build (30s):** guardrail checks pass (CI green, protected branch, CODEOWNERS); `terraform plan` diff shown.
6. **Deploy (60s):** network + IAM provision in real AWS; pause at DB manual gate → click Run; **smoke test fails (planted)** → automatic rollback in reverse order; AWS console shows clean state.
7. **Self-heal (45s):** Diagnostician opens a fix PR with root cause; merge; re-Deploy succeeds. Service live in AWS.
8. **Close (20s):** "Migration as Code — the migration itself is now a versioned, reviewable, re-runnable artifact. Nemotron turned your Confluence into an executable plan."

---

## 12. Build order (end-to-end first, then polish)

**Phase 0 — Accounts & scaffolding (2h)**
- Atlassian free site (Confluence + Jira project `MAC`), API token.
- AWS sandbox account, IAM user/role for runner, S3 bucket + DynamoDB table for TF state.
- NVIDIA build.nvidia.com API key; smoke-test Nemotron call.
- Neo4j Aura free (or Docker).
- Create 5 repos; CI + branch protection + CODEOWNERS on the 3 "prod" repos.

**Phase 1 — Walking skeleton (6h)** *(the MVP must work end-to-end before anything else)*
- Hand-write `migration.yaml` for the claims service.
- Runner: parse → Build (guardrail checks via GitHub API, Jira status) → Deploy (execute steps, Terraform apply of one tiny resource, rollback on failure).
- Minimal UI or CLI showing step states.
- ✅ Checkpoint: hand-written spec deploys to AWS and rolls back.

**Phase 2 — Agents (8h)**
- Draft the 10 Confluence pages; load into site.
- Ingestion agent → Neo4j.
- Planner agent → generates `migration.yaml` matching the hand-written one.
- Compliance agent → raises Jira tickets, wires approvals.
- Open PR to `mac-migrations`.
- ✅ Checkpoint: typed service name → PR + Jira tickets with no human input.

**Phase 3 — Review, diagnose, polish (6h)**
- Reviewer agent PR comments.
- Diagnostician on planted smoke-test failure → fix PR.
- React DAG UI with live agent feed.
- Jira webhook → live unblock.
- Rehearse demo twice; record a backup video.

**Stretch:** parallel step execution, pipeline templates, cost estimate per plan (Infracost), Slack notifications.

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Confluence→KG extraction is noisy | Small, well-structured corpus; structured-output schemas; provenance links so humans can verify |
| Real AWS hiccups during demo | Tiny resources (VPC, SG, IAM role, one small RDS or just ECS task); pre-warmed account; backup video |
| Planner hallucinates a repo/service | Reviewer lints against KG; only KG-known repos allowed; commits must resolve on GitHub |
| Jira approval latency in demo | Pre-create tickets in Build; approve live from a phone |
| Scope creep | Phase 1 checkpoint is non-negotiable; nothing from Phase 3 starts until Phase 2 checkpoint passes |

---

## 14. Decisions log

- 2026-11-07 — Pivot from "Data Migration SaaS" to **Migration as Code**: agent-generated, Git-reviewed migration pipelines composed from existing prod repos.
- 2026-11-07 — Knowledge graph is **built from Confluence** by an ingestion agent (not assumed to exist).
- 2026-11-07 — Approvals are real **Jira tickets** raised by the Compliance agent with agent-written justification.
- 2026-11-07 — Steps reference **pinned Git commits** of existing repos; runner **inherits those repos' guardrails** (CI, protected branch, CODEOWNERS) rather than re-approving.
- 2026-11-07 — Deploy targets a **real AWS** sandbox account.
- 2026-11-07 — LLMs plan/review/diagnose; the **runner is deterministic**.
- Defaults assumed (change if wrong): Nemotron via hosted NIM on build.nvidia.com; Python + FastAPI + LangGraph; React UI; Neo4j for the graph.
