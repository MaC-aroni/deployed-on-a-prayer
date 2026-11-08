import pytest
import yaml

from mac.spec import SpecError, parse_spec
from mac.validate import execution_order, follows_a_change, validate

from .conftest import DEMO_SPEC


def demo() -> dict:
    return yaml.safe_load(DEMO_SPEC.read_text(encoding="utf-8"))


def errors(data: dict) -> list[str]:
    return [str(i) for i in validate(parse_spec(yaml.safe_dump(data))) if i.level == "error"]


def step(data: dict, step_id: str) -> dict:
    return next(s for s in data["steps"] if s["id"] == step_id)


def test_demo_spec_is_valid():
    assert validate(parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))) == []


def test_order_is_stages_left_to_right():
    order = [s.id for s in execution_order(parse_spec(DEMO_SPEC.read_text(encoding="utf-8")))]
    assert order == ["preflight", "provision_network", "provision_iam", "db_migrate", "deploy_service", "smoke_test"]


def test_needs_reorders_steps_within_a_stage():
    data = demo()
    infra = [step(data, "provision_iam"), step(data, "provision_network")]
    infra[1]["needs"] = []
    infra[0]["needs"] = ["provision_network"]
    data["steps"] = [step(data, "preflight"), *infra] + [s for s in data["steps"]
                                                         if s["stage"] not in ("check", "infrastructure")]
    order = [s.id for s in execution_order(parse_spec(yaml.safe_dump(data)))]
    assert order.index("provision_network") < order.index("provision_iam")


def test_repo_refs_default_to_main_and_reject_junk():
    spec = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))
    assert spec.step("preflight").run.repo.ref == "main"
    data = demo()
    step(data, "preflight")["run"]["repo"] = "gitlab.com/x/y"
    with pytest.raises(SpecError, match="expected github.com"):
        parse_spec(yaml.safe_dump(data))


def test_branch_ref_is_parsed():
    data = demo()
    step(data, "preflight")["run"]["repo"] = "github.com/MaC-aroni/claims-smoke-tests@fix/dates"
    ref = parse_spec(yaml.safe_dump(data)).step("preflight").run.repo
    assert (ref.slug, ref.ref, ref.key) == ("MaC-aroni/claims-smoke-tests", "fix/dates",
                                            "github.com/MaC-aroni/claims-smoke-tests")


def test_unknown_fields_are_rejected():
    data = demo()
    step(data, "provision_network")["run"]["action"] = "apply"  # v0.1 field
    with pytest.raises(SpecError, match="Extra inputs"):
        parse_spec(yaml.safe_dump(data))


def test_cycle_is_reported():
    data = demo()
    step(data, "provision_network")["needs"] = ["provision_iam"]
    assert any("loop" in e for e in errors(data))


def test_needs_cannot_point_at_a_later_stage():
    data = demo()
    step(data, "provision_network")["needs"] = ["deploy_service"]
    assert any("later stage" in e for e in errors(data))


def test_unknown_references():
    data = demo()
    step(data, "deploy_service")["needs"] = ["nope"]
    step(data, "deploy_service")["requires_approval"] = ["APPR-NOPE"]
    step(data, "deploy_service")["stage"] = "nowhere"
    found = errors(data)
    assert any("unknown step 'nope'" in e for e in found)
    assert any("unknown approval 'APPR-NOPE'" in e for e in found)
    assert any("stage 'nowhere'" in e for e in found)


def test_mutating_steps_need_a_rollback():
    data = demo()
    del step(data, "deploy_service")["rollback"]
    assert any("need a rollback" in e for e in errors(data))


def test_iac_rolls_back_with_destroy_by_default():
    spec = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))
    assert spec.step("provision_network").effective_rollback.action == "destroy"


def test_check_steps_cannot_roll_back():
    data = demo()
    step(data, "smoke_test")["rollback"] = {"entrypoint": "x.py"}
    assert any("can't have a rollback" in e for e in errors(data))


def test_shape_rules_per_type():
    data = demo()
    step(data, "provision_iam")["run"] = {"repo": "github.com/a/b", "entrypoint": "x.py"}
    del step(data, "db_migrate")["verify"]
    found = errors(data)
    assert any("need run.path" in e for e in found)
    assert any("need verify" in e for e in found)


def test_db_migration_should_be_manual():
    data = demo()
    step(data, "db_migrate")["when"] = "auto"
    issues = validate(parse_spec(yaml.safe_dump(data)))
    assert [i.level for i in issues if "should be when: manual" in i.message] == ["warning"]


def test_duplicates_and_unused_approvals():
    data = demo()
    data["steps"].append(dict(step(data, "smoke_test")))
    data["approvals"].append({"id": "APPR-X", "type": "x", "jira": "MAC-9"})
    issues = validate(parse_spec(yaml.safe_dump(data)))
    assert any(i.level == "error" and "duplicate step 'smoke_test'" in i.message for i in issues)
    assert any(i.level == "warning" and i.where == "approvals.APPR-X" for i in issues)


def test_digest_ignores_formatting_but_not_content():
    text = DEMO_SPEC.read_text(encoding="utf-8")
    a = parse_spec(text)
    b = parse_spec("# a comment\n" + yaml.safe_dump(demo()))
    assert a.digest() == b.digest()
    data = demo()
    step(data, "smoke_test")["run"]["entrypoint"] = "checks/other.py"
    assert parse_spec(yaml.safe_dump(data)).digest() != a.digest()


def test_build_only_runs_checks_before_any_change():
    spec = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))
    assert not follows_a_change(spec, spec.step("preflight"))
    assert follows_a_change(spec, spec.step("smoke_test"))
