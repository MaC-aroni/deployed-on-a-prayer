"""Explain · Report · Auto-fix with a scripted LLM: the words come from the model, every rule
that matters comes from code (what it may read, what it may change, when it stops)."""

import json

import pytest

from mac.aihelp import LLMDiagnostician, autofix_cycle
from mac.diagnostics import Failure, Mode
from mac.store import RunStatus

from .conftest import DB, DEMO_SPEC
from .test_agents import ScriptedLLM

EXPLANATION = ("## What went wrong\nmigrate.py crashed.\n## Likely cause\nDates are copied raw.\n"
               "## Where\nclaims_export.py to_item [S1]\n## What to do\nConvert DD-MON-YY to ISO 8601.")
REPORT = "# Oracle dates copied raw\n## Failure\n...\n## Root cause\nto_item()\n## Fix\n...\n"
FIXED_FILE = "def to_item(row):\n    return {'service_date': iso(row['SERVICE_DATE'])}\n"
GOOD_FIX = json.dumps({"summary": "Convert the date in to_item [S1].",
                       "files": [{"path": "claims_export.py", "content": FIXED_FILE}]})
BAD_FIX = json.dumps({"summary": "Loosen the check.",
                      "files": [{"path": "verify.py", "content": "pass\n"},
                                {"path": "tests/test_x.py", "content": "pass\n"},
                                {"path": "../other/x.py", "content": "x"}]})

CODE = {"migrate.py": "import boto3\n", "claims_export.py": "def to_item(row): return row\n",
        "verify.py": "check()\n", "rollback.py": "undo()\n", "data/claims_export.csv": "a,b\n",
        "tests/test_export.py": "def test(): pass\n", "README.md": "# repo\n"}


class FakeOps:
    """What auto-fix is allowed to do on GitHub, recorded instead of done."""

    def __init__(self, github):
        self.github = github
        self.pushes: list[tuple[str, str, str, dict]] = []
        self.prs: list[tuple[str, str, str, str]] = []
        self.reads: list[tuple[str, str, str]] = []

    def read_files(self, api, slug, sha, prefix):
        self.reads.append((slug, sha, prefix))
        return dict(CODE)

    def push_branch(self, api, slug, base_sha, branch, files, message):
        self.pushes.append((slug, base_sha, branch, files))
        self.github.branches[(f"github.com/{slug}", branch)] = "d" * 40  # Build can now resolve it
        return "d" * 40

    def open_pr(self, api, slug, base, branch, title, body):
        self.prs.append((slug, base, branch, title))
        return f"https://github.com/{slug}/pull/9"


def diagnostician(env, llm, **kw):
    ops = FakeOps(env.github)
    diag = LLMDiagnostician(llm, env.github, env.store, sections=[], read_files=ops.read_files,
                            push_branch=ops.push_branch, open_pr=ops.open_pr, **kw)
    env.runner.diagnostician = diag
    return diag, ops


def failing_rehearsal(env, spec_path, mode):
    env.runner.build(spec_path)
    env.executor.fail[("db_migrate", "run")] = "migrate.py exited with code 1"
    run = env.runner.rehearse(spec_path, mode)
    return env.runner.play(run.id, "db_migrate")


def test_explain_puts_the_models_words_on_the_run(env, spec_path):
    llm = ScriptedLLM(EXPLANATION)
    diagnostician(env, llm)
    run = failing_rehearsal(env, spec_path, "explain")
    assert run.status == RunStatus.FAILED
    diagnosis = [e.message for e in env.store.events(run.id) if e.kind == "diagnosis"]
    assert diagnosis == [EXPLANATION]
    system, user = llm.prompts[0]
    assert "Failed step: db_migrate" in user and "migrate.py exited with code 1" in user
    assert env.store.report(run.id) is None  # explain writes no report


def test_report_reads_the_code_at_the_commit_and_stores_markdown(env, spec_path):
    llm = ScriptedLLM(EXPLANATION, REPORT)
    _, ops = diagnostician(env, llm)
    run = failing_rehearsal(env, spec_path, "report")
    assert ops.reads == [("MaC-aroni/claims-db-migrate", "b" * 40, "")]
    report = env.store.report(run.id)
    assert report["markdown"] == REPORT.strip() and report["mode"] == "report"
    _, user = llm.prompts[1]
    assert "### migrate.py" in user and "### claims_export.py" in user
    assert "data/claims_export.csv" not in user and "tests/test_export.py" not in user  # never shown
    assert ops.pushes == []  # report mode changes nothing
    diagnosis = [e.message for e in env.store.events(run.id) if e.kind == "diagnosis"][0]
    assert f"/runs/{run.id}/report.md" in diagnosis


