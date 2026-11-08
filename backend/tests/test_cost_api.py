"""The cost API: the usage reader as a run, and the estimate recalculated on request. Runs inline."""

import json
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from app import mac_api, planning_api
from app.main import app

from .conftest import DEMO_SPEC, REPO_ROOT
from .cost_fixtures import SVC, ScriptedReader
from .test_cost import _plans_write_resources

KNOWLEDGE = REPO_ROOT / "demo-data" / "confluence"


@pytest.fixture
def api(env, tmp_path):
    migrations = tmp_path / "migrations"
    (migrations / "claims").mkdir(parents=True)
    shutil.copy(DEMO_SPEC, migrations / "claims" / "migration.yaml")
    state = mac_api.State(runner=env.runner, migrations_dir=migrations, submit=lambda fn: fn(),
                          submit_agent=lambda fn: fn())
    mac_api.configure(state)
    holder = {"llm": ScriptedReader()}
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE))
    name = yaml.safe_load(DEMO_SPEC.read_text(encoding="utf-8"))["metadata"]["name"]
    yield TestClient(app), env, holder, name, migrations / "claims" / "migration.yaml"
    mac_api.configure(None)
    planning_api.configure(None)


def test_usage_needs_a_build_first(api):
    client, _, _, name, _ = api
    res = client.post(f"/api/mac/migrations/{name}/usage")
    assert res.status_code == 409 and "Run Build first" in res.json()["detail"]
    assert client.get(f"/api/mac/migrations/{name}/cost").status_code == 409
    assert client.get("/api/mac/migrations/nope/cost").status_code == 404


def test_usage_then_cost(api):
    client, env, holder, name, spec = api
    _plans_write_resources(env)
    build = env.runner.build(spec)
    assert build.report["cost"]["status"] == "unavailable"  # no usage figures yet

    res = client.post(f"/api/mac/migrations/{name}/usage")
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["mode"] == "usage" and run["status"] == "succeeded", run["reason"]
    assert [m["metric"] for m in run["report"]["usage"]["missing"]] == ["avg_billed_duration_ms"]
    events = client.get(f"/api/mac/runs/{run['id']}/events").json()
    agents = [json.loads(e["message"])["agent"] for e in events if e["kind"] == "agent"]
    assert "usage" in agents and "usage:service-claims-capacity" in agents

    data = client.get(f"/api/mac/migrations/{name}/cost").json()
    assert data["build"] == build.id and data["estimate"]["status"] == "partial"
    assert data["estimate"]["unpriced"][0]["subject"] == SVC
    assert data["estimate"]["onprem"]["monthly_usd"] == 8640
    assert len(data["usage"]["facts"]) > 10


def test_usage_without_an_llm_is_refused(api):
    client, env, holder, name, spec = api
    _plans_write_resources(env)
    env.runner.build(spec)
    planning_api.configure(planning_api.Planning(llm_factory=None, knowledge_dir=KNOWLEDGE))
    res = client.post(f"/api/mac/migrations/{name}/usage")
    assert res.status_code == 409 and "No LLM" in res.json()["detail"]
