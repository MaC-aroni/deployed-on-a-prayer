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
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "env": os.environ.get("TF_VAR_mac_env"),
                        "override": override.read_text(encoding="utf-8") if override.exists() else None}) + "\\n")
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
    write(IAC, "terraform/network/main.tf", "# a module\n")
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
    assert "copying for rehearsal 000000000000" in lines
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


def test_each_action_gets_a_fresh_checkout(setup, tmp_path):
    executor, workspace, ctx, _, _ = setup
    executor.execute(ctx("preflight", mode="build"), "run")
    executor.execute(ctx("preflight", mode="build"), "run")
    assert len(workspace.checkouts) == 2
    assert (tmp_path / "work" / "run1" / "preflight-run").is_dir()


def test_terraform_apply_uses_s3_state_per_environment_and_step(setup):
    executor, _, ctx, lines, tf_calls = setup
    executor.execute(ctx("provision_network"), "run")
    init, apply = tf_calls()
    assert init["args"][0] == "init"
    assert apply["args"][:2] == ["apply", "-input=false"] and "-auto-approve" in apply["args"]
    assert apply["env"] == "rehearsal"
    assert Path(apply["cwd"]).as_posix().endswith("provision_network-apply/terraform/network")
    assert 'key          = "mac/claims-adjudication-onprem-to-aws/rehearsal/provision_network.tfstate"' \
        in apply["override"]
    assert "use_lockfile = true" in apply["override"]
    assert "terraform says hi" in lines


def test_production_and_rehearsal_state_never_mix(setup):
    executor, _, ctx, _, tf_calls = setup
    executor.execute(ctx("provision_network", mode="deploy"), "rollback")
    destroy = tf_calls()[-1]
    assert destroy["args"][0] == "destroy"
    assert "/production/provision_network.tfstate" in destroy["override"]


def test_build_plans(setup):
    executor, _, ctx, _, tf_calls = setup
    executor.execute(ctx("provision_network", mode="build"), "plan")
    assert tf_calls()[-1]["args"][0] == "plan"


def test_terraform_failure_raises(setup, monkeypatch):
    executor, _, ctx, _, _ = setup
    monkeypatch.setenv("FAKE_TF_EXIT", "1")
    with pytest.raises(StepFailed, match="terraform apply exited with code 1"):
        executor.execute(ctx("provision_network"), "run")


def test_terraform_without_state_bucket_refuses(setup):
    executor, _, ctx, _, _ = setup
    executor.tf_state = None
    with pytest.raises(StepFailed, match="MAC_TF_STATE_BUCKET"):
        executor.execute(ctx("provision_network"), "run")


def test_hanging_command_times_out(setup):
    executor, workspace, ctx, _, _ = setup
    repo = workspace.repos[SMOKE]
    (repo / "checks" / "preflight.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    executor.timeout = 1
    with pytest.raises(StepFailed, match="took longer than 1s"):
        executor.execute(ctx("preflight"), "run")
