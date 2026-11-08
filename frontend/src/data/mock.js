// Mock run data for the first demo. Frozen at the brief's snapshot:
// smoke test failed → rollback ran → Diagnostician mid-fix.
// Times are seconds since the run started. Replace with /api/... later.

export const NANO = "nemotron-nano-9b-v2";
export const SUPER = "nemotron-super-49b";

export const STAGES = [
  { id: "knowledge", name: "Knowledge" },
  { id: "agents", name: "Nemotron agents" },
  { id: "repo", name: "MaC repo" },
  { id: "approvals", name: "Approvals" },
  { id: "build", name: "Build" },
  { id: "deploy", name: "Deploy" },
  { id: "recover", name: "Recover" },
];

export const STATUS = {
  succeeded: { label: "Succeeded", tone: "green" },
  approved: { label: "Approved", tone: "green" },
  failed: { label: "Failed", tone: "red" },
  running: { label: "Running", tone: "blue" },
  pending: { label: "Pending", tone: "grey" },
  blocked: { label: "Awaiting approval", tone: "amber" },
  manual: { label: "Manual gate", tone: "amber" },
  rolled_back: { label: "Rolled back", tone: "orange" },
  skipped: { label: "Skipped", tone: "grey" },
};

export const RUN = {
  id: 142,
  title: "Migrate claims-adjudication-service to AWS",
  service: "claims-adjudication-service",
  branch: "mac/claims-adjudication",
  pr: 12,
  startedAt: "19:08",
  generatedBy: "nemotron-planner",
  target: "aws · 418240011 · us-east-1",
};

export const NOW = 2041;

function s(id, name, stage, type, extra = {}) {
  return { id, name, stage, type, needs: [], start: null, end: null, result: "succeeded", ...extra };
}

