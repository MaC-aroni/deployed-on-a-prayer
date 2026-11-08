# MaC API (for the UI)

HTTP API over the runner. Same rules as the CLI; read [`runner.md`](runner.md) for what Build,
Rehearse and Deploy mean. Code: `backend/app/mac_api.py`; tests: `backend/tests/test_api.py`.

Everything is under **`/api/mac`**. JSON in and out, except the live stream.

## Running it while building the UI

Use **`mise run dev-local`**. It runs the backend with the runner on your machine and the
frontend at http://localhost:5173, and Vite forwards `/api/...` to it. Locally the API needs no
token. Runs are stored in `backend/.mac/` (gitignored). Delete that folder to start fresh.

To make real Builds reach GitHub, put `GITHUB_TOKEN=<token>` in `backend/.env`. Until the demo
repos exist, every Build fails with "repo or branch not found", which is still a real run,
with events, that you can build screens against.

`mise run dev` (the live backend on Fly) won't work for these endpoints. They need a token
there (see Access).

## Access

- **Locally:** open.
- **On Fly** (`APP_ENV=production`): every `/api/mac` endpoint needs the token in the
  `MAC_API_TOKEN` Fly secret. Without that secret set, the API answers 503. Send it as
  `Authorization: Bearer <token>`, or as `?token=<token>` for `EventSource`, which can't
  send headers. Ask ob1-can-obi for it, and never commit it. A good UI pattern: a settings
  box that keeps it in `localStorage`.
- `/api/health` and the rest of the app stay public.

## How a button works

Every action answers **immediately**:
- **`202`** plus the run: it started, and the work continues in the background.
- **`409`** plus `{"detail": "<reason>"}`: the runner refused. Show `detail` as it is.
  For example: "Rehearse needs a passing Build of this exact migration.yaml. Run Build first."
- **`404`**: no such migration or run.

Then follow the run, either live with the stream (best) or by polling `GET /runs/{id}`.

## Endpoints

### Migrations

`GET /api/mac/migrations`: every `*/migration.yaml` under `MAC_MIGRATIONS_DIR`, which is
`examples/` by default.
```json
[{"name": "claims-adjudication-onprem-to-aws", "valid": true, "problems": [],
  "service": "ClaimsAdjudicationService", "owner_team": "claims-platform",
  "stages": ["check", "infrastructure", "data", "release", "verify"],
  "latest": {"build": {"id": "…", "status": "succeeded", "…": "…"}, "rehearse": null, "deploy": null}}]
```
A file that can't be read is still listed, with `"valid": false` and its `problems`.

`GET /api/mac/migrations/{name}`: everything needed to draw the pipeline before any run exists.
```json
{"name": "…", "service": "…", "owner_team": "…", "target": {"provider": "aws", "account": "…", "region": "us-east-1"},
 "diagnostics_default": "explain",
 "stages": [{"name": "infrastructure", "steps": [
   {"id": "provision_network", "stage": "infrastructure", "type": "iac", "when": "auto",
    "needs": [], "requires_approval": ["APPR-TR-001"],
    "repo": "github.com/MaC-aroni/claims-service-iac@main", "entrypoint": null, "path": "terraform/network",
    "verify": null, "rollback": "terraform destroy"}]}],
 "approvals": [{"id": "APPR-MCP-001", "type": "access_request_owner", "approver": "claims-mcp-team",
                "summary": "…", "justification": "…", "after": ["APPR-MGR-001"], "design_doc": false,
                "ticket": {"key": "MAC-3", "url": "https://….atlassian.net/browse/MAC-3"}}],
 "design_page": {"url": "https://….atlassian.net/wiki/spaces/MAC/pages/…", "current": true},
 "issues": [], "latest": {"build": null, "rehearse": null, "deploy": null}, "active_run": null}
```
Stages and steps come **in run order**. Draw stages as columns, left to right, and steps as
cards inside them.

`approvals[].ticket` is the Jira ticket for **this version** of the spec, or `null` if it
hasn't been raised yet: after a chain approval (`after`) or the design page. Ticket statuses
come from the latest Build's `report.approvals`, or from a waiting Deploy's `reason`.
`design_page.current` is false when the spec changed since the page was written; the next
Build rewrites it.

### Starting runs (the top-bar buttons)

