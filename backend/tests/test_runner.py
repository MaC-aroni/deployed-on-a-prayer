import pytest

from mac.runner import GateError
from mac.store import RunStatus, StepState

from .conftest import DB, IAC

ALL = ["preflight", "provision_network", "provision_iam", "db_migrate", "deploy_service", "smoke_test"]
MUTATING = ["provision_network", "provision_iam", "db_migrate", "deploy_service"]


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


# ---- Build ---------------------------------------------------------------------------------

def test_build_plans_terraform_and_runs_only_early_checks(env, spec_path):
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert env.executor.calls == [("preflight", "run", "production"),
                                  ("provision_network", "plan", "production"),
                                  ("provision_iam", "plan", "production")]
    assert run.shas[IAC] == "a" * 40
    assert run.report["approvals"] == {"APPR-TR-001": "approved", "APPR-SEC-001": "approved",
                                       "APPR-DBA-001": "approved"}


def test_build_fails_on_guardrails(env, spec_path):
    env.github.failing.add(DB)
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.FAILED and run.reason == "guardrail checks failed"
    assert env.executor.calls == []  # nothing runs once a guardrail fails


def test_build_fails_on_a_failing_plan(env, spec_path):
    env.executor.fail[("provision_iam", "plan")] = "terraform plan exited with code 1"
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.FAILED and run.failed_step == "provision_iam"
    assert "terraform plan exited" in run.reason


def test_build_fails_on_spec_errors(env, spec_path):
    spec_path.write_text(spec_path.read_text().replace("needs: [provision_network]",
                                                       "needs: [provision_iam]"))
    run = env.runner.build(spec_path)
    assert run.status == RunStatus.FAILED and any("needs itself" in i for i in run.report["issues"])
    assert env.executor.calls == []


# ---- Gates between Build, Rehearse and Deploy --------------------------------------------------

def test_rehearse_needs_a_passing_build_of_this_exact_spec(env, spec_path):
    with pytest.raises(GateError, match="Run Build first"):
        env.runner.rehearse(spec_path)
    env.runner.build(spec_path)
    spec_path.write_text(spec_path.read_text().replace("checks/smoke.py", "checks/smoke2.py"))
    with pytest.raises(GateError, match="Run Build first"):
        env.runner.rehearse(spec_path)


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
    run = env.runner.rehearse(spec_path)
    assert run.status == RunStatus.WAITING
    with pytest.raises(GateError, match="still waiting"):
        env.runner.rehearse(spec_path)


# ---- Rehearse ----------------------------------------------------------------------------------

def test_rehearsal_runs_everything_then_undoes_it_newest_first(env, spec_path):
    run = passing_rehearsal(env, spec_path)
    assert run.status == RunStatus.SUCCEEDED
    assert run.completed == ALL
    assert all(state == StepState.ROLLED_BACK for s, state in run.steps.items() if s in MUTATING)


