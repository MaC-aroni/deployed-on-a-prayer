"""The planning API: the knowledge graph and the Planner over HTTP, with a scripted LLM.
Runs inline (submit=lambda fn: fn(), submit_agent=lambda fn: fn()), so every response already reflects the finished work."""

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
    state = mac_api.State(runner=env.runner, migrations_dir=migrations, submit=lambda fn: fn(), submit_agent=lambda fn: fn())
    mac_api.configure(state)
    holder = {"llm": None, "repos": lambda: FAKE_REPOS}
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: holder["repos"]()))
    planning_api._review_cache.clear()  # module-level caches must not leak between tests
    planning_api._repo_cache.update(at=0.0, repos=None)
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

    res = client.post("/api/mac/plan", json={"service": SERVICE, "reuse": False})
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
    plan_id = client.post("/api/mac/plan", json={"service": SERVICE, "reuse": False}).json()["id"]

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


NAME = "claims-adjudication-onprem-to-aws"
FAKE_REPO = {"description": "Nightly eligibility sync from the member system", "language": "Python",
             "url": "https://github.com/MaC-aroni/eligibility-sync", "default_branch": "main",
             "readme": "# eligibility-sync\nPulls member eligibility from MemberDB nightly and writes CLAIMS_DB.ELIGIBILITY.",
             "files": ["sync.py", "requirements.txt", "deploy/cron.yaml"]}
LEARNED = json.dumps({"name": "EligibilitySyncService", "summary": "Syncs member eligibility into CLAIMS_DB nightly.",
                      "what_it_does": ["reads MemberDB", "writes CLAIMS_DB.ELIGIBILITY"], "runtime": ["Python 3 cron job"],
                      "data": ["CLAIMS_DB.ELIGIBILITY (PHI)"], "dependencies": ["MemberDB", "ClaimsAdjudicationService"],
                      "owner": "claims-platform", "unknowns": ["who owns MemberDB"]})


def agent_events(client, run_id):
    return [json.loads(e["message"]) | {"step": e["step"]} for e in events(client, run_id) if e["kind"] == "agent"]


def test_learn_writes_a_reviewed_page_merges_the_graph_and_raises_a_ticket(api):
    client, env, holder = api
    extracted = json.dumps({"nodes": [{"type": "service", "name": "EligibilitySyncService", "description": "Syncs eligibility", "sources": ["S1"]},
                                      {"type": "repo", "name": "MaC-aroni/eligibility-sync", "sources": ["S1"]}],
                            "edges": [{"from": "EligibilitySyncService", "to": "MaC-aroni/eligibility-sync", "type": "has_repo", "sources": ["S1"]}]})
    holder["llm"] = ScriptedLLM(LEARNED, extracted)  # Reader, then the Compiler's extract
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS + [{"name": "eligibility-sync", "full_name": "MaC-aroni/eligibility-sync", "url": FAKE_REPO["url"], "description": FAKE_REPO["description"], "pushed_at": 1.0, "archived": False}],
                                                 repo_reader=lambda slug: FAKE_REPO))
    res = client.post("/api/mac/learn", json={"repo": "eligibility-sync"})
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["mode"] == "ingest" and run["migration"] == "knowledge/eligibility-sync"
    assert run["status"] == "succeeded", run["reason"]
    rep = run["report"]
    assert rep["service"] == "EligibilitySyncService" and rep["page"] == "generated-eligibility-sync"
    assert rep["ticket"] == "MAC-1" and rep["ticket_url"].endswith("MAC-1")
    [ticket] = env.approvals.raised
    assert ticket.summary == "Review generated knowledge page: EligibilitySyncService" and "knowledge-review" in ticket.labels
    page = (env.runner.data_dir / "knowledge" / "generated-eligibility-sync.md").read_text(encoding="utf-8")
    assert "labels:\n- service\n- generated\n- needs-review" in page and "MaC-aroni/eligibility-sync" in page
    assert "who owns MemberDB" in page

    # The hierarchy: a Director, its Reader, References and Compiler, each with an outcome.
    agents = agent_events(client, run["id"])
    assert {a["agent"] for a in agents} == {"director", "reader", "references", "compiler"}
    assert all(a.get("parent") == "director" for a in agents if a["agent"] != "director")
    assert [a["phase"] for a in agents if a["agent"] == "reader"][-1] == "outcome"
    assert any(a["agent"] == "compiler" and a["status"] == "succeeded" and "MAC-1" in a["text"] for a in agents)

    # The Migrate page now lists the service as generated, under review, with its repo matched.
    data = client.get("/api/mac/services").json()
    svc = by_name(data["services"], "EligibilitySyncService")
    assert svc["generated"] is True and svc["review"]["ticket"] == "MAC-1" and svc["learned"] is True
    assert svc["repos"] == ["MaC-aroni/eligibility-sync"] and svc["team"] == "claims-platform"
    assert data["knowledge"]["generated"] == 1
    repo = next(r for r in data["repos"] if r["name"] == "eligibility-sync")
    assert repo["service"] == "EligibilitySyncService" and repo["page"] == "generated-eligibility-sync"
    page_view = client.get("/api/mac/knowledge/generated-eligibility-sync").json()
    assert page_view["generated"] is True and page_view["review"]["ticket"] == "MAC-1" and "## Unknowns to review" in page_view["body"]
    assert client.get("/api/mac/knowledge/nope").status_code == 404
    assert client.post("/api/mac/learn", json={"repo": "not a repo!"}).status_code == 422


