"""Planning endpoints for the console: the knowledge graph, the Planner, and the Diagnostician
over HTTP.

Kept apart from mac_api.py on purpose (the runner API's module): this imports the runner API's
state and helpers and changes none of them. Plans, ingests, learns and investigations are
ordinary runs (modes "plan", "ingest" and "diagnose"), so the console follows them with the same
GET /runs/{id}, /events and /stream it already uses. Contract: docs/planning-api.md.

Every agent here narrates itself with `agent` events: one JSON message per observation,
reasoning, action or outcome, naming the agent and the agent that directed it. The console draws
them as the agent hierarchy (a Director, its workers, a Compiler).

Access is the same as the runner API's: GETs are open, POSTs need the GitHub sign-in on Fly.
"""

import base64
import dataclasses
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mac import agents_cli, cli as mac_cli, describe
from mac.graph import Graph, extract
from mac.integrations import GitHubAPI, IntegrationError, TicketRequest, _request, open_pull_request, read_files
from mac.knowledge import KnowledgeError, KnowledgePage, load_pages, publish
from mac.knowledge import render as render_page
from mac.llm import LLM, describe_providers, parse_json, providers as llm_providers, set_provider
from mac.planner import plan, pr_body
from mac.runner import GateError
from mac.sources import sections_from_pages
from mac.spec import Spec, SpecError, load_spec, parse_spec
from mac.store import RunRecord, RunStatus
from mac.validate import validate

from . import mac_api
from .auth import signed_in

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("mac.planning")

KNOWLEDGE_STEP = "knowledge"
DETECT_STEP = "detect"
PLAN_STEP = "plan"
DESCRIBE_STEP = "describe"

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


@dataclass
class Planning:
    llm_factory: Callable[[], LLM] | None  # None: no LLM configured here
    knowledge_dir: Path
    repo_lister: Callable[[], list[dict]] | None = None  # None: GitHub, the org of MAC_GITHUB_REPO
    repo_reader: Callable[[str], dict] | None = None  # slug -> README, file list, description (None: GitHub)
    code_reader: Callable[[str, str, str], dict[str, str]] | None = None  # (slug, sha, prefix) -> files
    pr_opener: Callable[..., str] | None = None  # open_pull_request's arguments, minus the api -> PR url
    repo_meta_reader: Callable[[str], dict] | None = None  # slug -> {"repo": GitHub repo json, "license": {...} | None}


_config: Planning | None = None


def configure(config: Planning | None) -> None:
    """Tests swap in a scripted LLM and a knowledge dir."""
    global _config
    _config = config


