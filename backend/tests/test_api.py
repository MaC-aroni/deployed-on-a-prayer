import shutil

import pytest
from fastapi.testclient import TestClient

from app import auth, mac_api
from app.main import app
from mac.store import RunStatus, StepState

from .conftest import DB, DEMO_SPEC

NAME = "claims-adjudication-onprem-to-aws"


@pytest.fixture
def api(env, tmp_path):
    migrations = tmp_path / "migrations"
    (migrations / "claims").mkdir(parents=True)
    shutil.copy(DEMO_SPEC, migrations / "claims" / "migration.yaml")
    # Background work runs inline, so each response already reflects the finished work.
    state = mac_api.State(runner=env.runner, migrations_dir=migrations, submit=lambda fn: fn(),
                          poll_seconds=0, webhook_secret="hook-secret")
    mac_api.configure(state)
    auth.configure(auth.AuthConfig(required=False, repo="MaC-aroni/deployed-on-a-prayer", github=None, key=b"k" * 32))
    yield TestClient(app), env, state
    mac_api.configure(None)
    auth.configure(None)


def latest_run(client, run_id):
    return client.get(f"/api/mac/runs/{run_id}").json()


def test_lists_migrations_with_stages_and_latest_runs(api):
    client, _, _ = api
    [item] = client.get("/api/mac/migrations").json()
    assert item["name"] == NAME and item["valid"] is True
    assert item["stages"] == ["check", "infrastructure", "data", "release", "access", "verify"]
    assert item["latest"] == {"build": None, "rehearse": None, "deploy": None}


def test_migration_detail_is_ready_to_draw(api):
    client, _, _ = api
    detail = client.get(f"/api/mac/migrations/{NAME}").json()
    infra = detail["stages"][1]
    assert infra["name"] == "infrastructure"
    assert [s["id"] for s in infra["steps"]] == ["provision_storage", "provision_iam"]
    storage = infra["steps"][0]
    assert storage["rollback"] == "terraform destroy" and storage["requires_approval"] == ["APPR-TR-001"]
    assert storage["codegen"] == "llm" and infra["steps"][1]["codegen"] == "engineer"
    assert detail["stages"][2]["steps"][0]["when"] == "manual"
    assert [(a["approver"], a["after"], a["ticket"]) for a in detail["approvals"]] == [
        ("tech-risk", [], None), ("manager", [], None), ("claims-mcp-team", ["APPR-MGR-001"], None)]
    assert detail["design_page"] is None


def test_migration_detail_shows_tickets_and_design_page_after_build(api):
    client, env, _ = api
    env.approvals.default = "pending"
    client.post(f"/api/mac/migrations/{NAME}/build")
    detail = client.get(f"/api/mac/migrations/{NAME}").json()
    tickets = {a["id"]: a["ticket"] for a in detail["approvals"]}
    assert tickets["APPR-TR-001"]["key"] == "MAC-1" and tickets["APPR-MGR-001"]["key"] == "MAC-2"
    assert tickets["APPR-MCP-001"] is None  # waits for the manager
    assert detail["design_page"] == {"url": "https://example.atlassian.net/wiki/spaces/MAC/pages/1", "current": True}
    build = client.get(f"/api/mac/runs/{detail['latest']['build']['id']}").json()
    assert build["report"]["approvals"]["APPR-MCP-001"]["detail"].startswith("not requested until")
    assert build["report"]["design_page"]["status"] == "written"


def test_unknown_migration_is_404(api):
    client, _, _ = api
    assert client.get("/api/mac/migrations/nope").status_code == 404
    assert client.post("/api/mac/migrations/nope/build").status_code == 404