export const STEPS = [
  s("ingest_confluence", "Ingest Confluence", "knowledge", "agent", { model: NANO, start: 0, end: 38, sub: "CLAIMS space · 10 pages" }),
  s("ingest_github", "Ingest GitHub repos", "knowledge", "agent", { model: NANO, start: 0, end: 29, sub: "3 repos · pinned SHAs" }),
  s("build_kg", "Build knowledge graph", "knowledge", "agent", { model: NANO, needs: ["ingest_confluence", "ingest_github"], start: 38, end: 51, sub: "41 nodes · 67 edges" }),

  s("plan_migration", "Plan migration DAG", "agents", "agent", { model: SUPER, needs: ["build_kg"], start: 51, end: 112, sub: "ReAct · 3 iterations" }),
  s("compliance", "Map required approvals", "agents", "agent", { model: SUPER, needs: ["plan_migration"], start: 112, end: 141, sub: "3 policies matched" }),
  s("review_dag", "Review DAG vs standards", "agents", "agent", { model: SUPER, needs: ["compliance"], start: 141, end: 163, sub: "2 comments · approved" }),

  s("open_pr", "Open PR #12", "repo", "git", { needs: ["review_dag"], start: 163, end: 166, sub: "mac-migrations" }),
  s("mac_validate", "CI · mac validate", "repo", "ci", { needs: ["open_pr"], start: 166, end: 190, sub: "schema · acyclic · rollbacks" }),
  s("merge", "Merge to main", "repo", "human", { needs: ["mac_validate"], start: 190, end: 1420, sub: "CODEOWNER review" }),

  s("appr_tr", "APPR-TR-001", "approvals", "approval", { jira: "MAC-14", needs: ["compliance"], start: 141, end: 1300, sub: "Tech Risk · cloud migration" }),
  s("appr_dba", "APPR-DBA-001", "approvals", "approval", { jira: "MAC-15", needs: ["compliance"], start: 141, end: 1380, sub: "DBA · CLAIMS_DB (PHI)" }),
  s("appr_sec", "APPR-SEC-001", "approvals", "approval", { jira: "MAC-16", needs: ["compliance"], start: 141, end: 980, sub: "Security · IAM role review" }),

  s("preflight", "Preflight checks", "build", "check", { needs: ["merge"], start: 1420, end: 1436, sub: "checks/preflight.py" }),
  s("guardrails", "Verify inherited guardrails", "build", "check", { needs: ["merge"], start: 1420, end: 1449, sub: "CI green · protected · CODEOWNERS" }),
  s("tf_plan", "terraform plan", "build", "iac", { needs: ["preflight", "guardrails"], start: 1449, end: 1502, sub: "+14 to add · 0 to change" }),

  s("provision_network", "Provision network", "deploy", "iac", { needs: ["tf_plan", "appr_tr"], start: 1502, end: 1688, rollbackAt: 2010, sub: "terraform-aws-vpc@v4.2" }),
  s("provision_iam", "Provision IAM roles", "deploy", "iac", { needs: ["provision_network", "appr_sec"], start: 1688, end: 1740, rollbackAt: 1995, sub: "terraform-aws-iam-role@v2.0" }),
  s("db_migrate", "Migrate CLAIMS_DB", "deploy", "db_migration", { needs: ["provision_network", "appr_dba"], start: 1688, gateUntil: 1760, end: 1890, rollbackAt: 1980, gate: "manual", sub: "PHI · manual gate" }),
  s("deploy_service", "Deploy claims-adjudication", "deploy", "script", { needs: ["provision_iam", "db_migrate"], start: 1890, end: 1932, rollbackAt: 1962, sub: "deploy.py @ 4a1f9c2" }),
  s("smoke_test", "Smoke test", "deploy", "check", { needs: ["deploy_service"], start: 1932, end: 1951, result: "failed", sub: "checks/smoke.py" }),

  s("rollback", "Rollback in reverse order", "recover", "runner", { needs: ["smoke_test"], start: 1951, end: 2010, sub: "4 compensating steps" }),
  s("diagnose", "Diagnose root cause", "recover", "agent", { model: SUPER, needs: ["rollback"], start: 2010, end: null, sub: "/think · reading 1,412 log lines" }),
  s("fix_pr", "Open fix PR", "recover", "git", { needs: ["diagnose"], sub: "mac-migrations" }),
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

export const RUN_STATUS = {
  passed: { label: "Passed", tone: "green" },
  running: { label: "Running", tone: "blue" },
  blocked: { label: "Blocked", tone: "amber" },
  failed: { label: "Failed", tone: "red" },
  recovering: { label: "Recovering", tone: "violet" },
  rolled_back: { label: "Rolled back", tone: "orange" },
  pending: { label: "Pending", tone: "grey" },
};

// ---- Agent traces: observation → reasoning → action → outcome -------------

export const TRACES = {
  plan_migration: [
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
  compliance: [
    { k: "observation", text: "Draft DAG v3 has one iac network step, one iac IAM step, one PHI database step and one deploy step." },
    { k: "action", text: 'kg.policies_for(["provision_network", "provision_iam", "db_migrate", "deploy_service"])' },
    { k: "outcome", text: "3 policies triggered: Cloud Migration Approval (Tech Risk), DBA Migration Sign-off, IAM Role Review (Security)." },
    { k: "reasoning", text: "Each ticket needs a justification an approver can act on without reading the YAML: what changes, why, the risk, the mitigation and the rollback. Attach the generated design doc so Tech Risk has one artifact to review." },
    { k: "action", text: "jira.create_issue(project=MAC, type=Approval) × 3" },
    { k: "outcome", text: "MAC-14, MAC-15, MAC-16 created. requires_approval wired into 4 steps." },
  ],
  review_dag: [
    { k: "observation", text: "Reviewing migration.yaml v3 against Platform AWS Landing Zone Standards and Approved Terraform Modules." },
    { k: "reasoning", text: "All modules are on the approved list. Every mutating step has a rollback. The PHI step is gated. Two things worth a comment: the smoke test should also check eligibility reachability, and the IAM role name should follow the lz- prefix convention." },
    { k: "action", text: "github.create_review(pr=12, event=APPROVE, comments=2)" },
    { k: "outcome", text: "Approved with 2 non-blocking comments. Waiting for a CODEOWNER to merge." },
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
  needs: [tf_plan]
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
