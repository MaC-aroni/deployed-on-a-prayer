// Mock run data for the first demo. Frozen at the brief's snapshot:
// smoke test failed → rollback ran → Diagnostician mid-fix.
// Times are seconds since the run started. Replace with /api/... later.

export const NANO = "nemotron-nano-9b-v2";
export const SUPER = "nemotron-super-49b";

export const STAGES = [
  { id: "knowledge", name: "Knowledge" },
  { id: "plan", name: "Plan" },
  { id: "approvals", name: "Approvals" },
  { id: "build", name: "Build" },
  { id: "deploy", name: "Deploy" },
  { id: "recover", name: "Recover" },
];

export { STATUS, RUN_STATUS } from "../status.js";

export const RUN = {
  id: 142,
  title: "Migrate claims-adjudication-service to AWS",
  service: "claims-adjudication-service",
  branch: "mac/claims-adjudication",
  pr: 12,
  jira: "MAC-14",
  startedAt: "19:08",
  generatedBy: "nemotron-planner",
  target: "aws · 418240011 · us-east-1",
};

export const NOW = 1530;

function s(id, name, stage, type, extra = {}) {
  return { id, name, stage, type, needs: [], start: null, end: null, result: "succeeded", ...extra };
}

// One story, one step after another. `ai` marks where an agent did more than run a script:
// it read, decided or wrote something a person then reviews. `aiWhy` is the tooltip.
export const STEPS = [
  s("learn_kb", "Learn knowledge base", "knowledge", "agent", { model: NANO, start: 0, end: 40, sub: "15 Confluence pages → graph", ai: true, aiWhy: "read every page and built the knowledge graph, each fact cited" }),

  s("plan", "Plan migration.yaml", "plan", "agent", { model: SUPER, needs: ["learn_kb"], start: 40, end: 120, sub: "ReAct · 3 attempts vs validator", ai: true, aiWhy: "wrote the pipeline from the graph; the validator sent two drafts back" }),
  s("approvals_plan", "Raise approvals in Jira", "plan", "agent", { model: SUPER, needs: ["plan"], start: 120, end: 150, sub: "3 policies → 3 tickets", ai: true, aiWhy: "matched the policies and wrote each ticket's justification" }),
  s("open_pr", "Open PR #12", "plan", "git", { needs: ["approvals_plan"], start: 150, end: 156, sub: "mac-migrations · CI: mac validate" }),
  s("merge", "Review & merge", "plan", "human", { needs: ["open_pr"], start: 156, end: 600, sub: "CODEOWNER review" }),

  s("appr_tr", "APPR-TR-001", "approvals", "approval", { jira: "MAC-14", needs: ["approvals_plan"], start: 150, end: 900, sub: "Tech Risk · cloud migration" }),
  s("appr_sec", "APPR-SEC-001", "approvals", "approval", { jira: "MAC-16", needs: ["approvals_plan"], start: 150, end: 700, sub: "Security · IAM role review" }),
  s("appr_dba", "APPR-DBA-001", "approvals", "approval", { jira: "MAC-15", needs: ["approvals_plan"], start: 150, end: 1000, sub: "DBA · CLAIMS_DB (PHI)" }),

  s("build", "Build", "build", "check", { needs: ["merge"], start: 600, end: 680, sub: "4 repos pinned · guardrails · terraform plan +14" }),

  s("provision_network", "Provision network", "deploy", "iac", { needs: ["build", "appr_tr"], start: 1000, end: 1180, rollbackAt: 1500, sub: "terraform-aws-vpc@v4.2" }),
  s("provision_iam", "Provision IAM roles", "deploy", "iac", { needs: ["provision_network", "appr_sec"], start: 1180, end: 1230, rollbackAt: 1485, sub: "terraform-aws-iam-role@v2.0" }),
  s("db_migrate", "Migrate CLAIMS_DB", "deploy", "db_migration", { needs: ["provision_network", "appr_dba"], start: 1180, gateUntil: 1260, end: 1380, rollbackAt: 1470, gate: "manual", sub: "PHI · breakpoint" }),
  s("deploy_service", "Deploy claims-adjudication", "deploy", "script", { needs: ["provision_iam", "db_migrate"], start: 1380, end: 1420, rollbackAt: 1455, sub: "deploy.py @ 4a1f9c2" }),
  s("smoke_test", "Smoke test", "deploy", "check", { needs: ["deploy_service"], start: 1420, end: 1440, result: "failed", sub: "checks/smoke.py" }),

  s("rollback", "Undo, newest first", "recover", "runner", { needs: ["smoke_test"], start: 1440, end: 1500, sub: "4 steps undone · state clean" }),
  s("diagnose", "Diagnose root cause", "recover", "agent", { model: SUPER, needs: ["rollback"], start: 1500, end: null, sub: "/think · reading 1,412 log lines", ai: true, aiWhy: "read the logs and the code at the failing commit; proposes the fix a person approves" }),
  s("fix_pr", "Open fix PR", "recover", "git", { needs: ["diagnose"], sub: "a person approves it", ai: true, aiWhy: "the fix is written by the Diagnostician; merging stays with a person" }),
];

