"""HTTP API over the MaC runner, for the UI. Same Runner, same rules as the CLI.

Every action answers at once: 202 with the run (it has started), 409 with the reason (the
runner refused, e.g. "Run Build first"). The slow work happens on a worker thread; watch it
with GET /runs/{id}/stream (server-sent events) or poll GET /runs/{id}. Full contract:
docs/api.md.

Access: reading is open. Every POST (they start or change runs, so real AWS) needs a signed-in
member of the GitHub org when APP_ENV=production; see app/auth.py. Locally nothing is required.
"""

import asyncio
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from mac import probe as probes
from mac.cli import make_runner
from mac.runner import GateError, Runner
from mac.spec import Spec, SpecError, Step, load_spec, parse_spec
from mac.store import RunRecord, RunStatus
from mac.validate import execution_order, validate

from .auth import signed_in

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("mac.api")


@dataclass
class State:
    runner: Runner
    migrations_dir: Path
    submit: Callable[[Callable[[], None]], None]  # runs work in the background
    poll_seconds: int = 0  # how often to ask Jira about pending approvals; 0 = never
    webhook_secret: str | None = None  # MAC_JIRA_WEBHOOK_SECRET; None = the Jira webhook is off
    prober: Callable = probes.send  # (url, probe, region) -> result; tests swap it


_state: State | None = None


def configure(state: State) -> None:
    """Tests (or a different deployment) can swap in their own runner and settings."""
    global _state
    _state = state


def _default_state() -> State:
    data_dir = Path(os.environ.get("MAC_DATA_DIR", ROOT / ".mac"))  # the same history as `mise run mac`
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mac-run")
    runner = make_runner(data_dir, submit=pool.submit)  # auto-fix's re-runs go through the same pool
    return State(
        runner=runner,
        migrations_dir=Path(os.environ.get("MAC_MIGRATIONS_DIR", ROOT / "examples")),
        submit=pool.submit,
        poll_seconds=int(os.environ.get("MAC_APPROVAL_POLL_SECONDS", "30")),
        webhook_secret=os.environ.get("MAC_JIRA_WEBHOOK_SECRET") or None,
    )


def get_state() -> State:
    global _state
    if _state is None:
        state = _default_state()
        queued = state.runner.recover()  # work queued before a restart
        # Checkouts from finished runs are dead weight on a small disk; their logs are in the store.
        state.runner.executor.prune(set(queued))
        for run_id in queued:
            state.submit(lambda r=run_id: _execute(state, r))
        if state.poll_seconds > 0:
            threading.Thread(target=_poll_loop, args=(state,), name="mac-approvals", daemon=True).start()
        _state = state
    return _state


# ---- Approvals that follow Jira on their own ------------------------------------------------


def sync_migration_approvals(state: State, path: Path) -> dict:
    """One sync for one migration: raises due tickets, records statuses, and starts the runs
    that were waiting on an approval. Safe to call from any thread."""
    result = state.runner.sync_approvals(path)
    for run_id in result["resumed"]:
        state.submit(lambda r=run_id: _execute(state, r))
    return result


def poll_approvals_once(state: State) -> list[dict]:
    """Every valid migration with tickets outstanding gets one Jira check."""
    results = []
    for name, (path, spec, _) in _find(state).items():
        if spec is None:
            continue
        try:
            result = sync_migration_approvals(state, path)
        except Exception:  # noqa: BLE001 - one migration's Jira trouble mustn't stop the others
            log.exception("approval sync failed for %s", name)
            continue
        if result["changed"] or result["raised"] or result["resumed"]:
            log.info("approvals for %s: changed=%s raised=%s resumed=%s", name,
                     result["changed"], result["raised"], result["resumed"])
        results.append(result)
    return results


def _poll_loop(state: State) -> None:
    while True:
        time.sleep(state.poll_seconds)
        try:
            poll_approvals_once(state)
        except Exception:  # noqa: BLE001
            log.exception("approval poll crashed; will try again")


