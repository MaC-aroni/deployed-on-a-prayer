# CLAUDE.md — MaC (Migration as Code)

Context file for Claude Code working on the MaC hackathon project. Everything below was decided or researched across several chats on 2026-11-07. Treat "DECIDED" items as settled unless the team says otherwise; "OPEN" items need a call before building.

---

## 0. TL;DR

**MaC = Migration as Code.** Nemotron agents read a company's existing knowledge (Confluence, Jira, GitHub), generate a complete migration pipeline as a reviewable `migration.yaml` DAG committed to a Git repo as a PR, draft and raise every required approval in Jira with business justification, and hand the merged spec to a **deterministic runner** that executes it with manual gates, approval gates, and saga rollback. When a step fails, a Diagnostician agent root-causes it and opens a fix PR.

**Design principle (say it in every pitch):** *LLMs plan, review and diagnose. A boring state machine executes. No model is in the execution path of Deploy.*

**Tracks:** NVIDIA Nemotron (primary target, must win) × 8090 Legacy Modernization. Tracks stack.

**Team:** 3 people. Hackathon: Hack UTD, ~30 hours remaining as of Sat evening 2026-11-07.

**Status:** Wayword (prior idea, real-time AI teleprompter) is **dropped**. MaC is the project.

---

## 1. Why MaC (and what we dropped)

- Wayword was a single-track project whose hard part (latency) is not what the Nemotron track scores. MaC is two tracks, Nemotron is load-bearing in every agent, and it matches the shape of the deck's past winners (DevOps tool-calling + automated bug fixer).
- The teammates' original verbal pitch ("LLMs build pipelines and raise requests") sounded generic. The written design is not: the wedge is **coordination** (approvals, gates, versioned artifact, deterministic runner), not code conversion.
- Competitive scan confirmed: code conversion / dependency graphs / KG are solved by hyperscalers (AWS Transform, Microsoft Legacy-Modernization-Agents w/ Neo4j, IBM). **Nobody** does approvals-as-part-of-the-artifact, migration-as-a-PR, deterministic saga runner with the LLM excluded, or inheriting source-repo guardrails. Build those; don't compete on the KG.

One-liner vs AWS Transform (memorize): *"Transform proposes a plan and stops. MaC raises the approvals, commits the pipeline, runs it with rollback, and fixes it when it breaks."*

---

## 2. Architecture

```
KNOWLEDGE SOURCES (read-only)
  Confluence: policies, landing-zone standards, service docs, data dictionaries
  GitHub: existing prod repos (IaC, DB migrations, smoke tests)
  Jira: approval history
        │ tools (MCP / REST)
NEMOTRON AGENT LAYER (LangGraph, Nemotron via NVIDIA NIM / build.nvidia.com)
  1. Ingestion agent   sources → knowledge graph
  2. Planner agent     KG → migration.yaml DAG   (ReAct loop against `mac validate`)
  3. Compliance agent  policies → required approvals → Jira tickets + justifications
  4. Reviewer agent    lints DAG vs standards, comments on PR   (may fold into CI — see cuts)
  5. Diagnostician     failed run → root cause → fix PR
        │ opens PR
MaC REPO (GitHub)  migrations/<service>/migration.yaml + approvals + runs/
  branch protection, CODEOWNERS, CI = `mac validate`
        │ merged spec
MaC RUNNER (deterministic state machine, Python)
  Build  → validate, guardrail verification, approval status, terraform plan, check steps
  Deploy → saga execution in topological order; manual gates; compensating rollback
  Run step / Rollback
        │
TARGET CLOUD (real AWS sandbox)  +  UI (DAG console; GitHub PR + Jira are also UI)
```

Two speeds: **agents are slow and smart** (seconds per call, reasoning on); **runner is fast and dumb**. The only bridge is: agents write the spec; runner reads the spec and reports state back.

### 2.1 Knowledge graph
- Built, not assumed. Ingestion extracts entities/relations with structured output and `doc_url` provenance.
- Two sub-graphs: **Legacy** (services, DBs, deps, data classification, owners, runbooks) and **Target** (approved cloud services, Terraform modules, landing-zone/network standards, who approves what).
- Schema (nodes): Service, Database{pii:bool}, Team{approver_role}, Policy{trigger_condition, approval_type, approver_team}, CloudService{approved, terraform_module}, Repo{url, entrypoint, protected_branch}.
- Edges: DEPENDS_ON, USES, OWNED_BY, HAS_REPO, MIGRATES_TO, REQUIRES_APPROVAL_FROM, TRIGGERED_BY.
- Agent tool contract (agents query, never get the whole graph): `kg.search(text)`, `kg.neighbors(id, depth)`, `kg.cypher(q)` read-only, `kg.policies_for(subgraph)`.
- **DECIDED (scope cut): storage = JSON graph in the repo, not Neo4j.** Same tool contract. Judges never see the DB; Microsoft already open-sourced the Neo4j version.