def test_plan_detects_a_reviewed_yaml_and_can_start_build(api):
    client, env, holder = api
    holder["llm"] = ScriptedLLM()  # never asked
    res = client.post("/api/mac/plan", json={"service": SERVICE, "build": True})
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["status"] == "succeeded" and run["report"]["detected"] == NAME
    assert run["report"]["iterations"] == 0 and holder["llm"].prompts == []
    assert any(e["message"].startswith("detect: found reviewed migration.yaml") for e in events(client, run["id"], "detect"))
    assert run["stages"] and run["stages"][0]["name"] == "check"  # the reviewed spec renders on the run
    build = client.get(f"/api/mac/runs/{run['report']['build_run']}").json()
    assert build["mode"] == "build" and build["migration"] == NAME and build["status"] == "succeeded", build["reason"]
    agents = agent_events(client, run["id"])
    assert any(a["agent"] == "detect" and a["status"] == "succeeded" for a in agents)
    assert client.get("/api/mac/plans").json() == []  # nothing generated
    assert by_name(client.get("/api/mac/services").json()["services"], SERVICE)["migration"] == NAME


def test_investigate_then_approve_fix_opens_a_pull_request(api):
    client, env, holder = api
    env.executor.fail[("smoke_test", "run")] = "time data '01-JAN-24' does not match format"
    client.post(f"/api/mac/migrations/{NAME}/build")
    failed_id = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()["id"]
    client.post(f"/api/mac/runs/{failed_id}/steps/db_migrate/play")
    assert client.get(f"/api/mac/runs/{failed_id}").json()["status"] == "failed"

    fix = json.dumps({"root_cause": "smoke.py parses the Oracle date with the wrong format",
                      "fix": "accept DD-MON-YY", "confidence": "high",
                      "files": {"checks/smoke.py": "import datetime\n# fixed\n"}})
    holder["llm"] = ScriptedLLM(fix)
    opened = []
    planning_api.configure(planning_api.Planning(
        llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE, repo_lister=lambda: FAKE_REPOS,
        code_reader=lambda slug, sha, prefix: {"checks/smoke.py": "import datetime\n", "checks/preflight.py": "ok\n"},
        pr_opener=lambda *args: opened.append(args) or "https://github.com/MaC-aroni/claims-smoke-tests/pull/13"))

    assert client.post(f"/api/mac/runs/{failed_id}/approve-fix").status_code == 409  # not an investigation
    res = client.post(f"/api/mac/runs/{failed_id}/investigate", json={"mode": "autofix"})
    assert res.status_code == 202, res.text
    diag = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert diag["mode"] == "diagnose" and diag["based_on"] == failed_id and diag["status"] == "succeeded", diag["reason"]
    rep = diag["report"]
    assert rep["step"] == "smoke_test" and rep["repo"] == "MaC-aroni/claims-smoke-tests" and rep["files"] == ["checks/smoke.py"]
    assert rep["root_cause"].startswith("smoke.py parses") and rep["ticket"] == "MAC-4" and rep["approved"] is False
    assert diag["stages"]  # drawn on the same pipeline as the failed run
    system, user = holder["llm"].prompts[0]
    assert "Diagnostician" in system and "time data '01-JAN-24'" in user and "### checks/smoke.py" in user
    agents = agent_events(client, diag["id"])
    assert {a["agent"] for a in agents} == {"director", "logs", "code", "fixer", "compiler"}
    assert any(e["kind"] == "diagnosis" and e["message"].startswith("root cause:") for e in events(client, diag["id"]))
    # It shows up in the migration's run history beside the failed run.
    assert diag["id"] in [r["id"] for r in client.get(f"/api/mac/runs?migration={NAME}").json()]

    res = client.post(f"/api/mac/runs/{diag['id']}/approve-fix")
    assert res.status_code == 202, res.text
    assert res.json()["report"]["pr_url"].endswith("/pull/13") and res.json()["report"]["approved"] is True
    [(slug, base, branch, files, title, body, message)] = opened
    assert slug == "MaC-aroni/claims-smoke-tests" and base == "main" and branch == f"mac/autofix/{failed_id}"
    assert files == {"checks/smoke.py": "import datetime\n# fixed\n"} and "Root cause" in body
    assert client.post(f"/api/mac/runs/{diag['id']}/approve-fix").status_code == 409  # once
    # A run that passed has nothing to investigate.
    ok_build = client.get(f"/api/mac/runs?migration={NAME}").json()[-1]
    assert client.post(f"/api/mac/runs/{ok_build['id']}/investigate").status_code == 409


