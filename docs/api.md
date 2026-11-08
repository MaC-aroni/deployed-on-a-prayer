# MaC API (for the UI)

HTTP API over the runner. Same rules as the CLI; read [`runner.md`](runner.md) for what Build,
Rehearse and Deploy mean. Code: `backend/app/mac_api.py`; tests: `backend/tests/test_api.py`.

Everything is under **`/api/mac`**. JSON in and out, except the live stream.

## Running it while building the UI

Use **`mise run dev-local`**. It runs the backend with the runner on your machine and the
frontend at http://localhost:5173, and Vite forwards `/api/...` to it. Locally nothing needs
a sign-in. Runs are stored in `backend/.mac/` (gitignored). Delete that folder to start fresh.

To make real Builds reach GitHub, put `GITHUB_TOKEN=<token>` in `backend/.env`. Until the demo
repos exist, every Build fails with "repo or branch not found", which is still a real run,
with events, that you can build screens against.

With `mise run dev` (the live backend on Fly) you can read everything, but the buttons need a
sign-in there (see Access), and they change real AWS.

## Access

- **Reading is open everywhere:** every `GET`, including the event stream.
- **Locally:** the `POST`s (they start or change runs) are open too.
- **On Fly** (`APP_ENV=production`): every `POST` needs someone signed in with GitHub who has
  write access to `MaC-aroni/deployed-on-a-prayer`. Otherwise it answers `401` ("Sign in with
  GitHub to do this"), or `503` if the GitHub OAuth app isn't configured. The session is a
  cookie the browser sends by itself, so the UI sends no headers. The run's log records who
  pressed the button (`requested by @login`).
- Sign-in (`app/auth.py`):

| Endpoint | What it does |
|---|---|
| `GET /api/auth/me` | `{login, required, available, repo}`: `login` is null when signed out; `required` is true on Fly; `available` is false when no OAuth app is set up |
| `GET /api/auth/login` | Full-page link: goes to GitHub, comes back to `/`, signed in for 7 days |
| `GET /api/auth/callback` | GitHub's return address. A failed sign-in comes back as `/?signin=no-access`, `expired` or `failed` |
| `POST /api/auth/logout` | Signs out |

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
hasn't been raised yet: after a chain approval (`after`) or the design page.
`approvals[].status` (`approved` · `pending` · `rejected` · `unknown` · `not_requested`),
`detail` and `checked` (Unix seconds) are the **live** state: the server asks Jira on its own
(every `MAC_APPROVAL_POLL_SECONDS`, default 30) and Jira can push changes to the webhook, so
the UI only has to re-fetch this endpoint. `approvals_checked` is the newest check;
`approvals_live` is false when neither the poller nor the webhook is configured.

When an approval is granted in Jira, MaC raises the next ticket in its `after` chain by itself
and any Deploy waiting on it continues (or fails and undoes everything, on a rejection). The log
of the migration's latest run gets a line like `approvals changed in Jira: APPR-MGR-001 approved`.
`POST /api/mac/migrations/{name}/approvals/sync` asks Jira right now (needs sign-in on Fly) and
returns `{changed, raised, resumed, statuses}`.
`design_page.current` is false when the spec changed since the page was written; the next
Build rewrites it.

### Outputs and probes: proof it runs in AWS

`GET /migrations/{name}` has `endpoints`: one entry per declared step output, e.g.
```json
{"step": "deploy_service", "name": "url", "description": "ClaimsAdjudicationService's AWS Lambda URL",
 "probes": [{"name": "health", "method": "GET", "path": "/health", "body": null, "expect": 200},
            {"name": "adjudicate", "method": "POST", "path": "/adjudicate", "body": {"claim_id": "CLM-1001"}, "expect": 200}],
 "production": {"run_id": "…", "value": "https://….lambda-url.us-east-1.on.aws/", "run_status": "succeeded", "expected_live": true},
 "rehearsal": {"run_id": "…", "value": "https://….lambda-url.us-east-1.on.aws/", "run_status": "succeeded", "expected_live": false}}
```
`expected_live` is false when the run undid itself (every finished Rehearse, an undone Deploy):
the URL is history, and probing it shows AWS refusing it. Each run also has `outputs`
(`{step: {name: value}}`).

| Request | What it does |
|---|---|
| `POST /runs/{id}/outputs/{step}/{output}/probes/{probe}` | MaC sends that probe's request, **signed with SigV4**, to the URL this run recorded, and returns AWS's answer. Open to viewers (no sign-in): it only reads, and only URLs MaC deployed. Repeats within 3 s return the last answer |
| `GET /runs/{id}/probes` | Every probe of this run, newest first: the before/after record |

A probe answer:
```json
{"url": "https://….lambda-url.us-east-1.on.aws/adjudicate", "method": "POST", "probe": "adjudicate",
 "status": 200, "ok": true, "elapsed_ms": 184, "request_id": "4f0c…", "served_by_aws": true, "region": "us-east-1",
 "body": {"claim_id": "CLM-1001", "decision": "approved", "reason": "…"}, "error": null,
 "env": "production", "expected_live": true, "checked": 1794111111.2,
 "curl": "curl -sS --aws-sigv4 'aws:amz:us-east-1:lambda' --user \"$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY\" … "}
```
- `request_id` is the id AWS Lambda stamps on every response: proof the answer came from AWS.
- **Before / after:** AWS answers **403** for a function URL that doesn't exist (yet, or any more),
  then **200** with the real result once deployed. `error` is set when nothing answered at all.
- `curl` is the same request for anyone with AWS keys in their shell (no keys are in it).

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
| `POST /api/mac/runs/{id}/resume` | the run is `waiting` on an approval (checks Jira again). Rarely needed now: the server does this itself when Jira changes |
| `POST /api/mac/runs/{id}/undo` | the run is `waiting`, a Deploy that `succeeded`, or any run that ended `rollback_failed` (retries only what wasn't undone) |
| `GET /api/mac/runs/{id}/report.md` | the AI's Markdown report (Report and Auto-fix modes); 404 when there is none. The run view's `ai_report` says whether one exists |

### Logs and the live stream

`GET /api/mac/runs/{id}/events?after=<seq>&step=<step id>` returns
`[{"run_id", "seq", "ts", "step", "kind", "message"}]`. `kind` is one of:
- `log`: a line of output; `step` says which card it belongs to
- `step`: a step changed state
- `run`: a run-level message, like started, waiting, failed or undoing
- `diagnosis`: the AI's take after a failure. In Explain mode it's Markdown with the headings
  "What went wrong / Likely cause / Where / What to do"; Report adds a link to `report.md`;
  Auto-fix adds what it changed, the branch, and the attempt number. An auto-fix run has
  `autofix: {parent, branch, attempt, repo, pr?}` on the run view, and its passing rehearsal
  gets a `diagnosis` event with the pull request URL

`GET /api/mac/runs/{id}/stream` sends server-sent events: everything so far, then every new
event as it happens, then `event: end` once the run stops moving. Reconnects resume
automatically through `Last-Event-ID`.

```js
const es = new EventSource(`/api/mac/runs/${runId}/stream`);
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

- Steps run one at a time. No parallel cards are running at once.