export const STEP_BY_ID = Object.fromEntries(STEPS.map((st) => [st.id, st]));

export function statusAt(step, t = NOW) {
  if (step.start == null || t < step.start) return "pending";
  if (step.rollbackAt != null && t >= step.rollbackAt) return "rolled_back";
  if (step.end == null || t < step.end) {
    if (step.type === "approval") return "blocked";
    if (step.gate === "manual" && step.gateUntil != null && t < step.gateUntil) return "manual";
    return "running";
  }
  if (step.type === "approval") return "approved";
  return step.result;
}

export function durationAt(step, t = NOW) {
  if (step.start == null || t < step.start) return null;
  const end = step.end == null ? t : Math.min(step.end, t);
  return end - step.start;
}

const PRIORITY = ["failed", "running", "manual", "blocked", "rolled_back", "pending", "succeeded", "approved"];

export function stageStatusAt(stageId, t = NOW) {
  const statuses = STEPS.filter((st) => st.stage === stageId).map((st) => statusAt(st, t));
  if (statuses.every((x) => x === "pending")) return "pending";
  if (statuses.every((x) => x === "succeeded" || x === "approved")) return "succeeded";
  for (const p of PRIORITY) if (statuses.includes(p)) return p;
  return "pending";
}

export function runStatusAt(t = NOW) {
  const statuses = STEPS.map((st) => statusAt(st, t));
  const recovering = STEPS.some((st) => st.stage === "recover" && ["running", "pending"].includes(statusAt(st, t)));
  if (statuses.includes("failed")) return recovering ? "recovering" : "failed";
  if (statuses.includes("running") || statuses.includes("manual")) return "running";
  if (statuses.includes("blocked")) return "blocked";
  if (statuses.every((x) => x === "succeeded" || x === "approved")) return "passed";
  return "pending";
}

// ---- Agent traces: observation → reasoning → action → outcome -------------