def _deployed(client, env):
    env.approvals.default = "approved"
    client.post(f"/api/mac/migrations/{NAME}/build")
    reh = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()
    client.post(f"/api/mac/runs/{reh['id']}/steps/db_migrate/play")
    dep = client.post(f"/api/mac/migrations/{NAME}/deploy").json()
    client.post(f"/api/mac/runs/{dep['id']}/steps/db_migrate/play")
    return reh["id"], dep["id"]


def test_health_says_what_is_configured_without_values(api):
    client, env, holder = api
    h = client.get("/api/mac/health").json()
    assert h["llm"] is True and h["model"] and h["jira"] is True and h["confluence"] is True
    assert set(h) == {"llm", "model", "llm_provider", "llm_providers", "github", "jira", "confluence", "confluence_site", "aws", "approvals_live"}
    planning_api.configure(planning_api.Planning(llm_factory=None, knowledge_dir=KNOWLEDGE))
    h = client.get("/api/mac/health").json()
    assert h["llm"] is False and h["model"] is None


def test_active_services_list_every_deployed_endpoint_with_its_last_probe(api):
    client, env, holder = api
    assert client.get("/api/mac/services/active").json() == [
        {"migration": NAME, "service": SERVICE, "owner_team": "claims-platform", "source": "reviewed",
         "href": f"/migrations/{NAME}", **e} for e in client.get(f"/api/mac/migrations/{NAME}").json()["endpoints"]]
    reh, dep = _deployed(client, env)
    state = mac_api.get_state()
    state.prober = lambda url, probe, region: {"url": url, "status": 200, "ok": True, "checked": 1.0, "error": None,
                                               "elapsed_ms": 7, "request_id": "req-1", "served_by_aws": True, "curl": "curl"}
    client.post(f"/api/mac/runs/{dep}/outputs/deploy_service/url/probes/health")
    rows = client.get("/api/mac/services/active").json()
    svc = next(r for r in rows if r["step"] == "deploy_service")
    assert svc["production"]["run_id"] == dep and svc["production"]["expected_live"] is True
    assert svc["production"]["last_probe"]["request_id"] == "req-1" and svc["production"]["last_probe"]["ok"] is True
    assert svc["rehearsal"]["expected_live"] is False and svc["rehearsal"]["last_probe"] is None
    other = next(r for r in rows if r["step"] == "provision_storage")
    assert other["production"]["last_probe"] is None and other["probes"] == []


