from mac.diagnostics import autofix_violations
from mac.integrations import classify_status
from mac.spec import parse_spec

from .conftest import DB, DEMO_SPEC, SMOKE

SPEC = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))


def test_autofix_may_change_migration_code():
    assert autofix_violations(SPEC, DB, ["migrate.py", "lib/dates.py"]) == []


def test_autofix_may_not_weaken_the_checks():
    problems = autofix_violations(SPEC, DB, ["verify.py"])
    assert problems == ["verify.py is a check or verify script; auto-fix can't change it"]
    assert autofix_violations(SPEC, SMOKE, ["checks/smoke.py"])  # the planted smoke test


def test_autofix_may_not_touch_ci_tests_owners_or_secrets():
    paths = [".github/workflows/ci.yml", "CODEOWNERS", "docs/CODEOWNERS", "tests/test_x.py",
             "src/test_dates.py", "dates_test.py", ".env", "config/.env.prod", "./.github/x.yml",
             r".github\workflows\ci.yml"]
    assert len(autofix_violations(SPEC, DB, paths)) == len(paths)


def test_autofix_only_touches_pipeline_repos():
    assert autofix_violations(SPEC, "github.com/someone/else", ["x.py"]) == [
        "github.com/someone/else isn't used by this pipeline"]


def test_jira_status_mapping():
    approved, rejected = {"approved", "done"}, {"rejected"}
    assert classify_status("Approved", approved, rejected) == "approved"
    assert classify_status("REJECTED", approved, rejected) == "rejected"
    assert classify_status("In Review", approved, rejected) == "pending"