def test_rehearsal_runs_in_the_rehearsal_environment(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    rehearse_to_end(env, spec_path)
    assert {e for _, _, e in env.executor.calls} == {"rehearsal"}
    assert env.executor.actions("rollback") == list(reversed(MUTATING))


def test_rehearsal_ignores_approvals_but_stops_at_manual_steps(env, spec_path):
    env.approvals.default = "pending"
    env.runner.build(spec_path)
    run = env.runner.rehearse(spec_path)
    assert run.steps["db_migrate"] == StepState.WAITING
    assert run.steps["provision_network"] == StepState.SUCCEEDED


def test_play_only_works_on_the_waiting_step(env, spec_path):
    env.runner.build(spec_path)
    run = env.runner.rehearse(spec_path)
    with pytest.raises(GateError, match="isn't waiting"):
        env.runner.play(run.id, "deploy_service")


# ---- Failure means undo everything -------------------------------------------------------------

def test_failure_undoes_every_finished_step_in_reverse(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("smoke_test", "run")] = "time data '01-JAN-24' does not match format"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.FAILED and run.failed_step == "smoke_test"
    assert env.executor.actions("rollback") == ["deploy_service", "db_migrate", "provision_iam", "provision_network"]
    assert run.steps["smoke_test"] == StepState.FAILED
    assert all(run.steps[s] == StepState.ROLLED_BACK for s in MUTATING)


def test_unreached_steps_are_skipped(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("provision_iam", "run")] = "AccessDenied"
    run = env.runner.rehearse(spec_path)
    assert run.status == RunStatus.FAILED
    assert [run.steps[s] for s in ("db_migrate", "deploy_service", "smoke_test")] == [StepState.SKIPPED] * 3


def test_a_failed_terraform_step_undoes_its_own_partial_apply_first(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("provision_iam", "run")] = "apply failed halfway"
    env.runner.rehearse(spec_path)
    assert env.executor.actions("rollback") == ["provision_iam", "provision_network"]


def test_a_failed_script_step_does_not_undo_itself(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("deploy_service", "run")] = "deploy failed"
    rehearse_to_end(env, spec_path)
    assert env.executor.actions("rollback") == ["db_migrate", "provision_iam", "provision_network"]


def test_failed_verify_counts_as_the_step_failing(env, spec_path):
    env.runner.build(spec_path)
    env.executor.calls.clear()
    env.executor.fail[("db_migrate", "verify")] = "row counts differ: 10000 vs 9998"
    run = rehearse_to_end(env, spec_path)
    assert run.failed_step == "db_migrate" and "row counts" in run.reason
    assert env.executor.actions("rollback") == ["db_migrate", "provision_iam", "provision_network"]


def test_rollback_failure_keeps_undoing_the_rest_and_is_reported(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    env.executor.fail[("provision_iam", "rollback")] = "DeleteRole: AccessDenied"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.ROLLBACK_FAILED
    assert run.steps["provision_iam"] == StepState.ROLLBACK_FAILED
    assert run.steps["provision_network"] == StepState.ROLLED_BACK


def test_failure_asks_for_ai_help_with_the_step_logs(env, spec_path):
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    run = rehearse_to_end(env, spec_path, diagnostics_mode="report")
    failure, mode = env.diagnostician.calls[-1]
    assert (failure.step_id, mode, failure.reason) == ("smoke_test", "report", "boom")
    assert "run smoke_test" in failure.logs
    events = env.store.events(run.id)
    assert events[-1].kind == "diagnosis"


def test_ai_help_crashing_does_not_change_the_outcome(env, spec_path):
    def crash(*args):
        raise RuntimeError("model unavailable")

    env.diagnostician.diagnose = crash
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    run = rehearse_to_end(env, spec_path)
    assert run.status == RunStatus.FAILED
    assert "AI help failed" in env.store.events(run.id)[-1].message


# ---- Deploy ------------------------------------------------------------------------------------

def test_deploy_waits_for_approval_then_resumes(env, spec_path):
    passing_rehearsal(env, spec_path)
    env.approvals.tickets["MAC-2"] = "pending"  # Security
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.WAITING and run.steps["provision_iam"] == StepState.BLOCKED
    assert "MAC-2" in run.reason
    assert env.runner.resume(run.id).steps["provision_iam"] == StepState.BLOCKED  # still pending

    env.approvals.tickets["MAC-2"] = "approved"
    run = env.runner.resume(run.id)
    assert run.steps["db_migrate"] == StepState.WAITING
    run = env.runner.play(run.id, "db_migrate")
    assert run.status == RunStatus.SUCCEEDED
    assert {e for _, _, e in env.executor.calls} == {"production"}
    assert env.executor.actions("rollback") == []  # a successful deploy stays


def test_rejected_approval_fails_and_undoes(env, spec_path):
    passing_rehearsal(env, spec_path)
    env.approvals.tickets["MAC-2"] = "rejected"
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.FAILED and "rejected" in run.reason
    assert env.executor.actions("run") == ["preflight", "provision_network"]
    assert env.executor.actions("rollback") == ["provision_network"]
    assert env.diagnostician.calls == []  # nothing to diagnose; a person said no


def test_unreachable_jira_blocks_instead_of_failing(env, spec_path):
    from mac.integrations import IntegrationError

    passing_rehearsal(env, spec_path)

    def down(ticket):
        raise IntegrationError("Jira timed out")

    env.approvals.status = down
    run = env.runner.deploy(spec_path)
    assert run.status == RunStatus.WAITING and "Jira timed out" in run.reason


def test_autofix_never_applies_to_deploy(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path, diagnostics_mode="autofix")
    assert run.diagnostics_mode == "report"


def test_undo_a_finished_deploy(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path)
    run = env.runner.play(run.id, "db_migrate")
    env.executor.calls.clear()
    run = env.runner.undo(run.id)
    assert run.status == RunStatus.UNDONE
    assert env.executor.actions("rollback") == list(reversed(MUTATING))


def test_undo_uses_the_spec_the_run_started_with(env, spec_path):
    passing_rehearsal(env, spec_path)
    run = env.runner.deploy(spec_path)  # waits at db_migrate
    spec_path.write_text("this is no longer yaml: [")
    run = env.runner.undo(run.id)
    assert run.status == RunStatus.UNDONE
    assert env.executor.actions("rollback") == ["provision_iam", "provision_network"]


# ---- Auto-fix branches -------------------------------------------------------------------------

def test_branch_build_and_rehearse_but_never_deploy(env, spec_path):
    env.github.branches[(DB, "mac/autofix/x")] = "e" * 40
    build = env.runner.build(spec_path, overrides={DB: "mac/autofix/x"})
    assert build.status == RunStatus.SUCCEEDED  # branch guardrails reported, not blocking
    assert build.shas[DB] == "e" * 40
    with pytest.raises(GateError, match="different branches"):
        env.runner.rehearse(spec_path)
    run = env.runner.play(env.runner.rehearse(spec_path, overrides={DB: "mac/autofix/x"}).id, "db_migrate")
    assert run.status == RunStatus.SUCCEEDED
    with pytest.raises(GateError, match="auto-fix branches"):
        env.runner.deploy(spec_path)


def test_overrides_must_name_a_pipeline_repo(env, spec_path):
    with pytest.raises(GateError, match="doesn't use"):
        env.runner.build(spec_path, overrides={"github.com/x/y": "b"})