### 2.2 `migration.yaml` (schema v0.1) — key shape
```yaml
apiVersion: mac/v0.1
kind: Migration
metadata: {name, service, owner_team, generated_by: nemotron-planner@<run>, source_docs: [...]}
target: {provider: aws, account, region}
approvals:
  - {id: APPR-TR-001, type: tech_risk_cloud_migration, jira: MAC-14, justification: "...", blocks: [provision_network, deploy_service]}
  - {id: APPR-DBA-001, type: dba_db_migration, jira: MAC-15, blocks: [db_migrate]}
  - {id: APPR-SEC-001, type: iam_role_review, jira: MAC-16, blocks: [provision_iam]}
steps:
  - {id: preflight, type: check, run: {repo: ...@sha, entrypoint: checks/preflight.py}, rollback: none}
  - {id: provision_network, type: iac, needs: [preflight], requires_approval: [APPR-TR-001], run: {repo, path, action: apply}, rollback: {action: destroy}}
  - {id: provision_iam, type: iac, needs: [provision_network], requires_approval: [APPR-SEC-001], ...}
  - {id: db_migrate, type: db_migration, needs: [provision_network], requires_approval: [APPR-DBA-001], gate: manual, run: {entrypoint: migrate.py}, verify: {entrypoint: verify.py}, rollback: {entrypoint: rollback.py}}
  - {id: deploy_service, type: script, needs: [provision_iam, db_migrate], requires_approval: [APPR-TR-001], run: {entrypoint: deploy.py}, rollback: {entrypoint: undeploy.py}}
  - {id: smoke_test, type: check, needs: [deploy_service], run: {entrypoint: checks/smoke.py}, on_failure: rollback_all}
guardrails: {require_ci_green: true, require_protected_branch: true, require_codeowners_review: true, pin_commits: true}
```
Step types: `check` (read-only; fail → stop/rollback), `script` (run entrypoint / rollback entrypoint), `iac` (plan at Build, apply at Deploy, destroy on rollback), `db_migration` (migrate + verify / rollback script), `approval_gate` (blocks until Jira Approved), `manual` gate flag (pauses for human click).

### 2.3 Runner state machine
Per step: `pending → blocked(approval|manual) → ready → running → succeeded | failed → rolled_back`.
- **Build** (safe, repeatable): parse+validate (schema, acyclic) → guardrail verification per repo ref via GitHub API (CI green on pinned SHA, SHA reachable from protected branch, CODEOWNERS review present) → approval status via Jira → `terraform plan` for iac steps, run `check` steps → Build report.
- **Deploy** (saga): topological order, parallel where independent; pause at manual gates and unresolved approvals; on failure run compensating rollbacks in reverse order of completed steps, mark `rolled_back`, hand logs to Diagnostician.
- Execution sandbox: each repo ref cloned fresh at pinned SHA into isolated workdir; short-lived assumed-role AWS creds; Terraform state in S3 + DynamoDB lock.
- Guardrails are **inherited** from source repos, not re-approved. If a step points at an unreviewed commit, Build fails.

