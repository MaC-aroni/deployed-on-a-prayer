"""Runs one action of one step: checks out the repo at its locked commit into a fresh
directory, then runs the entrypoint or Terraform there. Knows nothing about ordering,
approvals or rollback; that's the runner's job."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .integrations import Workspace
from .spec import RepoRef, Spec, Step, StepType

# plan: Terraform preview, used by Build. run / verify / rollback: the step's three phases.
ActionName = Literal["plan", "run", "verify", "rollback"]
Mode = Literal["build", "rehearse", "deploy"]

PLAN_FILE = "mac.tfplan"  # Build's saved plan, read back with `terraform show -json`

# The attributes the cost estimate reads, per resource type. Nothing else leaves the plan.
COST_ATTRIBUTES = {
    "aws_lambda_function": ("function_name", "memory_size", "timeout", "architectures", "runtime",
                            "ephemeral_storage"),
    "aws_dynamodb_table": ("name", "billing_mode", "read_capacity", "write_capacity"),
}
NAME_ATTRIBUTES = ("function_name", "name", "role", "bucket")


def resources_path(run_dir: Path, step_id: str) -> Path:
    return Path(run_dir) / f"{step_id}.resources.json"


def plan_resources(plan: dict) -> list[dict]:
    """The managed resources a `terraform show -json` plan creates or keeps, with the few
    attributes the cost estimate needs. Sensitive attributes are never kept."""
    out = []
    for rc in plan.get("resource_changes") or []:
        change = rc.get("change") or {}
        actions = change.get("actions") or []
        if rc.get("mode") != "managed" or actions == ["delete"]:
            continue
        after = change.get("after") or {}
        sensitive = change.get("after_sensitive") or {}
        sensitive = sensitive if isinstance(sensitive, dict) else {}
        keep = COST_ATTRIBUTES.get(rc.get("type"), ())
        attributes = {k: after[k] for k in keep if k in after and not sensitive.get(k)}
        name = next((after[k] for k in NAME_ATTRIBUTES if isinstance(after.get(k), str) and not sensitive.get(k)), None)
        out.append({"address": rc.get("address", ""), "type": rc.get("type", ""), "name": name,
                    "actions": actions, "attributes": attributes})
    return out


class StepFailed(Exception):
    """The step's command failed. The message is what people see as the reason."""


@dataclass(frozen=True)
class TerraformState:
    """Where Terraform keeps state, so rollback can destroy exactly what apply created.
    One S3 object per migration, environment and step; locking via S3 itself."""

    bucket: str
    region: str
    prefix: str = "mac"

    def key(self, migration: str, env: str, step_id: str) -> str:
        return f"{self.prefix}/{migration}/{env}/{step_id}.tfstate"


@dataclass
class StepContext:
    spec: Spec
    step: Step
    mode: Mode
    run_id: str
    shas: dict[str, str]  # RepoRef.key -> commit, locked by Build
    run_dir: Path  # persists for the whole run; entrypoints can leave artifacts here
    log: Callable[[str], None]
    extra_env: dict[str, str] = field(default_factory=dict)
    cancelled: Callable[[], bool] = lambda: False  # asked every second while a command runs

    @property
    def env_name(self) -> str:
        """rehearsal or production. Entrypoints and Terraform must keep the two apart.
        Build previews production, since that's what Deploy will change."""
        return "rehearsal" if self.mode == "rehearse" else "production"


