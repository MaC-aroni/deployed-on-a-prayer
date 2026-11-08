"""The migration.yaml spec (schema mac/v0.3): parsing and shape only.

Rules that span several fields (references, cycles, rollbacks) live in validate.py, so
a spec can be loaded and then report every problem at once instead of the first one.
"""

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

API_VERSION = "mac/v0.3"

_REPO = re.compile(r"^github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)(?:@(?P<ref>[^\s@]+))?$")
_ID = r"^[a-z][a-z0-9_]*$"


class SpecError(Exception):
    """The file isn't a readable migration.yaml. Carries every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


class StepType(StrEnum):
    CHECK = "check"
    SCRIPT = "script"
    IAC = "iac"
    DB_MIGRATION = "db_migration"


# Steps that change something, and so must be undoable.
MUTATING = frozenset({StepType.SCRIPT, StepType.IAC, StepType.DB_MIGRATION})
# Steps whose own half-finished work is undone when they fail (see docs/runner.md).
SELF_ROLLBACK_ON_FAILURE = frozenset({StepType.IAC, StepType.DB_MIGRATION})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RepoRef(_Model):
    """`github.com/<owner>/<name>[@<ref>]`. The ref defaults to the repo's main branch."""

    owner: str
    name: str
    ref: str = "main"

    @property
    def key(self) -> str:
        """The repo without the ref: what Build locks to a commit."""
        return f"github.com/{self.owner}/{self.name}"

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    def __str__(self) -> str:
        return f"{self.key}@{self.ref}"


def _parse_repo(value):
    if isinstance(value, str):
        match = _REPO.match(value.strip())
        if not match:
            raise ValueError(f"expected github.com/<owner>/<repo>[@<ref>], got {value!r}")
        return {k: v for k, v in match.groupdict().items() if v is not None}
    return value


class Action(_Model):
    repo: RepoRef
    entrypoint: str | None = None  # script/check/db_migration: file to run, relative to the repo
    path: str | None = None  # iac: Terraform root directory, relative to the repo

    @field_validator("repo", mode="before")
    @classmethod
    def parse_repo(cls, value):
        return _parse_repo(value)


class Verify(_Model):
    repo: RepoRef | None = None  # defaults to the step's run.repo
    entrypoint: str

    @field_validator("repo", mode="before")
    @classmethod
    def parse_repo(cls, value):
        return _parse_repo(value)


class Rollback(_Model):
    entrypoint: str | None = None  # script/db_migration: undo script in the step's repo
    action: Literal["destroy"] | None = None  # iac: terraform destroy


class Step(_Model):
    id: str = Field(pattern=_ID)
    stage: str
    type: StepType
    needs: tuple[str, ...] = ()
    requires_approval: tuple[str, ...] = ()
    when: Literal["auto", "manual"] = "auto"  # manual: waits for someone to press play
    run: Action
    verify: Verify | None = None
    rollback: Rollback | Literal["none"] | None = None

    @property
    def mutating(self) -> bool:
        return self.type in MUTATING

    @property
    def effective_rollback(self) -> Rollback | None:
        """What undoing this step runs. Terraform steps undo with destroy unless told otherwise."""
        if isinstance(self.rollback, Rollback):
            return self.rollback
        if self.rollback is None and self.type == StepType.IAC:
            return Rollback(action="destroy")
        return None


class Approval(_Model):
    """A sign-off Deploy waits for. MaC raises the Jira ticket itself, once per version of the
    spec, so a changed plan always needs fresh approval."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    type: str
    approver: str  # who signs off: "manager", "tech-risk", a team name; maps to a Jira assignee
    summary: str  # the ticket's title
    justification: str | None = None  # the ticket's body
    after: tuple[str, ...] = ()  # approvals that must be approved before this ticket is raised
    design_doc: bool = False  # link the design page; the ticket waits until the page exists


class Environment(_Model):
    account: str
    region: str


class Target(_Model):
    provider: Literal["aws"]
    account: str
    region: str
    rehearsal: Environment | None = None  # where Rehearse runs; defaults to the same account


class Metadata(_Model):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    service: str
    owner_team: str
    generated_by: str | None = None
    source_docs: tuple[str, ...] = ()


class Guardrails(_Model):
    """Checked by Build on every repo the pipeline uses, at the commit it will run."""

    require_ci_green: bool = True
    require_protected_branch: bool = True
    require_review: bool = True  # the commit reached the branch through an approved PR


class Diagnostics(_Model):
    """Default AI help when a run fails. A run can override it."""

    mode: Literal["explain", "report", "autofix"] = "explain"


class Spec(_Model):
    apiVersion: Literal["mac/v0.3"]
    kind: Literal["Migration"]
    metadata: Metadata
    target: Target
    stages: tuple[str, ...] = Field(min_length=1)
    approvals: tuple[Approval, ...] = ()
    steps: tuple[Step, ...] = Field(min_length=1)
    guardrails: Guardrails = Guardrails()
    diagnostics: Diagnostics = Diagnostics()

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)

    def approval(self, approval_id: str) -> Approval:
        return next(a for a in self.approvals if a.id == approval_id)

    def repos(self) -> dict[str, RepoRef]:
        """Every repo the pipeline uses, keyed by RepoRef.key."""
        refs: dict[str, RepoRef] = {}
        for step in self.steps:
            for ref in (step.run.repo, step.verify.repo if step.verify else None):
                if ref is not None:
                    refs.setdefault(ref.key, ref)
        return refs

    def digest(self) -> str:
        """Identifies this exact plan, ignoring formatting and comments in the YAML."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_spec(text: str, source: str = "migration.yaml") -> Spec:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError([f"{source}: not valid YAML: {e}"]) from e
    if not isinstance(data, dict):
        raise SpecError([f"{source}: expected a mapping at the top level"])
    try:
        return Spec.model_validate(data)
    except ValidationError as e:
        raise SpecError([f"{source}: {_where(err['loc'])}: {err['msg']}" for err in e.errors()]) from e


def load_spec(path: Path) -> Spec:
    return parse_spec(Path(path).read_text(encoding="utf-8"), source=str(path))


def _where(loc) -> str:
    return ".".join(str(part) for part in loc) or "(top level)"
