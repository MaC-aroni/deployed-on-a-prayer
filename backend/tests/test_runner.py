import pytest

from mac.runner import GateError
from mac.store import RunStatus, StepState

from .conftest import ALL_STEPS, DB, IAC, MGR, MUTATING, OWNER, TR, demo_data, write_spec

PLANS = ["provision_storage", "provision_iam", "deploy_mcp_server", "deploy_service", "grant_mcp_access"]


def rehearse_to_end(env, spec_path, **kwargs):
    run = env.runner.rehearse(spec_path, **kwargs)
    assert run.status == RunStatus.WAITING and run.steps["db_migrate"] == StepState.WAITING
    return env.runner.play(run.id, "db_migrate")


def passing_rehearsal(env, spec_path):
    assert env.runner.build(spec_path).status == RunStatus.SUCCEEDED
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.SUCCEEDED
    env.executor.calls.clear()
    return run


def deploy_to_end(env, spec_path):
    run = env.runner.deploy(spec_path)
    if run.status == RunStatus.WAITING and run.steps.get("db_migrate") == StepState.WAITING:
        run = env.runner.play(run.id, "db_migrate")
    return run


# ---- Build ---------------------------------------------------------------------------------

def test_build_plans_terraform_and_runs_only_early_checks(env, spec_path):
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert env.executor.calls == [("preflight", "run", "production")] + [(s, "plan", "production") for s in PLANS]
    assert run.shas[IAC] == "a" * 40


def test_build_fails_on_guardrails(env, spec_path):
    env.github.failing.add(DB)
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.FAILED and run.reason == "guardrail checks failed"
    assert env.executor.calls == [] and env.approvals.raised == [] and env.writer.calls == []


def test_build_fails_on_a_failing_plan(env, spec_path):
    env.executor.fail[("provision_iam", "plan")] = "terraform plan exited with code 1"
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.FAILED and run.failed_step == "provision_iam"
    assert "terraform plan exited" in run.reason


def test_build_fails_on_spec_errors(env, spec_path):
    data = demo_data()
    data["steps"][2]["needs"] = ["provision_iam"]  # provision_iam needs itself
    run = env.runner.build(write_spec(spec_path, data))
    assert run.status == RunStatus.FAILED and any("needs itself" in i for i in run.report["issues"])
    assert env.executor.calls == []


# ---- Design page ---------------------------------------------------------------------------

def test_build_writes_the_design_page_from_the_spec_facts(env, spec_path):
    run = env.runner.build(spec_path)
    [facts] = env.writer.calls
    assert "grant_mcp_access" in facts and "aaaaaaa" in facts  # every step, with locked commits
    [(title, page_html, page_id, _)] = env.pages.published
    assert title == "MaC design: ClaimsAdjudicationService (claims-adjudication-onprem-to-aws)"
    assert page_id is None and "<h2>Overview</h2>" in page_html and "Appendix" in page_html
    assert run.report["design_page"]["status"] == "written"


def test_design_page_is_only_rewritten_when_the_spec_changes(env, spec_path):
    env.runner.build(spec_path)
    run = env.runner.build(spec_path)
    assert len(env.writer.calls) == 1 and run.report["design_page"]["status"] == "up to date"
    data = demo_data()
    data["approvals"][0]["summary"] = "Tech Risk: a revised plan"
    env.runner.build(write_spec(spec_path, data))
    assert len(env.writer.calls) == 2
    assert env.pages.published[-1][2] == "page-1"  # same page, updated in place


def test_llm_failure_never_fails_the_build(env, spec_path):
    env.writer.fail = "HTTP 503 from the model"
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert "not written" in run.report["design_page"]["status"]
    assert run.report["approvals"][TR]["status"] == "pending"
    assert "design page" in run.report["approvals"][TR]["detail"]
    assert TR not in env.approvals.raised_ids()  # Tech Risk can't review without the page


def test_without_llm_configured_the_build_still_works(env, spec_path):
    env.runner.design_writer = None
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.SUCCEEDED and "isn't configured" in run.report["design_page"]["status"]


# ---- Tickets and approval chains ------------------------------------------------------------

