"""HTTP API over the MaC runner, for the UI. Same Runner, same rules as the CLI.

Every action answers at once: 202 with the run (it has started), 409 with the reason (the
runner refused, e.g. "Run Build first"). The slow work happens on a worker thread; watch it
with GET /runs/{id}/stream (server-sent events) or poll GET /runs/{id}. Full contract:
docs/api.md.

Access: with MAC_API_TOKEN set, every endpoint needs it, as `Authorization: Bearer <token>`
or `?token=<token>` (EventSource can't send headers). In production (APP_ENV=production) the
API refuses to run without one, because the app is public and Deploy changes real AWS.
"""

import asyncio
import json
import logging
import os
import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mac.cli import make_runner
from mac.runner import GateError, Runner
from mac.spec import Spec, SpecError, Step, load_spec, parse_spec
from mac.store import RunRecord, RunStatus
from mac.validate import execution_order, validate

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("mac.api")


@dataclass
class State:
    runner: Runner
    migrations_dir: Path
    submit: Callable[[Callable[[], None]], None]  # runs work in the background
    token: str | None
    require_token: bool


_state: State | None = None


def configure(state: State) -> None:
    """Tests (or a different deployment) can swap in their own runner and settings."""
    global _state
    _state = state


def _default_state() -> State:
    data_dir = Path(os.environ.get("MAC_DATA_DIR", ROOT / ".mac"))  # the same history as `mise run mac`
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mac-run")
    token = os.environ.get("MAC_API_TOKEN") or None
    return State(
        runner=make_runner(data_dir),
        migrations_dir=Path(os.environ.get("MAC_MIGRATIONS_DIR", ROOT / "examples")),
        submit=pool.submit,
        token=token,
        require_token=token is not None or os.environ.get("APP_ENV") == "production",
    )


def get_state() -> State:
    global _state
    if _state is None:
        state = _default_state()
        for run_id in state.runner.recover():  # work queued before a restart
            state.submit(lambda r=run_id: _execute(state, r))
        _state = state
    return _state


def authorized(state: State = Depends(get_state), authorization: str | None = Header(default=None),
               token: str | None = Query(default=None)) -> None:
    if not state.require_token:
        return
    if state.token is None:
        raise HTTPException(503, "The MaC API is off here until MAC_API_TOKEN is set")
    given = authorization.removeprefix("Bearer ").strip() if authorization else token
    if not given or not secrets.compare_digest(given, state.token):
        raise HTTPException(401, "Missing or wrong MaC API token")


router = APIRouter(prefix="/api/mac", tags=["mac"], dependencies=[Depends(authorized)])

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
    page = store.design(name)
    return {
        "name": name, "service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
        "target": spec.target.model_dump(mode="json"), "diagnostics_default": spec.diagnostics.mode,
        "stages": _stages(spec), "approvals": approvals,
        "design_page": {"url": page.url, "current": page.digest == spec.digest()} if page else None,
        "issues": problems, "latest": _latest(state, name), "active_run": _summary(active),
    }


def _start(state: State, starter: Callable[[], RunRecord]) -> dict:
    try:
        run = starter()
    except GateError as e:
        raise HTTPException(409, str(e)) from e
    state.submit(lambda: _execute(state, run.id))
    return _run_view(run)


@router.post("/migrations/{name}/build", status_code=202)
def build(name: str, body: StartBody | None = None, state: State = Depends(get_state)):
    path, _, _ = _migration(state, name)
    return _start(state, lambda: state.runner.start_build(path, (body or StartBody()).branches))


@router.post("/migrations/{name}/rehearse", status_code=202)
def rehearse(name: str, body: StartBody | None = None, state: State = Depends(get_state)):
    path, _, _ = _migration(state, name)
    body = body or StartBody()
    return _start(state, lambda: state.runner.start_rehearse(path, body.ai, body.branches))


@router.post("/migrations/{name}/deploy", status_code=202)
def deploy(name: str, body: StartBody | None = None, state: State = Depends(get_state)):
    path, _, _ = _migration(state, name)
    body = body or StartBody()
    if body.branches:
        raise HTTPException(409, "Deploy always runs main; branches are only for Build and Rehearse")
    return _start(state, lambda: state.runner.start_deploy(path, body.ai))


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
    return _run_view(_get_run(state, run_id))


@router.post("/runs/{run_id}/steps/{step_id}/play", status_code=202)
def play(run_id: str, step_id: str, state: State = Depends(get_state)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_play(run_id, step_id))


@router.post("/runs/{run_id}/resume", status_code=202)
def resume(run_id: str, state: State = Depends(get_state)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_resume(run_id))


@router.post("/runs/{run_id}/undo", status_code=202)
def undo(run_id: str, state: State = Depends(get_state)):
    _get_run(state, run_id)
    return _start(state, lambda: state.runner.request_undo(run_id))


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
            batch = store.events(run_id, after=cursor)
            for event in batch:
                cursor = event.seq
                yield f"id: {event.seq}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
            if batch:
                idle = 0.0
            elif not store.get(run_id).status.active:
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
            run.status, run.reason, run.next_action = RunStatus.ROLLBACK_FAILED, f"runner crashed: {e}", None
            store.save(run)
            store.add_event(run_id, "run", f"{run.mode} {run.status}: {run.reason}")
