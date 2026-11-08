// Every call to the backend goes through here (UI.md): the runner API at /api/mac
// (docs/api.md), the planning API (docs/planning-api.md) and sign-in (/api/auth).
// On Fly the POSTs need a GitHub sign-in: the server sets a session cookie, which the browser
// sends by itself. Locally nothing is needed. The UI never sends tokens or headers.

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function detailOf(data, status) {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg ?? JSON.stringify(x)).join("; ");
  return `HTTP ${status}`;
}

async function call(method, path, body) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path.startsWith("/auth/") ? `/api${path}` : `/api/mac${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status));
  return data;
}

const enc = encodeURIComponent;

export const api = {
  // Reviewed migrations (examples/) and their runs
  migrations: () => call("GET", "/migrations"),
  migration: (name) => call("GET", `/migrations/${enc(name)}`),
  start: (name, mode, body = {}) => call("POST", `/migrations/${enc(name)}/${mode}`, body),
  runs: (migration, limit = 50) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (migration) q.set("migration", migration);
    return call("GET", `/runs?${q}`);
  },
  run: (id) => call("GET", `/runs/${enc(id)}`),
  // GET /runs plus migration, based_on and autofix per run (planning API), for lists that link runs
  runIndex: (migration, limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (migration) q.set("migration", migration);
    return call("GET", `/run-index?${q}`);
  },
  events: (id, after = 0, step) => {
    const q = new URLSearchParams({ after: String(after) });
    if (step) q.set("step", step);
    return call("GET", `/runs/${enc(id)}/events?${q}`);
  },
  play: (id, step) => call("POST", `/runs/${enc(id)}/steps/${enc(step)}/play`),
  resume: (id) => call("POST", `/runs/${enc(id)}/resume`),
  undo: (id) => call("POST", `/runs/${enc(id)}/undo`),
  cancel: (id) => call("POST", `/runs/${enc(id)}/cancel`),
  approvalsSync: (name) => call("POST", `/migrations/${enc(name)}/approvals/sync`),
  // Outputs and probes: proof the deployed service answers from AWS
  probe: (id, step, output, probe) => call("POST", `/runs/${enc(id)}/outputs/${enc(step)}/${enc(output)}/probes/${enc(probe)}`),
  probes: (id) => call("GET", `/runs/${enc(id)}/probes`),

  // Planning: the knowledge graph, the Planner, and the plans it generated
  services: () => call("GET", "/services"),
  ingest: () => call("POST", "/ingest"),
  plan: (body) => call("POST", "/plan", body),
  plans: () => call("GET", "/plans"),
  planDetail: (runId) => call("GET", `/plans/${enc(runId)}`),
  startOnPlan: (runId, mode, body = {}) => call("POST", `/plans/${enc(runId)}/${mode}`, body),
  // Learn a repository nobody documented: writes a knowledge page, merges the graph, raises a review ticket
  learn: (repo) => call("POST", "/learn", { repo }),
  knowledge: (page) => call("GET", `/knowledge/${enc(page)}`),
  // The Diagnostician on a failed run, and the person's approval that turns its fix into a PR
  investigate: (runId, mode) => call("POST", `/runs/${enc(runId)}/investigate`, mode ? { mode } : {}),
  approveFix: (runId) => call("POST", `/runs/${enc(runId)}/approve-fix`),

  // What this deployment has configured (names only): { llm, model, github, jira, confluence, aws, approvals_live }
  health: () => call("GET", "/health"),
  // Every deployed endpoint across every pipeline, for the Services tab
  activeServices: () => call("GET", "/services/active"),
  // Repositories added by URL (an agent checks the licence) and the Confluence door's "create page"
  addRepo: (url) => call("POST", "/repos", { url }),
  removeRepo: (slug) => call("DELETE", `/repos/${slug}`),
  publishKnowledge: (page) => call("POST", `/knowledge/${enc(page)}/publish`),
  reviewKnowledge: (page, status, note) => call("POST", `/knowledge/${enc(page)}/review`, { status, note }),
  // Chat: a fresh agent over the whole knowledge base, one turn per call
  chat: (message, chatId) => call("POST", "/chat", { message, chat_id: chatId ?? null }),
  chats: () => call("GET", "/chats"),
  chatDetail: (id) => call("GET", `/chats/${enc(id)}`),
  deleteChat: (id) => call("DELETE", `/chats/${enc(id)}`),

  // Sign-in: { login, required, available, repo }
  me: () => call("GET", "/auth/me"),
};

// The AI report a Report or Auto-fix run wrote (a download; 404 when there is none).
export const reportUrl = (runId) => `/api/mac/runs/${enc(runId)}/report.md`;

// A pipeline page reads one of two sources with the same shape.
export function sourceApi(source) {
  if (source.kind === "plan") {
    return { detail: () => api.planDetail(source.id), start: (mode, body) => api.startOnPlan(source.id, mode, body) };
  }
  return { detail: () => api.migration(source.id), start: (mode, body) => api.start(source.id, mode, body) };
}

// Full-page navigations: GitHub's sign-in page, and back.
export const SIGN_IN_URL = "/api/auth/login";
export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.assign("/");
}

// Live events for a run (server-sent events). Returns a function that stops listening.
// onStatus gets "on" when connected, "retry" while the browser reconnects, "off" when closed.
export function follow(runId, after, onEvent, onEnd, onStatus = () => {}) {
  const query = new URLSearchParams({ after: String(after ?? 0) });
  const source = new EventSource(`/api/mac/runs/${enc(runId)}/stream?${query}`);
  source.onopen = () => onStatus("on");
  source.onerror = () => onStatus(source.readyState === EventSource.CLOSED ? "off" : "retry");
  for (const kind of ["log", "step", "run", "diagnosis", "agent", "approval", "failure"]) {
    source.addEventListener(kind, (e) => onEvent(JSON.parse(e.data)));
  }
  source.addEventListener("end", () => {
    source.close();
    onStatus("off");
    onEnd?.();
  });
  return () => source.close();
}

// Same as follow(), with the signature the pages use.
export function streamRun(runId, after, { onEvent, onEnd }) {
  return follow(runId, after, onEvent, onEnd);
}

export function fmtTime(epochSeconds) {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtAgo(epochSeconds) {
  if (!epochSeconds) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function shortRepo(repo) {
  // "github.com/MaC-aroni/claims-db-migrate@main" -> "claims-db-migrate"
  return (repo ?? "").replace(/@.*$/, "").split("/").pop();
}

export function repoKey(repo) {
  return (repo ?? "").replace(/@.*$/, "");
}

// Deep links into the repo a step points at: the tree at the locked commit, or one file in it.
export function githubUrl(repo, shas, path) {
  const [slug, ref = "main"] = (repo ?? "").replace(/^github\.com\//, "").split("@");
  const sha = shas?.[`github.com/${slug}`] || ref;
  const base = `https://github.com/${slug}`;
  return path ? `${base}/blob/${sha}/${path}` : `${base}/tree/${sha}`;
}

export function shortSha(repo, shas) {
  const sha = shas?.[repoKey(repo)];
  return sha ? sha.slice(0, 7) : null;
}

// An `agent` event's message is JSON: { agent, parent?, role?, model?, phase, text, status? }.
export function parseAgent(ev) {
  if (ev?.kind !== "agent") return null;
  try {
    return { ...JSON.parse(ev.message), seq: ev.seq, ts: ev.ts, step: ev.step };
  } catch {
    return null;
  }
}
