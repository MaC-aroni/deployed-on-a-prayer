// Talks to the runner's /api/mac (docs/api.md). On Fly, the buttons need a GitHub sign-in: the
// server sets a session cookie, which the browser sends by itself. Locally nothing is needed.

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
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
  if (!res.ok) throw new ApiError(res.status, data.detail || `HTTP ${res.status}`);
  return data;
}

export const api = {
  migrations: () => call("GET", "/migrations"),
  migration: (name) => call("GET", `/migrations/${name}`),
  start: (name, mode, ai) => call("POST", `/migrations/${name}/${mode}`, ai ? { ai } : {}),
  runs: (name) => call("GET", `/runs?migration=${encodeURIComponent(name)}&limit=20`),
  run: (id) => call("GET", `/runs/${id}`),
  events: (id) => call("GET", `/runs/${id}/events`),
  play: (id, step) => call("POST", `/runs/${id}/steps/${step}/play`),
  resume: (id) => call("POST", `/runs/${id}/resume`),
  undo: (id) => call("POST", `/runs/${id}/undo`),
  me: () => call("GET", "/auth/me"), // { login, required, available, repo }
};

// Full-page navigations: GitHub's sign-in page, and back.
export const SIGN_IN_URL = "/api/auth/login";
export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.assign("/");
}

// Live events for a run (server-sent events). Returns a function that stops listening.
// onStatus gets "on" when connected and "retry" while the browser reconnects.
export function follow(runId, after, onEvent, onEnd, onStatus = () => {}) {
  const query = new URLSearchParams({ after: String(after) });
  const source = new EventSource(`/api/mac/runs/${runId}/stream?${query}`);
  source.onopen = () => onStatus("on");
  source.onerror = () => onStatus(source.readyState === EventSource.CLOSED ? "off" : "retry");
  for (const kind of ["log", "step", "run", "diagnosis"]) {
    source.addEventListener(kind, (e) => onEvent(JSON.parse(e.data)));
  }
  source.addEventListener("end", () => {
    source.close();
    onEnd();
  });
  return () => source.close();
}