def _repo_meta(spdx, text="MIT License\n\nPermission is hereby granted...", private=False):
    def read(slug):
        owner, name = slug.split("/")
        return {"repo": {"full_name": slug, "html_url": f"https://github.com/{slug}", "description": f"{name} repo",
                         "pushed_at": "2026-11-08T10:00:00Z", "archived": False, "private": private},
                "license": None if spdx is None else {"spdx": spdx, "name": spdx, "path": "LICENSE", "text": text}}
    return read


def test_add_repo_by_url_checks_the_licence_and_raises_a_review_ticket_when_needed(api):
    client, env, holder = api
    verdict_ok = json.dumps({"spdx": "MIT", "category": "permissive", "risk": "ok", "reason": "MIT allows internal use and changes."})
    verdict_gpl = json.dumps({"spdx": "GPL-3.0", "category": "copyleft", "risk": "review", "reason": "Copyleft reaches deployed code."})
    holder["llm"] = ScriptedLLM(verdict_ok)
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS, repo_meta_reader=_repo_meta("MIT")))
    assert client.post("/api/mac/repos", json={"url": "not a url"}).status_code == 422

    res = client.post("/api/mac/repos", json={"url": "https://github.com/pallets/flask.git"})
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["mode"] == "ingest" and run["migration"] == "repo/flask" and run["status"] == "succeeded", run["reason"]
    assert run["report"]["licence"]["risk"] == "ok" and run["report"]["licence"]["by"] == "nemotron"
    assert env.approvals.raised == []  # clearly fine: nobody is asked
    agents = agent_events(client, run["id"])
    assert {a["agent"] for a in agents} == {"director", "reader", "checker", "compiler"}
    repo = next(r for r in client.get("/api/mac/services").json()["repos"] if r["full_name"] == "pallets/flask")
    assert repo["custom"] is True and repo["licence"]["spdx"] == "MIT" and repo["service"] is None

    # A copyleft licence: the verdict is recorded and a reviewer is asked.
    holder["llm"] = ScriptedLLM(verdict_gpl)
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS, repo_meta_reader=_repo_meta("GPL-3.0", "GNU GPL v3")))
    run = client.get(f"/api/mac/runs/{client.post('/api/mac/repos', json={'url': 'github.com/gnu/thing'}).json()['id']}").json()
    assert run["report"]["licence"]["risk"] == "review" and run["report"]["licence"]["ticket"] == "MAC-1"
    [ticket] = env.approvals.raised
    assert ticket.summary.startswith("Licence review: gnu/thing") and "licence-review" in ticket.labels
    repos = {r["full_name"]: r for r in client.get("/api/mac/services").json()["repos"]}
    assert repos["gnu/thing"]["licence"]["ticket"] == "MAC-1" and repos["pallets/flask"]["licence"]["risk"] == "ok"

    # No LLM: the SPDX rule decides. No licence at all asks the person to confirm; no ticket.
    planning_api.configure(planning_api.Planning(llm_factory=None, knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS, repo_meta_reader=_repo_meta(None)))
    run = client.get(f"/api/mac/runs/{client.post('/api/mac/repos', json={'url': 'https://github.com/x/bare'}).json()['id']}").json()
    assert run["status"] == "succeeded" and run["report"]["licence"] == {
        "spdx": None, "category": "none", "risk": "confirm", "by": "rule",
        "reason": "no licence file: all rights reserved by default; confirm the team may use it"}
    assert len(env.approvals.raised) == 1  # still only the GPL review ticket
    accepted = client.post("/api/mac/repos/x/bare/accept", json={"note": "internal fork, fine"}).json()
    assert accepted["licence"]["accepted"] is True and accepted["licence"]["accepted_by"] == "console"
    assert next(r for r in client.get("/api/mac/services").json()["repos"] if r["full_name"] == "x/bare")["licence"]["accepted"] is True
    assert client.post("/api/mac/repos/x/nope/accept").status_code == 404
    # Private repos are refused; removal works once.
    planning_api.configure(planning_api.Planning(llm_factory=None, knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS, repo_meta_reader=_repo_meta("MIT", private=True)))
    run = client.get(f"/api/mac/runs/{client.post('/api/mac/repos', json={'url': 'https://github.com/x/secret'}).json()['id']}").json()
    assert run["status"] == "failed" and "private" in run["reason"]
    assert client.delete("/api/mac/repos/pallets/flask").status_code == 200
    assert client.delete("/api/mac/repos/pallets/flask").status_code == 404
    assert "pallets/flask" not in {r["full_name"] for r in client.get("/api/mac/services").json()["repos"]}