def test_autofix_pushes_only_allowed_files_and_reruns_until_it_passes(env, spec_path):
    llm = ScriptedLLM(EXPLANATION, REPORT, GOOD_FIX)
    diag, ops = diagnostician(env, llm)
    diag.continue_with = lambda path, overrides, autofix: autofix_cycle(env.runner, path, overrides, autofix)
    env.runner.build(spec_path)
    env.executor.fail[("db_migrate", "run")] = "migrate.py exited with code 1"
    # The "fix" works: once the branch is in use, db_migrate passes.
    original_execute = env.executor.execute

    def execute(ctx, action):
        if ctx.shas.get(DB) == "d" * 40:
            env.executor.fail.pop(("db_migrate", "run"), None)
        return original_execute(ctx, action)

    env.executor.execute = execute
    run = env.runner.rehearse(spec_path, "autofix")
    run = env.runner.play(run.id, "db_migrate")
    assert run.status == RunStatus.FAILED  # the original rehearsal still fails and undoes itself

    assert ops.pushes == [("MaC-aroni/claims-db-migrate", "b" * 40, f"mac/autofix/{run.id}", {"claims_export.py": FIXED_FILE})]
    runs = env.store.runs()
    retry_build = next(r for r in runs if r.mode == "build" and r.overrides)
    retry_rehearsal = next(r for r in runs if r.mode == "rehearse" and r.overrides)
    assert retry_build.overrides == {DB: f"mac/autofix/{run.id}"}
    assert retry_rehearsal.autofix["attempt"] == 1 and retry_rehearsal.autofix["parent"] == run.id
    assert retry_rehearsal.status == RunStatus.WAITING  # the manual step again
    done = env.runner.play(retry_rehearsal.id, "db_migrate")
    assert done.status == RunStatus.SUCCEEDED
    assert ops.prs == [("MaC-aroni/claims-db-migrate", "main", f"mac/autofix/{run.id}", "MaC auto-fix: ClaimsAdjudicationService rehearsal failure")]
    assert env.store.get(done.id).autofix["pr"].endswith("/pull/9")
    assert any("Pull request: https://github.com" in e.message for e in env.store.events(done.id) if e.kind == "diagnosis")


def test_autofix_refuses_checks_tests_and_escapes(env, spec_path):
    llm = ScriptedLLM(EXPLANATION, REPORT, BAD_FIX)
    diag, ops = diagnostician(env, llm)
    diag.continue_with = lambda *a: pytest.fail("nothing should be re-run")
    run = failing_rehearsal(env, spec_path, "autofix")
    assert ops.pushes == []
    diagnosis = [e.message for e in env.store.events(run.id) if e.kind == "diagnosis"][0]
    assert "no allowed change" in diagnosis and "verify script" in diagnosis and "protected" in diagnosis


def test_autofix_stops_after_the_limit_and_hands_over_a_pr(env, spec_path):
    llm = ScriptedLLM(EXPLANATION, REPORT)
    diag, ops = diagnostician(env, llm, max_attempts=3)
    spec = env.runner._load(spec_path)[0]
    failure = Failure(run_id="r9", mode="rehearse", step_id="db_migrate", reason="still broken", logs=["x"],
                      repo=DB, sha="d" * 40, spec_path=str(spec_path), attempt=3, branch="mac/autofix/r1", parent="r1")
    summary = diag.diagnose(spec, failure, Mode.AUTOFIX)
    assert "stopped after 3 attempts" in summary and "pull/9" in summary
    assert ops.prs[0][2] == "mac/autofix/r1" and ops.pushes == []


def test_a_failing_check_is_traced_to_the_step_that_caused_it(env, spec_path):
    culprit = json.dumps({"step": "db_migrate", "why": "it writes the dates the smoke test reads"})
    llm = ScriptedLLM(EXPLANATION, culprit, REPORT, GOOD_FIX)
    diag, ops = diagnostician(env, llm)
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "time data '01-JAN-24' does not match format '%Y-%m-%d'"
    run = env.runner.rehearse(spec_path, "autofix")
    run = env.runner.play(run.id, "db_migrate")
    assert run.failed_step == "smoke_test"
    assert ops.reads == [("MaC-aroni/claims-db-migrate", "b" * 40, "")]  # the culprit's repo, not smoke-tests
    assert ops.pushes and ops.pushes[0][0] == "MaC-aroni/claims-db-migrate"
    assert env.store.report(run.id)["step"] == "db_migrate"
    culprit_prompt = llm.prompts[1][1]
    assert "- db_migrate:" in culprit_prompt and "- smoke_test" not in culprit_prompt


def test_a_culprit_the_model_invents_is_ignored(env, spec_path):
    llm = ScriptedLLM(EXPLANATION, json.dumps({"step": "some_other_repo"}), REPORT)
    diag, ops = diagnostician(env, llm)
    env.runner.build(spec_path)
    env.executor.fail[("smoke_test", "run")] = "boom"
    run = env.runner.rehearse(spec_path, "autofix")
    env.runner.play(run.id, "db_migrate")
    assert ops.pushes == []  # falls back to the check itself, which auto-fix never patches


def test_diagnosis_in_progress_counts_as_busy(env, spec_path):
    seen = []
    llm = ScriptedLLM(lambda user: seen.append(set(env.runner.diagnosing)) or EXPLANATION)
    diagnostician(env, llm)
    run = failing_rehearsal(env, spec_path, "explain")
    assert seen == [{run.id}] and env.runner.diagnosing == set()


def test_an_llm_outage_never_changes_the_outcome(env, spec_path):
    class Down:
        def complete(self, *a, **k):
            raise TimeoutError("The read operation timed out")

    diagnostician(env, Down())
    run = failing_rehearsal(env, spec_path, "autofix")
    assert run.status == RunStatus.FAILED
    diagnosis = [e.message for e in env.store.events(run.id) if e.kind == "diagnosis"][0]
    assert diagnosis.startswith("AI help failed")


def test_the_demo_spec_is_what_the_tests_use():
    assert DEMO_SPEC.exists()