export const TRACES = {
  learn_kb: [
    { k: "observation", text: "15 pages in the CLAIMS space: service, runbook, data dictionary, landing-zone and approval standards." },
    { k: "reasoning", text: "One Reader per page keeps every fact cited to its section; the Compiler merges them and drops anything uncited." },
    { k: "action", text: "extract(pages) → 41 nodes, 67 edges; 3 facts dropped for missing citations" },
    { k: "outcome", text: "graph.json saved. ClaimsAdjudicationService → CLAIMS_DB (PHI), Claims MCP tool, 4 repositories, 3 approver roles." },
  ],
  plan: [
    { k: "observation", text: "Request: migrate claims-adjudication-service to AWS. Service node found in KG with two dependencies: CLAIMS_DB (Oracle 12c, pii=true) and eligibility-service." },
    { k: "reasoning", text: "CLAIMS_DB is tagged PII. The Tech Risk PHI/PII Standard puts a manual gate and a DBA sign-off on any step that moves it. The landing zone needs network and IAM before the database, so the order is network → iam → db → service → smoke." },
    { k: "action", text: 'kg.neighbors("svc:claims-adjudication", depth=2)' },
    { k: "outcome", text: "7 nodes, 9 edges. Approved target modules: terraform-aws-vpc@v4.2, terraform-aws-iam-role@v2.0." },
    { k: "action", text: "mac validate migration.yaml   (draft v1)" },
    { k: "outcome", text: "2 errors: deploy_service has no rollback; repo ref claims-service-iac@main is not pinned." },
    { k: "reasoning", text: "Add undeploy.py as the compensating action. Resolve main to a SHA through github.get_ref so the runner can verify guardrails on a fixed commit." },
    { k: "action", text: "mac validate migration.yaml   (draft v2)" },
    { k: "outcome", text: "1 error: smoke_test must declare on_failure." },
    { k: "action", text: "mac validate migration.yaml   (draft v3)" },
    { k: "outcome", text: "Valid. 6 steps, 3 approvals required, DAG acyclic." },
  ],
  approvals_plan: [
    { k: "observation", text: "Draft DAG v3 has one iac network step, one iac IAM step, one PHI database step and one deploy step." },
    { k: "action", text: 'kg.policies_for(["provision_network", "provision_iam", "db_migrate", "deploy_service"])' },
    { k: "outcome", text: "3 policies triggered: Cloud Migration Approval (Tech Risk), DBA Migration Sign-off, IAM Role Review (Security)." },
    { k: "reasoning", text: "Each ticket needs a justification an approver can act on without reading the YAML: what changes, why, the risk, the mitigation and the rollback. Attach the generated design doc so Tech Risk has one artifact to review." },
    { k: "action", text: "jira.create_issue(project=MAC, type=Approval) × 3" },
    { k: "outcome", text: "MAC-14, MAC-15, MAC-16 created. requires_approval wired into 4 steps." },
  ],
  diagnose: [
    { k: "observation", text: "smoke_test failed at 19:41:19. Last error: connect ECONNREFUSED eligibility-service.internal:8443, retried 3 times. All four deploy steps were rolled back; terraform state is clean." },
    { k: "reasoning", text: "The adjudication path calls eligibility-service, which has not been migrated and still runs on-prem behind the legacy VPN. The new VPC has no route back to the 10.40.0.0/16 range, so the call cannot leave the subnet. Two options: add a Transit Gateway attachment to the on-prem CIDR, or stub eligibility in the smoke test. Stubbing hides the problem, so the route is the fix. Checking the landing-zone standard for the approved TGW module before I touch the YAML…", live: true },
    { k: "action", text: 'kg.search("on-prem connectivity transit gateway approved module")' },
  ],
};

export const LOGS = {
  smoke_test: [
    "19:40:51  checks/smoke.py @ 9b8e21f (claims-smoke-tests)",
    "19:40:52  GET https://claims.internal/health → 200 (112 ms)",
    "19:40:53  POST /claims/adjudicate sample=CLM-000017",
    "19:40:58  upstream eligibility-service.internal:8443 → connect ECONNREFUSED",
    "19:41:08  retry 2/3 … ECONNREFUSED",
    "19:41:19  retry 3/3 … ECONNREFUSED",
    "19:41:19  smoke_test FAILED  (on_failure: rollback_all)",
  ],
  rollback: [
    "19:41:19  saga: 4 completed steps to compensate, reverse order",
    "19:41:20  deploy_service   → undeploy.py @ 4a1f9c2 … ok (11s)",
    "19:41:31  db_migrate       → rollback.py @ c71d0e4 … ok, row count verified (18s)",
    "19:41:49  provision_iam    → terraform destroy … 3 destroyed (15s)",
    "19:42:04  provision_network → terraform destroy … 11 destroyed (15s)",
    "19:42:19  state clean. handing logs to diagnostician.",
  ],
  provision_network: [
    "19:33:02  clone claims-service-iac @ 4a1f9c2 → /work/9f3a",
    "19:33:04  assume-role mac-runner-deploy (900s)",
    "19:33:05  terraform init  (s3 backend, dynamodb lock)",
    "19:33:21  terraform apply -auto-approve plan.out",
    "19:36:08  Apply complete! Resources: 11 added, 0 changed, 0 destroyed.",
  ],
  db_migrate: [
    "19:36:08  waiting on manual gate (PHI). Operator: Elathius",
    "19:37:20  gate released",
    "19:37:21  migrate.py @ c71d0e4 … 1,204,118 rows",
    "19:39:30  verify.py … checksum match, row count match",
    "19:39:30  db_migrate SUCCEEDED",
  ],
};