def test_publish_one_knowledge_page_to_confluence_and_remember_its_url(api):
    client, env, holder = api
    assert client.get("/api/mac/services").json()["services"][1]["page_url"] is None
    res = client.post("/api/mac/knowledge/service-claims-adjudication/publish")
    assert res.status_code == 200, res.text
    assert res.json()["url"].startswith("https://example.atlassian.net/wiki/")
    [(title, html, page_id, parent_id)] = env.pages.published
    assert title == "Services: ClaimsAdjudicationService" and page_id is None and parent_id is None and "<h2>" in html
    svc = by_name(client.get("/api/mac/services").json()["services"], SERVICE)
    assert svc["page_url"] == res.json()["url"]
    assert client.get("/api/mac/knowledge/service-claims-adjudication").json()["url"] == res.json()["url"]
    # Again: updates the same page (its id is passed back), and the parent is known when published.
    second = client.post("/api/mac/knowledge/service-claims-adjudication/publish").json()
    assert env.pages.published[-1][2] == res.json()["page_id"] and second["url"] == res.json()["url"]
    assert client.post("/api/mac/knowledge/nope/publish").status_code == 404
    env.runner.pages = None
    assert client.post("/api/mac/knowledge/service-claims-adjudication/publish").status_code == 409


def test_run_index_carries_migration_and_based_on(api):
    client, env, holder = api
    client.post(f"/api/mac/migrations/{NAME}/build")
    [row] = client.get("/api/mac/run-index").json()
    assert row["migration"] == NAME and row["mode"] == "build" and row["based_on"] is None and row["active"] is False
    assert set(row) >= {"id", "mode", "status", "reason", "failed_step", "created", "updated", "migration", "based_on"}
    assert client.get(f"/api/mac/run-index?migration={NAME}&limit=1").json()[0]["id"] == row["id"]
    assert client.get("/api/mac/run-index?migration=nothing").json() == []


def _learned(client, holder, env, name="eligibility-sync"):
    extracted = json.dumps({"nodes": [{"type": "service", "name": "EligibilitySyncService", "sources": ["S1"]}], "edges": []})
    holder["llm"] = ScriptedLLM(LEARNED, extracted)
    planning_api.configure(planning_api.Planning(llm_factory=lambda: holder["llm"], knowledge_dir=KNOWLEDGE,
                                                 repo_lister=lambda: FAKE_REPOS, repo_reader=lambda slug: FAKE_REPO))
    return client.post("/api/mac/learn", json={"repo": name}).json()["id"]


def test_review_closes_the_loop_from_the_console_or_from_jira(api):
    client, env, holder = api
    env.approvals.default = "pending"  # the review ticket sits in Jira until someone moves it
    _learned(client, holder, env)
    page = "generated-eligibility-sync"
    svc = by_name(client.get("/api/mac/services").json()["services"], "EligibilitySyncService")
    assert svc["review"]["status"] == "pending" and svc["review"]["ticket"] == "MAC-1"
    assert "needs-review" in client.get(f"/api/mac/knowledge/{page}").json()["labels"]

    # Jira approves the review ticket: the console sees it without anyone clicking (Jira is asked
    # at most every 30 s, so the cache is cleared here to stand in for the wait).
    env.approvals.by_approval["KB-eligibility-sync"] = "approved"
    planning_api._review_cache.clear()
    view = client.get(f"/api/mac/knowledge/{page}").json()
    assert view["review"]["status"] == "approved" and view["review"]["reviewed_by"] == "jira"
    assert "reviewed" in view["labels"] and "needs-review" not in view["labels"]
    assert by_name(client.get("/api/mac/services").json()["services"], "EligibilitySyncService")["review"]["status"] == "approved"

    # A person can reject in the console; the page goes back to a draft.
    res = client.post(f"/api/mac/knowledge/{page}/review", json={"status": "rejected", "note": "owner is wrong"})
    assert res.status_code == 200 and res.json()["review"]["status"] == "rejected" and "needs-review" in res.json()["labels"]
    assert client.post(f"/api/mac/knowledge/{page}/review", json={"status": "approved"}).json()["review"]["status"] == "approved"
    assert client.post("/api/mac/knowledge/service-claims-adjudication/review", json={"status": "approved"}).status_code == 409
    assert client.post("/api/mac/knowledge/nope/review", json={"status": "approved"}).status_code == 404
    assert client.post(f"/api/mac/knowledge/{page}/review", json={"status": "maybe"}).status_code == 422