def _default_config() -> Planning:
    return Planning(
        llm_factory=agents_cli._llm if llm_providers() else None,
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "plan"


def _org() -> str:
    return os.environ.get("MAC_GITHUB_REPO", "MaC-aroni/deployed-on-a-prayer").split("/")[0]


def _gh_headers() -> dict[str, str]:
    headers = dict(GITHUB_HEADERS)
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return headers


def _graph_path(state: mac_api.State) -> Path:
    return state.runner.data_dir / "graph.json"


def _plans_dir(state: mac_api.State) -> Path:
    return state.runner.data_dir / "plans"


def _generated_dir(state: mac_api.State) -> Path:
    """Knowledge pages MaC wrote itself (Learn, Describe), beside the hand-written knowledge base."""
    return mac_api.generated_dir(state)


def _fixes_dir(state: mac_api.State) -> Path:
    return state.runner.data_dir / "fixes"


def _load_graph(state: mac_api.State) -> Graph | None:
    path = _graph_path(state)
    if not path.exists():
        return None
    return Graph.from_json(path.read_text(encoding="utf-8"))


def _new_run(state: mac_api.State, mode: str, migration: str, spec_text: str = "", based_on: str | None = None) -> RunRecord:
    run = RunRecord(migration=migration, mode=mode, spec_path="", spec_digest="", spec_text=spec_text,
                    status=RunStatus.RUNNING, based_on=based_on)
    state.runner.store.save(run)
    return run


def _refuse_if_active(state: mac_api.State, migration: str, what: str, mode: str | None = None) -> None:
    active = next((r for r in state.runner.store.runs(migration)
                   if r.status.active and (mode is None or r.mode == mode)), None)
    if active is not None:
        raise HTTPException(409, f"{what} {active.id} is still running. Wait for it to finish.")


def _finish(state: mac_api.State, run: RunRecord, status: RunStatus, reason: str) -> None:
    run.status, run.reason = status, reason
    state.runner.store.save(run)
    state.runner.store.add_event(run.id, "run", f"{run.mode} {status}: {reason}")


def _model_name(llm: LLM) -> str | None:
    return getattr(llm, "model", None) or os.environ.get("MAC_LLM_MODEL")


class Cancelled(Exception):
    """Someone pressed Cancel on an agent run: raised before the next model call."""


class _Cancellable:
    """The agent's LLM, checking for a Cancel before every call. Agent runs change nothing that
    needs undoing (they write files and open PRs only at the very end), so stopping between model
    calls is a clean stop."""

    def __init__(self, llm, store, run_id: str):
        self.llm, self.store, self.run_id = llm, store, run_id

    @property
    def model(self):
        return getattr(self.llm, "model", None)

    def _check(self) -> None:
        if self.store.cancel_requested(self.run_id):
            raise Cancelled()

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        self._check()
        return self.llm.complete(system, user, max_tokens=max_tokens)

    def chat(self, messages, tools=None, *, max_tokens: int = 2048):
        self._check()
        return self.llm.chat(messages, tools, max_tokens=max_tokens)


def _cancellable(state: mac_api.State, run_id: str, llm):
    return None if llm is None else _Cancellable(llm, state.runner.store, run_id)


def _cancelled(state: mac_api.State, run: RunRecord, e: Exception, emit, trace: "_Trace") -> bool:
    """True when the failure was a Cancel: the run ends as cancelled, not failed."""
    if not isinstance(e, Cancelled):
        return False
    state.runner.store.clear_cancel(run.id)
    emit("step", f"{trace.step}: cancelled", trace.step)
    trace("director", "outcome", "cancelled: stopped before the next step", status="failed")
    _finish(state, run, RunStatus.CANCELLED, "cancelled")
    return True


class _Trace:
    """Agent events for one run: `kind: "agent"`, the message a JSON object the console draws
    as the agent hierarchy. `parent` is the agent that directed this one; `status` moves the
    agent's card; `phase` is observation | reasoning | action | outcome."""

    def __init__(self, state: mac_api.State, run_id: str, step: str, model: str | None):
        self.store, self.run_id, self.step, self.model = state.runner.store, run_id, step, model

    def __call__(self, agent: str, phase: str, text: str, *, parent: str | None = None, role: str | None = None,
                 status: str | None = None, model: str | None = None, step: str | None = None) -> None:
        payload = {"agent": agent, "parent": parent, "role": role, "phase": phase, "text": text,
                   "status": status, "model": model}
        self.store.add_event(self.run_id, "agent", json.dumps({k: v for k, v in payload.items() if v is not None}),
                             step or self.step)


# ---- The knowledge base: hand-written pages plus the ones MaC learned --------------------------


def _parse_generated(path: Path) -> KnowledgePage | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return None
    head, body = text[4:].split("\n---\n", 1)
    meta = yaml.safe_load(head) or {}
    if not meta.get("id") or not meta.get("title"):
        return None
    return KnowledgePage(id=str(meta["id"]), title=str(meta["title"]), body=body.strip(), parent=meta.get("parent"),
                         owner=str(meta.get("owner", "")), labels=tuple(meta.get("labels") or ()), source=path.name)


def _generated_pages(state: mac_api.State) -> list[KnowledgePage]:
    folder = _generated_dir(state)
    if not folder.is_dir():
        return []
    pages = [_parse_generated(p) for p in sorted(folder.glob("*.md"))]
    return [p for p in pages if p is not None]


def _generated_meta(state: mac_api.State, page_id: str) -> dict:
    """The sidecar written by Learn: repo, review ticket, run id."""
    path = _generated_dir(state) / f"{page_id}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_generated_meta(state: mac_api.State, page_id: str, meta: dict) -> None:
    folder = _generated_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{page_id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _set_page_labels(state: mac_api.State, page_id: str, drop: str, add: str) -> None:
    """Rewrite a generated page's front-matter labels (e.g. needs-review → reviewed)."""
    path = _generated_dir(state) / f"{page_id}.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return
    head, body = text[4:].split("\n---\n", 1)
    meta = yaml.safe_load(head) or {}
    labels = [label for label in (meta.get("labels") or []) if label != drop]
    if add not in labels:
        labels.append(add)
    meta["labels"] = labels
    path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n" + body, encoding="utf-8")


_review_cache: dict[str, tuple[float, str | None]] = {}


def _review_state(state: mac_api.State, page_id: str, meta: dict) -> dict:
    """The sidecar plus the effective review `status`: what Jira says about the ticket when
    there is one (asked at most every 30 s), else what a person set in the console, else pending."""
    status = meta.get("review_status") or "pending"
    ticket = meta.get("ticket")
    if ticket and not isinstance(state.runner.approvals, mac_cli._NoJira) and status == "pending":
        cached = _review_cache.get(page_id)
        if cached and time.time() - cached[0] < 30:
            jira = cached[1]
        else:
            try:
                jira = str(getattr(state.runner.approvals.status(ticket), "value", state.runner.approvals.status(ticket)))
            except IntegrationError:
                jira = None
            _review_cache[page_id] = (time.time(), jira)
        if jira in ("approved", "rejected"):
            status = jira
            meta = {**meta, "review_status": jira, "reviewed_by": "jira", "reviewed_at": time.time()}
            _save_generated_meta(state, page_id, meta)
            if jira == "approved":
                _set_page_labels(state, page_id, "needs-review", "reviewed")
    return {**meta, "status": status}


def _base_pages(config: Planning) -> list[KnowledgePage]:
    try:
        return load_pages(config.knowledge_dir)
    except (KnowledgeError, OSError):
        return []


def _all_pages(state: mac_api.State, config: Planning) -> list[KnowledgePage]:
    base = _base_pages(config)
    known = {p.id for p in base}
    return base + [p for p in _generated_pages(state) if p.id not in known]


def _urls(state: mac_api.State, pages: list[KnowledgePage] | None = None) -> dict[str, str]:
    """Our page id -> Confluence URL, from the publish record. When Confluence is configured and
    a page has no record (published from another machine, or by hand), ask Confluence for a page
    with that title, at most every 10 minutes, and remember what it says."""
    urls = {page: url for page, (_, url, _) in state.runner.store.knowledge_pages().items()}
    for page in pages or []:
        if page.id not in urls:
            url = mac_api.lookup_confluence_page(state, page.id, page.title)
            if url:
                urls[page.id] = url
    return urls


def _sections(state: mac_api.State, config: Planning):
    return sections_from_pages(_all_pages(state, config), _urls(state))


def _reviewed_for(state: mac_api.State, service: str | None) -> tuple[str, Path] | None:
    """A reviewed migration.yaml (examples/) for this service, if one exists."""
    if not service:
        return None
    for name, (path, spec, _) in mac_api._find(state).items():
        if spec is not None and spec.metadata.service.lower() == service.lower():
            return name, path
    return None


@router.get("/knowledge/{page_id}")
def knowledge_page(page_id: str, state: mac_api.State = Depends(mac_api.get_state),
                   config: Planning = Depends(get_config)):
    """One knowledge-base page, for the console to show when there's no Confluence to link to."""
    page = next((p for p in _all_pages(state, config) if p.id == page_id), None)
    if page is None:
        raise HTTPException(404, f"no knowledge page {page_id!r}")
    return _page_view(state, page)


def _page_view(state: mac_api.State, page: KnowledgePage) -> dict:
    generated = "generated" in {label.lower() for label in page.labels}
    meta = _generated_meta(state, page.id)
    review = _review_state(state, page.id, meta) if generated else None
    if generated:  # the Jira readback may have just rewritten the labels on disk
        page = _parse_generated(_generated_dir(state) / f"{page.id}.md") or page
    return {"id": page.id, "title": page.title, "body": page.body, "parent": page.parent, "owner": page.owner,
            "labels": list(page.labels), "source": page.source, "url": _urls(state, [page]).get(page.id),
            "generated": generated, "review": review}


class ReviewBody(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = None


@router.post("/knowledge/{page_id}/review")
def review_knowledge_page(page_id: str, body: ReviewBody, state: mac_api.State = Depends(mac_api.get_state),
                          config: Planning = Depends(get_config), user: str | None = Depends(signed_in)):
    """The manual sign-off on a page MaC wrote: approved pages lose their needs-review label
    and count as documentation; rejected ones stay drafts until Learn rewrites them."""
    page = next((p for p in _all_pages(state, config) if p.id == page_id), None)
    if page is None:
        raise HTTPException(404, f"no knowledge page {page_id!r}")
    if "generated" not in {label.lower() for label in page.labels}:
        raise HTTPException(409, "only pages MaC wrote are reviewed here; hand-written pages are reviewed in Confluence")
    meta = {**_generated_meta(state, page_id), "review_status": body.status, "reviewed_by": user or "console",
            "reviewed_at": time.time(), "note": body.note}
    _save_generated_meta(state, page_id, meta)
    _review_cache.pop(page_id, None)
    if body.status == "approved":
        _set_page_labels(state, page_id, "needs-review", "reviewed")
    else:
        _set_page_labels(state, page_id, "reviewed", "needs-review")
    page = next(p for p in _all_pages(state, config) if p.id == page_id)
    return _page_view(state, page)


@router.post("/knowledge/{page_id}/publish")
def publish_knowledge_page(page_id: str, state: mac_api.State = Depends(mac_api.get_state),
                           config: Planning = Depends(get_config), user: str | None = Depends(signed_in)):
    """Create (or update) this one page in Confluence and remember its URL, so the console's
    Confluence door opens the real page from now on."""
    page = next((p for p in _all_pages(state, config) if p.id == page_id), None)
    if page is None:
        raise HTTPException(404, f"no knowledge page {page_id!r}")
    if state.runner.pages is None:
        raise HTTPException(409, "Confluence isn't configured here (ATLASSIAN_* and CONFLUENCE_SPACE_KEY)")
    store = state.runner.store
    known = {k: v[0] for k, v in store.knowledge_pages().items()}
    parent_id = known.get(page.parent) if page.parent else None
    try:
        conf_id, url = state.runner.pages.publish(page.title, render_page(page), known.get(page.id), parent_id=parent_id)
    except IntegrationError as e:
        raise HTTPException(409, f"Confluence refused: {e}") from e
    store.save_knowledge_page(page.id, conf_id, url, page.title)
    return {"id": page.id, "url": url, "page_id": conf_id, "published_by": user}


# ---- Ingest: the whole knowledge base into the graph ------------------------------------------


class _PerPage:
    """Wraps the LLM for `extract`, which asks the model once per page in a known order, so each
    Reader's card turns running right before its page is read."""

    def __init__(self, llm: LLM, pages: list[str], trace: _Trace):
        self.llm, self.pages, self.trace, self.n = llm, pages, trace, 0

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        page = self.pages[self.n] if self.n < len(self.pages) else f"page-{self.n + 1}"
        self.n += 1
        self.trace(f"reader:{page}", "action", f"compressing {page} into facts and relations, each cited",
                   parent="director", status="running")
        return self.llm.complete(system, user, max_tokens=max_tokens)


def _references(pages: list[KnowledgePage], graph: Graph) -> list[str]:
    """What the pages name that the graph didn't catch: repositories and services mentioned in
    the text but missing as nodes. Deterministic; the Reviewer's cross-check."""
    repo_re = re.compile(rf"{re.escape(_org())}/[A-Za-z0-9_-]+", re.I)
    named = {m.group(0) for p in pages for m in repo_re.finditer(p.body)}
    known = {n.name.lower() for n in graph.nodes.values() if n.type == "repo"}
    missing_repos = sorted(r for r in named if r.lower() not in known)
    services = [p.title.split(":", 1)[1].strip() for p in pages if ":" in p.title and "service" in {x.lower() for x in p.labels}]
    missing_services = sorted(s for s in services if graph.find(s) is None)
    return [f"repository {r} is named in the pages but has no node" for r in missing_repos] + \
           [f"service {s} has a page but no node" for s in missing_services]


def _extract_with_trace(state, run_id, llm, pages: list[KnowledgePage], sections, emit, trace: _Trace) -> tuple[Graph, list[str]]:
    for page in pages:
        trace(f"reader:{page.id}", "observation", f"will read “{page.title}” ({len(page.body)} chars)",
              parent="director", role="Reader", model=trace.model, status="pending")
    order = list(dict.fromkeys(s.doc_id for s in sections))

    def on_log(message: str) -> None:
        emit("log", message, KNOWLEDGE_STEP)
        if message.startswith("extracted "):
            trace(f"reader:{message[len('extracted '):]}", "outcome", "facts extracted, every one cited to a section",
                  parent="director", status="succeeded")

    graph, dropped = extract(sections, _PerPage(llm, order, trace), log=on_log)
    for doc_id in order:
        if any(d.startswith(f"{doc_id}:") for d in dropped):
            trace(f"reader:{doc_id}", "outcome", "some facts dropped: bad type or missing citation", parent="director",
                  status="succeeded")
    return graph, dropped


def _execute_ingest(state: mac_api.State, config: Planning, run_id: str, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, KNOWLEDGE_STEP, _model_name(llm))
    try:
        pages = _all_pages(state, config)
        sections = sections_from_pages(pages, _urls(state))
        had_graph = _graph_path(state).exists()
        emit("step", f"knowledge: reading {len(pages)} pages from {config.knowledge_dir.name}", KNOWLEDGE_STEP)
        trace("director", "observation", f"{len(pages)} pages in the knowledge base; "
              + ("the graph exists and will be rebuilt" if had_graph else "no graph yet"),
              role="Director", model=trace.model, status="running")
        trace("director", "reasoning", "every page is read by its own Reader so each fact keeps its citation; "
              "References then checks the pages against the graph; the Compiler merges and saves")
        trace("director", "action", f"dispatching {len(pages)} Readers")

        graph, dropped = _extract_with_trace(state, run_id, llm, pages, sections, emit, trace)
        for reason in dropped:
            emit("log", f"dropped: {reason}", KNOWLEDGE_STEP)

        trace("references", "observation", "checking the pages' repositories and services against the graph",
              parent="director", role="References", status="running")
        gaps = _references(pages, graph)
        for gap in gaps:
            emit("log", f"reference check: {gap}", KNOWLEDGE_STEP)
        trace("references", "outcome", "every named repository and service has a node" if not gaps
              else f"{len(gaps)} gap(s): " + "; ".join(gaps[:3]) + (" …" if len(gaps) > 3 else ""),
              parent="director", status="succeeded")

        trace("compiler", "action", f"merging {len(graph.nodes)} facts and {len(graph.edges)} relations into graph.json",
              parent="director", role="Compiler", status="running")
        graph.save(_graph_path(state))
        run.report = {"nodes": len(graph.nodes), "edges": len(graph.edges), "dropped": len(dropped),
                      "services": sorted(graph.names("service")), "gaps": gaps, "pages": len(pages)}
        trace("compiler", "outcome", "graph saved; the Planner reads it next", parent="director", status="succeeded")
        emit("step", f"knowledge: {len(graph.nodes)} facts, {len(graph.edges)} relations", KNOWLEDGE_STEP)
        trace("director", "outcome", f"{len(graph.nodes)} facts, {len(graph.edges)} relations"
              + (f", {len(dropped)} dropped" if dropped else ""), status="succeeded")
        _finish(state, run, RunStatus.SUCCEEDED,
                f"{len(graph.nodes)} facts and {len(graph.edges)} relations from {len(pages)} pages")
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("ingest %s failed", run_id)
        emit("step", f"knowledge: failed: {e}", KNOWLEDGE_STEP)
        trace("director", "outcome", f"failed: {e}", status="failed")
        _finish(state, run, RunStatus.FAILED, f"ingest failed: {e}")


@router.post("/ingest", status_code=202)
def ingest(state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
           user: str | None = Depends(signed_in)):
    llm = _llm(config)
    _refuse_if_active(state, "knowledge", "ingest")
    run = _new_run(state, "ingest", "knowledge")
    llm = _cancellable(state, run.id, llm)
    state.runner.store.add_event(run.id, "run", "Ingest started: building the knowledge graph"
                                 + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_ingest(state, config, run.id, llm))
    return mac_api._run_view(run)


# ---- Learn: a repository nobody documented ----------------------------------------------------


LEARN_PROMPT = """You write a company's internal engineering documentation. From a repository's README,
file list and metadata, describe the service it implements, for the engineers who will migrate it.
Say only what the repository shows; put everything you can't tell under unknowns. Reply with JSON
only:
{"name": "<ServiceName, CamelCase, ending in Service or Tool if it is one>",
 "summary": "<one sentence: what it does>",
 "what_it_does": ["<bullet>", ...],
 "runtime": ["<language/framework>", "<how it runs: container, VM, lambda, cron…>", ...],
 "data": ["<datastore and what it holds; say PII/PHI if the data suggests it>", ...],
 "dependencies": ["<service, repo or API it talks to>", ...],
 "owner": "<team name if the repo says, else null>",
 "unknowns": ["<what a reviewer must fill in>", ...]}"""


class LearnBody(BaseModel):
    repo: str  # "owner/name" or just "name" in the org


def _github_repo(slug: str) -> dict:
    headers = _gh_headers()
    meta = _request(f"{GITHUB_API}/repos/{slug}", headers) or {}
    branch = meta.get("default_branch", "main")
    readme = ""
    try:
        raw = _request(f"{GITHUB_API}/repos/{slug}/readme", headers) or {}
        readme = base64.b64decode(raw.get("content", "")).decode("utf-8", "replace")
    except IntegrationError:
        pass
    files: list[str] = []
    try:
        tree = _request(f"{GITHUB_API}/repos/{slug}/git/trees/{branch}?recursive=1", headers) or {}
        files = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"][:400]
    except IntegrationError:
        pass
    return {"description": meta.get("description") or "", "language": meta.get("language"), "url": meta.get("html_url"),
            "default_branch": branch, "readme": readme[:20000], "files": files}


def _bullets(items) -> str:
    if isinstance(items, str):
        items = [items]
    lines = [f"- {str(i).strip()}" for i in (items or []) if str(i).strip()]
    return "\n".join(lines) if lines else "- (nothing in the repository says)"


def _compose_page(page_id: str, title: str, parent: str | None, owner: str, slug: str, repo: dict, facts: dict,
                  mentions: list[str], today: str) -> str:
    front = {"id": page_id, "title": title, "parent": parent, "owner": owner or _org(),
             "labels": ["service", "generated", "needs-review"]}
    front = {k: v for k, v in front.items() if v is not None}
    body = f"""## What it does

{str(facts.get("summary") or "").strip() or f"{title.split(':', 1)[-1].strip()} lives in {slug}."}

{_bullets(facts.get("what_it_does"))}

## Repositories

- {slug}{': ' + repo['description'] if repo.get('description') else ''}{' (' + repo['url'] + ')' if repo.get('url') else ''}

## Runtime

{_bullets(facts.get("runtime") or ([repo["language"]] if repo.get("language") else []))}

## Data

{_bullets(facts.get("data"))}

## Depends on

{_bullets(facts.get("dependencies"))}

## References

{_bullets([f"mentioned in “{m}”" for m in mentions]) if mentions else "- no other page mentions this repository"}

## Unknowns to review

{_bullets(facts.get("unknowns"))}

_Written by MaC from the repository on {today}. A person reviews it before the Planner relies on it._
"""
    return "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n" + body


def _execute_learn(state: mac_api.State, config: Planning, run_id: str, slug: str, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, KNOWLEDGE_STEP, _model_name(llm))
    name = slug.split("/")[-1]
    try:
        base = _base_pages(config)
        pages = _all_pages(state, config)
        emit("step", f"knowledge: {slug} isn't documented; learning it from the repository", KNOWLEDGE_STEP)
        trace("director", "observation", f"{slug} has no page in the {len(pages)}-page knowledge base",
              role="Director", model=trace.model, status="running")
        trace("director", "reasoning", "a Reader compresses the repository into facts; References checks what the "
              "existing pages and graph already say about it; the Compiler writes the page, merges the graph and "
              "raises a review ticket, because a generated page is a draft until a person signs it off")
        trace("director", "action", "dispatching Reader and References")

        # Reader: the repository, compressed.
        trace("reader", "action", f"reading {slug}: README, file list, language", parent="director", role="Reader",
              model=trace.model, status="running")
        repo = (config.repo_reader or _github_repo)(slug)
        trace("reader", "observation", f"README {len(repo.get('readme') or '')} chars · {len(repo.get('files') or [])} files"
              + (f" · {repo['language']}" if repo.get("language") else ""), parent="director")
        emit("log", f"read {slug}: {len(repo.get('files') or [])} files", KNOWLEDGE_STEP)
        prompt = (f"Repository: {slug}\nDescription: {repo.get('description') or '(none)'}\n"
                  f"Language: {repo.get('language') or '(unknown)'}\n\nFiles:\n"
                  + "\n".join(repo.get("files") or [])[:6000] + f"\n\nREADME:\n{repo.get('readme') or '(none)'}")
        try:
            facts = parse_json(llm.complete(LEARN_PROMPT, prompt, max_tokens=2048))
            if not isinstance(facts, dict):
                raise ValueError("not an object")
        except ValueError as e:
            facts = {"unknowns": [f"the model's reply couldn't be read ({e}); everything about this service"]}
            emit("log", f"reader: unreadable reply, writing a stub page ({e})", KNOWLEDGE_STEP)
        service = str(facts.get("name") or "").strip() or re.sub(r"[^A-Za-z0-9]+", " ", name).title().replace(" ", "")
        trace("reader", "outcome", f"it is {service}: {str(facts.get('summary') or '').strip() or 'summary unknown'}",
              parent="director", status="succeeded")

        # References: what the knowledge base already says.
        trace("references", "action", f"searching {len(pages)} pages and the graph for {name}", parent="director",
              role="References", status="running")
        mentions = [p.title for p in pages if name.lower() in p.body.lower()]
        graph = _load_graph(state)
        known_node = graph.find(slug) if graph else None
        trace("references", "outcome", (f"{len(mentions)} page(s) mention it" if mentions else "no page mentions it")
              + ("; the graph already has a repo node" if known_node else "; nothing in the graph"),
              parent="director", status="succeeded")
        emit("log", f"references: {len(mentions)} mention(s)", KNOWLEDGE_STEP)

        # Compiler: the page, the graph, the ticket.
        trace("compiler", "action", "writing the page and merging its facts into the graph", parent="director",
              role="Compiler", model=trace.model, status="running")
        page_id = f"generated-{_slug(name)}"
        title = f"Services: {service}"
        if any(p.title == title and p.id != page_id for p in pages):
            title += " (generated)"
        root = next((p.id for p in base if not p.parent), None)
        owner = str(facts.get("owner") or "")
        text = _compose_page(page_id, title, root, owner, slug, repo, facts, mentions, date.today().isoformat())
        folder = _generated_dir(state)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{page_id}.md"
        path.write_text(text, encoding="utf-8")
        page = _parse_generated(path)
        emit("log", f"wrote {path.name}", KNOWLEDGE_STEP)

        fragment, dropped = extract(sections_from_pages([page], _urls(state)), llm,
                                    log=lambda m: emit("log", m, KNOWLEDGE_STEP))
        merged = graph or Graph()
        for node in fragment.nodes.values():
            merged.add_node(node)
        have = {(e.source, e.target, e.type) for e in merged.edges}
        for edge in fragment.edges:
            if (edge.source, edge.target, edge.type) not in have:
                merged.edges.append(edge)
        merged.save(_graph_path(state))

        review: dict = {"repo": slug, "page": page_id, "run_id": run_id, "created": time.time(), "service": service}
        try:
            ticket = state.runner.approvals.raise_ticket(TicketRequest(
                approval_id=f"KB-{_slug(name)}", summary=f"Review generated knowledge page: {service}",
                paragraphs=[f"MaC learned {slug} from its repository and wrote the knowledge page “{title}”.",
                            "Please check the facts, fill in the unknowns, and mark this ticket Approved so the "
                            "Planner may rely on the page.",
                            "Unknowns: " + "; ".join(str(u) for u in (facts.get("unknowns") or [])) if facts.get("unknowns") else
                            "The model listed no unknowns."],
                approver=owner or "knowledge-owners", labels=["mac", "knowledge-review"],
                links=[(slug, repo["url"])] if repo.get("url") else []))
            review.update(ticket=ticket.key, ticket_url=ticket.url)
            emit("log", f"review ticket {ticket.key}: {ticket.url}", KNOWLEDGE_STEP)
        except IntegrationError as e:
            review.update(ticket=None, ticket_error=str(e))
            emit("log", f"review ticket not raised: {e}", KNOWLEDGE_STEP)
        if state.runner.pages is not None:
            try:
                published = publish([dataclasses.replace(page, parent=None)], state.runner.pages,
                                    known={k: v[0] for k, v in store.knowledge_pages().items()},
                                    log=lambda m: emit("log", m, KNOWLEDGE_STEP))
                conf_id, url = published[page_id]
                store.save_knowledge_page(page_id, conf_id, url, title)
                review["confluence_url"] = url
            except IntegrationError as e:
                emit("log", f"Confluence page not written: {e}", KNOWLEDGE_STEP)
        (folder / f"{page_id}.json").write_text(json.dumps(review, indent=2), encoding="utf-8")

        run.report = {"repo": slug, "service": service, "page": page_id, "title": title, "path": str(path),
                      "nodes": len(fragment.nodes), "edges": len(fragment.edges), "dropped": len(dropped),
                      "ticket": review.get("ticket"), "ticket_url": review.get("ticket_url"),
                      "confluence_url": review.get("confluence_url"), "mentions": mentions}
        outcome = (f"page {page_id} written, {len(fragment.nodes)} facts merged"
                   + (f", review ticket {review['ticket']}" if review.get("ticket") else ", no Jira configured for the review ticket"))
        trace("compiler", "outcome", outcome, parent="director", status="succeeded")
        emit("step", f"knowledge: {outcome}", KNOWLEDGE_STEP)
        trace("director", "outcome", f"{service} learned from {slug}; a person reviews the page next", status="succeeded")
        _finish(state, run, RunStatus.SUCCEEDED, outcome)
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("learn %s failed", run_id)
        emit("step", f"knowledge: failed: {e}", KNOWLEDGE_STEP)
        trace("director", "outcome", f"failed: {e}", status="failed")
        _finish(state, run, RunStatus.FAILED, f"learn failed: {e}")


@router.post("/learn", status_code=202)
def learn(body: LearnBody, state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
          user: str | None = Depends(signed_in)):
    """Write a knowledge page for a repository no page documents, merge it into the graph, and
    raise a review ticket. The page is a draft until the ticket is approved."""
    slug = body.repo.strip().strip("/")
    if not slug:
        raise HTTPException(422, "Say which repository to learn")
    if "/" not in slug:
        slug = f"{_org()}/{slug}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
        raise HTTPException(422, f"{slug!r} isn't an owner/name repository")
    llm = _llm(config)
    migration = f"knowledge/{slug.split('/')[-1]}"
    _refuse_if_active(state, migration, "learn")
    run = _new_run(state, "ingest", migration)
    llm = _cancellable(state, run.id, llm)
    state.runner.store.add_event(run.id, "run", f"Learn started: {slug}" + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_learn(state, config, run.id, slug, llm))
    return mac_api._run_view(run)


# ---- Describe: the Confluence page that introduces a migration -----------------------------------


def _cited_sections(state: mac_api.State, config: Planning, spec: Spec) -> list:
    """The knowledge-base sections the spec cites (steps', approvals' and metadata's sources)."""
    sections = sections_from_pages(_all_pages(state, config), _urls(state))
    cited = {src for step in spec.steps for src in step.sources} | {src for a in spec.approvals for src in a.sources}
    docs = set(spec.metadata.source_docs)
    picked = [s for s in sections if s.id in cited or s.doc_id in docs]
    return picked[:16]


def _execute_describe(state: mac_api.State, config: Planning, run_id: str, name: str, path: Path, spec: Spec,
                      llm: LLM | None) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, DESCRIBE_STEP, _model_name(llm) if llm else None)
    page_id, title = describe.page_id(spec), describe.page_title(spec)
    source_url = mac_api._file_source(state, path).get("url")
    try:
        repos = sorted({step.run.repo.slug for step in spec.steps})
        emit("step", f"describe: writing the page for {spec.metadata.service}", DESCRIBE_STEP)
        trace("director", "observation", f"{spec.metadata.service}: {len(spec.steps)} steps, {len(spec.approvals)} "
              f"approvals, code in {len(repos)} repositories; no page describes this migration yet",
              role="Director", model=trace.model, status="running")
        trace("director", "reasoning", "a Reader reads each repository's own README and the knowledge-base sections "
              "the plan cites; the Writer turns those facts into the page; code appends the authoritative appendix "
              "(exactly what will run, from migration.yaml) and publishes it to Confluence")
        trace("director", "action", "dispatching Reader, then Writer")

        trace("reader", "action", f"reading {', '.join(repos)}", parent="director", role="Reader", status="running")
        read: dict[str, dict] = {}
        for slug in repos:
            try:
                info = (config.repo_reader or _github_repo)(slug)
                read[slug] = {"description": info.get("description") or "", "readme": info.get("readme") or ""}
            except (IntegrationError, KeyError, TypeError, ValueError) as e:
                read[slug] = {"description": "", "readme": ""}
                emit("log", f"{slug}: README not read ({e})", DESCRIBE_STEP)
        sections = _cited_sections(state, config, spec)
        trace("reader", "outcome", f"{sum(1 for r in read.values() if r['readme'])} README(s), "
              f"{len(sections)} cited section(s)", parent="director", status="succeeded")
        emit("log", f"read {len(read)} repositories and {len(sections)} knowledge-base sections", DESCRIBE_STEP)

        facts = describe.facts(spec, read, sections, source_url)
        trace("writer", "action", "writing Summary, What moves and why, How it runs, Approvals, Risks and rollback",
              parent="director", role="Writer", model=trace.model, status="running")
        model = None
        if llm is not None:
            try:
                markdown = llm.complete(describe.SYSTEM_PROMPT, "Write the page for this migration.\n\n" + facts,
                                        max_tokens=2048).strip()
                if "##" not in markdown:
                    raise ValueError("the reply has no sections")
                model = trace.model
            except (IntegrationError, ValueError, OSError) as e:  # the page is written either way
                emit("log", f"writer: the model's reply couldn't be used ({str(e)[:200]}); writing the facts instead", DESCRIBE_STEP)
                markdown = describe.fallback_markdown(spec)
        else:
            emit("log", "no LLM configured here: the page is the facts from migration.yaml", DESCRIBE_STEP)
            markdown = describe.fallback_markdown(spec)
        summary = describe.summary_of(markdown)
        trace("writer", "outcome", summary or "page written", parent="director", status="succeeded")

        root = next((p.id for p in _base_pages(config) if not p.parent), None)
        text = describe.compose_page(spec, markdown, source_url, run_id, root)
        folder = _generated_dir(state)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{page_id}.md").write_text(text, encoding="utf-8")
        page = _parse_generated(folder / f"{page_id}.md")
        emit("log", f"wrote {page_id}.md", DESCRIBE_STEP)
        meta = {"migration": name, "page": page_id, "title": title, "run_id": run_id, "written": time.time(),
                "model": model, "summary": summary, "source_url": source_url}
        url = None
        if state.runner.pages is not None and page is not None:
            known = {k: v[0] for k, v in store.knowledge_pages().items()}
            try:
                conf_id, url = state.runner.pages.publish(title, render_page(page), known.get(page_id),
                                                          parent_id=known.get(root) if root else None)
                store.save_knowledge_page(page_id, conf_id, url, title)
                emit("log", f"Confluence: {url}", DESCRIBE_STEP)
            except IntegrationError as e:
                emit("log", f"Confluence page not written: {e}", DESCRIBE_STEP)
        else:
            emit("log", "Confluence isn't configured here: the console shows the page itself", DESCRIBE_STEP)
        meta["confluence_url"] = url
        _save_generated_meta(state, page_id, meta)

        run.report = {"migration": name, "page": page_id, "title": title, "confluence_url": url, "summary": summary,
                      "model": model, "repos": repos, "sections": [s.id for s in sections]}
        outcome = f"page “{title}” written" + (" and published to Confluence" if url else "")
        trace("director", "outcome", outcome, status="succeeded")
        emit("step", f"describe: {outcome}", DESCRIBE_STEP)
        _finish(state, run, RunStatus.SUCCEEDED, outcome)
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("describe %s failed", run_id)
        emit("step", f"describe: failed: {e}", DESCRIBE_STEP)
        trace("director", "outcome", f"failed: {e}", status="failed")
        _finish(state, run, RunStatus.FAILED, f"describe failed: {e}")


@router.post("/migrations/{name}/page", status_code=202)
def describe_migration(name: str, state: mac_api.State = Depends(mac_api.get_state),
                       config: Planning = Depends(get_config), user: str | None = Depends(signed_in)):
    """Write (or rewrite) the Confluence page that describes a migration: an agent reads the
    migration.yaml, the repositories it runs and the knowledge-base sections it cites, writes the
    page, and publishes it. Works without an LLM (the facts alone) and without Confluence (the
    console shows the page). Follow it at GET /runs/{id} like Learn."""
    path, spec, _ = mac_api._migration(state, name)
    llm = None
    if config.llm_factory is not None:
        try:
            llm = config.llm_factory()
        except SystemExit:
            llm = None
    _refuse_if_active(state, f"page/{name}", "describe")
    run = _new_run(state, "ingest", f"page/{name}")
    llm = _cancellable(state, run.id, llm)
    state.runner.store.add_event(run.id, "run", f"Describe started: {name}" + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_describe(state, config, run.id, name, path, spec, llm))
    return mac_api._run_view(run)


# ---- Health: what's configured here (names only, never values) --------------------------------


@router.get("/health")
def health(state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config)):
    """Which integrations this deployment has, so the console can explain a 409 before the click.
    `llm_providers` are the models that can be switched between; `llm_provider` is the one in use."""
    llm = config.llm_factory is not None
    chosen = describe_providers()
    model = next((p["model"] for p in chosen["llm_providers"] if p["active"]), None)
    return {"llm": llm, "model": model if llm else None, **chosen,
            "github": bool(os.environ.get("GITHUB_TOKEN")),
            "jira": not isinstance(state.runner.approvals, mac_cli._NoJira),
            "confluence": state.runner.pages is not None,
            "confluence_site": (os.environ.get("ATLASSIAN_SITE") or os.environ.get("JIRA_SITE") or "").rstrip("/") or None,
            "aws": bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")),
            "approvals_live": state.poll_seconds > 0 or state.webhook_secret is not None}


class LlmBody(BaseModel):
    provider: str  # "nemotron" | "grok", as listed in GET /health llm_providers


@router.post("/settings/llm")
def choose_llm(body: LlmBody, state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
               user: str | None = Depends(signed_in)):
    """The model switch: every agent, the design page, AI help and the chat use the chosen
    provider from the next call on. Kept in MAC_DATA_DIR/settings.json. Returns GET /health."""
    try:
        set_provider(body.provider.strip().lower())
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    log.info("LLM provider set to %s%s", body.provider, f" by {user}" if user else "")
    return health(state, config)


# ---- Run index: the run list with the fields the console's lists need --------------------------


@router.get("/run-index")
def run_index(migration: str | None = None, limit: int = 100, state: mac_api.State = Depends(mac_api.get_state)):
    """Like GET /runs, plus `migration`, `based_on`, `diagnostics_mode` and `autofix`, so the Runs
    page can link a run to its pipeline and the pipeline page can find the investigation of a
    failed run. (The runner API's summaries leave those out; asked for in docs/ui-data-needs.md.)"""
    out = []
    for run in state.runner.store.runs(migration, min(max(limit, 1), 200)):
        out.append({**mac_api._summary(run), "migration": run.migration, "based_on": run.based_on,
                    "diagnostics_mode": run.diagnostics_mode, "autofix": run.autofix or None, "active": run.status.active})
    return out


# ---- Active services: every deployed endpoint across every pipeline -----------------------------


@router.get("/services/active")
def active_services(state: mac_api.State = Depends(mac_api.get_state)):
    """One row per declared output of every pipeline (reviewed and generated), with its latest
    production and rehearsal values and the probes that prove it answers. The Services tab."""
    store = state.runner.store
    rows = []
    seen = set()
    sources = [(name, spec, "reviewed", f"/migrations/{name}") for name, (_, spec, _) in mac_api._find(state).items() if spec]
    sources += [(spec.metadata.name, spec, "generated", f"/plans/{run_id}") for run_id, spec in _generated(state)]
    for name, spec, source, href in sources:
        if name in seen:  # a generated plan usually keeps the reviewed spec's name: one row set per name
            continue
        seen.add(name)
        for entry in mac_api._endpoints(store, name, spec):
            last = None
            for env in ("production", "rehearsal"):
                if entry.get(env):
                    probes = [p for p in store.probes(entry[env]["run_id"], limit=50)
                              if (p["step"], p["output"]) == (entry["step"], entry["name"])]
                    entry[env]["last_probe"] = probes[0] if probes else None
            rows.append({"migration": name, "service": spec.metadata.service, "owner_team": spec.metadata.owner_team,
                         "source": source, "href": href, **entry})
    return rows


# ---- Repositories added by URL, with a licence check -------------------------------------------


LICENCE_PROMPT = """You review open-source licences for an engineering team that wants to run and
modify this repository's code inside their own migration pipelines (internal use, possibly
deployed to their cloud, not redistributed as a product). From the licence text and SPDX id,
classify it. Reply with JSON only:
{"spdx": "<id or null>", "category": "permissive" | "weak-copyleft" | "copyleft" | "proprietary" | "none" | "unknown",
 "risk": "ok" | "review" | "confirm" | "blocked",
 "reason": "<one or two sentences for the reviewer: obligations, and why this risk level>"}
Rules: MIT, BSD, Apache-2.0, ISC and similar are ok. LGPL/MPL are review (obligations on changes).
GPL/AGPL/SSPL are review (copyleft reaches the deployed code). No licence at all is confirm: the
person adding it must confirm the team may use it (all rights reserved by default), nobody else
needs to be asked. Only terms that forbid this use outright are blocked. Proprietary or custom
terms are review unless clearly permissive."""

RISK_BY_RULE = {  # used when no LLM is configured, by SPDX id
    "mit": "ok", "bsd-2-clause": "ok", "bsd-3-clause": "ok", "apache-2.0": "ok", "isc": "ok", "unlicense": "ok",
    "cc0-1.0": "ok", "0bsd": "ok", "mpl-2.0": "review", "lgpl-2.1": "review", "lgpl-3.0": "review",
    "gpl-2.0": "review", "gpl-3.0": "review", "agpl-3.0": "review",
}


class RepoBody(BaseModel):
    url: str


def _repos_path(state: mac_api.State) -> Path:
    return state.runner.data_dir / "repos.json"


def _custom_repos(state: mac_api.State) -> list[dict]:
    path = _repos_path(state)
    if not path.is_file():
        return []
    try:
        repos = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    for repo in repos:  # entries from before "no licence" became a confirmation, not a block
        lic = repo.get("licence") or {}
        if lic.get("by") == "rule" and not lic.get("spdx") and lic.get("risk") == "blocked":
            lic.update(risk="confirm", reason="no licence file: all rights reserved by default; confirm the team may use it")
    return repos


def _save_custom_repos(state: mac_api.State, repos: list[dict]) -> None:
    path = _repos_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(repos, indent=2), encoding="utf-8")