export const SPECS = {
  provision_network: `- id: provision_network
  type: iac
  needs: [build]
  requires_approval: [APPR-TR-001]
  run:
    repo: MaC-aroni/claims-service-iac@4a1f9c2
    path: network
    action: apply
  rollback:
    action: destroy`,
  db_migrate: `- id: db_migrate
  type: db_migration
  needs: [provision_network]
  requires_approval: [APPR-DBA-001]
  gate: manual
  run:    { repo: MaC-aroni/claims-db-migrate@c71d0e4, entrypoint: migrate.py }
  verify: { entrypoint: verify.py }
  rollback: { entrypoint: rollback.py }`,
  smoke_test: `- id: smoke_test
  type: check
  needs: [deploy_service]
  run:
    repo: MaC-aroni/claims-smoke-tests@9b8e21f
    entrypoint: checks/smoke.py
  on_failure: rollback_all`,
};

export const APPROVALS = [
  {
    id: "APPR-TR-001",
    stepId: "appr_tr",
    jira: "MAC-14",
    type: "Tech Risk · cloud migration",
    team: "Tech Risk",
    approver: "R. Okafor",
    blocks: ["provision_network", "deploy_service"],
    justification:
      "Moves claims-adjudication-service from on-prem Java 8 / Oracle 12c to EKS in the approved us-east-1 landing zone. Risk: cutover window during claims intake. Mitigation: blue/green with smoke test on the new path before traffic shifts. Rollback: terraform destroy of all new resources, no change to the legacy stack.",
  },
  {
    id: "APPR-DBA-001",
    stepId: "appr_dba",
    jira: "MAC-15",
    type: "DBA · database migration",
    team: "DBA",
    approver: "M. Chen",
    blocks: ["db_migrate"],
    justification:
      "Copies CLAIMS_DB (1.2M rows, PHI) to Aurora PostgreSQL via migrate.py with checksum verification. Source stays read-write until cutover. Rollback: drop target schema; source untouched. Manual gate before the copy starts.",
  },
  {
    id: "APPR-SEC-001",
    stepId: "appr_sec",
    jira: "MAC-16",
    type: "Security · IAM role review",
    team: "Security",
    approver: "A. Patel",
    blocks: ["provision_iam"],
    justification:
      "Creates lz-claims-adjudication-task role from terraform-aws-iam-role@v2.0 with least-privilege access to the Aurora cluster and one S3 bucket. No wildcard actions. Rollback: terraform destroy.",
  },
];

// ---- Migrations list ---------------------------------------------------------

export const MIGRATIONS = [
  {
    id: 142,
    title: RUN.title,
    service: RUN.service,
    branch: RUN.branch,
    pr: 12,
    generatedBy: "nemotron-planner",
    when: "34 minutes ago",
    duration: NOW,
    live: true,
    tags: ["latest"],
  },
  {
    id: 141,
    title: "Migrate eligibility-service to AWS",
    service: "eligibility-service",
    branch: "mac/eligibility",
    pr: 11,
    generatedBy: "nemotron-planner",
    when: "2 days ago",
    duration: 4310,
    status: "passed",
    stages: ["succeeded", "succeeded", "succeeded", "approved", "succeeded", "succeeded", "skipped"],
  },
  {
    id: 140,
    title: "Migrate member-portal to AWS",
    service: "member-portal",
    branch: "mac/member-portal",
    pr: 10,
    generatedBy: "nemotron-planner",
    when: "3 days ago",
    duration: 1180,
    status: "blocked",
    stages: ["succeeded", "succeeded", "succeeded", "blocked", "pending", "pending", "pending"],
  },
  {
    id: 139,
    title: "Migrate claims-adjudication-service to AWS",
    service: "claims-adjudication-service",
    branch: "mac/claims-adjudication",
    pr: 9,
    generatedBy: "nemotron-planner",
    when: "4 days ago",
    duration: 2890,
    status: "rolled_back",
    stages: ["succeeded", "succeeded", "succeeded", "approved", "succeeded", "rolled_back", "succeeded"],
  },
];