router = APIRouter(prefix="/api/mac", tags=["mac"])

# ---- Shapes --------------------------------------------------------------------------------


class StartBody(BaseModel):
    ai: Literal["explain", "report", "autofix"] | None = None  # AI help if a step fails
    branches: dict[str, str] = {}  # repo key -> branch, instead of main (auto-fix testing)


def _step_view(step: Step) -> dict:
    rollback = step.effective_rollback
    return {
        "id": step.id, "stage": step.stage, "type": step.type, "when": step.when, "codegen": step.codegen,
        "needs": list(step.needs), "requires_approval": list(step.requires_approval),
        "repo": str(step.run.repo), "entrypoint": step.run.entrypoint, "path": step.run.path,
        "verify": step.verify.entrypoint if step.verify else None,
        "rollback": None if rollback is None else (rollback.entrypoint or f"terraform {rollback.action}"),
    }


def _stages(spec: Spec) -> list[dict]:
    order = execution_order(spec)
    return [{"name": stage, "steps": [_step_view(s) for s in order if s.stage == stage]} for stage in spec.stages]


def _summary(run: RunRecord | None) -> dict | None:
    if run is None:
        return None
    return {"id": run.id, "mode": run.mode, "status": run.status, "reason": run.reason,
            "failed_step": run.failed_step, "created": run.created, "updated": run.updated}


def _run_view(run: RunRecord) -> dict:
    view = run.model_dump(mode="json", exclude={"spec_text", "next_action"})
    view["active"] = run.status.active
    try:
        spec = parse_spec(run.spec_text, run.spec_path)
        view["stages"] = [{"name": stage, "steps": [{"id": s.id, "state": run.steps.get(s.id)}
                                                    for s in execution_order(spec) if s.stage == stage]}
                          for stage in spec.stages]
    except SpecError:
        view["stages"] = []  # a Build of an invalid spec
    return view


# ---- Migrations ------------------------------------------------------------------------------


def _find(state: State) -> dict[str, tuple[Path, Spec | None, list[str]]]:
    """name -> (path, spec or None, problems). Invalid files are listed under their folder name."""
    found = {}
    for path in sorted(state.migrations_dir.glob("*/migration.yaml")):
        try:
            spec = load_spec(path)
            found[spec.metadata.name] = (path, spec, [str(i) for i in validate(spec)])
        except SpecError as e:
            found[path.parent.name] = (path, None, e.problems)
    return found


def _migration(state: State, name: str) -> tuple[Path, Spec, list[str]]:
    found = _find(state).get(name)
    if found is None:
        raise HTTPException(404, f"no migration named {name!r}")
    path, spec, problems = found
    if spec is None:
        raise HTTPException(409, "migration.yaml can't be read: " + "; ".join(problems))
    return path, spec, problems


def _latest(state: State, name: str) -> dict:
    store = state.runner.store
    return {mode: _summary(store.latest(name, mode)) for mode in ("build", "rehearse", "deploy")}


@router.get("/migrations")
def list_migrations(state: State = Depends(get_state)):
    result = []
    for name, (path, spec, problems) in _find(state).items():
        item = {"name": name, "path": path.relative_to(state.migrations_dir).as_posix(), "problems": problems,
                "valid": spec is not None and not any(p.startswith("error") for p in problems)}
        if spec is not None:
            item |= {"service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
                     "stages": list(spec.stages), "latest": _latest(state, name)}
        result.append(item)
    return result