def _github_repo_meta(slug: str) -> dict:
    headers = _gh_headers()
    repo = _request(f"{GITHUB_API}/repos/{slug}", headers) or {}
    licence = None
    try:
        raw = _request(f"{GITHUB_API}/repos/{slug}/license", headers) or {}
        info = raw.get("license") or {}
        licence = {"spdx": info.get("spdx_id") if info.get("spdx_id") not in (None, "NOASSERTION") else None,
                   "name": info.get("name"), "path": raw.get("path"),
                   "text": base64.b64decode(raw.get("content") or b"").decode("utf-8", "replace")[:12000]}
    except IntegrationError as e:
        if e.status != 404:
            raise
    return {"repo": repo, "license": licence}


def _parse_repo_url(url: str) -> str:
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url.strip())
    if not m:
        raise HTTPException(422, "Give a public GitHub repository URL, like https://github.com/owner/name")
    return f"{m.group(1)}/{m.group(2)}"


def _execute_add_repo(state: mac_api.State, config: Planning, run_id: str, slug: str, llm: LLM | None, user: str | None) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, "licence", _model_name(llm) if llm else None)
    try:
        emit("step", f"licence: checking {slug}", "licence")
        trace("director", "observation", f"{slug} was added by hand; it isn't in the org's list", role="Director",
              model=trace.model, status="running")
        trace("director", "reasoning", "a repository the Planner may build from must be one the company may run and "
              "change: the Reader fetches its licence, the Compiler records the verdict and raises a review ticket "
              "when a person has to decide")
        trace("reader", "action", f"fetching {slug}'s metadata and LICENSE from GitHub", parent="director", role="Reader",
              status="running")
        try:
            meta = (config.repo_meta_reader or _github_repo_meta)(slug)
        except IntegrationError as e:
            if e.status == 404:
                raise ValueError(f"{slug} isn't a public GitHub repository (or doesn't exist)") from e
            raise
        repo, licence = meta.get("repo") or {}, meta.get("license")
        if repo.get("private"):
            raise ValueError(f"{slug} is private; only public repositories can be added here")
        spdx = (licence or {}).get("spdx")
        trace("reader", "outcome", (f"licence file {licence.get('path')}: {licence.get('name') or spdx or 'unrecognised'}"
                                    if licence else "no licence file in the repository"), parent="director", status="succeeded")

        trace("checker", "action", "classifying the licence for internal use and modification", parent="director",
              role="Licence checker", model=trace.model, status="running")
        verdict = None
        if llm is not None:
            prompt = (f"Repository: {slug}\nSPDX from GitHub: {spdx or '(none)'}\n"
                      f"Licence file: {(licence or {}).get('path') or '(none)'}\n\nLicence text:\n"
                      + ((licence or {}).get("text") or "(no licence file)"))
            try:
                reply = parse_json(llm.complete(LICENCE_PROMPT, prompt, max_tokens=800))
                if isinstance(reply, dict) and reply.get("risk") in ("ok", "review", "confirm", "blocked"):
                    verdict = {"spdx": reply.get("spdx") or spdx, "category": reply.get("category") or "unknown",
                               "risk": reply["risk"], "reason": str(reply.get("reason") or "").strip(), "by": "nemotron"}
            except (ValueError, IntegrationError) as e:
                emit("log", f"licence checker: model reply unusable ({e}); falling back to the SPDX rule", "licence")
        if verdict is None:
            key = (spdx or "").lower()
            risk = "confirm" if licence is None else RISK_BY_RULE.get(key, "review")
            verdict = {"spdx": spdx, "category": "none" if licence is None else ("permissive" if risk == "ok" else "unknown"),
                       "risk": risk, "reason": ("no licence file: all rights reserved by default; confirm the team may use it"
                                                if licence is None else f"classified by SPDX rule ({spdx or 'unrecognised'})"), "by": "rule"}
        trace("checker", "outcome", f"{verdict['spdx'] or 'no licence'} · {verdict['category']} · {verdict['risk']}: {verdict['reason']}",
              parent="director", status="failed" if verdict["risk"] == "blocked" else "succeeded")

        needs_ticket = verdict["risk"] in ("review", "blocked")  # confirm is the adder's own call, not a reviewer's
        trace("compiler", "action", "recording the repository" + (" and raising a review ticket" if needs_ticket else
              "; the person who added it confirms its use" if verdict["risk"] == "confirm" else ""),
              parent="director", role="Compiler", status="running")
        entry = {"name": slug.split("/")[1], "full_name": slug, "url": repo.get("html_url") or f"https://github.com/{slug}",
                 "description": repo.get("description") or "", "pushed_at": _epoch(repo.get("pushed_at")),
                 "archived": bool(repo.get("archived")), "custom": True, "added_by": user, "added_at": time.time(),
                 "licence": verdict, "run_id": run_id}
        if needs_ticket:
            try:
                raised = state.runner.approvals.raise_ticket(TicketRequest(
                    approval_id=f"LIC-{_slug(slug)}", summary=f"Licence review: {slug} ({verdict['spdx'] or 'no licence'})",
                    paragraphs=[f"{slug} was added to MaC's repository list" + (f" by @{user}" if user else "") + ".",
                                f"Licence: {verdict['spdx'] or 'none found'} ({verdict['category']}); risk {verdict['risk']}.",
                                verdict["reason"] or "", "Approve this ticket if the team may run and modify this code."],
                    approver="tech-risk", labels=["mac", "licence-review"], links=[(slug, entry["url"])]))
                entry["licence"].update(ticket=raised.key, ticket_url=raised.url)
                emit("log", f"review ticket {raised.key}: {raised.url}", "licence")
            except IntegrationError as e:
                emit("log", f"review ticket not raised: {e}", "licence")
        repos = [r for r in _custom_repos(state) if r["full_name"].lower() != slug.lower()] + [entry]
        _save_custom_repos(state, repos)
        _repo_cache["repos"] = None  # services() merges on the next call
        run.report = {"repo": slug, "licence": verdict, "url": entry["url"]}
        outcome = f"{slug} added: {verdict['spdx'] or 'no licence'} · {verdict['risk']}" + (f" · {verdict.get('ticket')}" if verdict.get("ticket") else "")
        trace("compiler", "outcome", outcome, parent="director", status="succeeded")
        emit("step", f"licence: {outcome}", "licence")
        trace("director", "outcome", outcome, status="succeeded")
        _finish(state, run, RunStatus.SUCCEEDED, outcome)
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("add repo %s failed", run_id)
        emit("step", f"licence: failed: {e}", "licence")
        trace("director", "outcome", f"failed: {e}", status="failed")
        _finish(state, run, RunStatus.FAILED, f"adding {slug} failed: {e}")


