import pytest
import yaml

from mac.spec import SpecError, parse_spec
from mac.validate import execution_order, follows_a_change, validate

from .conftest import ALL_STEPS, DEMO_SPEC, demo_data


def errors(data: dict) -> list[str]:
    return [str(i) for i in validate(parse_spec(yaml.safe_dump(data))) if i.level == "error"]


def step(data: dict, step_id: str) -> dict:
    return next(s for s in data["steps"] if s["id"] == step_id)


def approval(data: dict, approval_id: str) -> dict:
    return next(a for a in data["approvals"] if a["id"] == approval_id)


def demo_spec():
    return parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))


def test_demo_spec_is_valid():
    assert validate(demo_spec()) == []


def test_order_is_stages_left_to_right():
    assert [s.id for s in execution_order(demo_spec())] == ALL_STEPS


def test_needs_reorders_steps_within_a_stage():
    data = demo_data()
    step(data, "provision_storage")["needs"] = ["provision_iam"]
    order = [s.id for s in execution_order(parse_spec(yaml.safe_dump(data)))]
    assert order.index("provision_iam") < order.index("provision_storage")


def test_repo_refs_default_to_main_and_reject_junk():
    assert demo_spec().step("preflight").run.repo.ref == "main"
    data = demo_data()
    step(data, "preflight")["run"]["repo"] = "gitlab.com/x/y"
    with pytest.raises(SpecError, match="expected github.com"):
        parse_spec(yaml.safe_dump(data))


def test_branch_ref_is_parsed():
    data = demo_data()
    step(data, "preflight")["run"]["repo"] = "github.com/MaC-aroni/claims-smoke-tests@fix/dates"
    ref = parse_spec(yaml.safe_dump(data)).step("preflight").run.repo
    assert (ref.slug, ref.ref, ref.key) == ("MaC-aroni/claims-smoke-tests", "fix/dates",
                                            "github.com/MaC-aroni/claims-smoke-tests")


def test_old_versions_and_fields_are_rejected():
    data = demo_data()
    data["apiVersion"] = "mac/v0.2"
    with pytest.raises(SpecError, match="apiVersion"):
        parse_spec(yaml.safe_dump(data))
    data = demo_data()
    approval(data, "APPR-TR-001")["jira"] = "MAC-1"  # v0.2: MaC raises tickets itself now
    with pytest.raises(SpecError, match="Extra inputs"):
        parse_spec(yaml.safe_dump(data))
    data = demo_data()
    step(data, "provision_storage")["run"]["action"] = "apply"  # v0.1
    with pytest.raises(SpecError, match="Extra inputs"):
        parse_spec(yaml.safe_dump(data))


def test_approvals_need_an_approver_and_summary():
    data = demo_data()
    del approval(data, "APPR-MGR-001")["approver"]
    del approval(data, "APPR-MGR-001")["summary"]
    with pytest.raises(SpecError) as e:
        parse_spec(yaml.safe_dump(data))
    assert len(e.value.problems) == 2


def test_cycle_is_reported():
    data = demo_data()
    step(data, "provision_storage")["needs"] = ["provision_iam"]
    step(data, "provision_iam")["needs"] = ["provision_storage"]
    assert any("loop" in e for e in errors(data))


def test_needs_cannot_point_at_a_later_stage():
    data = demo_data()
    step(data, "provision_storage")["needs"] = ["deploy_service"]
    assert any("later stage" in e for e in errors(data))


def test_unknown_references():
    data = demo_data()
    step(data, "deploy_service")["needs"] = ["nope"]
    step(data, "deploy_service")["requires_approval"] = ["APPR-NOPE"]
    step(data, "deploy_service")["stage"] = "nowhere"
    found = errors(data)
    assert any("unknown step 'nope'" in e for e in found)
    assert any("unknown approval 'APPR-NOPE'" in e for e in found)
    assert any("stage 'nowhere'" in e for e in found)


def test_approval_after_rules():
    data = demo_data()
    approval(data, "APPR-MCP-001")["after"] = ["APPR-NOPE"]
    approval(data, "APPR-TR-001")["after"] = ["APPR-TR-001"]
    found = errors(data)
    assert any("after unknown approval 'APPR-NOPE'" in e for e in found)
    assert any("APPR-TR-001: is after itself" in e for e in found)


def test_approval_loop_is_reported():
    data = demo_data()
    approval(data, "APPR-MGR-001")["after"] = ["APPR-MCP-001"]
    assert any("approvals wait on each other in a loop" in e for e in errors(data))


def test_mutating_steps_need_a_rollback():
    data = demo_data()
    step(data, "db_migrate")["rollback"] = "none"
    assert any("need a rollback" in e for e in errors(data))


def test_iac_rolls_back_with_destroy_by_default():
    assert demo_spec().step("grant_mcp_access").effective_rollback.action == "destroy"


def test_check_steps_cannot_roll_back():
    data = demo_data()
    step(data, "smoke_test")["rollback"] = {"entrypoint": "x.py"}
    assert any("can't have a rollback" in e for e in errors(data))


def test_shape_rules_per_type():
    data = demo_data()
    step(data, "provision_iam")["run"] = {"repo": "github.com/a/b", "entrypoint": "x.py"}
    del step(data, "db_migrate")["verify"]
    found = errors(data)
    assert any("need run.path" in e for e in found)
    assert any("need verify" in e for e in found)


def test_db_migration_should_be_manual():
    data = demo_data()
    step(data, "db_migrate")["when"] = "auto"
    issues = validate(parse_spec(yaml.safe_dump(data)))
    assert [i.level for i in issues if "should be when: manual" in i.message] == ["warning"]


def test_duplicates_and_unused_approvals():
    data = demo_data()
    data["steps"].append(dict(step(data, "smoke_test")))
    data["approvals"].append({"id": "APPR-X", "type": "x", "approver": "x", "summary": "x"})
    issues = validate(parse_spec(yaml.safe_dump(data)))
    assert any(i.level == "error" and "duplicate step 'smoke_test'" in i.message for i in issues)
    assert any(i.level == "warning" and i.where == "approvals.APPR-X" for i in issues)


def test_digest_ignores_formatting_but_not_content():
    a = demo_spec()
    assert parse_spec("# a comment\n" + yaml.safe_dump(demo_data())).digest() == a.digest()
    data = demo_data()
    approval(data, "APPR-TR-001")["summary"] = "something else"
    assert parse_spec(yaml.safe_dump(data)).digest() != a.digest()


def test_build_only_runs_checks_before_any_change():
    spec = demo_spec()
    assert not follows_a_change(spec, spec.step("preflight"))
    assert follows_a_change(spec, spec.step("smoke_test"))


def test_every_repo_is_listed_once():
    assert sorted(demo_spec().repos()) == sorted([
        "github.com/MaC-aroni/claims-db-migrate", "github.com/MaC-aroni/claims-mcp-server",
        "github.com/MaC-aroni/claims-service-iac", "github.com/MaC-aroni/claims-smoke-tests"])


def test_codegen_says_who_writes_each_steps_code():
    spec = demo_spec()
    assert spec.step("provision_storage").codegen == "llm"
    assert {s.codegen for s in spec.steps if s.id != "provision_storage"} == {"engineer"}  # the default
    data = demo_data()
    step(data, "provision_iam")["codegen"] = "robot"
    with pytest.raises(SpecError, match="codegen"):
        parse_spec(yaml.safe_dump(data))