### 2.4 Agents (Nemotron via NIM, LangGraph)
Model routing (**decided, and it's a pitch point, not a cost hack**): **Nemotron Nano** for high-volume extraction (Ingestion); **Nemotron Super with reasoning (`/think`) on** for Planner, Compliance, Reviewer, Diagnostician. Never put Nano on the Planner (structured output reliability). Zero non-NVIDIA models anywhere, including fallbacks. Use NVIDIA embeddings + reranker (nv-embedqa / nv-rerankqa on build.nvidia.com) for `kg.search`.

| Agent | Input | Loop | Output |
|---|---|---|---|
| Ingestion | Confluence space keys | list → fetch → extract (structured) → upsert → dedupe → provenance | Legacy + Target graph |
| Planner | "Migrate `<service>` to AWS" | `kg.neighbors(svc,2)` → map legacy→target → order by dependency → emit yaml → **call `mac validate` as a tool → observe errors → fix → repeat** | draft DAG (ReAct, show iteration count) |
| Compliance | draft DAG + `kg.policies_for` | match policy triggers → write justification (what/why/risk/mitigation/rollback) → `jira.create_issue` → wire `requires_approval` | DAG with approvals; tickets raised |
| Reviewer | full DAG + standards | approved services only, approved modules, PHI steps gated, every mutating step has rollback, pinned commits, acyclic → PR comments | PR review (human merges) |
| Diagnostician | failed step logs + entrypoint source + yaml + KG | root cause → propose fix → open fix PR → optionally re-trigger Build | PR with explanation |

**Retrieval is a decision, not a step** (Agentic RAG card): Planner/Diagnostician start from request/logs and *decide* to call `kg.*` when they hit an unknown; the trace says why. Same code, different prompt + visible reasoning.

---

## 3. NVIDIA track — what wins (read from the 15-slide deck)

**Hard requirements:** uses Nemotron · beyond a chatbot · multi-step ("agents that plan **and execute**") · tool integration ("intelligently") · real-world applicability.
**"Nemotron is best for":** reasoning/multi-step · function calling · **autonomous decision-making within agent workflows** · RAG · multi-agent orchestration.
**Ideal project cards:** Multi-Agent · Agentic RAG (decides WHEN) · ReAct · Tool-Calling (finance/**DevOps**/content) · Multi-Modal (Nemotron + VLM) · Agent Simulation & Eval.
**Past winners:** Route Optimization Agent (multi-agent, specialized: constraint extraction + planning) · Automated Bug Fixer ("non-technical users describe bugs; agent **autonomously** diagnoses and fixes") · Multi-Agent Research System ("autonomous collaboration"). Common trait: one-sentence request → long **autonomous** chain → verifiable result.
**Soft signals:** deck's code sample uses `nvidia-nemotron-nano-9b-v2` with `/think` (reasoning toggle expected); "Nemotron is more than models — models, datasets, techniques, tooling" (ecosystem use counts); LangGraph Report Generator is the reference architecture; $60 Brev credits per team (use the GPU, mention it).
**Resources:** build.nvidia.com (API key via View Code), OpenRouter, HF open weights, brev.nvidia.com. Contact: Ethan Einhorn, eeinhorn@nvidia.com.

### 3.1 MaC scorecard & required fixes (ranked by points/hour)
| Fix | Hours | Why |
|---|---|---|
| 1. **Reframe autonomy**: "autonomous between gates." Sentence → KG → plan → validate → tickets → PR → review with zero human input; one click; deploy → fail → rollback → diagnose → fix PR with zero input. Say "twelve places a human *decides*, zero where a human *does*." Never say "human in the loop" to NVIDIA judge. | 0 | Winners' common trait is autonomy |
| 2. **Planner as ReAct loop** against `mac validate` | 2 | ReAct card; makes validate do double duty |
| 3. **Retrieval as decision** (prompt + trace) | 1 | Agentic RAG card: C → A |
| 4. **Stream `/think` reasoning into the activity feed** | 1 | Answers "what does Nemotron do" visually |
| 5. **Sim & Eval**: score Planner vs golden yaml across 5 scenarios (step match, gate match, validity); Diagnostician vs 3 planted failures (missing route, wrong SHA, failed verify). Report numbers. | 3 | Card nobody else will have |
| 6. **Multimodal (optional)**: Confluence architecture *diagram image* → Nemotron VL model → components/edges into KG | 2 | Real, not gimmick |
| 7. **Ecosystem**: NVIDIA embeddings/rerank; Nano+Super routing; Brev GPU for Nano open-weights ingestion | 1 | "More than models" slide |

### 3.2 How we lose anyway (avoid)
- Nano on structured generation → broken YAML. Super for anything structured.
- 5-minute demo with six live external systems. Judge gives ~3 min at a table.
- Reads as "Jira automation" → trace panel with reasoning is the antidote.
- Reads as AWS Transform → one-liner above.
- Over-engineering KG (Neo4j wins nothing).
- Synthetic Confluence corpus objection ("you wrote the pages") → say it first: "demo corpus; the schema and tool contract are the product." Mix in real docs if possible.

### 3.3 Nemotron differentiators to cite (from research)
Open weights (OpenMDW-1.1 / Nemotron Open Model License) → run inside customer VPC → **data sovereignty** (PHI never leaves account; NIM on EKS in the landing zone). Three sizes built for **routing** (NeMo Switchyard). Super: 1M-token context → Diagnostician reads everything in one pass. Efficient hybrid Mamba-Transformer MoE → cheap at volume for reading thousands of pages. Open data/recipes → **fine-tune on your own approved `migration.yaml` history** (roadmap slide). Sidecars: Nemotron Content Safety (did a justification leak PHI?), Nemotron RAG embed/rerank, Nemotron-Terminal (Diagnostician runs read-only `terraform show`/log greps). Honest: frontier closed models still lead hardest reasoning; Nemotron's claim is "most efficient open model at its size."

---

## 4. 8090 track fit
Brief: "Build agents and tools that accelerate legacy system modernization… make this software easier to understand, improve, or replace." Medicare: $28.8B improper payments through claims systems on decades-old code. Prize: DJI Mic Mini for all winners.
MaC fit: documentation becomes an executable plan (understand); runtime/DB upgraded (improve); off legacy infra (replace). **OPEN RISK:** if demo target is a modern GCP microservices app (Online Boutique), 8090 judges may read it as cloud-to-cloud migration, not *legacy* modernization. See §6.

---

## 5. Humans in the loop (where, who, why)
Rule: a human sits where a decision is **irreversible**, carries **accountability**, or is **ambiguous**. Everything else is friction to remove.

| # | Where | Who | Why not an agent |
|---|---|---|---|
| 1 | Scope the request (confirm blast radius) | Engineer | Business intent |
| 2 | Correct the KG via provenance | Engineer/owner | Wiki is wrong more than agent |
| 3 | Review/edit `migration.yaml` (checks, breakpoints) | Engineer | Plan is the contract |
| 4 | Answer approvers' questions (agent drafts, human sends) | Engineer ↔ approvers | Accountability |
| 5 | **Approve** in Jira | Tech Risk / DBA / Security | Compliance agent raises, never approves |
| 6 | Merge | CODEOWNER | Authority over prod |
| 7 | Manual gates (PHI/data steps, **cutover**) | Engineer | Irreversible |
| 8 | Hold vs rollback on failure | Engineer | Sometimes failure is the test |
| 9 | Review Diagnostician fix PR | Engineer | No unsupervised self-fix loop |
| 10 | Confirm a leak ("security bucket / leak check" idea: agent flags hard-coded cred/PHI; human confirms + rotates) | Security | Rotation irreversible |
| 11 | Sign off + decommission legacy | Service owner | Truly unrecoverable |
| 12 | Own the policies in Confluence | Tech Risk | Rules are human |

For the build, make **3, 5, 7, 9** real (in demo); rest is a slide. Teammate dump also had: "Design documents are generated and linked to the ticket to the tech risk team" → Compliance agent attaches a generated design doc to each Jira ticket.

---

## 6. Demo target — OPEN DECISION (two candidates)

### Option A — Online Boutique, GCP → AWS (most recent direction, from "GCP to AWS migration" chat)
`github.com/GoogleCloudPlatform/microservices-demo`. 11 polyglot gRPC microservices, monorepo (`src/<service>`), GKE-native, Terraform path, Locust load generator, Memorystore/Spanner variants, Workload Identity, Istio. Footer renders cluster/zone/pod from cloud metadata.
Mapping: GKE→EKS (replatform), Memorystore→ElastiCache, Spanner cart→DynamoDB/Aurora (refactor, **manual gate**), Workload Identity→IRSA, GKE Ingress→ALB, Cloud Ops→CloudWatch/OTel, GCP TF→AWS TF, GCR→ECR.
Knowledge sources become: k8s manifests, Kustomize variants, Terraform (plus Confluence policy pages). Planner steps: `provision_eks`, `migrate_cart_store` (manual gate), `swap_identity`, `deploy_services`, `smoke_test`; planted failure: frontend can't reach a service still on GKE → Diagnostician adds cross-cloud route.
**Signature demo ("heartbeat and the burn"):** Locust orders/sec + error rate chart flat green on top; infra map below lights up EKS boxes wave by wave, GKE greys out; traffic slider 0→100%; footer flips `us-central1-b` → `us-east-1`; order IDs never gap; then `gcloud container clusters delete` on camera, chart stays flat. Alternates: cart that crosses clouds; curl loop that never drops a 200. **"Migration preserves, modernization unlocks"**: one visible unlock = `recommendationservice` stub replatformed onto a Nemotron NIM so recommendations become relevant (a `migration.yaml` step with its own rollback).
Pros: public, reproducible, real managed-service deps, visceral continuity demo. Cons: needs both GCP and AWS accounts + two k8s clusters in 30h (high infra risk); weaker "legacy" story for 8090. Sibling with heavier DB story: Bank of Anthos (Postgres/Cloud SQL → DMS → RDS).

### Option B — Small real old app, on-prem (Docker Compose) → AWS (ECS + RDS)
- **Spring PetClinic, early-2013 commit** (Spring 3.x, JSP, Java 7, Tomcat WAR, MySQL). Small, real, dated, schema+seed SQL, known-good modern reference. Don't say its name on stage.
- **iBATIS JPetStore 5** (~2006, Struts 1, Ant, ships Oracle/MySQL/HSQL SQL) — more legacy smell, build-risk.
- **Old PHP5+MySQL hospital/clinic app from SourceForge** — healthcare resonance, hard-coded creds make the leak-check beat real; code quality risk.
Pros: one cloud, tiny infra, true "legacy" for 8090. Cons: less spectacular than the burn.
**Skip:** writing a fake "legacy claims system." Keep Medicare as *problem framing* only.

Recommendation on record: pick by Sat night based on infra appetite. If both GCP+AWS aren't provisioned and working by hour ~4, fall to Option B.

---

## 7. Integrations (tool contracts)
| System | Used by | Calls |
|---|---|---|
| Confluence Cloud (free site) | Ingestion | `GET /wiki/api/v2/spaces/{id}/pages`, `GET /pages/{id}?body-format=storage` |
| Jira Cloud (same site, project `MAC`) | Compliance, Runner | `POST /rest/api/3/issue`, `GET /issue/{key}`, webhook → runner on transition |
| GitHub | Planner, Runner, Reviewer, Diagnostician | contents, `/commits/{sha}/check-runs`, branch protection, PR create/review |
| AWS sandbox | Runner | Terraform AWS provider, boto3 verification |
| KG store | Ingestion, Planner, Compliance | JSON graph (decided) |
| NVIDIA NIM (build.nvidia.com) | all agents | OpenAI-compatible chat completions, `/think`, function calling; embeddings + rerank |

Demo corpus (~10 Confluence pages, Medicare-claims flavored, to be drafted): ClaimsAdjudicationService Architecture (on-prem, Java 8, Oracle 12c), Runbook, CLAIMS_DB Data Dictionary (PHI), Eligibility Service Interface Contract, Tech Risk Cloud Migration Approval Policy, Tech Risk PHI/PII Standard, Platform AWS Landing Zone Standards, Approved Terraform Modules, DBA Migration Sign-off Procedure, Security IAM Role Review Process. (Adapt names if Option A chosen.)

## 8. Repos
| Repo | Role |
|---|---|
| `mac-platform` | agents (LangGraph), runner, API, console |
| `mac-migrations` | **the MaC repo**: `migrations/<service>/migration.yaml`; CI `mac validate`; branch protection + CODEOWNERS |
| `claims-service-iac` (or boutique equivalent) | "existing prod" Terraform + deploy.py/undeploy.py |
| `claims-db-migrate` | migrate.py / verify.py / rollback.py |
| `claims-smoke-tests` | checks/preflight.py, checks/smoke.py |
Each "prod" repo gets Actions CI, protected `main`, CODEOWNERS so guardrail verification has real signals.

## 9. UI
GitLab-pipeline-inspired DAG console (teammate decision). Published mockup exists: stage columns (Knowledge · Nemotron agents · MaC repo · Approvals · Build · Deploy · Recover), bezier deps, status icons, violet = Nemotron, lock = Jira gate, hover traces lineage, click opens node drawer with agent reasoning + logs. Snapshot frozen at: smoke test failed → rollback ran → Diagnostician mid-fix.
**Scope cut:** GitHub PR + Jira board *are* UI; agent activity feed = PR description/comments + streamed `/think`. Build the React/HTML console only if Phase 2 checkpoint passes.

## 10. Scope (30h) — must / should / cut
**Must:** Nemotron function calling working on build.nvidia.com (hour 1) · JSON KG + tool contract · Planner w/ validate loop · Compliance → Jira tickets · PR to mac-migrations · runner Build+Deploy+rollback on one tiny AWS resource · Diagnostician on planted failure · trace with reasoning.
**Should:** Reviewer agent (else fold into `mac validate` CI) · Sim & Eval numbers · Jira webhook live unblock · console UI.
**Cut:** Neo4j · full React console before checkpoint · real large AWS resources · Infracost/Slack/templates (stretch).
**Gates:** Phase 1 checkpoint (hand-written yaml deploys + rolls back) by Sat night, or drop Diagnostician + live approval. Phase 2 checkpoint: typed service name → PR + Jira tickets with no human input.

Build order: Phase 0 accounts/scaffolding (2h, budget 5) → Phase 1 walking skeleton (6h) → Phase 2 agents (8h) → Phase 3 review/diagnose/polish (6h). Rehearse twice; record backup video tonight regardless.

## 11. Demo script (≤3 min at a table)
1. Problem (20s): Medicare $28.8B / approvals drown migrations.
2. Type `migrate <service> to AWS` → KG query trace → plan v1→v3 (validate loop) → **3 Jira tickets appear** → PR opens with Reviewer comments. Zero clicks. (90s)
3. Approve one ticket on a phone → DAG node unblocks live. (15s)
4. Build report → Deploy → planted smoke failure → **rollback in reverse** → Diagnostician `/think` trace → fix PR #13 opens. Zero clicks. (60s)
5. Close: "Transform proposes and stops. MaC raises, commits, runs, fixes. The LLM never touches Deploy." (10s)
If Option A: the heartbeat chart runs across steps 2–4.
Fallbacks: pre-created tickets; recorded run with cached trace; 60s video.

## 12. Competitive landscape (for Q&A)
- **AWS Transform**: wave plans, human sign-off on plan, admits agents non-deterministic (playbooks +15.79% consistency). No ticket generation, no rollback guarantee.
- **Azure-Samples/Legacy-Modernization-Agents**: analyzer/business-logic/dependency-mapper/converter agents, Neo4j graph, deterministic parsing. No approvals, no Jira, no execution.
- **IBM, Deloitte, Hypercubic**: consulting/mainframe conversion.
- **ServiceNow Now Assist Change, Lightrun Change Risk Analyzer**: prepare CAB risk briefings; "agents prepare evidence, board decides." Don't raise gated tickets from policy or wire them into a pipeline.
- Gaps MaC owns: Compliance agent; `migration.yaml` as PR; deterministic saga runner; inherited guardrails.

## 13. Decisions log
- 2026-11-07 Dropped Wayword; MaC is the project.
- 2026-11-07 Pivot from "Data Migration SaaS" → Migration as Code.
- 2026-11-07 KG built from Confluence by Ingestion agent; **storage = JSON graph** (Neo4j cut).
- 2026-11-07 Approvals = real Jira tickets with agent-written justification + attached design doc.
- 2026-11-07 Steps pin Git commits of existing repos; runner inherits their guardrails.
- 2026-11-07 Deploy targets real AWS sandbox (tiny resources).
- 2026-11-07 LLMs plan/review/diagnose; runner deterministic.
- 2026-11-07 Model routing: Nano (ingest) / Super + `/think` (planner, compliance, reviewer, diagnostician); NVIDIA embed/rerank; no non-NVIDIA models.
- 2026-11-07 UI inspired by GitLab pipeline DAG; Jira for tickets, Confluence for KB.
- OPEN: demo target (Online Boutique GCP→AWS vs old app on-prem→AWS) — see §6.
- OPEN: Reviewer as agent vs folded into CI.
- OPEN: ask NVIDIA rep — which Nemotron size they want to see; streaming + function calling via NIM limits; is hosted-only fine or does Brev GPU use matter; judging weights; live demo required?

## 14. Conventions for Claude Code in this repo
- Python 3.11+, FastAPI, LangGraph; Terraform for IaC; GitHub Actions CI.
- Every agent emits a trace line: `observation → reasoning → action → outcome`, with model name and reasoning content when available. Traces are the demo.
- Agents call tools; they never shell out to Terraform/AWS. Only the runner executes.
- Every mutating step in a generated yaml must have a rollback; `mac validate` enforces it.
- Pin every repo ref to a SHA. Never `@main`.
- Secrets via env; never commit API keys (Atlassian token, NVIDIA key, AWS creds).
- Keep demo corpus and golden `migration.yaml` under `fixtures/` so eval is reproducible.
- When unsure whether something is an agent decision or a pipeline step: make it a decision and log why.
