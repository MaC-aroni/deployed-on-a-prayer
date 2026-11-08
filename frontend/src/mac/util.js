// Formatting and derivations shared by the console's components. Pure functions, no fetches.

export const STEP_LABEL = {
  pending: "Pending", blocked: "Blocked", waiting: "Manual", running: "Running", succeeded: "Passed",
  failed: "Failed", rolled_back: "Rolled back", rollback_failed: "Rollback failed", skipped: "Skipped",
  none: "Not run",
};

export const RUN_LABEL = {
  running: "Running", waiting: "Waiting", rolling_back: "Rolling back", succeeded: "Passed",
  failed: "Failed", rollback_failed: "Rollback failed", undone: "Undone",
};

export const APPROVAL_LABEL = {
  approved: "Approved", pending: "Pending", rejected: "Rejected", unknown: "Unknown",
  not_requested: "Not requested",
};

// An approval still moving: not yet approved or rejected. Without a status (mock data) it isn't live.
export function approvalOutstanding(approval) {
  return typeof approval?.status === "string" && approval.status !== "approved" && approval.status !== "rejected";
}

// One colour per meaning, everywhere: badges, icons, rows and timeline nodes agree.
export const VARIANT = {
  succeeded: "success", approved: "success",
  failed: "danger", rejected: "danger", rollback_failed: "danger",
  running: "info", rolling_back: "info",
  waiting: "warning", blocked: "warning", pending: "warning",
  rolled_back: "purple", undone: "purple",
  skipped: "neutral", none: "neutral", unknown: "neutral", not_requested: "muted",
};

export const STEP_TYPE = {
  check: "Check (read-only)", script: "Script", iac: "Terraform", db_migration: "Data migration",
};

export const MODE_LABEL = { build: "Build", rehearse: "Rehearse", deploy: "Deploy" };

export function shortId(id) {
  return id ? id.slice(0, 7) : "";
}

export function timeAgo(seconds) {
  if (!seconds) return "";
  const diff = Math.max(0, Date.now() / 1000 - seconds);
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return `${Math.round(diff / 86400)} d ago`;
}

export function absTime(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "";
}

export function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

const TERMINAL = new Set(["succeeded", "failed", "rolled_back", "rollback_failed", "skipped"]);

// Per step: when it started running, when it finished, and how long the run took (not the undo).
export function stepTimings(events) {
  const out = {};
  for (const e of events) {
    if (e.kind !== "step" || !e.step) continue;
    const state = e.message.split(": ").pop();
    const t = (out[e.step] ||= {});
    if (state === "running" && t.started == null) t.started = e.ts;
    else if (TERMINAL.has(state) && t.started != null && t.finished == null) t.finished = e.ts;
    if (state === "rolled_back") t.rolledBack = e.ts;
  }
  for (const t of Object.values(out)) {
    if (t.started != null && t.finished != null) t.duration = t.finished - t.started;
  }
  return out;
}

export function requestedBy(events) {
  const hit = events.find((e) => e.kind === "log" && e.message.startsWith("requested by @"));
  return hit ? hit.message.slice("requested by @".length).trim() : null;
}

// Terraform's one-line summary in a Build's plan output, per step.
export function planSummary(events, stepId) {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.step !== stepId || e.kind !== "log") continue;
    const m = /Plan: (\d+) to add, (\d+) to change, (\d+) to destroy/.exec(e.message);
    if (m) return { add: +m[1], change: +m[2], destroy: +m[3] };
    if (/No changes\./.test(e.message)) return { add: 0, change: 0, destroy: 0 };
  }
  return null;
}

export function runDuration(run) {
  if (!run) return null;
  return (run.active ? Date.now() / 1000 : run.updated) - run.created;
}

// The stage's overall state, for the column header's icon, the way GitLab summarises a stage.
export function stageState(stage, run) {
  const states = stage.steps.map((s) => run?.steps?.[s.id] || "none");
  const has = (x) => states.includes(x);
  if (has("running")) return "running";
  if (has("rollback_failed")) return "rollback_failed";
  if (has("failed")) return "failed";
  if (has("waiting")) return "waiting";
  if (has("blocked")) return "blocked";
  if (states.every((s) => s === "none")) return "none";
  if (states.every((s) => s === "succeeded" || s === "none")) return "succeeded";
  if (states.every((s) => s === "rolled_back" || s === "skipped" || s === "none")) return has("rolled_back") ? "rolled_back" : "skipped";
  if (has("pending")) return "pending";
  if (has("rolled_back")) return "rolled_back";
  return "skipped";
}

// GitHub deep links at the commit a run actually used.
export function githubUrl(repo, shas, path) {
  const [slug, ref = "main"] = repo.replace(/^github\.com\//, "").split("@");
  const sha = shas?.[`github.com/${slug}`] || shas?.[repo] || ref;
  const base = `https://github.com/${slug}`;
  return path ? `${base}/blob/${sha}/${path}` : `${base}/tree/${sha}`;
}

export function shortSha(repo, shas) {
  const slug = repo.replace(/^github\.com\//, "").split("@")[0];
  const sha = shas?.[`github.com/${slug}`];
  return sha ? sha.slice(0, 7) : null;
}

export function repoName(repo) {
  return repo.replace(/^github\.com\//, "").split("@")[0].split("/").pop();
}

export function maskAccount(account) {
  return account && account.length > 4 ? `…${account.slice(-4)}` : account;
}