@router.get("/migrations/{name}")
def get_migration(name: str, state: State = Depends(get_state)):
    path, spec, problems = _migration(state, name)
    store = state.runner.store
    active = next((r for r in store.runs(name) if r.status.active), None)
    # Tickets belong to this exact version of the spec; an edited plan gets fresh ones.
    tickets = store.tickets(name, spec.digest())
    approvals = []
    for approval in spec.approvals:
        ticket = tickets.get(approval.id)
        approvals.append(approval.model_dump(mode="json")
                         | {"ticket": ticket.model_dump(exclude={"approval"}) if ticket else None})
    # Live statuses: the poller, the webhook, Build and a waiting Deploy all record them here.
    records = store.approval_records(name, spec.digest())
    for item in approvals:
        record = records.get(item["id"])
        item["status"] = record.status if record else ("pending" if item["ticket"] else "not_requested")
        item["detail"] = record.detail if record else None
        item["checked"] = record.checked if record else None
    page = store.design(name)
    return {
        "name": name, "service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
        "target": spec.target.model_dump(mode="json"), "diagnostics_default": spec.diagnostics.mode,
        "stages": _stages(spec), "approvals": approvals, "endpoints": _endpoints(store, name, spec),
        "approvals_checked": max((r.checked for r in records.values()), default=None),
        "approvals_live": state.poll_seconds > 0 or state.webhook_secret is not None,
        "design_page": {"url": page.url, "current": page.digest == spec.digest()} if page else None,
        "issues": problems, "latest": _latest(state, name), "active_run": _summary(active),
    }


def _endpoints(store, name: str, spec: Spec) -> list[dict]:
    """Every declared output, with its latest value per environment: what to show (and probe)
    to prove the migration is really running in AWS."""
    latest = {}
    for run in store.runs(name, limit=100):  # newest first
        env = {"deploy": "production", "rehearse": "rehearsal"}.get(run.mode)
        if env and env not in latest and run.outputs:
            latest[env] = run
    result = []
    for step in spec.steps:
        for out in step.outputs:
            entry = {"step": step.id, "name": out.name, "description": out.description,
                     "probes": [p.model_dump(mode="json") for p in out.probes]}
            for env, run in latest.items():
                value = run.outputs.get(step.id, {}).get(out.name)
                if value:
                    # A finished Rehearse undid everything; an undone Deploy too. The URL is history.
                    gone = run.mode == "rehearse" and not run.status.active or run.status == RunStatus.UNDONE
                    entry[env] = {"run_id": run.id, "value": value, "run_status": run.status,
                                  "expected_live": not gone}
            result.append(entry)
    return result


@router.post("/runs/{run_id}/outputs/{step_id}/{output}/probes/{probe_name}")
def run_probe(run_id: str, step_id: str, output: str, probe_name: str, state: State = Depends(get_state)):
    """Sends one signed request to a URL this run recorded, and keeps the answer. Open to
    viewers on purpose (it only reads, and only URLs MaC itself deployed); a repeat within
    3 seconds returns the last answer instead of calling AWS again."""
    run = _get_run(state, run_id)
    value = run.outputs.get(step_id, {}).get(output)
    if not value:
        raise HTTPException(404, f"run {run_id} has no output {step_id}.{output}")
    spec = parse_spec(run.spec_text, run.spec_path)
    declared = next((o for s in spec.steps if s.id == step_id for o in s.outputs if o.name == output), None)
    probe = next((p for p in (declared.probes if declared else ()) if p.name == probe_name), None)
    if probe is None:
        raise HTTPException(404, f"{step_id}.{output} has no probe {probe_name!r}")
    store = state.runner.store
    recent = next((p for p in store.probes(run_id, limit=20)
                   if (p["step"], p["output"], p["probe"]) == (step_id, output, probe_name)), None)
    if recent and time.time() - recent["checked"] < 3:
        return recent
    region = probes.region_of(value, spec.target.region)
    result = state.prober(value, probe, region)
    result.update(step=step_id, output=output, probe=probe_name, run_id=run_id,
                  env="production" if run.mode == "deploy" else "rehearsal",
                  expected_live=not (run.mode == "rehearse" and not run.status.active or run.status == RunStatus.UNDONE))
    store.add_probe(run_id, step_id, output, probe_name, result)
    store.add_event(run_id, "log", f"probe {probe_name}: {probe.method} {result['url']} -> "
                    + (f"{result['status']} in {result.get('elapsed_ms')} ms" if result["status"] else result["error"]), step_id)
    return result


