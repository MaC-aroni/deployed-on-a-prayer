"""The executor against real processes: real Python entrypoints, and a stand-in `terraform`
program that records its arguments, so the exact commands and state location are checked."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from mac.executors import Executor, StepContext, StepFailed, TerraformState
from mac.spec import parse_spec

from .conftest import DB, DEMO_SPEC, IAC, SMOKE

FAKE_TERRAFORM = """
import json, os, pathlib, sys
log = pathlib.Path(os.environ["FAKE_TF_LOG"])
override = pathlib.Path("mac_backend_override.tf")
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "env": os.environ.get("TF_VAR_mac_env"), "cache": os.environ.get("TF_PLUGIN_CACHE_DIR"),
                        "override": override.read_text(encoding="utf-8") if override.exists() else None}) + "\\n")
if sys.argv[1] == "output":
    print(json.dumps({"table_name": {"value": "mac-claims-" + os.environ["TF_VAR_mac_env"] + "-claims", "sensitive": False},
                      "url": {"value": "https://abc.lambda-url.us-east-1.on.aws/", "sensitive": False},
                      "password": {"value": "hunter2", "sensitive": True}}))
    sys.exit(0)
print("terraform says hi")
sys.exit(int(os.environ.get("FAKE_TF_EXIT", "0")) if sys.argv[1] != "init" else 0)
"""


class DirWorkspace:
    """Checks out from local directories instead of GitHub."""

    def __init__(self, repos: dict[str, Path]):
        self.repos = repos
        self.checkouts = []

    def checkout(self, repo, sha, dest):
        self.checkouts.append((repo.key, sha))
        shutil.copytree(self.repos[repo.key], dest, dirs_exist_ok=True)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repos = {key: tmp_path / "repos" / key.rsplit("/", 1)[1] for key in (IAC, DB, SMOKE)}
    for path in repos.values():
        path.mkdir(parents=True)
    write = lambda key, rel, text: (repos[key] / rel).parent.mkdir(parents=True, exist_ok=True) or \
        (repos[key] / rel).write_text(text, encoding="utf-8")
    write(DB, "migrate.py", "import os\nprint('copying for', os.environ['MAC_ENV'], os.environ['MAC_TARGET_ACCOUNT'])\n")
    write(DB, "verify.py", "import sys\nprint('row counts differ')\nsys.exit(3)\n")
    write(SMOKE, "checks/preflight.py", "import os\nprint(os.environ['MAC_ACTION'], os.environ['MAC_STEP_ID'])\n")
    write(IAC, "terraform/storage/main.tf", "# a module\n")
    fake_tf = tmp_path / "fake_terraform.py"
    fake_tf.write_text(FAKE_TERRAFORM, encoding="utf-8")
    log = tmp_path / "tf.log"
    monkeypatch.setenv("FAKE_TF_LOG", str(log))

    workspace = DirWorkspace(repos)
    executor = Executor(workspace, tmp_path / "work", TerraformState("mac-state", "us-east-1"),
                        terraform=[sys.executable, str(fake_tf)])
    spec = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))
    lines: list[str] = []

    def ctx(step_id, mode="rehearse"):
        return StepContext(spec=spec, step=spec.step(step_id), mode=mode, run_id="run1",
                           shas={IAC: "a" * 40, DB: "b" * 40, SMOKE: "c" * 40},
                           run_dir=tmp_path / "rundir", log=lines.append)

    def tf_calls():
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return executor, workspace, ctx, lines, tf_calls


def test_entrypoint_runs_with_mac_environment(setup):
    executor, workspace, ctx, lines, _ = setup
    executor.execute(ctx("db_migrate"), "run")
    account = parse_spec(DEMO_SPEC.read_text(encoding="utf-8")).target.account
    assert f"copying for rehearsal {account}" in lines
    assert workspace.checkouts == [(DB, "b" * 40)]


def test_failing_entrypoint_raises_with_output_logged(setup):
    executor, _, ctx, lines, _ = setup
    with pytest.raises(StepFailed, match="verify.py exited with code 3"):
        executor.execute(ctx("db_migrate"), "verify")
    assert "row counts differ" in lines


def test_missing_entrypoint_is_a_clear_failure(setup):
    executor, _, ctx, _, _ = setup
    with pytest.raises(StepFailed, match="rollback.py doesn't exist in MaC-aroni/claims-db-migrate@bbbbbbb"):
        executor.execute(ctx("db_migrate"), "rollback")


def test_each_action_gets_a_fresh_checkout_and_cleans_it_up(setup, tmp_path):
    executor, workspace, ctx, _, _ = setup
    executor.execute(ctx("preflight", mode="build"), "run")
    executor.execute(ctx("preflight", mode="build"), "run")
    assert len(workspace.checkouts) == 2
    assert not (tmp_path / "work" / "run1" / "preflight-run").exists()  # logs are in the store


def test_terraform_shares_one_provider_cache_and_cleans_up(setup, tmp_path):
    executor, _, ctx, _, tf_calls = setup
    executor.execute(ctx("provision_storage", mode="build"), "plan")
    assert all(c["cache"] == str(tmp_path / "tf-plugin-cache") for c in tf_calls())
    assert (tmp_path / "tf-plugin-cache").is_dir()
    assert not (tmp_path / "work" / "run1").exists() or not any((tmp_path / "work" / "run1").iterdir())


def test_prune_keeps_only_active_runs(setup, tmp_path):
    executor, *_ = setup
    for run in ("old1", "old2", "active"):
        (tmp_path / "work" / run / "step-run").mkdir(parents=True)
    assert executor.prune({"active"}) == 2
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == ["active"]


def test_terraform_apply_uses_s3_state_per_environment_and_step(setup):
    executor, _, ctx, lines, tf_calls = setup
    executor.execute(ctx("provision_storage"), "run")
    init, apply, output = tf_calls()  # output: the step declares outputs
    assert init["args"][0] == "init" and output["args"][0] == "output"
    assert apply["args"][:2] == ["apply", "-input=false"] and "-auto-approve" in apply["args"]
    assert apply["env"] == "rehearsal"
    assert Path(apply["cwd"]).as_posix().endswith("provision_storage-apply/terraform/storage")
    assert 'key          = "mac/claims-adjudication-onprem-to-aws/rehearsal/provision_storage.tfstate"' \
        in apply["override"]
    assert "use_lockfile = true" in apply["override"]
    assert "terraform says hi" in lines


def test_production_and_rehearsal_state_never_mix(setup):
    executor, _, ctx, _, tf_calls = setup
    executor.execute(ctx("provision_storage", mode="deploy"), "rollback")
    destroy = tf_calls()[-1]
    assert destroy["args"][0] == "destroy"
    assert "/production/provision_storage.tfstate" in destroy["override"]


def test_build_plans(setup):
    executor, _, ctx, _, tf_calls = setup
    executor.execute(ctx("provision_storage", mode="build"), "plan")
    assert tf_calls()[-1]["args"][0] == "plan"


def test_terraform_failure_raises(setup, monkeypatch):
    executor, _, ctx, _, _ = setup
    monkeypatch.setenv("FAKE_TF_EXIT", "1")
    with pytest.raises(StepFailed, match="terraform apply exited with code 1"):
        executor.execute(ctx("provision_storage"), "run")


def test_terraform_without_state_bucket_refuses(setup):
    executor, _, ctx, _, _ = setup
    executor.tf_state = None
    with pytest.raises(StepFailed, match="MAC_TF_STATE_BUCKET"):
        executor.execute(ctx("provision_storage"), "run")


def test_hanging_command_times_out(setup):
    executor, workspace, ctx, _, _ = setup
    repo = workspace.repos[SMOKE]
    (repo / "checks" / "preflight.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    executor.timeout = 1
    with pytest.raises(StepFailed, match="took longer than 1s"):
        executor.execute(ctx("preflight"), "run")


def test_terraform_apply_returns_outputs_but_never_sensitive_ones(setup):
    executor, _, ctx, _, tf_calls = setup
    outputs = executor.execute(ctx("provision_storage"), "run")
    assert outputs["table_name"] == "mac-claims-rehearsal-claims" and "password" not in outputs
    assert ["output", "-json", "-no-color"] in [c["args"] for c in tf_calls()]


def test_plan_and_destroy_return_no_outputs(setup):
    executor, _, ctx, _, _ = setup
    assert executor.execute(ctx("provision_storage", mode="build"), "plan") == {}


def test_script_outputs_come_from_the_mac_outputs_file(setup, tmp_path):
    executor, workspace, ctx, _, _ = setup
    script = ("import json, os\n"
              "open(os.environ['MAC_OUTPUTS'], 'w').write(json.dumps({'rows': 3, 'table': 'claims'}))\n")
    (workspace.repos[DB] / "migrate.py").write_text(script, encoding="utf-8")
    assert executor.execute(ctx("db_migrate"), "run") == {"rows": "3", "table": "claims"}
    (workspace.repos[DB] / "migrate.py").write_text(
        "import os\nopen(os.environ['MAC_OUTPUTS'], 'w').write('rows=5\\nnote=ok\\n')\n", encoding="utf-8")
    assert executor.execute(ctx("db_migrate"), "run") == {"rows": "5", "note": "ok"}


def test_scripts_get_the_region_the_way_boto3_reads_it(setup, tmp_path):
    executor, workspace, ctx, lines, _ = setup
    (workspace.repos[DB] / "migrate.py").write_text(
        "import os\nprint(os.environ['AWS_DEFAULT_REGION'], os.environ['AWS_REGION'])\n", encoding="utf-8")
    executor.execute(ctx("db_migrate"), "run")
    assert "us-east-1 us-east-1" in lines