@router.post("/repos", status_code=202)
def add_repo(body: RepoBody, state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
             user: str | None = Depends(signed_in)):
    """Add a public repository by URL. An agent checks its licence (Nemotron when configured,
    an SPDX rule otherwise) and raises a review ticket unless it's clearly fine."""
    slug = _parse_repo_url(body.url)
    llm = None
    if config.llm_factory is not None:
        try:
            llm = config.llm_factory()
        except SystemExit:
            llm = None
    migration = f"repo/{slug.split('/')[1]}"
    _refuse_if_active(state, migration, "licence check")
    run = _new_run(state, "ingest", migration)
    llm = _cancellable(state, run.id, llm)
    state.runner.store.add_event(run.id, "run", f"Repository added: {slug}" + (f" (by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_add_repo(state, config, run.id, slug, llm, user))
    return mac_api._run_view(run)


@router.delete("/repos/{owner}/{name}")
def remove_repo(owner: str, name: str, state: mac_api.State = Depends(mac_api.get_state), user: str | None = Depends(signed_in)):
    slug = f"{owner}/{name}".lower()
    repos = _custom_repos(state)
    kept = [r for r in repos if r["full_name"].lower() != slug]
    if len(kept) == len(repos):
        raise HTTPException(404, f"{owner}/{name} wasn't added by hand")
    _save_custom_repos(state, kept)
    return {"removed": f"{owner}/{name}"}


# ---- Chat transcripts -------------------------------------------------------------------------
# The assistant itself is the runner API's `POST /api/mac/chat` (mac/assistant.py: a streaming,
# tool-using agent over Confluence, Jira and MaC's records). The server keeps no history, so the
# console stores each conversation here, so chats survive reloads and list in the rail.


class ChatTranscript(BaseModel):
    title: str
    turns: list[dict]  # [{role: user|assistant|error, text, ts, tools?: [...]}]


def _chats_dir(state: mac_api.State) -> Path:
    return state.runner.data_dir / "chats"


def _load_chat(state: mac_api.State, chat_id: str) -> dict | None:
    path = _chats_dir(state) / f"{chat_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@router.put("/chats/{chat_id}")
def save_chat(chat_id: str, body: ChatTranscript, state: mac_api.State = Depends(mac_api.get_state),
              user: str | None = Depends(signed_in)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,40}", chat_id):
        raise HTTPException(422, "chat id: 6 to 40 letters, digits, - or _")
    if len(body.turns) > 400:
        raise HTTPException(422, "that conversation is too long to keep; start a new chat")
    existing = _load_chat(state, chat_id) or {"id": chat_id, "created": time.time(), "by": user}
    chat = {**existing, "title": body.title[:120], "turns": body.turns, "updated": time.time()}
    folder = _chats_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{chat_id}.json").write_text(json.dumps(chat, indent=2), encoding="utf-8")
    return {"id": chat_id, "title": chat["title"], "turns": len(chat["turns"]), "updated": chat["updated"]}


@router.get("/chats")
def list_chats(state: mac_api.State = Depends(mac_api.get_state)):
    out = []
    for path in _chats_dir(state).glob("*.json") if _chats_dir(state).is_dir() else []:
        c = _load_chat(state, path.stem)
        if c:
            out.append({"id": c["id"], "title": c["title"], "created": c["created"], "updated": c["updated"],
                        "turns": len(c["turns"])})
    return sorted(out, key=lambda c: c["updated"], reverse=True)


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str, state: mac_api.State = Depends(mac_api.get_state)):
    c = _load_chat(state, chat_id)
    if c is None:
        raise HTTPException(404, f"no chat {chat_id!r}")
    return c


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, state: mac_api.State = Depends(mac_api.get_state), user: str | None = Depends(signed_in)):
    path = _chats_dir(state) / f"{chat_id}.json"
    if not path.is_file():
        raise HTTPException(404, f"no chat {chat_id!r}")
    path.unlink()
    return {"deleted": chat_id}


