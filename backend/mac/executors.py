"""Runs one action of one step: checks out the repo at its locked commit into a fresh
directory, then runs the entrypoint or Terraform there. Knows nothing about ordering,
approvals or rollback; that's the runner's job."""

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .integrations import Workspace
from .spec import RepoRef, Spec, Step, StepType

# plan: Terraform preview, used by Build. run / verify / rollback: the step's three phases.
ActionName = Literal["plan", "run", "verify", "rollback"]
Mode = Literal["build", "rehearse", "deploy"]


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

    def execute(self, ctx: StepContext, action: ActionName) -> None:
        step = ctx.step
        if step.type == StepType.IAC and action in ("plan", "run", "rollback"):
            self._terraform(ctx, {"plan": "plan", "run": "apply", "rollback": "destroy"}[action])
            return
        if action == "plan":
            raise ValueError("only iac steps have a plan")

        repo, entrypoint = self._entrypoint(step, action)
        workdir = self._checkout(ctx, repo, action)
        try:
            path = workdir / entrypoint
            if not path.is_file():
                raise StepFailed(f"{entrypoint} doesn't exist in {repo.slug}@{ctx.shas[repo.key][:7]}")
            cmd = [self.python, str(path)] if path.suffix == ".py" else [str(path)]
            self._run(cmd, workdir, ctx, action, label=entrypoint)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # the log is in the store; the files aren't needed

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
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

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
        args = {"plan": ["plan", *flags, "-lock-timeout=60s"],
                "apply": ["apply", *flags, "-auto-approve", "-lock-timeout=60s"],
                "destroy": ["destroy", *flags, "-auto-approve", "-lock-timeout=60s"]}[command]
        self._run([*self.terraform, *args], tf_dir, ctx, command, label=f"terraform {command}")

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
              "AWS_REGION": region, "PYTHONUNBUFFERED": "1"}
        return {**os.environ, **tf, **mac, **ctx.extra_env}

    def _run(self, cmd: list[str], cwd: Path, ctx: StepContext, action: str, label: str) -> None:
        ctx.log(f"$ {label}")
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=self._env(ctx, action), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            raise StepFailed(f"{label}: can't start {cmd[0]!r} ({e.strerror})") from e
        # Read output on a thread so the timeout also catches a command that hangs silently.
        reader = threading.Thread(target=lambda: [ctx.log(line.rstrip("\n")) for line in proc.stdout])
        reader.start()
        try:
            code = proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            proc.kill()
            raise StepFailed(f"{label} took longer than {self.timeout}s") from e
        finally:
            reader.join(timeout=10)
        if code != 0:
            raise StepFailed(f"{label} exited with code {code}")
