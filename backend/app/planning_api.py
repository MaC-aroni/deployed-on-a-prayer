"""Planning endpoints for the console: the knowledge graph and the Planner over HTTP.

Kept apart from mac_api.py on purpose (the runner API's module): this imports the runner API's
state and helpers and changes none of them. Plans and ingests are ordinary runs (modes "plan"
and "ingest"), so the console follows them with the same GET /runs/{id}, /events and /stream
it already uses. Contract: docs/planning-api.md.

Access is the same as the runner API's: GETs are open, POSTs need the GitHub sign-in on Fly.
"""

import logging
import os
import re
import time
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mac import agents_cli
from mac.graph import Graph, extract
from mac.integrations import GitHubAPI, IntegrationError, _request, open_pull_request
from mac.knowledge import KnowledgeError, load_pages
from mac.llm import LLM
from mac.planner import plan, pr_body
from mac.spec import Spec, SpecError, load_spec
from mac.store import RunRecord, RunStatus
from mac.validate import validate

from . import mac_api
from .auth import signed_in

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("mac.planning")

KNOWLEDGE_STEP = "knowledge"
PLAN_STEP = "plan"


GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


@dataclass
class Planning:
    llm_factory: Callable[[], LLM] | None  # None: no LLM configured here
    knowledge_dir: Path
    repo_lister: Callable[[], list[dict]] | None = None  # None: GitHub, the org of MAC_GITHUB_REPO


_config: Planning | None = None


def configure(config: Planning | None) -> None:
    """Tests swap in a scripted LLM and a knowledge dir."""
    global _config
    _config = config


def _default_config() -> Planning:
    has_key = bool(os.environ.get("MAC_LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY"))
    return Planning(
        llm_factory=agents_cli._llm if has_key else None,
        knowledge_dir=Path(os.environ.get("MAC_KNOWLEDGE_DIR", ROOT / "demo-data" / "confluence")),
    )


def get_config() -> Planning:
    global _config
    if _config is None:
        _config = _default_config()
    return _config


def _llm(config: Planning) -> LLM:
    if config.llm_factory is None:
        raise HTTPException(409, "No LLM is configured here: set MAC_LLM_API_KEY (or NVIDIA_API_KEY), "
                                 "MAC_LLM_BASE_URL and MAC_LLM_MODEL (see docs/cloud-setup.md)")
    try:
        return config.llm_factory()
    except SystemExit as e:  # agents_cli._llm exits when the key is missing
        raise HTTPException(409, str(e)) from e


router = APIRouter(prefix="/api/mac", tags=["planning"])


# ---- Shared bits -----------------------------------------------------------------------------


class PlanBody(BaseModel):
    service: str | None = None
    goal: str | None = None
    pr: bool = False  # also open a PR into MAC_MIGRATIONS_REPO


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "plan"


def _graph_path(state: mac_api.State) -> Path:
    return state.runner.data_dir / "graph.json"


def _plans_dir(state: mac_api.State) -> Path:
    return state.runner.data_dir / "plans"


def _load_graph(state: mac_api.State) -> Graph | None:
    path = _graph_path(state)
    if not path.exists():
        return None
    return Graph.from_json(path.read_text(encoding="utf-8"))


def _new_run(state: mac_api.State, mode: str, migration: str) -> RunRecord:
    run = RunRecord(migration=migration, mode=mode, spec_path="", spec_digest="", spec_text="",
                    status=RunStatus.RUNNING)
    state.runner.store.save(run)
    return run


def _refuse_if_active(state: mac_api.State, migration: str, what: str) -> None:
    active = next((r for r in state.runner.store.runs(migration) if r.status.active), None)
    if active is not None:
        raise HTTPException(409, f"{what} {active.id} is still running. Wait for it to finish.")


def _finish(state: mac_api.State, run: RunRecord, status: RunStatus, reason: str) -> None:
    run.status, run.reason = status, reason
    state.runner.store.save(run)
    state.runner.store.add_event(run.id, "run", f"{run.mode} {status}: {reason}")


