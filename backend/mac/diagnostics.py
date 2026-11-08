"""AI help when a run fails: the three-position selector and the auto-fix guardrails.

The modes build on each other:
  explain  - read the logs, say what went wrong and the likely cause
  report   - also read the failing repo's code; produce a downloadable .md for a coding agent
  autofix  - also change the code on a branch and re-run Rehearse until it passes

The model calls themselves live behind the Diagnostician protocol; this module holds the
rules that must not depend on what a model decides.
"""

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from typing import Protocol

from .spec import Spec, StepType


class Mode(StrEnum):
    EXPLAIN = "explain"
    REPORT = "report"
    AUTOFIX = "autofix"


MAX_AUTOFIX_ATTEMPTS = 3

# Auto-fix may never touch these: it must make the code pass the checks, not weaken them.
PROTECTED_PATHS = (
    ".github/*", "CODEOWNERS", "*/CODEOWNERS",
    "tests/*", "*/tests/*", "test_*.py", "*/test_*.py", "*_test.py",
    ".env*", "*/.env*",
)


@dataclass(frozen=True)
class Failure:
    run_id: str
    mode: str  # rehearse | deploy
    step_id: str
    reason: str
    logs: list[str]
    repo: str  # RepoRef.key of the failing step
    sha: str
    spec_path: str = ""  # so auto-fix can start the next Build and Rehearse
    attempt: int = 0  # 0: the original failure; n: the n-th auto-fix attempt failed
    branch: str | None = None  # the auto-fix branch, once one exists
    parent: str | None = None  # the run whose failure started the auto-fix
    completed: tuple[str, ...] = ()  # steps that ran before the failure, in order
    shas: dict = None  # RepoRef.key -> commit, for every repo the run used


class Diagnostician(Protocol):
    def diagnose(self, spec: Spec, failure: Failure, mode: Mode) -> str:
        """Returns a summary for the run's event log."""


class NotConfigured:
    """No LLM key on this server: records that a diagnosis was asked for, and how to turn it on."""

    def diagnose(self, spec: Spec, failure: Failure, mode: Mode) -> str:
        return (f"AI help ({mode}) is off: set MAC_LLM_API_KEY (or NVIDIA_API_KEY) on the server. "
                f"Failure in {failure.step_id}: {failure.reason}")


def autofix_branch(run_id: str) -> str:
    return f"mac/autofix/{run_id}"


def autofix_violations(spec: Spec, repo_key: str, changed_paths: list[str]) -> list[str]:
    """Why a proposed auto-fix change isn't allowed. Empty means it's allowed."""
    if repo_key not in spec.repos():
        return [f"{repo_key} isn't used by this pipeline"]

    # A repo's checks and verify scripts are what proves the fix works, so they're off limits.
    guarded = set()
    for step in spec.steps:
        if step.type == StepType.CHECK and step.run.repo.key == repo_key:
            guarded.add(step.run.entrypoint)
        if step.verify and (step.verify.repo or step.run.repo).key == repo_key:
            guarded.add(step.verify.entrypoint)

    problems = []
    for path in changed_paths:
        clean = path.replace("\\", "/").removeprefix("./")
        if clean in guarded:
            problems.append(f"{clean} is a check or verify script; auto-fix can't change it")
        elif any(fnmatch(clean, pattern) for pattern in PROTECTED_PATHS):
            problems.append(f"{clean} is protected (tests, CI, CODEOWNERS or secrets)")
    return problems