@router.get("/runs/{run_id}/probes")
def list_probes(run_id: str, state: State = Depends(get_state)):
    """Every probe of this run's outputs, newest first: the before/after record."""
    _get_run(state, run_id)
    return state.runner.store.probes(run_id)


@router.post("/migrations/{name}/approvals/sync")
def sync_approvals(name: str, state: State = Depends(get_state), user: str | None = Depends(signed_in)):
    """Check Jira now, instead of waiting for the poller."""
    path, _, _ = _migration(state, name)
    return sync_migration_approvals(state, path)


@router.post("/jira/webhook", include_in_schema=False)
async def jira_webhook(request: Request, token: str | None = Query(default=None),
                       state: State = Depends(get_state)):
    """Jira Cloud calls this when an issue changes (no sign-in: the URL carries a shared secret).
    Only tickets MaC raised are looked at; anything else is ignored."""
    if state.webhook_secret is None:
        raise HTTPException(404, "the Jira webhook isn't enabled (MAC_JIRA_WEBHOOK_SECRET)")
    if not token or not secrets.compare_digest(token, state.webhook_secret):
        raise HTTPException(401, "wrong webhook token")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    key = (body.get("issue") or {}).get("key")
    owner = state.runner.store.ticket_owner(key) if key else None
    if owner is None:
        return {"issue": key, "synced": None}
    migration = owner[0]
    found = _find(state).get(migration)
    if found is None or found[1] is None:
        return {"issue": key, "synced": None}
    result = await asyncio.to_thread(sync_migration_approvals, state, found[0])
    return {"issue": key, "synced": migration, **{k: result[k] for k in ("changed", "raised", "resumed")}}


def _start(state: State, starter: Callable[[], RunRecord], user: str | None) -> dict:
    try:
        run = starter()
    except GateError as e:
        raise HTTPException(409, str(e)) from e
    if user:
        state.runner.store.add_event(run.id, "log", f"requested by @{user}")
    state.submit(lambda: _execute(state, run.id))
    return _run_view(run)


@router.post("/migrations/{name}/build", status_code=202)
def build(name: str, body: StartBody | None = None, state: State = Depends(get_state),
          user: str | None = Depends(signed_in)):
    path, _, _ = _migration(state, name)
    return _start(state, lambda: state.runner.start_build(path, (body or StartBody()).branches), user)


@router.post("/migrations/{name}/rehearse", status_code=202)
def rehearse(name: str, body: StartBody | None = None, state: State = Depends(get_state),
             user: str | None = Depends(signed_in)):
    path, _, _ = _migration(state, name)
    body = body or StartBody()
    return _start(state, lambda: state.runner.start_rehearse(path, body.ai, body.branches), user)


@router.post("/migrations/{name}/deploy", status_code=202)
def deploy(name: str, body: StartBody | None = None, state: State = Depends(get_state),
           user: str | None = Depends(signed_in)):
    path, _, _ = _migration(state, name)
    body = body or StartBody()
    if body.branches:
        raise HTTPException(409, "Deploy always runs main; branches are only for Build and Rehearse")
    return _start(state, lambda: state.runner.start_deploy(path, body.ai), user)


# ---- Runs ------------------------------------------------------------------------------------


def _get_run(state: State, run_id: str) -> RunRecord:
    try:
        return state.runner.store.get(run_id)
    except KeyError as e:
        raise HTTPException(404, f"no run {run_id!r}") from e