def test_full_flow_build_rehearse_play_deploy(api):
    client, env, _ = api
    resp = client.post(f"/api/mac/migrations/{NAME}/build")
    assert resp.status_code == 202
    assert latest_run(client, resp.json()["id"])["status"] == "succeeded"

    resp = client.post(f"/api/mac/migrations/{NAME}/rehearse", json={"ai": "autofix"})
    assert resp.status_code == 202
    run = latest_run(client, resp.json()["id"])
    assert run["status"] == "waiting" and run["diagnostics_mode"] == "autofix"
    data_stage = next(s for s in run["stages"] if s["name"] == "data")
    assert data_stage["steps"] == [{"id": "db_migrate", "state": "waiting"}]

    resp = client.post(f"/api/mac/runs/{run['id']}/steps/db_migrate/play")
    assert resp.status_code == 202
    assert latest_run(client, run["id"])["status"] == "succeeded"

    resp = client.post(f"/api/mac/migrations/{NAME}/deploy", json={"ai": "explain"})
    deploy = latest_run(client, resp.json()["id"])
    assert deploy["mode"] == "deploy" and deploy["status"] == "waiting"
    client.post(f"/api/mac/runs/{deploy['id']}/steps/db_migrate/play")
    assert latest_run(client, deploy["id"])["status"] == "succeeded"
    assert client.get(f"/api/mac/migrations/{NAME}").json()["latest"]["deploy"]["status"] == "succeeded"


def test_refusals_are_409_with_the_reason(api):
    client, _, _ = api
    resp = client.post(f"/api/mac/migrations/{NAME}/rehearse")
    assert resp.status_code == 409 and "Run Build first" in resp.json()["detail"]
    resp = client.post(f"/api/mac/migrations/{NAME}/deploy")
    assert resp.status_code == 409 and "Run Rehearse first" in resp.json()["detail"]


def test_deploy_never_takes_branches(api):
    client, _, _ = api
    resp = client.post(f"/api/mac/migrations/{NAME}/deploy", json={"branches": {DB: "x"}})
    assert resp.status_code == 409 and "always runs main" in resp.json()["detail"]


def test_second_play_click_is_refused(api, env):
    client, env, state = api
    queued = []
    state.submit = queued.append  # hold the work, as if the worker hasn't picked it up yet
    client.post(f"/api/mac/migrations/{NAME}/build")
    queued.pop()()
    rehearsal = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()
    queued.pop()()
    assert client.post(f"/api/mac/runs/{rehearsal['id']}/steps/db_migrate/play").status_code == 202
    second = client.post(f"/api/mac/runs/{rehearsal['id']}/steps/db_migrate/play")
    assert second.status_code == 409


def test_failure_and_events(api, env):
    client, env, _ = api
    env.executor.fail[("smoke_test", "run")] = "time data '01-JAN-24' does not match format"
    client.post(f"/api/mac/migrations/{NAME}/build")
    run_id = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()["id"]
    client.post(f"/api/mac/runs/{run_id}/steps/db_migrate/play")
    run = latest_run(client, run_id)
    assert run["status"] == "failed" and run["failed_step"] == "smoke_test"
    assert run["steps"]["provision_storage"] == "rolled_back"

    smoke_logs = client.get(f"/api/mac/runs/{run_id}/events", params={"step": "smoke_test"}).json()
    assert any(e["message"] == "run smoke_test" for e in smoke_logs)
    everything = client.get(f"/api/mac/runs/{run_id}/events").json()
    assert everything[-1]["kind"] == "diagnosis"
    later = client.get(f"/api/mac/runs/{run_id}/events", params={"after": everything[-3]["seq"]}).json()
    assert len(later) == 2