class Executor:
    def __init__(self, workspace: Workspace, work_root: Path, tf_state: TerraformState | None,
                 terraform: list[str] | None = None, python: str = sys.executable, timeout: int = 1800):
        self.workspace = workspace
        self.work_root = Path(work_root)
        # Providers are downloaded once and shared by every step and run. Without this, each iac
        # step pulled its own ~700 MB AWS provider, which filled the prod disk in one Build.
        self.plugin_cache = self.work_root.parent / "tf-plugin-cache"
        self.tf_state = tf_state
        self.terraform = terraform or ["terraform"]
        self.python = python
        self.timeout = timeout

    def execute(self, ctx: StepContext, action: ActionName) -> dict[str, str]:
        """Runs one action. For "run", returns the step's outputs (name -> value), the ones the
        spec declares; the runner fails the step if one is missing."""
        step = ctx.step
        if step.type == StepType.IAC and action in ("plan", "run", "rollback"):
            return self._terraform(ctx, {"plan": "plan", "run": "apply", "rollback": "destroy"}[action])
        if action == "plan":
            raise ValueError("only iac steps have a plan")

        repo, entrypoint = self._entrypoint(step, action)
        workdir = self._checkout(ctx, repo, action)
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        outputs_file = ctx.run_dir / f"{step.id}.{action}.outputs"
        outputs_file.unlink(missing_ok=True)
        try:
            path = workdir / entrypoint
            if not path.is_file():
                raise StepFailed(f"{entrypoint} doesn't exist in {repo.slug}@{ctx.shas[repo.key][:7]}")
            cmd = [self.python, str(path)] if path.suffix == ".py" else [str(path)]
            self._run(cmd, workdir, ctx, action, label=entrypoint, extra={"MAC_OUTPUTS": str(outputs_file)})
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # the log is in the store; the files aren't needed
        return _read_outputs_file(outputs_file) if action == "run" else {}

    def prune(self, keep: set[str]) -> int:
        """Delete the work dirs of every run not in `keep` (runs still in progress). Returns how many."""
        gone = 0
        if self.work_root.is_dir():
            for child in self.work_root.iterdir():
                if child.is_dir() and child.name not in keep:
                    shutil.rmtree(child, ignore_errors=True)
                    gone += 1
        return gone

    def _entrypoint(self, step: Step, action: ActionName) -> tuple[RepoRef, str]:
        if action == "run":
            return step.run.repo, step.run.entrypoint
        if action == "verify":
            return (step.verify.repo or step.run.repo), step.verify.entrypoint
        rollback = step.effective_rollback
        if rollback is None or not rollback.entrypoint:
            raise ValueError(f"{step.id} has no rollback entrypoint")
        return step.run.repo, rollback.entrypoint

    def _checkout(self, ctx: StepContext, repo: RepoRef, action: str) -> Path:
        workdir = self.work_root / ctx.run_id / f"{ctx.step.id}-{action}"
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        ctx.log(f"checking out {repo.slug}@{ctx.shas[repo.key][:7]}")
        self.workspace.checkout(repo, ctx.shas[repo.key], workdir)
        return workdir

    def _terraform(self, ctx: StepContext, command: str) -> None:
        if self.tf_state is None:
            raise StepFailed("Terraform state bucket isn't configured (MAC_TF_STATE_BUCKET)")
        workdir = self._checkout(ctx, ctx.step.run.repo, command)
        try:
            self._terraform_in(ctx, command, workdir / ctx.step.run.path)
            if command == "plan":
                self._save_plan_resources(ctx, workdir / ctx.step.run.path)
            if command == "apply" and ctx.step.outputs:
                return self._terraform_outputs(ctx, workdir / ctx.step.run.path)
            return {}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _terraform_outputs(self, ctx: StepContext, tf_dir: Path) -> dict[str, str]:
        result = subprocess.run([*self.terraform, "output", "-json", "-no-color"], cwd=tf_dir,
                                env=self._env(ctx, "run"), capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise StepFailed(f"terraform output failed: {result.stderr.strip()[-300:]}")
        try:
            raw = json.loads(result.stdout or "{}")
        except ValueError as e:
            raise StepFailed("terraform output didn't return JSON") from e
        # Sensitive outputs never leave Terraform.
        return {name: str(item.get("value")) for name, item in raw.items()
                if isinstance(item, dict) and not item.get("sensitive")}

    def _save_plan_resources(self, ctx: StepContext, tf_dir: Path) -> None:
        """What the plan will create, for the cost estimate: `<run dir>/<step>.resources.json`.
        Only a few non-sensitive attributes per resource are kept. Never fails the step."""
        out = resources_path(ctx.run_dir, ctx.step.id)
        out.unlink(missing_ok=True)
        try:
            result = subprocess.run([*self.terraform, "show", "-json", "-no-color", PLAN_FILE], cwd=tf_dir,
                                    env=self._env(ctx, "plan"), capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise ValueError(result.stderr.strip()[-300:] or f"exit code {result.returncode}")
            resources = plan_resources(json.loads(result.stdout or "{}"))
        except (ValueError, OSError, subprocess.TimeoutExpired) as e:
            ctx.log(f"couldn't read the plan's resources for the cost estimate: {e}")
            return
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(resources, indent=2), encoding="utf-8")
        ctx.log(f"plan creates {len(resources)} resources: " + ", ".join(r["address"] for r in resources))

    def _terraform_in(self, ctx: StepContext, command: str, tf_dir: Path) -> None:
        if not tf_dir.is_dir():
            raise StepFailed(f"{ctx.step.run.path} doesn't exist in {ctx.step.run.repo.slug}")
        # Our own backend config wins over whatever the repo declares, so state always lands
        # where rollback will look for it. Terraform merges *_override.tf files last.
        key = self.tf_state.key(ctx.spec.metadata.name, ctx.env_name, ctx.step.id)
        (tf_dir / "mac_backend_override.tf").write_text(
            "terraform {\n"
            '  backend "s3" {\n'
            f'    bucket       = "{self.tf_state.bucket}"\n'
            f'    key          = "{key}"\n'
            f'    region       = "{self.tf_state.region}"\n'
            "    use_lockfile = true\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        flags = ["-input=false", "-no-color"]
        self.plugin_cache.mkdir(parents=True, exist_ok=True)
        self._run([*self.terraform, "init", *flags], tf_dir, ctx, command, label="terraform init")
        # Build's plan is read-only, so it takes no state lock: a run killed mid-plan can't leave a
        # stale lock behind, and a Build never waits on a Rehearse or Deploy that holds one.
        args = {"plan": ["plan", *flags, "-lock=false", f"-out={PLAN_FILE}"],
                "apply": ["apply", *flags, "-auto-approve", "-lock-timeout=60s"],
                "destroy": ["destroy", *flags, "-auto-approve", "-lock-timeout=60s"]}[command]
        self._run([*self.terraform, *args], tf_dir, ctx, command, label=f"terraform {command}")
        if command == "destroy":
            self._verify_destroyed(ctx, tf_dir)

    def _verify_destroyed(self, ctx: StepContext, tf_dir: Path) -> None:
        """Proof, not trust: after destroy, the step's state must hold nothing. A resource still in
        state means the undo didn't finish, and the run must say so."""
        result = subprocess.run([*self.terraform, "state", "list", "-no-color"], cwd=tf_dir,
                                env=self._env(ctx, "rollback"), capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise StepFailed(f"couldn't verify the undo: terraform state list failed: {result.stderr.strip()[-300:]}")
        left = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if left:
            raise StepFailed(f"undo incomplete: still in Terraform state: {', '.join(left)}")
        ctx.log("verified: Terraform state for this step is empty; nothing it created is left")

    def _env(self, ctx: StepContext, action: str) -> dict[str, str]:
        target = ctx.spec.target
        account, region = target.account, target.region
        if ctx.env_name == "rehearsal" and target.rehearsal:
            account, region = target.rehearsal.account, target.rehearsal.region
        mac = {
            "MAC_RUN_ID": ctx.run_id,
            "MAC_MODE": ctx.mode,
            "MAC_ENV": ctx.env_name,
            "MAC_ACTION": action,
            "MAC_MIGRATION": ctx.spec.metadata.name,
            "MAC_STEP_ID": ctx.step.id,
            "MAC_RUN_DIR": str(ctx.run_dir),
            "MAC_TARGET_ACCOUNT": account,
            "MAC_TARGET_REGION": region,
        }
        tf = {"TF_IN_AUTOMATION": "1", "TF_PLUGIN_CACHE_DIR": str(self.plugin_cache),
              "TF_VAR_mac_env": ctx.env_name, "TF_VAR_mac_run_id": ctx.run_id,
              # boto3 reads AWS_DEFAULT_REGION; Terraform and the AWS CLI read AWS_REGION. Set both,
              # so no script has to know the target region itself.
              "AWS_REGION": region, "AWS_DEFAULT_REGION": region, "PYTHONUNBUFFERED": "1"}
        return {**os.environ, **tf, **mac, **ctx.extra_env}

    def _run(self, cmd: list[str], cwd: Path, ctx: StepContext, action: str, label: str,
             extra: dict[str, str] | None = None) -> None:
        ctx.log(f"$ {label}")
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env={**self._env(ctx, action), **(extra or {})}, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            raise StepFailed(f"{label}: can't start {cmd[0]!r} ({e.strerror})") from e
        # Read output on a thread so the timeout also catches a command that hangs silently.
        reader = threading.Thread(target=lambda: [ctx.log(line.rstrip("\n")) for line in proc.stdout])
        reader.start()
        # Terraform is never interrupted (a half-applied state is worse than a finished step that
        # gets destroyed a moment later); scripts are killed as soon as a cancel is requested.
        interruptible = cmd[:len(self.terraform)] != self.terraform
        started = time.monotonic()
        try:
            while True:
                try:
                    code = proc.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired as e:
                    if time.monotonic() - started > self.timeout:
                        proc.kill()
                        raise StepFailed(f"{label} took longer than {self.timeout}s") from e
                    if interruptible and ctx.cancelled():
                        proc.kill()
                        raise StepFailed(f"{label} was cancelled") from e
        finally:
            reader.join(timeout=10)
        if code != 0:
            raise StepFailed(f"{label} exited with code {code}")


def _read_outputs_file(path: Path) -> dict[str, str]:
    """A script's outputs: a JSON object, or NAME=value lines, written to $MAC_OUTPUTS."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        try:
            return {str(k): str(v) for k, v in json.loads(text).items()}
        except ValueError as e:
            raise StepFailed(f"$MAC_OUTPUTS isn't valid JSON: {e}") from e
    pairs = (line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs}