@router.get("/runs")
def list_runs(migration: str | None = None, limit: int = Query(default=50, le=200),
              state: State = Depends(get_state)):
    return [_summary(r) for r in state.runner.store.runs(migration, limit)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, state: State = Depends(get_state)):
    view = _run_view(_get_run(state, run_id))
    view["ai_report"] = state.runner.store.report(run_id) is not None
    return view


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def get_report(run_id: str, state: State = Depends(get_state)):
    """The AI's Markdown report for a failed run (Report and Auto-fix modes), for a coding agent."""
    _get_run(state, run_id)
    report = state.runner.store.report(run_id)
    if report is None:
        raise HTTPException(404, "this run has no AI report (it passed, or its AI mode was Explain)")
    return PlainTextResponse(report["markdown"], media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="mac-report-{run_id}.md"'})


@router.post("/runs/{run_id}/steps/{step_id}/play", status_code=202)
def play(run_id: str, step_id: str, state: State = Depends(get_state),
         user: str | None = Depends(signed_in)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_play(run_id, step_id), user)


@router.post("/runs/{run_id}/resume", status_code=202)
def resume(run_id: str, state: State = Depends(get_state),
           user: str | None = Depends(signed_in)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_resume(run_id), user)


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel(run_id: str, state: State = Depends(get_state), user: str | None = Depends(signed_in)):
    """Stop the run and undo everything it did. A waiting run is undone now; a run mid-step
    finishes that step first (a running script is killed, Terraform is left to finish)."""
    _get_run(state, run_id)
    try:
        run = state.runner.request_cancel(run_id)
    except GateError as e:
        raise HTTPException(409, str(e)) from e
    if user:
        state.runner.store.add_event(run.id, "log", f"cancelled by @{user}")
    if run.next_action:  # it was waiting: the undo is queued and needs a worker
        state.submit(lambda: _execute(state, run.id))
    return _run_view(run)


@router.post("/runs/{run_id}/undo", status_code=202)
def undo(run_id: str, state: State = Depends(get_state),
         user: str | None = Depends(signed_in)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_undo(run_id), user)


@router.get("/runs/{run_id}/events")
def events(run_id: str, after: int = 0, step: str | None = None, state: State = Depends(get_state)):
    _get_run(state, run_id)
    return [e.model_dump(mode="json") for e in state.runner.store.events(run_id, after=after, step=step)]


@router.get("/runs/{run_id}/stream")
async def stream(run_id: str, request: Request, after: int = 0,
                 last_event_id: int | None = Header(default=None), state: State = Depends(get_state)):
    """Server-sent events: every event after `after`, live, then `end` once the run stops moving.
    Reconnecting EventSources resume from Last-Event-ID automatically."""
    _get_run(state, run_id)
    store = state.runner.store
    cursor = last_event_id if last_event_id is not None else after

    async def generate():
        nonlocal cursor
        idle = 0.0
        while not await request.is_disconnected():
            # SQLite reads go to a worker thread, so a busy database never stalls the event loop
            # (and with it every other request, including the health check).
            batch = await asyncio.to_thread(store.events, run_id, after=cursor)
            for event in batch:
                cursor = event.seq
                yield f"id: {event.seq}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
            if batch:
                idle = 0.0
            elif not (await asyncio.to_thread(store.get, run_id)).status.active:
                yield f"event: end\ndata: {json.dumps(_summary(store.get(run_id)))}\n\n"
                return
            else:
                idle += 0.5
                if idle >= 15:  # keeps proxies from closing a quiet connection
                    idle = 0.0
                    yield ": still here\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _execute(state: State, run_id: str) -> None:
    try:
        state.runner.execute(run_id)
    except Exception as e:  # noqa: BLE001 - a crash must not leave the run looking active forever
        log.exception("run %s crashed", run_id)
        store = state.runner.store
        run = store.get(run_id)
        if run.status.active:
            # A Build only reads and plans, so there's nothing to undo; anything else may have left changes.
            status = RunStatus.FAILED if run.mode == "build" else RunStatus.ROLLBACK_FAILED
            state.runner.settle(run, status)
            run.status, run.reason, run.next_action = status, f"runner crashed: {e}", None
            store.save(run)
            store.add_event(run_id, "run", f"{run.mode} {run.status}: {run.reason}")