class _Observed:
    """Wraps the LLM so every call shows up live as an attempt card."""

    def __init__(self, llm: LLM, emit: Callable[[str, str, str | None], None]):
        self.llm, self.emit, self.n = llm, emit, 0

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        self.n += 1
        self.emit("step", f"attempt-{self.n}: running, asking the model for a migration.yaml", f"attempt-{self.n}")
        return self.llm.complete(system, user, max_tokens=max_tokens)


def _knowledge(state: mac_api.State, config: Planning, llm: LLM, emit) -> tuple[list, Graph]:
    """The knowledge base's sections, and the graph (ingested now if there isn't one yet)."""
    sections = agents_cli._sections(state.runner, config.knowledge_dir)
    graph = _load_graph(state)
    if graph is not None:
        emit("step", f"knowledge: graph loaded, {len(graph.nodes)} facts and {len(graph.edges)} relations",
             KNOWLEDGE_STEP)
        return sections, graph
    emit("step", "knowledge: no graph yet, reading the knowledge base first", KNOWLEDGE_STEP)
    graph, dropped = extract(sections, llm, log=lambda m: emit("log", m, KNOWLEDGE_STEP))
    graph.save(_graph_path(state))
    for reason in dropped:
        emit("log", f"dropped: {reason}", KNOWLEDGE_STEP)
    emit("step", f"knowledge: {len(graph.nodes)} facts, {len(graph.edges)} relations"
                 + (f", {len(dropped)} dropped" if dropped else ""), KNOWLEDGE_STEP)
    return sections, graph


# ---- Ingest ----------------------------------------------------------------------------------


def _execute_ingest(state: mac_api.State, config: Planning, run_id: str, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    try:
        sections = agents_cli._sections(state.runner, config.knowledge_dir)
        pages = len({s.doc_id for s in sections})
        emit("step", f"knowledge: reading {pages} pages from {config.knowledge_dir.name}", KNOWLEDGE_STEP)
        graph, dropped = extract(sections, llm, log=lambda m: emit("log", m, KNOWLEDGE_STEP))
        graph.save(_graph_path(state))
        for reason in dropped:
            emit("log", f"dropped: {reason}", KNOWLEDGE_STEP)
        run.report = {"nodes": len(graph.nodes), "edges": len(graph.edges), "dropped": len(dropped),
                      "services": sorted(graph.names("service"))}
        emit("step", f"knowledge: {len(graph.nodes)} facts, {len(graph.edges)} relations", KNOWLEDGE_STEP)
        _finish(state, run, RunStatus.SUCCEEDED,
                f"{len(graph.nodes)} facts and {len(graph.edges)} relations from {pages} pages")
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        log.exception("ingest %s failed", run_id)
        emit("step", f"knowledge: failed: {e}", KNOWLEDGE_STEP)
        _finish(state, run, RunStatus.FAILED, f"ingest failed: {e}")


@router.post("/ingest", status_code=202)
def ingest(state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
           user: str | None = Depends(signed_in)):
    llm = _llm(config)
    _refuse_if_active(state, "knowledge", "ingest")
    run = _new_run(state, "ingest", "knowledge")
    state.runner.store.add_event(run.id, "run", "Ingest started: building the knowledge graph"
                                 + (f" (requested by @{user})" if user else ""))
    state.submit(lambda: _execute_ingest(state, config, run.id, llm))
    return mac_api._run_view(run)


# ---- Services --------------------------------------------------------------------------------


def _org() -> str:
    return os.environ.get("MAC_GITHUB_REPO", "MaC-aroni/deployed-on-a-prayer").split("/")[0]


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


_repo_cache: dict = {"at": 0.0, "repos": None}


def _github_repos() -> list[dict]:
    """Every repo in the org, newest push first. Cached for a minute to stay inside rate limits."""
    if _repo_cache["repos"] is not None and time.time() - _repo_cache["at"] < 60:
        return _repo_cache["repos"]
    headers = dict(GITHUB_HEADERS)
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    reply = _request(f"{GITHUB_API}/orgs/{_org()}/repos?per_page=100&sort=pushed", headers) or []
    repos = [{"name": r["name"], "full_name": r["full_name"], "url": r.get("html_url"),
              "description": r.get("description"), "pushed_at": _epoch(r.get("pushed_at")),
              "archived": bool(r.get("archived"))} for r in reply]
    _repo_cache.update(at=time.time(), repos=repos)
    return repos


def _knowledge_services(config: Planning) -> tuple[list[dict], int]:
    """Services the knowledge base documents (pages labelled `service`), with the repos each
    page mentions. No model call: this is what the Migrate page shows before anything is learned."""
    try:
        pages = load_pages(config.knowledge_dir)
    except (KnowledgeError, OSError):
        return [], 0
    repo_re = re.compile(rf"{re.escape(_org())}/[A-Za-z0-9_-]+", re.I)
    out = []
    for page in pages:
        if "service" not in {label.lower() for label in page.labels}:
            continue
        name = page.title.split(":", 1)[1].strip() if ":" in page.title else page.title.strip()
        repos = sorted({m.group(0) for m in repo_re.finditer(page.body)}, key=str.lower)
        description = next((line.strip() for line in page.body.splitlines()
                            if line.strip() and not line.lstrip().startswith(("#", "-", "|", "*", "```"))), "")
        first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0]  # the first sentence reads best on a card
        description = first if len(first) <= 160 else description[:157].rstrip() + "…"
        out.append({"name": name, "page": page.id, "team": page.owner or None, "description": description,
                    "repos": repos, "approvers": [], "sources": [], "learned": False})
    return out, len(pages)