class AcceptBody(BaseModel):
    note: str | None = None


@router.post("/repos/{owner}/{name}/accept")
def accept_repo_licence(owner: str, name: str, body: AcceptBody | None = None,
                        state: mac_api.State = Depends(mac_api.get_state), user: str | None = Depends(signed_in)):
    """The person's answer to a licence prompt (no licence, review, blocked): yes, use it."""
    slug = f"{owner}/{name}".lower()
    repos = _custom_repos(state)
    entry = next((r for r in repos if r["full_name"].lower() == slug), None)
    if entry is None:
        raise HTTPException(404, f"{owner}/{name} wasn't added by hand")
    licence = dict(entry.get("licence") or {})
    licence.update(accepted=True, accepted_by=user or "console", accepted_at=time.time(),
                   note=(body.note if body else None))
    entry["licence"] = licence
    _save_custom_repos(state, repos)
    return entry


# ---- Services --------------------------------------------------------------------------------


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
    reply = _request(f"{GITHUB_API}/orgs/{_org()}/repos?per_page=100&sort=pushed", _gh_headers()) or []
    repos = [{"name": r["name"], "full_name": r["full_name"], "url": r.get("html_url"),
              "description": r.get("description"), "pushed_at": _epoch(r.get("pushed_at")),
              "archived": bool(r.get("archived"))} for r in reply]
    _repo_cache.update(at=time.time(), repos=repos)
    return repos


