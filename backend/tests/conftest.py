"""Stand-ins for GitHub, Jira and step execution, so runner logic is tested without AWS.
The real connectors are exercised against real processes in test_executors.py."""

import shutil
from pathlib import Path

import pytest

from mac.executors import StepFailed
from mac.integrations import Check
from mac.runner import Runner
from mac.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SPEC = REPO_ROOT / "examples" / "claims-adjudication" / "migration.yaml"

IAC = "github.com/MaC-aroni/claims-service-iac"
DB = "github.com/MaC-aroni/claims-db-migrate"
SMOKE = "github.com/MaC-aroni/claims-smoke-tests"


class FakeGitHub:
    def __init__(self):
        self.shas = {IAC: "a" * 40, DB: "b" * 40, SMOKE: "c" * 40}
        self.branches: dict[tuple[str, str], str] = {}  # (repo key, branch) -> sha
        self.failing: set[str] = set()

    def resolve(self, repo):
        if repo.ref != "main":
            return self.branches[(repo.key, repo.ref)]
        return self.shas[repo.key]

    def guardrails(self, repo, sha, rules):
        passed = repo.key not in self.failing and repo.ref == "main"
        return [Check("ci_green", passed, "fake")]


class FakeApprovals:
    def __init__(self, default="approved"):
        self.default = default
        self.tickets: dict[str, str] = {}

    def status(self, ticket):
        return self.tickets.get(ticket, self.default)


class FakeExecutor:
    """Records (step, action, env) and fails where told to."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.fail: dict[tuple[str, str], str] = {}

    def execute(self, ctx, action):
        self.calls.append((ctx.step.id, action, ctx.env_name))
        ctx.log(f"{action} {ctx.step.id}")
        if (ctx.step.id, action) in self.fail:
            raise StepFailed(self.fail[(ctx.step.id, action)])

    def actions(self, action):
        return [step for step, act, _ in self.calls if act == action]


class RecordingDiagnostician:
    def __init__(self):
        self.calls = []

    def diagnose(self, spec, failure, mode):
        self.calls.append((failure, mode))
        return f"diagnosed {failure.step_id} ({mode})"


@pytest.fixture
def spec_path(tmp_path):
    path = tmp_path / "migration.yaml"
    shutil.copy(DEMO_SPEC, path)
    return path


@pytest.fixture
def env(tmp_path):
    class Env:
        github = FakeGitHub()
        approvals = FakeApprovals()
        executor = FakeExecutor()
        diagnostician = RecordingDiagnostician()
        store = Store(":memory:")
        runner = Runner(store, github, approvals, executor, tmp_path / "data", diagnostician)

    return Env()