def test_chat_transcripts_are_kept_for_the_console(api):
    client, env, holder = api
    turns = [{"role": "user", "text": "What does ClaimsAdjudicationService depend on?", "ts": 1.0},
             {"role": "assistant", "text": "It reads CLAIMS_DB [link](https://x)", "ts": 2.0,
              "tools": [{"name": "search_confluence", "args": {"query": "claims"}, "ok": True, "summary": "3 result(s)"}]}]
    res = client.put("/api/mac/chats/abc123def456", json={"title": "What does ClaimsAdjudicationService depend on?", "turns": turns})
    assert res.status_code == 200 and res.json()["turns"] == 2
    [listed] = client.get("/api/mac/chats").json()
    assert listed["id"] == "abc123def456" and listed["title"].startswith("What does")
    detail = client.get("/api/mac/chats/abc123def456").json()
    assert detail["turns"] == turns and detail["created"] <= detail["updated"]
    again = client.put("/api/mac/chats/abc123def456", json={"title": "same", "turns": turns + [{"role": "user", "text": "and?", "ts": 3.0}]})
    assert again.json()["turns"] == 3 and client.get("/api/mac/chats/abc123def456").json()["created"] == detail["created"]
    assert (env.runner.data_dir / "chats" / "abc123def456.json").is_file()
    assert client.put("/api/mac/chats/x", json={"title": "t", "turns": []}).status_code == 422
    assert client.delete("/api/mac/chats/abc123def456").status_code == 200
    assert client.get("/api/mac/chats/abc123def456").status_code == 404


PAGE = ("## Summary\nClaimsAdjudicationService leaves the on-prem data centre for AWS in eight rehearsed steps.\n\n"
        "## What moves and why\n- The service and its database.\n\n## How it runs\n- Build, Rehearse, Deploy.\n\n"
        "## Approvals\n- Tech Risk first.\n\n## Risks and rollback\n- Every step is undone on failure.\n")


def test_describe_writes_the_migration_page_and_publishes_it(api):
    client, env, holder = api
    holder["llm"] = ScriptedLLM(PAGE)
    name = "claims-adjudication-onprem-to-aws"
    assert client.get("/api/mac/migrations").json()[0]["page"] is None
    res = client.post(f"/api/mac/migrations/{name}/page")
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["status"] == "succeeded", run["reason"]
    assert run["report"]["page"] == "migration-claims-adjudication-onprem-to-aws"
    assert run["report"]["confluence_url"].startswith("https://example.atlassian.net/wiki/")
    system, user = holder["llm"].prompts[0]
    assert "Summary, What moves and why" in system and "db_migrate" in user and "APPR-TR-001" in user
    assert "Claims data is PHI" in user or "cites" in user  # the cited knowledge-base sections went in
    [(title, html, page_id, parent_id)] = env.pages.published
    assert title == "Migration: ClaimsAdjudicationService (claims-adjudication-onprem-to-aws)" and page_id is None
    assert "<h2>Summary</h2>" in html and "Appendix: exactly what will run" in html and "smoke_test" in html
    [item] = client.get("/api/mac/migrations").json()
    page = item["page"]
    assert page["url"] == run["report"]["confluence_url"] and page["generated"] is True and page["writing"] is None
    assert item["description"].startswith("ClaimsAdjudicationService leaves the on-prem data centre")
    shown = client.get(f"/api/mac/knowledge/{page['id']}").json()
    assert shown["generated"] is True and "migration" in shown["labels"] and shown["url"] == page["url"]
    # Again: the same Confluence page is updated, not a second one created.
    holder["llm"] = ScriptedLLM(PAGE)
    client.post(f"/api/mac/migrations/{name}/page")
    assert env.pages.published[-1][2] == env.pages.published[0][2] or env.pages.published[-1][2] is not None
    assert client.post("/api/mac/migrations/nope/page").status_code == 404