def _service_view(graph: Graph, node, plans_by_service: dict[str, list[str]]) -> dict:
    near = graph.neighbors(node.key, depth=1)
    wider = graph.neighbors(node.key, depth=2)
    repos = sorted({n.name for n in near.nodes.values() if n.type == "repo"}, key=str.lower)
    teams = sorted({graph.nodes[e.source].name for e in graph.edges
                    if e.type == "owns" and e.target == node.key and e.source in graph.nodes})
    approvers = sorted({n.name.strip("`") for n in wider.nodes.values() if n.type == "approver"})
    return {"name": node.name, "page": None, "description": node.description, "team": teams[0] if teams else None,
            "repos": repos, "approvers": approvers, "sources": node.sources, "learned": True,
            "plans": plans_by_service.get(node.name.lower(), [])}


@router.get("/services")
def services(state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config)):
    """What can be migrated: the knowledge base's services (always), enriched by the graph once
    it's learned, plus every repo in the org so nothing is hidden."""
    plans_by_service: dict[str, list[str]] = {}
    for run_id, spec in _generated(state):
        plans_by_service.setdefault(spec.metadata.service.lower(), []).append(run_id)

    base, page_count = _knowledge_services(config)
    by_name = {s["name"].lower(): s for s in base}
    graph = _load_graph(state)
    if graph is not None:
        for node in graph.nodes.values():
            if node.type != "service":
                continue
            view = _service_view(graph, node, plans_by_service)
            cur = by_name.get(node.name.lower())
            if cur is None:
                by_name[node.name.lower()] = view
                continue
            cur.update(learned=True, approvers=view["approvers"], sources=view["sources"],
                       repos=sorted(set(cur["repos"]) | set(view["repos"]), key=str.lower),
                       team=cur["team"] or view["team"], description=cur["description"] or view["description"])
    for svc in by_name.values():
        svc["plans"] = plans_by_service.get(svc["name"].lower(), [])

    repos, repos_error = [], None
    try:
        repos = [dict(r) for r in (config.repo_lister or _github_repos)()]
    except IntegrationError as e:
        repos_error = str(e)
    owner_of = {repo.lower(): svc["name"] for svc in by_name.values() for repo in svc["repos"]}
    for repo in repos:
        repo["service"] = owner_of.get(repo["full_name"].lower())

    return {"ingested": graph is not None,
            "graph_updated": _graph_path(state).stat().st_mtime if graph is not None else None,
            "knowledge": {"pages": page_count, "dir": config.knowledge_dir.name},
            "services": sorted(by_name.values(), key=lambda s: s["name"].lower()),
            "repos": repos, "repos_error": repos_error}