def test_build_raises_tickets_in_chain_order(env, spec_path):
    env.approvals.default = "pending"
    run = env.runner.build(spec_path)
    assert env.approvals.raised_ids() == [TR, MGR]  # the MCP team isn't asked yet
    owner = run.report["approvals"][OWNER]
    assert owner == {"status": "pending", "detail": f"not requested until {MGR} is approved",
                     "ticket": None, "url": None}
    assert run.report["approvals"][MGR]["ticket"] == "MAC-2"


def test_tech_risk_ticket_links_the_design_page(env, spec_path):
    env.runner.build(spec_path)
    tr = next(r for r in env.approvals.raised if r.approval_id == TR)
    assert tr.links == [("Design page", "https://example.atlassian.net/wiki/spaces/MAC/pages/1")]
    assert "provision_storage" in " ".join(tr.paragraphs) and tr.approver == "tech-risk"
    assert {"mac", TR} <= set(tr.labels)


def test_tickets_are_raised_once_per_spec_version(env, spec_path):
    env.runner.build(spec_path)
    env.runner.build(spec_path)
    assert env.approvals.raised_ids() == [TR, MGR, OWNER]
    data = demo_data()
    data["approvals"][0]["justification"] = "A different plan needs fresh sign-off."
    env.runner.build(write_spec(spec_path, data))
    assert env.approvals.raised_ids() == [TR, MGR, OWNER] * 2


def test_jira_down_during_build_is_reported_not_fatal(env, spec_path):
    env.approvals.down = "Jira timed out"
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert run.report["approvals"][TR] == {"status": "unknown", "detail": "Jira timed out",
                                           "ticket": None, "url": None}


# ---- Gates between Build, Rehearse and Deploy --------------------------------------------------

def test_rehearse_needs_a_passing_build_of_this_exact_spec(env, spec_path):
    with pytest.raises(GateError, match="Run Build first"):
        env.runner.rehearse(spec_path)
    env.runner.build(spec_path)
    data = demo_data()
    data["steps"][-1]["run"]["entrypoint"] = "checks/smoke2.py"
    with pytest.raises(GateError, match="Run Build first"):
        env.runner.rehearse(write_spec(spec_path, data))


def test_deploy_needs_a_passing_rehearsal(env, spec_path):
    env.runner.build(spec_path)
    with pytest.raises(GateError, match="Run Rehearse first"):
        env.runner.deploy(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    rehearse_to_end(env, spec_path)
    with pytest.raises(GateError, match="Run Rehearse first"):
        env.runner.deploy(spec_path)


def test_deploy_refuses_if_main_moved_since_rehearsal(env, spec_path):
    passing_rehearsal(env, spec_path)
    env.github.shas[DB] = "d" * 40
    with pytest.raises(GateError, match="claims-db-migrate"):
        env.runner.deploy(spec_path)


def test_deploy_uses_the_rehearsed_commits(env, spec_path):
    rehearsal = passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path)
    assert run.shas == rehearsal.shas and run.based_on == rehearsal.id


def test_only_one_active_run_per_migration(env, spec_path):
    env.runner.build(spec_path)
    assert env.runner.rehearse(spec_path).status == RunStatus.WAITING
    with pytest.raises(GateError, match="still waiting"):
        env.runner.rehearse(spec_path)


# ---- Rehearse ----------------------------------------------------------------------------------