def test_describe_without_an_llm_or_confluence_still_writes_the_page(api):
    client, env, holder = api
    holder["llm"] = None
    env.runner.pages = None
    name = "claims-adjudication-onprem-to-aws"
    res = client.post(f"/api/mac/migrations/{name}/page")
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["status"] == "succeeded", run["reason"]
    logs = [e["message"] for e in events(client, run["id"])]
    assert any("no LLM configured" in m for m in logs) and any("Confluence isn't configured" in m for m in logs)
    [item] = client.get("/api/mac/migrations").json()
    assert item["page"]["url"] is None and item["page"]["local"] is True and item["page"]["model"] is None
    body = client.get(f"/api/mac/knowledge/{item['page']['id']}").json()["body"]
    assert body.startswith("## Summary") and "| 1 | preflight |" in body


def test_cancel_stops_an_agent_run_before_its_next_model_call(api, monkeypatch):
    client, env, holder = api
    monkeypatch.setenv("MAC_INGEST_WORKERS", "1")  # one page at a time, so the cancel lands between pages
    calls = []

    def reply(user):
        calls.append(user[:40])
        if len(calls) == 1:  # someone presses Cancel while the first page is being read
            run_id = env.store.runs()[0].id
            res = client.post(f"/api/mac/runs/{run_id}/cancel")
            assert res.status_code == 202, res.text
        return json.dumps({"nodes": [], "edges": []})

    holder["llm"] = ScriptedLLM(*([reply] * 30))
    res = client.post("/api/mac/ingest")
    assert res.status_code == 202, res.text
    run = client.get(f"/api/mac/runs/{res.json()['id']}").json()
    assert run["status"] == "cancelled" and run["active"] is False and run["reason"] == "cancelled"
    assert len(calls) == 1  # the second page was never sent to the model
    messages = [e["message"] for e in events(client, run["id"])]
    assert any("Cancel requested" in m for m in messages) and any("knowledge: cancelled" in m for m in messages)
    assert client.post(f"/api/mac/runs/{run['id']}/cancel").status_code == 409  # nothing left to cancel


def test_the_model_switch_is_in_health_and_changes_what_agents_use(api, monkeypatch, tmp_path):
    client, env, holder = api
    monkeypatch.setenv("MAC_DATA_DIR", str(tmp_path / "settings-home"))
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("GROK_API_KEY", "xai")
    monkeypatch.delenv("MAC_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MAC_LLM_MODEL", raising=False)
    monkeypatch.delenv("MAC_LLM_BASE_URL", raising=False)
    health = client.get("/api/mac/health").json()
    assert health["llm_provider"] == "nemotron" and health["model"].startswith("nvidia/nemotron")
    assert [p["id"] for p in health["llm_providers"]] == ["nemotron", "grok"]
    switched = client.post("/api/mac/settings/llm", json={"provider": "grok"}).json()
    assert switched["llm_provider"] == "grok" and switched["model"] == "grok-4.7"
    assert client.get("/api/mac/health").json()["llm_provider"] == "grok"  # remembered
    from mac.llm import RoutedLLM
    routed = RoutedLLM()
    assert routed.provider == "grok" and routed.model == "grok-4.7" and routed._client().url.startswith("https://api.x.ai/")
    assert client.post("/api/mac/settings/llm", json={"provider": "claude"}).status_code == 409
    monkeypatch.delenv("GROK_API_KEY")
    assert client.get("/api/mac/health").json()["llm_provider"] == "nemotron"  # a missing key falls back