// ---- Agent hierarchies for the pitch (/agents/demo?for=<step>) ---------------------------------
// Each is a list of API-shaped `agent` events; the Agents page replays them one by one.

function hierarchy(director, workers, compiler, opts = {}) {
  const t0 = Math.floor(Date.now() / 1000) - 120;
  let seq = 0;
  const ev = (step, data) => ({ run_id: "demo", seq: ++seq, ts: t0 + seq * 3, step, kind: "agent", message: JSON.stringify(data) });
  const out = [
    ev(opts.step ?? "agent", { agent: "director", role: "Director", model: SUPER, phase: "observation", status: "running", text: director.observation }),
    ev(opts.step ?? "agent", { agent: "director", phase: "reasoning", text: director.reasoning }),
    ev(opts.step ?? "agent", { agent: "director", phase: "action", text: `dispatching ${workers.map((w) => w.role).join(", ")}` }),
  ];
  for (const w of workers) out.push(ev(opts.step ?? "agent", { agent: w.id, role: w.role, parent: "director", model: w.model ?? NANO, phase: "action", status: "running", text: w.action }));
  for (const w of workers) {
    if (w.observation) out.push(ev(opts.step ?? "agent", { agent: w.id, parent: "director", phase: "observation", text: w.observation }));
    out.push(ev(opts.step ?? "agent", { agent: w.id, parent: "director", phase: "outcome", status: w.failed ? "failed" : "succeeded", text: w.outcome }));
  }
  out.push(ev(opts.step ?? "agent", { agent: "compiler", role: "Compiler", parent: "director", model: SUPER, phase: "action", status: "running", text: compiler.action }));
  if (compiler.reasoning) out.push(ev(opts.step ?? "agent", { agent: "compiler", parent: "director", phase: "reasoning", text: compiler.reasoning }));
  out.push(ev(opts.step ?? "agent", { agent: "compiler", parent: "director", phase: "outcome", status: "succeeded", text: compiler.outcome }));
  out.push(ev(opts.step ?? "agent", { agent: "director", phase: "outcome", status: "succeeded", text: director.outcome }));
  return out;
}

const PAGES = ["00-handbook", "10-landing-zone", "11-terraform", "12-naming", "13-lambda", "20-mcp-access", "30-data-migration", "50-claims-service"];