def _knowledge_services(state: mac_api.State, config: Planning) -> tuple[list[dict], int]:
    """Services the knowledge base documents (pages labelled `service`), with the repos each
    page mentions. No model call: this is what the Migrate page shows before anything is learned."""
    pages = _all_pages(state, config)
    urls = _urls(state, pages)
    repo_re = re.compile(rf"{re.escape(_org())}/[A-Za-z0-9_-]+", re.I)
    out = []
    for page in pages:
        labels = {label.lower() for label in page.labels}
        if "service" not in labels:
            continue
        name = page.title.split(":", 1)[1].strip() if ":" in page.title else page.title.strip()
        repos = sorted({m.group(0) for m in repo_re.finditer(page.body)}, key=str.lower)
        description = next((line.strip() for line in page.body.splitlines()
                            if line.strip() and not line.lstrip().startswith(("#", "-", "|", "*", "```", "_"))), "")
        first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0]  # the first sentence reads best on a card
        description = first if len(first) <= 160 else description[:157].rstrip() + "…"
        generated = "generated" in labels
        out.append({"name": name, "page": page.id, "page_title": page.title, "page_url": urls.get(page.id),
                    "team": page.owner or None, "description": description, "repos": repos, "approvers": [],
                    "sources": [], "learned": False, "generated": generated,
                    "review": _review_state(state, page.id, _generated_meta(state, page.id)) if generated else None})
    return out, len(pages)


def _service_view(graph: Graph, node, plans_by_service: dict[str, list[str]]) -> dict:
    near = graph.neighbors(node.key, depth=1)
    wider = graph.neighbors(node.key, depth=2)
    repos = sorted({n.name for n in near.nodes.values() if n.type == "repo"}, key=str.lower)
    teams = sorted({graph.nodes[e.source].name for e in graph.edges
                    if e.type == "owns" and e.target == node.key and e.source in graph.nodes})
    approvers = sorted({n.name.strip("`") for n in wider.nodes.values() if n.type == "approver"})
    return {"name": node.name, "page": None, "page_title": None, "page_url": None, "description": node.description,
            "team": teams[0] if teams else None, "repos": repos, "approvers": approvers, "sources": node.sources,
            "learned": True, "generated": False, "review": None, "plans": plans_by_service.get(node.name.lower(), [])}


@router.get("/services")
def services(state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config)):
    """What can be migrated: the knowledge base's services (always), enriched by the graph once
    it's learned, plus every repo in the org so nothing is hidden."""
    plans_by_service: dict[str, list[str]] = {}
    for run_id, spec in _generated(state):
        plans_by_service.setdefault(spec.metadata.service.lower(), []).append(run_id)
    reviewed = {spec.metadata.service.lower(): name for name, (_, spec, _) in mac_api._find(state).items() if spec}

    base, page_count = _knowledge_services(state, config)
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
    for key, svc in by_name.items():
        svc["plans"] = plans_by_service.get(key, [])
        svc["migration"] = reviewed.get(key)

    repos, repos_error = [], None
    try:
        repos = [dict(r) for r in (config.repo_lister or _github_repos)()]
    except IntegrationError as e:
        repos_error = (f"GitHub answered HTTP {e.status}; the organisation's repositories appear when it recovers"
                       if e.status else f"GitHub couldn't be reached ({str(e)[:120]})")
    listed = {r["full_name"].lower() for r in repos}
    for custom in _custom_repos(state):
        if custom["full_name"].lower() in listed:
            # the org's own repo, added by hand too: keep GitHub's row, carry the licence verdict
            for r in repos:
                if r["full_name"].lower() == custom["full_name"].lower():
                    r["licence"], r["custom"] = custom.get("licence"), True
            continue
        repos.append(dict(custom))
    owner_of = {repo.lower(): svc for svc in by_name.values() for repo in svc["repos"]}
    for repo in repos:
        repo.setdefault("custom", False)
        repo.setdefault("licence", None)
        svc = owner_of.get(repo["full_name"].lower())
        repo["service"] = svc["name"] if svc else None
        repo["page"] = svc["page"] if svc else None
        repo["page_title"] = svc.get("page_title") if svc else None
        repo["page_url"] = svc["page_url"] if svc else None

    return {"ingested": graph is not None,
            "graph_updated": _graph_path(state).stat().st_mtime if graph is not None else None,
            "knowledge": {"pages": page_count, "dir": config.knowledge_dir.name,
                          "generated": len(_generated_pages(state))},
            "services": sorted(by_name.values(), key=lambda s: s["name"].lower()),
            "repos": repos, "repos_error": repos_error}