def test_rehearsal_runs_everything_then_undoes_it_newest_first(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.SUCCEEDED and run.completed == ALL_STEPS
    assert env.executor.actions("rollback") == list(reversed(MUTATING))
    assert all(run.steps[s] == StepState.ROLLED_BACK for s in MUTATING)
    assert {e for _, _, e in env.executor.calls} == {"rehearsal"}


def test_rehearsal_ignores_approvals_but_stops_at_manual_steps(env, spec_path):
    env.approvals.default = "pending"
    env.runner.build(spec_path)
    run = env.runner.rehearse(spec_path)
    assert run.steps["db_migrate"] == StepState.WAITING
    assert run.steps["provision_storage"] == StepState.SUCCEEDED
    run = env.runner.play(run.id, "db_migrate")
    assert run.status == RunStatus.SUCCEEDED  # grant_mcp_access ran without waiting for Jira


def test_play_only_works_on_the_waiting_step(env, spec_path):
    env.runner.build(spec_path)
    run = env.runner.rehearse(spec_path)
    with pytest.raises(GateError, match="isn't waiting"):
        env.runner.play(run.id, "deploy_service")


# ---- Failure means undo everything -------------------------------------------------------------

def test_failure_undoes_every_finished_step_in_reverse(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("smoke_test", "run")] = "time data '01-JAN-24' does not match format '%Y-%m-%d'"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.FAILED and run.failed_step == "smoke_test"
    assert env.executor.actions("rollback") == list(reversed(MUTATING))
    assert run.steps["smoke_test"] == StepState.FAILED
    assert all(run.steps[s] == StepState.ROLLED_BACK for s in MUTATING)


def test_unreached_steps_are_skipped(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("provision_iam", "run")] = "AccessDenied"
    run = env.runner.rehearse(spec_path)
    assert run.status == RunStatus.FAILED
    assert [run.steps[s] for s in ALL_STEPS[3:]] == [StepState.SKIPPED] * 5


def test_a_failed_terraform_step_undoes_its_own_partial_apply_first(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("provision_iam", "run")] = "apply failed halfway"
    env.runner.rehearse(spec_path)
    assert env.executor.actions("rollback") == ["provision_iam", "provision_storage"]


def test_a_failed_script_step_does_not_undo_itself(env, spec_path):
    data = demo_data()
    deploy = next(s for s in data["steps"] if s["id"] == "deploy_service")
    deploy.update(type="script", run={"repo": IAC, "entrypoint": "deploy.py"}, rollback={"entrypoint": "undeploy.py"})
    write_spec(spec_path, data)
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("deploy_service", "run")] = "deploy failed"
    rehearse_to_end(env, spec_path)
    assert env.executor.actions("rollback") == ["deploy_mcp_server", "db_migrate", "provision_iam",
                                                "provision_storage"]


def test_failed_verify_counts_as_the_step_failing(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("db_migrate", "verify")] = "row counts differ: 12 vs 11"
    run = rehearse_to_end(env, spec_path)
    assert run.failed_step == "db_migrate" and "row counts" in run.reason
    assert env.executor.actions("rollback") == ["db_migrate", "provision_iam", "provision_storage"]


