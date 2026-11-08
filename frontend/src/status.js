// Step states and run statuses, as the runner reports them (docs/api.md), plus the few
// extra ones the pitch demo page uses.

export const STATUS = {
  pending: { label: "Pending", tone: "grey" },
  blocked: { label: "Awaiting approval", tone: "amber" },
  waiting: { label: "Waiting for play", tone: "amber" },
  manual: { label: "Manual gate", tone: "amber" },
  running: { label: "Running", tone: "blue" },
  succeeded: { label: "Succeeded", tone: "green" },
  approved: { label: "Approved", tone: "green" },
  failed: { label: "Failed", tone: "red" },
  rejected: { label: "Rejected", tone: "red" },
  rolled_back: { label: "Rolled back", tone: "orange" },
  rollback_failed: { label: "Rollback failed", tone: "red" },
  skipped: { label: "Skipped", tone: "grey" },
  unknown: { label: "Unknown", tone: "grey" },
};

export const RUN_STATUS = {
  running: { label: "Running", tone: "blue", icon: "running" },
  waiting: { label: "Waiting", tone: "amber", icon: "waiting" },
  rolling_back: { label: "Rolling back", tone: "orange", icon: "rolled_back" },
  succeeded: { label: "Passed", tone: "green", icon: "succeeded" },
  failed: { label: "Failed", tone: "red", icon: "failed" },
  rollback_failed: { label: "Rollback failed", tone: "red", icon: "rollback_failed" },
  undone: { label: "Undone", tone: "grey", icon: "skipped" },
  // pitch demo only
  passed: { label: "Passed", tone: "green", icon: "succeeded" },
  blocked: { label: "Blocked", tone: "amber", icon: "blocked" },
  recovering: { label: "Recovering", tone: "violet", icon: "running" },
  rolled_back: { label: "Rolled back", tone: "orange", icon: "rolled_back" },
  pending: { label: "Pending", tone: "grey", icon: "pending" },
  none: { label: "No runs yet", tone: "grey", icon: "pending" },
};

// Plan and ingest runs have nothing to roll back: a cut-off one is just interrupted.
const AGENT_MODES = new Set(["plan", "ingest"]);

export function runMeta(status, mode) {
  if (AGENT_MODES.has(mode)) {
    if (status === "rollback_failed") return { label: "Interrupted", tone: "red", icon: "failed" };
    if (status === "succeeded") return { label: mode === "plan" ? "Plan ready" : "Ingested", tone: "green", icon: "succeeded" };
    if (status === "running") return { label: mode === "plan" ? "Planning" : "Ingesting", tone: "violet", icon: "running" };
  }
  return RUN_STATUS[status] ?? RUN_STATUS.none;
}

export const MODE_LABEL = { build: "Build", rehearse: "Rehearse", deploy: "Deploy", plan: "Plan", ingest: "Ingest" };