| Request | Body (optional) |
|---|---|
| `POST /api/mac/migrations/{name}/build` | `{"branches": {"github.com/o/r": "branch"}}`, for auto-fix testing only |
| `POST /api/mac/migrations/{name}/rehearse` | `{"ai": "explain" \| "report" \| "autofix", "branches": {…}}` |
| `POST /api/mac/migrations/{name}/deploy` | `{"ai": "explain" \| "report"}`. Branches are refused; `autofix` becomes `report` |

`ai` is the **Explain · Report · Auto-fix** selector. Leave it out to use the migration's
`diagnostics_default`.

**Which buttons to enable.** These are also enforced server-side, which answers 409:
- **Build:** always.
- **Rehearse:** `latest.build.status == "succeeded"` and there's no `active_run`.
- **Deploy:** `latest.rehearse.status == "succeeded"` and there's no `active_run`. The server
  also checks that no repo's `main` moved, which the UI can't know, so still show the 409 reason.

### Following a run

`GET /api/mac/runs/{id}`
```json
{"id": "037976b8ade0", "migration": "…", "mode": "rehearse", "status": "waiting", "active": true,
 "reason": "db_migrate is manual: press play to run it", "failed_step": null,
 "diagnostics_mode": "autofix", "shas": {"github.com/MaC-aroni/claims-db-migrate": "<40-char sha>"},
 "steps": {"preflight": "succeeded", "db_migrate": "waiting", "deploy_service": "pending"},
 "stages": [{"name": "data", "steps": [{"id": "db_migrate", "state": "waiting"}]}],
 "completed": ["preflight", "provision_network", "provision_iam"], "played": [],
 "report": {}, "based_on": "<build or rehearse id>", "created": 1794108020.19, "updated": 1794108020.50}
```
- `report` is filled in by Build:
  - `issues`
  - `guardrails`: per repo, `[{name, passed, detail}]`
  - `approvals`: per approval id, `{status, detail, ticket, url}`. `status` is `approved`,
    `pending`, `rejected` or `unknown`; `detail` is the ticket key or why it's waiting
  - `design_page`: `{url, status}`
- `GET /api/mac/runs?migration=<name>&limit=50` lists run summaries, newest first. Use it
  for a history list.

**Run `status`:** `running` · `waiting` (on approval or play) · `rolling_back` · `succeeded`
· `failed` (a step failed and everything was undone cleanly) · `rollback_failed` (the undo
didn't finish; needs a person) · `undone`. `active` is true for the first three.

**Step `state`** (colour the cards with these): `pending` · `blocked` (waiting for approval) ·
`waiting` (manual: show ▶) · `running` · `succeeded` · `failed` · `rolled_back` ·
`rollback_failed` · `skipped` (never reached).

### Run actions

| Request | When |
|---|---|
| `POST /api/mac/runs/{id}/steps/{step}/play` | that step's state is `waiting` (the ▶ button) |
| `POST /api/mac/runs/{id}/resume` | the run is `waiting` on an approval (checks Jira again) |
| `POST /api/mac/runs/{id}/undo` | the run is `waiting`, or a Deploy that `succeeded` |

### Logs and the live stream

`GET /api/mac/runs/{id}/events?after=<seq>&step=<step id>` returns
`[{"run_id", "seq", "ts", "step", "kind", "message"}]`. `kind` is one of:
- `log`: a line of output; `step` says which card it belongs to
- `step`: a step changed state
- `run`: a run-level message, like started, waiting, failed or undoing
- `diagnosis`: the AI's take after a failure

`GET /api/mac/runs/{id}/stream` sends server-sent events: everything so far, then every new
event as it happens, then `event: end` once the run stops moving. Reconnects resume
automatically through `Last-Event-ID`.

```js
const es = new EventSource(`/api/mac/runs/${runId}/stream`); // + `?token=…` on Fly
for (const kind of ["log", "step", "run", "diagnosis"]) {
  es.addEventListener(kind, (e) => {
    const ev = JSON.parse(e.data); // {seq, step, kind, message, ...}
    if (kind === "log") appendLog(ev.step, ev.message);
    else refreshRun(); // GET /runs/{id} for the new states
  });
}
es.addEventListener("end", () => { es.close(); refreshRun(); });
```

## Not there yet

- The `.md` download for the **Report** mode. The AI agents aren't connected yet; until then,
  failures add a `diagnosis` event saying so.
- **Run history on Fly is wiped on every deploy,** because the disk isn't persistent. A Fly
  volume will fix that before the demo.
- Steps run one at a time. No parallel cards are running at once.