def test_rollback_failure_keeps_undoing_the_rest_and_is_reported(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    env.executor.fail[("provision_iam", "rollback")] = "DeleteRole: AccessDenied"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.ROLLBACK_FAILED
    assert run.steps["provision_iam"] == StepState.ROLLBACK_FAILED
    assert run.steps["provision_storage"] == StepState.ROLLED_BACK


def test_failure_asks_for_ai_help_with_the_step_logs(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    run = rehearse_to_end(env, spec_path, diagnostics_mode="report")
    failure, mode = env.diagnostician.calls[-1]
    assert (failure.step_id, mode, failure.reason) == ("smoke_test", "report", "boom")
    assert "run smoke_test" in failure.logs
    assert env.store.events(run.id)[-1].kind == "diagnosis"


def test_ai_help_crashing_does_not_change_the_outcome(env, spec_path):
    def crash(*args):
        raise RuntimeError("model unavailable")

    env.diagnostician.diagnose = crash
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.FAILED
    assert "AI help failed" in env.store.events(run.id)[-1].message


# ---- Deploy and approvals ------------------------------------------------------------------------

def test_deploy_with_everything_approved(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = deploy_to_end(env, spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert {e for _, _, e in env.executor.calls} == {"production"}
    assert env.executor.actions("rollback") == []  # a successful deploy stays


def test_deploy_waits_for_tech_risk_before_changing_anything(env, spec_path):
    passing_rehearsal(env, spec_path)
    env.approvals.by_approval[TR] = "pending"
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.WAITING and run.steps["provision_storage"] == StepState.BLOCKED
    assert "APPR-TR-001 (MAC-1)" in run.reason
    assert env.executor.actions("run") == ["preflight"]


def test_mcp_access_chain_manager_then_owner(env, spec_path):
    env.approvals.by_approval.update({MGR: "pending", OWNER: "pending"})
    passing_rehearsal(env, spec_path)
    run = deploy_to_end(env, spec_path)
    assert run.status == RunStatus.WAITING and run.steps["grant_mcp_access"] == StepState.BLOCKED
    assert "APPR-MCP-001 (not requested until APPR-MGR-001 is approved)" in run.reason
    assert OWNER not in env.approvals.raised_ids()

    env.approvals.by_approval[MGR] = "approved"  # the manager approves in Jira
    run = env.runner.resume(run.id)
    assert env.approvals.raised_ids()[-1] == OWNER  # now the MCP team is asked
    assert run.status == RunStatus.WAITING and "APPR-MCP-001 (MAC-3)" in run.reason

    env.approvals.by_approval[OWNER] = "approved"
    run = env.runner.resume(run.id)
    assert run.status == RunStatus.SUCCEEDED and run.steps["grant_mcp_access"] == StepState.SUCCEEDED


def test_manager_rejection_fails_and_undoes_everything(env, spec_path):
    env.approvals.by_approval[MGR] = "rejected"
    passing_rehearsal(env, spec_path)
    run = deploy_to_end(env, spec_path)
    assert run.status == RunStatus.FAILED and run.failed_step == "grant_mcp_access"
    assert "APPR-MGR-001 (MAC-2)" in run.reason and "APPR-MCP-001" in run.reason
    assert env.executor.actions("rollback") == ["deploy_service", "deploy_mcp_server", "db_migrate",
                                                "provision_iam", "provision_storage"]
    assert env.diagnostician.calls == []  # nothing to diagnose; a person said no


def test_deploy_waits_for_the_design_page_before_asking_tech_risk(env, spec_path):
    env.writer.fail = "model down"
    passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.WAITING and "design page" in run.reason
    env.writer.fail = None
    run = env.runner.undo(run.id)
    env.runner.build(spec_path)  # writes the page now; the commits are unchanged
    rehearse_to_end(env, spec_path)
    assert deploy_to_end(env, spec_path).status == RunStatus.SUCCEEDED


def test_unreachable_jira_blocks_instead_of_failing(env, spec_path):
    passing_rehearsal(env, spec_path)
    env.approvals.down = "Jira timed out"
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.WAITING and "Jira timed out" in run.reason


def test_autofix_never_applies_to_deploy(env, spec_path):
    passing_rehearsal(env, spec_path)
    assert env.runner.deploy(spec_path, diagnostics_mode="autofix").diagnostics_mode == "report"


def test_undo_a_finished_deploy(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = deploy_to_end(env, spec_path)
    env.executor.calls.clear()
    assert env.runner.undo(run.id).status == RunStatus.UNDONE
    assert env.executor.actions("rollback") == list(reversed(MUTATING))


def test_undo_uses_the_spec_the_run_started_with(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path)  # waits at db_migrate
    spec_path.write_text("this is no longer yaml: [")
    assert env.runner.undo(run.id).status == RunStatus.UNDONE
    assert env.executor.actions("rollback") == ["provision_iam", "provision_storage"]


# ---- Auto-fix branches -------------------------------------------------------------------------

def test_branch_build_and_rehearse_but_never_deploy(env, spec_path):
    env.github.branches[(DB, "mac/autofix/x")] = "e" * 40
    build = env.runner.build(spec_path, overrides={DB: "mac/autofix/x"})
    assert build.status == RunStatus.SUCCEEDED and build.shas[DB] == "e" * 40
    with pytest.raises(GateError, match="different branches"):
        env.runner.rehearse(spec_path)
    run = env.runner.play(env.runner.rehearse(spec_path, overrides={DB: "mac/autofix/x"}).id, "db_migrate")
    assert run.status == RunStatus.SUCCEEDED
    with pytest.raises(GateError, match="auto-fix branches"):
        env.runner.deploy(spec_path)


def test_overrides_must_name_a_pipeline_repo(env, spec_path):
    with pytest.raises(GateError, match="doesn't use"):
        env.runner.build(spec_path, overrides={"github.com/x/y": "b"})