# ---- Plan ------------------------------------------------------------------------------------


class PlanBody(BaseModel):
    service: str | None = None
    goal: str | None = None
    pr: bool = False  # also open a PR into MAC_MIGRATIONS_REPO
    reuse: bool = True  # a reviewed migration.yaml for the service counts as the plan; False: always generate
    build: bool = False  # once the plan is ready, start Build on it


class _Observed:
    """Wraps the LLM so every call shows up live as an attempt card and a Planner agent event."""

    def __init__(self, llm: LLM, emit: Callable[[str, str, str | None], None], trace: _Trace):
        self.llm, self.emit, self.trace, self.n = llm, emit, trace, 0

    def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> str:
        self.n += 1
        self.emit("step", f"attempt-{self.n}: running, asking the model for a migration.yaml", f"attempt-{self.n}")
        self.trace("planner", "action", f"attempt {self.n}: writing migration.yaml from the graph and the cited sections"
                   + ("" if self.n == 1 else ", with the validator's problems from the last attempt"),
                   parent="director", role="Planner", model=self.trace.model, status="running", step=f"attempt-{self.n}")
        return self.llm.complete(system, user, max_tokens=max_tokens)


def _knowledge(state: mac_api.State, config: Planning, llm: LLM, emit, trace: _Trace) -> tuple[list, Graph]:
    """The knowledge base's sections, and the graph (ingested now if there isn't one yet)."""
    sections = _sections(state, config)
    graph = _load_graph(state)
    if graph is not None:
        emit("step", f"knowledge: graph loaded, {len(graph.nodes)} facts and {len(graph.edges)} relations",
             KNOWLEDGE_STEP)
        trace("knowledge", "outcome", f"graph loaded: {len(graph.nodes)} facts, {len(graph.edges)} relations",
              parent="director", role="Knowledge", status="succeeded", step=KNOWLEDGE_STEP)
        return sections, graph
    emit("step", "knowledge: no graph yet, reading the knowledge base first", KNOWLEDGE_STEP)
    pages = _all_pages(state, config)
    trace("knowledge", "action", f"no graph yet: reading {len(pages)} pages first", parent="director", role="Knowledge",
          model=trace.model, status="running", step=KNOWLEDGE_STEP)
    graph, dropped = extract(sections, llm, log=lambda m: emit("log", m, KNOWLEDGE_STEP))
    graph.save(_graph_path(state))
    for reason in dropped:
        emit("log", f"dropped: {reason}", KNOWLEDGE_STEP)
    emit("step", f"knowledge: {len(graph.nodes)} facts, {len(graph.edges)} relations"
                 + (f", {len(dropped)} dropped" if dropped else ""), KNOWLEDGE_STEP)
    trace("knowledge", "outcome", f"{len(graph.nodes)} facts, {len(graph.edges)} relations", parent="director",
          status="succeeded", step=KNOWLEDGE_STEP)
    return sections, graph


def _start_build(state: mac_api.State, run: RunRecord, path: Path, emit, trace: _Trace) -> None:
    try:
        build = state.runner.start_build(path)
    except GateError as e:
        emit("log", f"Build not started: {e}", PLAN_STEP)
        trace("compiler", "outcome", f"Build not started: {e}", parent="director")
        return
    state.submit(lambda: mac_api._execute(state, build.id))
    run.report["build_run"] = build.id
    emit("step", f"plan: Build {build.id} started", PLAN_STEP)
    trace("compiler", "action", f"handed the pipeline to the runner: Build {build.id}", parent="director")


def _execute_plan(state: mac_api.State, config: Planning, run_id: str, goal: str, body: PlanBody, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, PLAN_STEP, _model_name(llm))
    try:
        trace("director", "observation", goal, role="Director", model=trace.model, status="running")
        reviewed = _reviewed_for(state, body.service) if body.reuse else None
        if reviewed is not None:
            name, path = reviewed
            spec = load_spec(path)
            emit("step", f"detect: found reviewed migration.yaml {name} for {body.service}", DETECT_STEP)
            trace("detect", "outcome", f"a reviewed migration.yaml already exists: {name}, {len(spec.steps)} steps",
                  parent="director", role="Detect", status="succeeded", step=DETECT_STEP)
            trace("director", "reasoning", "a plan people already reviewed beats a fresh one; rendering it instead of "
                  "generating")
            run.spec_text, run.spec_path, run.spec_digest = path.read_text(encoding="utf-8"), str(path), spec.digest()
            run.report = {"detected": name, "name": name, "service": spec.metadata.service, "iterations": 0,
                          "steps": len(spec.steps), "approvals": len(spec.approvals)}
            emit("step", f"plan: using {name}, {len(spec.steps)} steps and {len(spec.approvals)} approvals", PLAN_STEP)
            if body.build:
                _start_build(state, run, path, emit, trace)
            trace("director", "outcome", f"pipeline {name} is ready", status="succeeded")
            _finish(state, run, RunStatus.SUCCEEDED, f"reviewed migration.yaml {name} found")
            return
        emit("step", "detect: no migration.yaml for this goal, generating one", DETECT_STEP)
        trace("detect", "outcome", "no migration.yaml exists for this goal", parent="director", role="Detect",
              status="succeeded", step=DETECT_STEP)
        trace("director", "reasoning", "Knowledge supplies the graph and cited sections; the Planner drafts; the "
              "validator is the Planner's tool, so every attempt is checked before anyone sees it; the Compiler writes the file")
        sections, graph = _knowledge(state, config, llm, emit, trace)
        observed = _Observed(llm, emit, trace)

        def on_log(m: str) -> None:
            emit("step", m.replace("attempt ", "attempt-", 1), f"attempt-{observed.n}")
            ok = m.endswith("valid")
            trace("planner", "outcome", "valid: schema, validator, citations, documented repos" if ok else m,
                  parent="director", status="succeeded" if ok else "failed", step=f"attempt-{observed.n}")
            trace("validator", "outcome", ("attempt passed" if ok else f"attempt {observed.n}: " + m.split(": ", 1)[-1]),
                  parent="director", role="Validator", status="succeeded" if ok else "running", step=f"attempt-{observed.n}")

        result = plan(goal, graph, sections, observed, log=on_log)
        for n, problems in enumerate(result.history, 1):
            for problem in problems:
                emit("log", problem, f"attempt-{n}")
        if not result.ok:
            run.report = {"iterations": result.iterations, "problems": result.problems}
            emit("step", f"plan: not valid after {result.iterations} attempt(s)", PLAN_STEP)
            trace("validator", "outcome", f"still invalid after {result.iterations} attempts", parent="director", status="failed")
            trace("director", "outcome", "no valid plan; a person must look at the problems", status="failed")
            _finish(state, run, RunStatus.FAILED,
                    f"the planner couldn't produce a valid migration.yaml in {result.iterations} attempt(s)")
            return
        spec = result.spec
        trace("compiler", "action", "writing migration.yaml", parent="director", role="Compiler", status="running")
        out = _plans_dir(state) / run_id / "migration.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.yaml + "\n", encoding="utf-8")
        run.spec_text, run.spec_path, run.spec_digest = result.yaml, str(out), spec.digest()
        run.report = {"plan": run_id, "name": spec.metadata.name, "service": spec.metadata.service,
                      "iterations": result.iterations, "steps": len(spec.steps), "approvals": len(spec.approvals),
                      "breakpoints": [s.id for s in spec.steps if s.when == "manual"]}
        emit("step", f"plan: migration.yaml written, {len(spec.steps)} steps and {len(spec.approvals)} approvals"
                     f" in {result.iterations} attempt(s)", PLAN_STEP)
        if body.pr:
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
        trace("compiler", "outcome", f"migration.yaml: {len(spec.steps)} steps, {len(spec.approvals)} approvals, "
              f"{len(run.report['breakpoints'])} breakpoint(s)" + (f", PR {run.report['pr_url']}" if run.report.get("pr_url") else ""),
              parent="director", status="succeeded")
        if body.build:
            _start_build(state, run, out, emit, trace)
        trace("director", "outcome", f"valid plan in {result.iterations} attempt(s)", status="succeeded")
        _finish(state, run, RunStatus.SUCCEEDED, f"valid after {result.iterations} attempt(s)")
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("plan %s failed", run_id)
        emit("step", f"plan: failed: {e}", PLAN_STEP)
        trace("director", "outcome", f"failed: {e}", status="failed")
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
    llm = _cancellable(state, run.id, llm)
    state.runner.store.add_event(run.id, "run", f"Planning started: {goal}" + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_plan(state, config, run.id, goal, body, llm))
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
        "stages": mac_api._stages(spec), "approvals": approvals, "endpoints": mac_api._endpoints(store, name, spec),
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


# ---- Investigate a failed run, then a person approves the fix ------------------------------------


FIX_PROMPT = """You are MaC's Diagnostician. A migration pipeline step failed. From the step's definition, its
log tail and the code of the repository it ran, find the root cause and propose the smallest fix.
Never weaken a check or a test; never touch CI, CODEOWNERS or .env files. Reply with JSON only:
{"root_cause": "<one or two sentences>",
 "fix": "<what to change and why, for the engineer who approves it>",
 "confidence": "high" | "medium" | "low",
 "files": {"<path in the repository>": "<the complete new content of that file>"}}
`files` may be empty when the fix is not a code change (wrong approval, missing permission, infrastructure)."""


class InvestigateBody(BaseModel):
    mode: str | None = None  # explain | report | autofix; informational


def _github_code(slug: str, sha: str, prefix: str) -> dict[str, str]:
    return read_files(GitHubAPI(os.environ.get("GITHUB_TOKEN")), slug, sha, prefix)


def _code_sample(files: dict[str, str], entry: str | None, limit_files: int = 12, limit_chars: int = 60_000) -> dict[str, str]:
    """The files the Fixer may see: the entrypoint first, then the rest, capped."""
    ordered = sorted(files.items(), key=lambda kv: (0 if entry and kv[0].endswith(entry) else 1, kv[0]))
    out, total = {}, 0
    for path, text in ordered[:limit_files]:
        if total + len(text) > limit_chars:
            break
        out[path] = text
        total += len(text)
    return out