export const DEMO_AGENT_SETS = {
  learn_kb: {
    run: { id: "demo", mode: "ingest", migration: "knowledge", report: {} },
    events: hierarchy(
      { observation: "15 pages in the CLAIMS space; no graph yet", reasoning: "one Reader per page keeps every fact cited to its section; References checks names across pages; the Compiler merges and drops anything uncited", outcome: "41 facts, 67 relations; the Planner can start" },
      [
        ...PAGES.map((p) => ({ id: `reader:${p}`, role: "Reader", action: `compressing ${p} into cited facts`, outcome: "facts extracted, every one cited" })),
        { id: "references", role: "References", action: "checking repositories and services named across pages", observation: "4 repositories named; all have nodes", outcome: "no gaps" },
      ],
      { action: "merging 41 facts into graph.json", outcome: "graph saved" },
      { step: "knowledge" },
    ),
  },
  plan: {
    run: { id: "demo", mode: "plan", migration: "plan/migrate-claimsadjudicationservice-to-aws", report: {} },
    events: hierarchy(
      { observation: "Migrate ClaimsAdjudicationService to AWS; no migration.yaml exists yet", reasoning: "the Planner drafts from the graph's 2-hop neighbourhood and the cited sections; the validator is its tool, so every draft is checked before anyone sees it", outcome: "valid plan in 3 attempts: 8 steps, 3 approvals, 1 breakpoint" },
      [
        { id: "knowledge", role: "Knowledge", action: "loading the graph neighbourhood of ClaimsAdjudicationService", observation: "7 nodes, 9 edges; CLAIMS_DB is PHI", outcome: "14 relevant sections picked, all cited" },
        { id: "planner", role: "Planner", model: SUPER, action: "attempt 1: writing migration.yaml", observation: "validator: deploy_service has no rollback; claims-service-iac@main isn't pinned", outcome: "attempt 3 valid after two rounds of validator feedback" },
        { id: "validator", role: "Validator", action: "mac validate on each draft: schema, acyclic, rollbacks, citations, documented repos", outcome: "draft 3 passes" },
      ],
      { action: "writing migration.yaml and opening PR #12 into mac-migrations", reasoning: "a person merges; the runner only ever runs what was reviewed", outcome: "PR #12 open · CI mac validate green" },
      { step: "plan" },
    ),
  },
  approvals_plan: {
    run: { id: "demo", mode: "plan", migration: "plan/approvals", report: {} },
    events: hierarchy(
      { observation: "the plan has an IaC network step, an IAM step, a PHI database step and a deploy step", reasoning: "each policy in the knowledge base names a trigger and an approver; the Compliance agent matches them and writes a justification an approver can act on without reading YAML", outcome: "3 tickets raised; the pipeline waits on them at Deploy" },
      [
        { id: "policies", role: "Policy matcher", action: "kg.policies_for(provision_network, provision_iam, db_migrate, deploy_service)", outcome: "Cloud Migration Approval (Tech Risk), DBA Sign-off, IAM Role Review (Security)" },
        { id: "writer:tr", role: "Justification writer", model: SUPER, action: "APPR-TR-001: what changes, why, risk, mitigation, rollback", outcome: "draft ready, design page linked" },
        { id: "writer:dba", role: "Justification writer", model: SUPER, action: "APPR-DBA-001: 1.2M rows of PHI, checksum verify, breakpoint before copy", outcome: "draft ready" },
        { id: "writer:sec", role: "Justification writer", model: SUPER, action: "APPR-SEC-001: least-privilege task role, no wildcards", outcome: "draft ready" },
      ],
      { action: "raising MAC-14, MAC-15, MAC-16 in Jira and wiring requires_approval into 4 steps", outcome: "3 tickets raised · MAC-15 chained after MAC-14" },
      { step: "approvals" },
    ),
  },
  diagnose: {
    run: { id: "demo", mode: "diagnose", migration: "claims-adjudication-onprem-to-aws", failed_step: "smoke_test", report: {} },
    events: hierarchy(
      { observation: "Deploy 142 failed at smoke_test: connect ECONNREFUSED eligibility-service.internal:8443; everything was undone", reasoning: "Logs reads the trace; Code reads the repository at the commit that ran; the Fixer proposes the smallest change; a person approves before it becomes a pull request", outcome: "root cause: the new VPC has no route to the on-prem eligibility service" },
      [
        { id: "logs", role: "Logs", action: "reading smoke_test's 1,412 log lines", observation: "3 retries to eligibility-service.internal:8443, all refused", outcome: "the failing call leaves the VPC and never arrives" },
        { id: "code", role: "Code", action: "reading claims-service-iac @ 4a1f9c2 · network/", observation: "no Transit Gateway attachment to 10.40.0.0/16", outcome: "route missing, not a code bug in the service" },
        { id: "fixer", role: "Fixer", model: SUPER, action: "proposing the smallest fix", observation: "the landing-zone standard approves terraform-aws-tgw@v1.3 for on-prem reach", outcome: "add a TGW attachment to the on-prem CIDR; stubbing the check would hide it" },
      ],
      { action: "recording the proposal and raising the approval ticket", reasoning: "a person approves; only then does the fix become a pull request", outcome: "MAC-17 raised · fix ready for approval" },
      { step: "diagnose" },
    ),
  },
};
DEMO_AGENT_SETS.fix_pr = DEMO_AGENT_SETS.diagnose;
export const DEMO_AGENT_RUN = DEMO_AGENT_SETS.learn_kb.run;
export const DEMO_AGENT_EVENTS = DEMO_AGENT_SETS.learn_kb.events;
