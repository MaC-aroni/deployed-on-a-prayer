"""The planning API: the knowledge graph and the Planner over HTTP, with a scripted LLM.
Runs inline (submit=lambda fn: fn()), so every response already reflects the finished work."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app import mac_api, planning_api
from app.main import app
from mac.integrations import IntegrationError

from .conftest import DEMO_SPEC, REPO_ROOT
from .test_agents import DEMO_TEXT, ScriptedLLM, demo_graph

KNOWLEDGE = REPO_ROOT / "demo-data" / "confluence"
SERVICE = "ClaimsAdjudicationService"
FAKE_REPOS = [
    {"name": "claims-service-iac", "full_name": "MaC-aroni/claims-service-iac", "url": "https://github.com/MaC-aroni/claims-service-iac",
     "description": "Terraform for the claims service", "pushed_at": 1794100000.0, "archived": False},
    {"name": "deployed-on-a-prayer", "full_name": "MaC-aroni/deployed-on-a-prayer", "url": "https://github.com/MaC-aroni/deployed-on-a-prayer",
     "description": "MaC itself", "pushed_at": 1794100100.0, "archived": False},
]


class ExtractingLLM(ScriptedLLM):
    """For ingest: every page yields the same small, correctly cited graph fragment."""

    def default(self, user):
        return json.dumps({"nodes": [{"type": "service", "name": SERVICE, "description": "Adjudicates claims",
                                      "sources": ["S1"]},
                                     {"type": "repo", "name": "MaC-aroni/claims-service-iac", "sources": ["S1"]}],
                           "edges": [{"from": SERVICE, "to": "MaC-aroni/claims-service-iac", "type": "has_repo",
                                      "sources": ["S1"]}]})


@pytest.fixture
def api(env, tmp_path):
    migrations = tmp_path / "migrations"
    (migrations / "claims").mkdir(parents=True)
    shutil.copy(DEMO_SPEC, migrations / "claims" / "migration.yaml")
    state = mac_api.State(runner=env.runner, migrations_dir=migrations, submit=lambda fn: fn())
    mac_api.configure(state)
    holder = {"llm": None, "repos": lambda: FAKE_REPOS}
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: holder["repos"]()))
    yield TestClient(app), env, holder
    mac_api.configure(None)
    planning_api.configure(None)


def events(client, run_id, step=None):
    query = f"?step={step}" if step else ""
    return client.get(f"/api/mac/runs/{run_id}/events{query}").json()


def by_name(services, name):
    return next(s for s in services if s["name"] == name)


def test_services_come_from_the_knowledge_base_before_anything_is_learned(api):
    client, _, holder = api
    data = client.get("/api/mac/services").json()
    assert data["ingested"] is False and data["graph_updated"] is None
    assert data["knowledge"]["pages"] >= 10 and data["knowledge"]["dir"] == "confluence"
    names = [s["name"] for s in data["services"]]
    assert SERVICE in names and "Claims MCP Tool" in names
    svc = by_name(data["services"], SERVICE)
    assert svc["learned"] is False and svc["team"] == "claims-platform" and svc["plans"] == []
    assert "MaC-aroni/claims-service-iac" in svc["repos"] and svc["description"]
    # Every repo in the org is listed; the ones a service documents point at it.
    repos = {r["full_name"]: r for r in data["repos"]}
    assert repos["MaC-aroni/claims-service-iac"]["service"] == SERVICE
    assert repos["MaC-aroni/deployed-on-a-prayer"]["service"] is None
    assert data["repos_error"] is None

    def broken():
        raise IntegrationError("GET /orgs -> HTTP 403: rate limited")

    holder["repos"] = broken
    data = client.get("/api/mac/services").json()
    assert data["repos"] == [] and "rate limited" in data["repos_error"]
    assert by_name(data["services"], SERVICE)["learned"] is False  # the knowledge base still answers


def test_ingest_builds_the_graph_and_reports_every_page(api):
    client, env, holder = api
    holder["llm"] = ExtractingLLM()
    res = client.post("/api/mac/ingest")
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["mode"] == "ingest" and run["status"] == "succeeded"
    assert run["report"]["services"] == [SERVICE]
    assert (env.runner.data_dir / "graph.json").exists()
    page_lines = [e for e in events(client, run["id"], "knowledge") if e["kind"] == "log" and e["message"].startswith("extracted ")]
    assert len(page_lines) == len(holder["llm"].prompts) >= 10
    services = client.get("/api/mac/services").json()
    assert services["ingested"] is True
    svc = by_name(services["services"], SERVICE)
    assert svc["learned"] is True and "MaC-aroni/claims-service-iac" in svc["repos"] and svc["plans"] == []
    assert by_name(services["services"], "Claims MCP Tool")["learned"] is False  # the fake graph only knows one


def test_plan_shows_each_attempt_writes_the_file_and_lists_it(api):
    client, env, holder = api
    demo_graph().save(env.runner.data_dir / "graph.json")
    bad = DEMO_TEXT.replace("github.com/MaC-aroni/claims-service-iac", "github.com/someone/random-repo")
    holder["llm"] = ScriptedLLM(f"```yaml\n{bad}\n```", f"```yaml\n{DEMO_TEXT}\n```")

    res = client.post("/api/mac/plan", json={"service": SERVICE})
    assert res.status_code == 202, res.text
    run_id = res.json()["id"]
    run = client.get(f"/api/mac/runs/{run_id}").json()
    assert run["mode"] == "plan" and run["status"] == "succeeded", run["reason"]
    assert run["report"]["iterations"] == 2 and run["report"]["service"] == SERVICE
    assert "spec_text" not in run  # the run view leaves the YAML out; GET /plans/{id} has it
    assert run["stages"] and run["stages"][0]["name"] == "check"  # the run view draws the generated spec

    first = events(client, run_id, "attempt-1")
    assert any(e["kind"] == "step" and "running" in e["message"] for e in first)
    assert any(e["kind"] == "step" and "problems" in e["message"] for e in first)
    assert any(e["kind"] == "log" and "someone/random-repo isn't in the documentation" in e["message"] for e in first)
    assert any(e["kind"] == "step" and e["message"] == "attempt-2: valid" for e in events(client, run_id, "attempt-2"))
    assert any("migration.yaml written" in e["message"] for e in events(client, run_id, "plan"))
    assert any(e["message"] == f"knowledge: graph loaded, {len(demo_graph().nodes)} facts and 0 relations"
               for e in events(client, run_id, "knowledge"))

    assert (env.runner.data_dir / "plans" / run_id / "migration.yaml").read_text(encoding="utf-8").strip() == DEMO_TEXT.strip()
    [listed] = client.get("/api/mac/plans").json()
    assert listed["run_id"] == run_id and listed["service"] == SERVICE and listed["valid"] is True
    assert listed["latest"] == {"build": None, "rehearse": None, "deploy": None}

    detail = client.get(f"/api/mac/plans/{run_id}").json()
    assert detail["source"] == "generated" and detail["plan_run"] == run_id
    assert [s["name"] for s in detail["stages"]] == ["check", "infrastructure", "data", "release", "access", "verify"]
    assert detail["goal"] == f"migrate-{SERVICE.lower()}-to-aws" and detail["yaml"].strip() == DEMO_TEXT.strip()

    assert by_name(client.get("/api/mac/services").json()["services"], SERVICE)["plans"] == [run_id]
    # Reviewed migrations are untouched by generated plans.
    assert [m["name"] for m in client.get("/api/mac/migrations").json()] == ["claims-adjudication-onprem-to-aws"]


def test_plan_that_never_validates_fails_with_the_problems(api):
    client, env, holder = api
    demo_graph().save(env.runner.data_dir / "graph.json")
    holder["llm"] = ScriptedLLM(*["```yaml\nnot: a spec\n```"] * 4)
    run_id = client.post("/api/mac/plan", json={"goal": f"Migrate {SERVICE} to AWS"}).json()["id"]
    run = client.get(f"/api/mac/runs/{run_id}").json()
    assert run["status"] == "failed" and "4 attempt" in run["reason"]
    assert run["report"]["iterations"] == 4 and run["report"]["problems"]
    assert client.get("/api/mac/plans").json() == []


def test_plan_without_an_llm_or_a_goal_is_refused(api):
    client, _, _ = api
    assert client.post("/api/mac/plan", json={}).status_code == 422
    planning_api.configure(planning_api.Planning(llm_factory=None, knowledge_dir=KNOWLEDGE))
    res = client.post("/api/mac/plan", json={"service": SERVICE})
    assert res.status_code == 409 and "No LLM is configured" in res.json()["detail"]
    assert client.post("/api/mac/ingest").status_code == 409
    assert client.get("/api/mac/plans/nope").status_code == 404


def test_build_runs_on_a_generated_plan(api):
    client, env, holder = api
    demo_graph().save(env.runner.data_dir / "graph.json")
    holder["llm"] = ScriptedLLM(f"```yaml\n{DEMO_TEXT}\n```")
    plan_id = client.post("/api/mac/plan", json={"service": SERVICE}).json()["id"]

    res = client.post(f"/api/mac/plans/{plan_id}/build", json={})
    assert res.status_code == 202, res.text
    build = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert build["mode"] == "build" and build["status"] == "succeeded", build["reason"]
    assert build["spec_path"].endswith(f"plans/{plan_id}/migration.yaml")
    detail = client.get(f"/api/mac/plans/{plan_id}").json()
    assert detail["latest"]["build"]["id"] == build["id"]
    # Rehearse is still gated by the runner's own rules, answered as 409.
    env.runner.store  # noqa: B018 - the same store the runner API uses
    second = client.post(f"/api/mac/plans/{plan_id}/deploy", json={})
    assert second.status_code == 409
