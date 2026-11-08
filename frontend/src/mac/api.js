// Talks to the runner's /api/mac (docs/api.md). Locally no token is needed; on Fly, the MaC API
// token is kept in this browser's localStorage and sent with every call.

const TOKEN_KEY = "mac-api-token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(value) {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private mode: the token just won't be remembered.
  }
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

async function call(method, path, body) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api/mac${path}`, {
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
};

// Live events for a run (server-sent events). Returns a function that stops listening.
export function follow(runId, after, onEvent, onEnd) {
  const token = getToken();
  const query = new URLSearchParams({ after: String(after) });
  if (token) query.set("token", token);
  const source = new EventSource(`/api/mac/runs/${runId}/stream?${query}`);
  for (const kind of ["log", "step", "run", "diagnosis"]) {
    source.addEventListener(kind, (e) => onEvent(JSON.parse(e.data)));
  }
  source.addEventListener("end", () => {
    source.close();
    onEnd();
  });
  return () => source.close();
}
