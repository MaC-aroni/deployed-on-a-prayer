// The only way the UI talks to the runner: /api/mac (contract in docs/api.md).
// Relative URLs only; Vite proxies them in dev and FastAPI serves them in prod.

const TOKEN_KEY = "mac.api.token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* per-viewer convenience only */
  }
}

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

async function request(method, path, body) {
  const token = getToken();
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["content-type"] = "application/json";
  const res = await fetch(`/api/mac${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status));
  return data;
}

const enc = encodeURIComponent;

export const api = {
  migrations: () => request("GET", "/migrations"),
  migration: (name) => request("GET", `/migrations/${enc(name)}`),
  start: (name, mode, body = {}) => request("POST", `/migrations/${enc(name)}/${mode}`, body),
  runs: (migration, limit = 50) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (migration) q.set("migration", migration);
    return request("GET", `/runs?${q}`);
  },
  run: (id) => request("GET", `/runs/${enc(id)}`),
  events: (id, after = 0, step) => {
    const q = new URLSearchParams({ after: String(after) });
    if (step) q.set("step", step);
    return request("GET", `/runs/${enc(id)}/events?${q}`);
  },
  play: (id, step) => request("POST", `/runs/${enc(id)}/steps/${enc(step)}/play`),
  resume: (id) => request("POST", `/runs/${enc(id)}/resume`),
  undo: (id) => request("POST", `/runs/${enc(id)}/undo`),
};

// Server-sent events for a run. Returns a function that closes the stream.
export function streamRun(id, after, { onEvent, onEnd, onError }) {
  const q = new URLSearchParams({ after: String(after ?? 0) });
  const token = getToken();
  if (token) q.set("token", token);
  const es = new EventSource(`/api/mac/runs/${enc(id)}/stream?${q}`);
  for (const kind of ["log", "step", "run", "diagnosis"]) {
    es.addEventListener(kind, (e) => onEvent?.(JSON.parse(e.data)));
  }
  es.addEventListener("end", (e) => {
    es.close();
    let summary = null;
    try {
      summary = JSON.parse(e.data);
    } catch {
      /* no body */
    }
    onEnd?.(summary);
  });
  es.onerror = (e) => onError?.(e);
  return () => es.close();
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