# ---- Plan ------------------------------------------------------------------------------------


def _execute_plan(state: mac_api.State, config: Planning, run_id: str, goal: str, pr: bool, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    try:
        sections, graph = _knowledge(state, config, llm, emit)
        observed = _Observed(llm, emit)
        result = plan(goal, graph, sections, observed,
                      log=lambda m: emit("step", m.replace("attempt ", "attempt-", 1), f"attempt-{observed.n}"))
        for n, problems in enumerate(result.history, 1):
            for problem in problems:
                emit("log", problem, f"attempt-{n}")
        if not result.ok:
            run.report = {"iterations": result.iterations, "problems": result.problems}
            emit("step", f"plan: not valid after {result.iterations} attempt(s)", PLAN_STEP)
            _finish(state, run, RunStatus.FAILED,
                    f"the planner couldn't produce a valid migration.yaml in {result.iterations} attempt(s)")
            return
        spec = result.spec
        out = _plans_dir(state) / run_id / "migration.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.yaml + "\n", encoding="utf-8")
        run.spec_text, run.spec_path, run.spec_digest = result.yaml, str(out), spec.digest()
        run.report = {"plan": run_id, "name": spec.metadata.name, "service": spec.metadata.service,
                      "iterations": result.iterations, "steps": len(spec.steps), "approvals": len(spec.approvals)}
        emit("step", f"plan: migration.yaml written, {len(spec.steps)} steps and {len(spec.approvals)} approvals"
                     f" in {result.iterations} attempt(s)", PLAN_STEP)
        if pr:
            try:
                api = GitHubAPI(os.environ.get("GITHUB_TOKEN"))
                name = spec.metadata.name
                url = open_pull_request(api, agents_cli.MIGRATIONS_REPO, "main", f"mac/plan/{name}-{int(time.time())}",
                                        {f"migrations/{name}/migration.yaml": result.yaml + "\n"},
                                        f"Plan: {spec.metadata.service} ({name})", pr_body(result, goal, sections),
                                        f"Plan {name} with MaC's planner")
                run.report["pr_url"] = url
                emit("step", f"plan: opened {url}", PLAN_STEP)
            except IntegrationError as e:
                emit("log", f"PR not opened: {e}", PLAN_STEP)
        _finish(state, run, RunStatus.SUCCEEDED, f"valid after {result.iterations} attempt(s)")
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        log.exception("plan %s failed", run_id)
        emit("step", f"plan: failed: {e}", PLAN_STEP)
        _finish(state, run, RunStatus.FAILED, f"planner failed: {e}")


@router.post("/plan", status_code=202)
def start_plan(body: PlanBody, state: mac_api.State = Depends(mac_api.get_state),
               config: Planning = Depends(get_config), user: str | None = Depends(signed_in)):
    goal = (body.goal or "").strip() or (f"Migrate {body.service.strip()} to AWS" if body.service else "")
    if not goal:
        raise HTTPException(422, "Say which service to migrate, or give a goal")
    llm = _llm(config)
    migration = f"plan/{_slug(goal)}"
    _refuse_if_active(state, migration, "plan")
    run = _new_run(state, "plan", migration)
    state.runner.store.add_event(run.id, "run", f"Planning started: {goal}" + (f" (requested by @{user})" if user else ""))
    state.submit(lambda: _execute_plan(state, config, run.id, goal, body.pr, llm))
    return mac_api._run_view(run)


# ---- Generated plans -------------------------------------------------------------------------


def _generated(state: mac_api.State) -> list[tuple[str, Spec]]:
    """(run id, spec) for every generated plan on disk, newest first; unreadable ones are skipped."""
    out = []
    for path in sorted(_plans_dir(state).glob("*/migration.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append((path.parent.name, load_spec(path)))
        except SpecError:
            continue
    return out


def _plan_file(state: mac_api.State, run_id: str) -> tuple[Path, Spec]:
    path = _plans_dir(state) / run_id / "migration.yaml"
    if not path.is_file():
        raise HTTPException(404, f"no generated plan {run_id!r}")
    try:
        return path, load_spec(path)
    except SpecError as e:
        raise HTTPException(409, "the generated migration.yaml can't be read: " + "; ".join(e.problems)) from e


def _plan_run(state: mac_api.State, run_id: str) -> RunRecord | None:
    try:
        return state.runner.store.get(run_id)
    except KeyError:
        return None  # history wiped, file kept


@router.get("/plans")
def list_plans(state: mac_api.State = Depends(mac_api.get_state)):
    result = []
    for run_id, spec in _generated(state):
        run = _plan_run(state, run_id)
        name = spec.metadata.name
        result.append({
            "run_id": run_id, "name": name, "service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
            "stages": list(spec.stages), "created": run.created if run else (_plans_dir(state) / run_id).stat().st_mtime,
            "goal": run.migration.removeprefix("plan/") if run else None,
            "iterations": (run.report or {}).get("iterations") if run else None,
            "pr_url": (run.report or {}).get("pr_url") if run else None,
            "valid": not any(str(i).startswith("error") for i in validate(spec)),
            "latest": mac_api._latest(state, name),
        })
    return result


@router.get("/plans/{run_id}")
def get_plan(run_id: str, state: mac_api.State = Depends(mac_api.get_state)):
    _, spec = _plan_file(state, run_id)
    store = state.runner.store
    name = spec.metadata.name
    run = _plan_run(state, run_id)
    active = next((r for r in store.runs(name) if r.status.active), None)
    tickets = store.tickets(name, spec.digest())
    approvals = [a.model_dump(mode="json") | {"ticket": (t := tickets.get(a.id)) and t.model_dump(exclude={"approval"})}
                 for a in spec.approvals]
    page = store.design(name)
    return {
        "name": name, "service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
        "target": spec.target.model_dump(mode="json"), "diagnostics_default": spec.diagnostics.mode,
        "stages": mac_api._stages(spec), "approvals": approvals,
        "design_page": {"url": page.url, "current": page.digest == spec.digest()} if page else None,
        "issues": [str(i) for i in validate(spec)], "latest": mac_api._latest(state, name),
        "active_run": mac_api._summary(active),
        "source": "generated", "plan_run": run_id, "goal": run.migration.removeprefix("plan/") if run else None,
        "pr_url": (run.report or {}).get("pr_url") if run else None, "yaml": spec_text(run, state, run_id),
    }


def spec_text(run: RunRecord | None, state: mac_api.State, run_id: str) -> str:
    if run and run.spec_text:
        return run.spec_text
    return (_plans_dir(state) / run_id / "migration.yaml").read_text(encoding="utf-8")


@router.post("/plans/{run_id}/build", status_code=202)
def plan_build(run_id: str, body: mac_api.StartBody | None = None, state: mac_api.State = Depends(mac_api.get_state),
               user: str | None = Depends(signed_in)):
    path, _ = _plan_file(state, run_id)
    return mac_api._start(state, lambda: state.runner.start_build(path, (body or mac_api.StartBody()).branches), user)


@router.post("/plans/{run_id}/rehearse", status_code=202)
def plan_rehearse(run_id: str, body: mac_api.StartBody | None = None,
                  state: mac_api.State = Depends(mac_api.get_state), user: str | None = Depends(signed_in)):
    path, _ = _plan_file(state, run_id)
    body = body or mac_api.StartBody()
    return mac_api._start(state, lambda: state.runner.start_rehearse(path, body.ai, body.branches), user)


@router.post("/plans/{run_id}/deploy", status_code=202)
def plan_deploy(run_id: str, body: mac_api.StartBody | None = None,
                state: mac_api.State = Depends(mac_api.get_state), user: str | None = Depends(signed_in)):
    path, _ = _plan_file(state, run_id)
    body = body or mac_api.StartBody()
    if body.branches:
        raise HTTPException(409, "Deploy always runs main; branches are only for Build and Rehearse")
    return mac_api._start(state, lambda: state.runner.start_deploy(path, body.ai), user)