def test_stream_replays_events_then_ends(api):
    client, _, _ = api
    run_id = client.post(f"/api/mac/migrations/{NAME}/build").json()["id"]
    with client.stream("GET", f"/api/mac/runs/{run_id}/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert "event: run\n" in body and "Build started" in body
    assert body.rstrip().splitlines()[-2] == "event: end"
    # Resuming from an event id only sends what came after it.
    with client.stream("GET", f"/api/mac/runs/{run_id}/stream", headers={"Last-Event-ID": "9999"}) as resp:
        assert "Build started" not in "".join(resp.iter_text())


def test_undo_over_the_api(api):
    client, _, _ = api
    client.post(f"/api/mac/migrations/{NAME}/build")
    run_id = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()["id"]  # waits at db_migrate
    assert client.post(f"/api/mac/runs/{run_id}/undo").status_code == 202
    assert latest_run(client, run_id)["status"] == "undone"
    assert client.post(f"/api/mac/runs/{run_id}/undo").status_code == 409


def test_runs_list(api):
    client, _, _ = api
    client.post(f"/api/mac/migrations/{NAME}/build")
    client.post(f"/api/mac/migrations/{NAME}/build")
    runs = client.get("/api/mac/runs", params={"migration": NAME}).json()
    assert [r["mode"] for r in runs] == ["build", "build"]


def test_invalid_migration_is_listed_but_cannot_run(api):
    client, _, state = api
    broken = state.migrations_dir / "broken"
    broken.mkdir()
    (broken / "migration.yaml").write_text("apiVersion: mac/v0.1\n", encoding="utf-8")
    items = {i["name"]: i for i in client.get("/api/mac/migrations").json()}
    assert items["broken"]["valid"] is False and items["broken"]["problems"]
    resp = client.post("/api/mac/migrations/broken/build")
    assert resp.status_code == 409 and "can't be read" in resp.json()["detail"]


def test_recover_after_restart(env, spec_path):
    env.runner.build(spec_path)
    stuck = env.runner.start_rehearse(spec_path)
    stuck.next_action = None  # it had been picked up and was mid-work when the server died
    env.store.save(stuck)
    queued_build = env.runner.start_build(spec_path)  # queued, never picked up
    assert env.runner.recover() == [queued_build.id]
    assert env.store.get(stuck.id).status == RunStatus.ROLLBACK_FAILED
    assert env.runner.execute(queued_build.id).status == RunStatus.SUCCEEDED


def test_a_crash_mid_build_is_failed_not_rollback_failed(api, env):
    client, env, state = api
    env.runner.execute = lambda run_id: (_ for _ in ()).throw(TimeoutError("The read operation timed out"))
    run_id = client.post(f"/api/mac/migrations/{NAME}/build").json()["id"]
    run = latest_run(client, run_id)
    assert run["status"] == "failed" and "timed out" in run["reason"]
    assert "running" not in run["steps"].values() and "pending" not in run["steps"].values()


def test_recover_fails_a_build_cut_short_and_settles_its_steps(env, spec_path):
    stuck = env.runner.start_build(spec_path)
    stuck.next_action, stuck.status = None, RunStatus.RUNNING
    stuck.steps = {"preflight": StepState.SUCCEEDED, "provision_storage": StepState.RUNNING, "provision_iam": StepState.PENDING}
    env.store.save(stuck)
    assert env.runner.recover() == []
    after = env.store.get(stuck.id)
    assert after.status == RunStatus.FAILED and after.failed_step == "provision_storage"
    assert after.steps == {"preflight": "succeeded", "provision_storage": "failed", "provision_iam": "skipped"}


def test_recover_repairs_a_finished_run_left_with_running_steps(env, spec_path):
    old = env.runner.build(spec_path)
    old.steps["provision_storage"] = StepState.RUNNING  # as the server left it before settle() existed
    env.store.save(old)
    env.runner.recover()
    assert env.store.get(old.id).steps["provision_storage"] == "failed"


def _waiting_deploy(client, env):
    """A Deploy blocked on approvals: Build and Rehearse pass, approvals stay pending in Jira."""
    env.approvals.default = "pending"
    client.post(f"/api/mac/migrations/{NAME}/build")
    reh = client.post(f"/api/mac/migrations/{NAME}/rehearse").json()
    client.post(f"/api/mac/runs/{reh['id']}/steps/db_migrate/play")
    deploy = client.post(f"/api/mac/migrations/{NAME}/deploy").json()
    deploy = latest_run(client, deploy["id"])
    assert deploy["status"] == "waiting" and "waiting for approval" in deploy["reason"]
    return deploy


def test_approvals_follow_jira_without_a_click(api):
    client, env, state = api
    deploy = _waiting_deploy(client, env)
    detail = client.get(f"/api/mac/migrations/{NAME}").json()
    by_id = {a["id"]: a for a in detail["approvals"]}
    assert by_id["APPR-TR-001"]["status"] == "pending" and by_id["APPR-TR-001"]["checked"]
    assert by_id["APPR-MCP-001"]["status"] == "pending" and by_id["APPR-MCP-001"]["ticket"] is None
    assert detail["approvals_live"] is True  # the webhook is configured in this fixture

    # Nothing changed in Jira: a poll is quiet.
    assert all(not r["changed"] and not r["resumed"] for r in mac_api.poll_approvals_once(state))

    # The manager approves in Jira: the poller raises the MCP team's ticket (the chain) by itself.
    env.approvals.by_approval["APPR-MGR-001"] = "approved"
    [result] = mac_api.poll_approvals_once(state)
    assert result["changed"] == ["APPR-MGR-001"] and "APPR-MCP-001" in env.approvals.raised_ids()
    by_id = {a["id"]: a for a in client.get(f"/api/mac/migrations/{NAME}").json()["approvals"]}
    assert by_id["APPR-MGR-001"]["status"] == "approved" and by_id["APPR-MCP-001"]["ticket"]["key"]
    assert latest_run(client, deploy["id"])["status"] == "waiting"  # Tech Risk still pending

    # Everything approved: the waiting Deploy continues on its own, to the manual step.
    env.approvals.by_approval.update({"APPR-TR-001": "approved", "APPR-MCP-001": "approved"})
    [result] = mac_api.poll_approvals_once(state)
    assert result["resumed"] == [deploy["id"]]
    after = latest_run(client, deploy["id"])
    assert after["status"] == "waiting" and "manual" in after["reason"]
    messages = [e["message"] for e in client.get(f"/api/mac/runs/{deploy['id']}/events").json()]
    assert any("approvals changed in Jira" in m for m in messages)


def test_jira_webhook_syncs_the_ticket_owner(api):
    client, env, state = api
    deploy = _waiting_deploy(client, env)
    key = next(k for k, a in env.approvals.key_to_approval.items() if a == "APPR-TR-001")
    env.approvals.default = "approved"

    assert client.post("/api/mac/jira/webhook", json={"issue": {"key": key}}).status_code == 401
    assert client.post("/api/mac/jira/webhook?token=nope", json={"issue": {"key": key}}).status_code == 401
    resp = client.post("/api/mac/jira/webhook?token=hook-secret", json={"issue": {"key": "OTHER-1"}})
    assert resp.status_code == 200 and resp.json()["synced"] is None
    resp = client.post("/api/mac/jira/webhook?token=hook-secret", json={"issue": {"key": key}})
    assert resp.status_code == 200 and resp.json()["synced"] == NAME and resp.json()["resumed"] == [deploy["id"]]
    assert "manual" in latest_run(client, deploy["id"])["reason"]

    state.webhook_secret = None
    assert client.post("/api/mac/jira/webhook?token=x", json={}).status_code == 404


def test_manual_sync_endpoint(api):
    client, env, _ = api
    _waiting_deploy(client, env)
    env.approvals.default = "approved"
    resp = client.post(f"/api/mac/migrations/{NAME}/approvals/sync")
    assert resp.status_code == 200 and resp.json()["changed"]


def test_a_rejection_found_by_the_poller_fails_the_deploy_and_undoes_it(api):
    client, env, state = api
    deploy = _waiting_deploy(client, env)
    env.approvals.by_approval["APPR-TR-001"] = "rejected"
    mac_api.poll_approvals_once(state)
    after = latest_run(client, deploy["id"])
    assert after["status"] == "failed" and "rejected" in after["reason"]


def test_access_log_masks_the_webhook_secret_and_sign_in_codes():
    import logging

    from app.main import RedactSecrets
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4", "POST", "/api/mac/jira/webhook?token=s3cret&x=1", "1.1", 200), None)
    RedactSecrets().filter(record)
    assert "s3cret" not in record.getMessage() and "token=***&x=1" in record.getMessage()
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '"%s %s"',
                               ("GET", "/api/auth/callback?code=abc123&state=xyz"), None)
    RedactSecrets().filter(record)
    assert "abc123" not in record.getMessage() and "xyz" not in record.getMessage()
