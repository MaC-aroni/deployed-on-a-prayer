"""The cost estimate over HTTP: the usage reader as a run, and the current estimate.

    POST /api/mac/migrations/{name}/usage   start the usage reader (an LLM run, mode "usage")
    GET  /api/mac/migrations/{name}/cost    the estimate now: last Build's plan × usage × prices

Build already puts the estimate in its report (`report.cost`); these let the console refresh it
without a new Build. Contract: docs/api.md, "Cost estimate". Its own module, like
planning_api.py, so it never touches the runner API's module.
"""

from fastapi import APIRouter, Depends, HTTPException

from mac.cost import estimate
from mac.cost_cli import CostInputError, build_resources
from mac.llm import LLM
from mac.pricing import PricingError
from mac.sources import sections_from_pages
from mac.spec import Spec, SpecError, parse_spec
from mac.store import RunStatus
from mac.usage import load_usage, run_usage

from . import mac_api, planning_api
from .auth import signed_in

USAGE_STEP = "usage"

router = APIRouter(prefix="/api/mac", tags=["cost"])


def _spec(state: mac_api.State, name: str) -> Spec:
    """The migration's spec: the reviewed one in the migrations repo, else the one its latest Build ran
    (a generated plan)."""
    found = mac_api._find(state).get(name)
    if found and found[1] is not None:
        return found[1]
    build = state.runner.store.latest(name, "build")
    if build is None:
        raise HTTPException(404, f"no migration named {name!r} has been built")
    try:
        return parse_spec(build.spec_text)
    except SpecError as e:
        raise HTTPException(409, "migration.yaml can't be read: " + "; ".join(e.problems)) from e


def _execute_usage(state: mac_api.State, config: planning_api.Planning, run_id: str, spec: Spec,
                   resources: dict, llm: LLM) -> None:
    store = state.runner.store
    run = store.get(run_id)
    model = planning_api._model_name(llm)
    trace = planning_api._Trace(state, run_id, USAGE_STEP, model)
    try:
        pages = planning_api._all_pages(state, config)
        sections = sections_from_pages(pages, planning_api._urls(state))
        store.add_event(run_id, "step", f"{USAGE_STEP}: reading {len(pages)} pages for usage figures", USAGE_STEP)
        usage = run_usage(spec.metadata.name, spec.metadata.service, resources, sections,
                          {p.id: p.owner for p in pages}, llm, state.runner.data_dir, state.runner.approvals,
                          log=lambda m: store.add_event(run_id, "log", m, USAGE_STEP), trace=trace, model=model)
        run.report["usage"] = {"facts": len(usage["facts"]), "rejected": len(usage["rejected"]),
                               "missing": usage["missing"]}
        planning_api._finish(state, run, RunStatus.SUCCEEDED,
                             f"{len(usage['facts'])} figures found, {len(usage['missing'])} missing"
                             + (" (asked in Jira)" if usage["missing"] else "") + ". Build again to update the estimate.")
    except Exception as e:  # noqa: BLE001 - an agent run reports its failure, it never crashes the server
        planning_api._finish(state, run, RunStatus.FAILED, f"usage reader failed: {e}")


@router.post("/migrations/{name}/usage", status_code=202)
def read_usage(name: str, state: mac_api.State = Depends(mac_api.get_state),
               config: planning_api.Planning = Depends(planning_api.get_config),
               user: str | None = Depends(signed_in)):
    spec = _spec(state, name)
    try:
        resources = build_resources(state.runner, spec)
    except CostInputError as e:
        raise HTTPException(409, str(e)) from e
    llm = planning_api._llm(config)
    planning_api._refuse_if_active(state, name, "The usage reader", mode="usage")
    run = planning_api._new_run(state, "usage", name)
    state.runner.store.add_event(run.id, "run", "Usage reader started: finding the figures the cost estimate needs"
                                 + (f" (requested by @{user})" if user else ""))
    state.submit_agent(lambda: _execute_usage(state, config, run.id, spec, resources, llm))
    return mac_api._run_view(run)


@router.get("/migrations/{name}/cost")
def cost(name: str, state: mac_api.State = Depends(mac_api.get_state)):
    spec = _spec(state, name)
    try:
        resources = build_resources(state.runner, spec)
        prices, notes = state.runner.price_loader(spec.target.region)  # the same prices Build uses
    except CostInputError as e:
        raise HTTPException(409, str(e)) from e
    except PricingError as e:
        raise HTTPException(503, f"no AWS prices: {e}") from e
    usage = load_usage(state.runner.data_dir, name)
    build = state.runner.store.latest(name, "build")
    return {"migration": name, "build": build.id if build else None,
            "estimate": estimate(resources, usage, prices, notes),
            "usage": None if usage is None else {k: usage.get(k) for k in ("read_at", "model", "facts", "rejected",
                                                                             "missing")}}