def _execute_investigate(state: mac_api.State, config: Planning, run_id: str, failed: RunRecord, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    emit = lambda kind, message, step=None: store.add_event(run_id, kind, message, step)  # noqa: E731
    trace = _Trace(state, run_id, "diagnose", _model_name(llm))
    step_id = failed.failed_step or "?"
    try:
        spec = parse_spec(failed.spec_text, failed.spec_path)
        step = next((s for s in spec.steps if s.id == step_id), None)
        if step is None:
            raise ValueError(f"the failed run has no step {step_id!r}")
        repo = step.run.repo
        sha = failed.shas.get(repo.key) or repo.ref
        entry = step.run.entrypoint or step.run.path
        emit("step", f"diagnose: {step_id} failed in {failed.mode} {failed.id}: {failed.reason}", "diagnose")
        trace("director", "observation", f"{failed.mode} {failed.id} failed at {step_id}: {failed.reason}",
              role="Director", model=trace.model, status="running")
        trace("director", "reasoning", "Logs reads the step's output; Code reads the repository at the commit that "
              "ran; the Fixer proposes the smallest change; the Compiler raises the ticket, because a person approves "
              "every fix before it becomes a pull request")
        trace("director", "action", "dispatching Logs and Code")

        trace("logs", "action", f"reading {step_id}'s output from run {failed.id}", parent="director", role="Logs",
              status="running")
        lines = [e.message for e in store.events(failed.id, step=step_id) if e.kind == "log"][-40:]
        trace("logs", "outcome", (f"{len(lines)} lines; last: {lines[-1][:120]}" if lines else "the step wrote no output"),
              parent="director", status="succeeded")

        trace("code", "action", f"reading {repo.slug} at {sha[:12]}" + (f" around {entry}" if entry else ""),
              parent="director", role="Code", status="running")
        prefix = str(PurePosixPath(entry).parent) if entry and "/" in entry else ""
        prefix = "" if prefix == "." else prefix
        try:
            files = (config.code_reader or _github_code)(repo.slug, sha, prefix)
        except IntegrationError as e:
            files = {}
            emit("log", f"code not read: {e}", "diagnose")
        sample = _code_sample(files, entry)
        trace("code", "outcome", f"{len(sample)} file(s) read" if sample else "no code available (GitHub not readable)",
              parent="director", status="succeeded")

        trace("fixer", "action", "root-causing from the step, its log tail and the code", parent="director",
              role="Fixer", model=trace.model, status="running")
        prompt = (f"Migration: {spec.metadata.name} ({spec.metadata.service})\nStep:\n"
                  f"{json.dumps(mac_api._step_view(step), indent=2)}\nFailure reason: {failed.reason}\n\n"
                  f"Log tail:\n" + "\n".join(lines) + "\n\nCode:\n"
                  + "\n\n".join(f"### {p}\n{t}" for p, t in sample.items()))
        reply = parse_json(llm.complete(FIX_PROMPT, prompt, max_tokens=6000))
        if not isinstance(reply, dict):
            raise ValueError("the Diagnostician's reply wasn't an object")
        proposed = {str(p): str(t) for p, t in (reply.get("files") or {}).items()} if isinstance(reply.get("files"), dict) else {}
        root_cause = str(reply.get("root_cause") or "").strip() or "not determined"
        fix = str(reply.get("fix") or "").strip() or "no fix proposed"
        trace("fixer", "outcome", f"{root_cause} → {fix}", parent="director", status="succeeded")
        emit("diagnosis", f"root cause: {root_cause}", "diagnose")
        emit("diagnosis", f"fix: {fix}", "diagnose")

        trace("compiler", "action", "recording the proposal and raising the approval ticket", parent="director",
              role="Compiler", status="running")
        folder = _fixes_dir(state) / run_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "files.json").write_text(json.dumps(proposed, indent=2), encoding="utf-8")
        ticket = None
        try:
            raised = state.runner.approvals.raise_ticket(TicketRequest(
                approval_id=f"FIX-{failed.id}", summary=f"Approve fix: {step_id} in {spec.metadata.name}",
                paragraphs=[f"{failed.mode.capitalize()} {failed.id} failed at {step_id}: {failed.reason}",
                            f"Root cause: {root_cause}", f"Proposed fix: {fix}",
                            ("Files: " + ", ".join(proposed)) if proposed else "No code change proposed."],
                approver=spec.metadata.owner_team, labels=["mac", "fix-approval"], links=[]))
            ticket = {"key": raised.key, "url": raised.url}
            emit("log", f"approval ticket {raised.key}: {raised.url}", "diagnose")
        except IntegrationError as e:
            emit("log", f"approval ticket not raised: {e}", "diagnose")
        run.report = {"investigated": failed.id, "step": step_id, "repo": repo.slug, "sha": sha, "entrypoint": entry,
                      "root_cause": root_cause, "fix": fix, "confidence": reply.get("confidence"),
                      "files": sorted(proposed), "ticket": ticket and ticket["key"], "ticket_url": ticket and ticket["url"],
                      "mode": run.diagnostics_mode, "approved": False}
        trace("compiler", "outcome", ("ticket " + ticket["key"] if ticket else "no Jira configured; approve in the console")
              + f"; {len(proposed)} file(s) ready for a pull request", parent="director", status="succeeded")
        emit("step", "diagnose: root cause found; a person approves the fix", "diagnose")
        trace("director", "outcome", f"root cause: {root_cause}", status="succeeded")
        _finish(state, run, RunStatus.SUCCEEDED, f"root cause: {root_cause}"[:200])
    except Exception as e:  # noqa: BLE001 - a crash must never leave the run looking active
        if _cancelled(state, run, e, emit, trace):
            return
        log.exception("investigate %s failed", run_id)
        emit("step", f"diagnose: failed: {e}", "diagnose")
        trace("director", "outcome", f"failed: {e}", status="failed")
        _finish(state, run, RunStatus.FAILED, f"investigation failed: {e}")


@router.post("/runs/{run_id}/investigate", status_code=202)
def investigate(run_id: str, body: InvestigateBody | None = None, state: mac_api.State = Depends(mac_api.get_state),
                config: Planning = Depends(get_config), user: str | None = Depends(signed_in)):
    """Launch the Diagnostician on a failed run. Answers a new run (mode `diagnose`) whose report
    carries the root cause, the proposed fix and the approval ticket."""
    failed = mac_api._get_run(state, run_id)
    if failed.status.active:
        raise HTTPException(409, f"run {run_id} is still {failed.status}; investigate once it has stopped")
    if failed.status not in (RunStatus.FAILED, RunStatus.ROLLBACK_FAILED) or not failed.failed_step:
        raise HTTPException(409, f"run {run_id} {failed.status} without a failed step; nothing to investigate")
    llm = _llm(config)
    _refuse_if_active(state, failed.migration, "investigation", mode="diagnose")
    run = _new_run(state, "diagnose", failed.migration, spec_text=failed.spec_text, based_on=failed.id)
    llm = _cancellable(state, run.id, llm)
    run.spec_path, run.spec_digest, run.shas = failed.spec_path, failed.spec_digest, dict(failed.shas)
    run.failed_step, run.diagnostics_mode = failed.failed_step, (body.mode if body and body.mode else failed.diagnostics_mode)
    state.runner.store.save(run)
    state.runner.store.add_event(run.id, "run", f"Investigation started: {failed.mode} {failed.id} failed at {failed.failed_step}"
                                 + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_investigate(state, config, run.id, failed, llm))
    return mac_api._run_view(run)


def _open_pr(slug: str, base: str, branch: str, files: dict[str, str], title: str, body: str, message: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise IntegrationError("GITHUB_TOKEN isn't set, so MaC can't open a pull request")
    return open_pull_request(GitHubAPI(token), slug, base, branch, files, title, body, message)


@router.post("/runs/{run_id}/approve-fix", status_code=202)
def approve_fix(run_id: str, state: mac_api.State = Depends(mac_api.get_state), config: Planning = Depends(get_config),
                user: str | None = Depends(signed_in)):
    """The manual command after an investigation: a person approves, MaC opens the fix as a pull
    request on the failing repository. Nothing merges by itself."""
    run = mac_api._get_run(state, run_id)
    if run.mode != "diagnose" or run.status != RunStatus.SUCCEEDED:
        raise HTTPException(409, f"run {run_id} isn't a finished investigation")
    report = dict(run.report or {})
    if report.get("pr_url"):
        raise HTTPException(409, f"already approved: {report['pr_url']}")
    path = _fixes_dir(state) / run_id / "files.json"
    files = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not files:
        raise HTTPException(409, "the Diagnostician proposed no code change, so there is nothing to open a pull request for")
    branch = f"mac/autofix/{report.get('investigated', run_id)}"
    title = f"Fix {report.get('step')}: {str(report.get('root_cause') or '')[:60]}"
    body_text = (f"MaC's Diagnostician investigated run {report.get('investigated')} ({run.migration}).\n\n"
                 f"**Root cause:** {report.get('root_cause')}\n\n**Fix:** {report.get('fix')}\n\n"
                 + (f"Approval ticket: {report['ticket_url']}\n\n" if report.get("ticket_url") else "")
                 + (f"Approved in the console by @{user}." if user else "Approved in the console."))
    try:
        url = (config.pr_opener or _open_pr)(report["repo"], "main", branch, files, title, body_text,
                                             f"Fix {report.get('step')} ({run.migration})")
    except IntegrationError as e:
        raise HTTPException(409, str(e)) from e
    report.update(pr_url=url, approved=True, approved_by=user, approved_at=time.time())
    run.report = report
    state.runner.store.save(run)
    state.runner.store.add_event(run.id, "step", "diagnose: fix approved" + (f" by @{user}" if user else "") + f", pull request {url}", "diagnose")
    _Trace(state, run.id, "diagnose", None)("compiler", "outcome", f"approved; pull request {url}", parent="director", status="succeeded")
    return mac_api._run_view(run)
