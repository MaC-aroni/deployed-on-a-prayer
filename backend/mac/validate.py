"""`mac validate`: rules that span the whole spec, and the order steps run in."""

from dataclasses import dataclass
from typing import Literal

from .spec import Spec, Step, StepType


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.message}"


def validate(spec: Spec) -> list[Issue]:
    issues: list[Issue] = []

    def error(where, message):
        issues.append(Issue("error", where, message))

    def warning(where, message):
        issues.append(Issue("warning", where, message))

    for label, ids in (("stage", spec.stages), ("step", [s.id for s in spec.steps]),
                       ("approval", [a.id for a in spec.approvals])):
        for dup in sorted({i for i in ids if list(ids).count(i) > 1}):
            error(f"{label}s", f"duplicate {label} {dup!r}")

    for step in spec.steps:
        names = [o.name for o in step.outputs]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            error(f"steps.{step.id}.outputs", f"duplicate output {dup!r}")
        for out in step.outputs:
            probe_names = [p.name for p in out.probes]
            for dup in sorted({n for n in probe_names if probe_names.count(n) > 1}):
                error(f"steps.{step.id}.outputs.{out.name}", f"duplicate probe {dup!r}")
            for probe in out.probes:
                if not probe.path.startswith("/"):
                    error(f"steps.{step.id}.outputs.{out.name}.probes.{probe.name}", "path must start with /")
                if probe.body is not None and probe.method != "POST":
                    error(f"steps.{step.id}.outputs.{out.name}.probes.{probe.name}", "only POST probes send a body")
            if out.probes and step.type == "check":
                warning(f"steps.{step.id}.outputs.{out.name}", "a check step changes nothing, so there's nothing to probe")

    stage_index = {name: i for i, name in enumerate(spec.stages)}
    steps = {s.id: s for s in spec.steps}
    approval_ids = {a.id for a in spec.approvals}
    used_approvals: set[str] = set()

    for step in spec.steps:
        where = f"steps.{step.id}"
        if step.stage not in stage_index:
            error(where, f"stage {step.stage!r} is not listed in stages")

        for need in step.needs:
            if need not in steps:
                error(where, f"needs unknown step {need!r}")
            elif need == step.id:
                error(where, "needs itself")
            elif steps[need].stage in stage_index and step.stage in stage_index \
                    and stage_index[steps[need].stage] > stage_index[step.stage]:
                error(where, f"needs {need!r}, which is in a later stage ({steps[need].stage})")

        for approval in step.requires_approval:
            used_approvals.add(approval)
            if approval not in approval_ids:
                error(where, f"requires unknown approval {approval!r}")

        _check_shape(step, where, error, warning)

    for approval in spec.approvals:
        where = f"approvals.{approval.id}"
        if approval.id not in used_approvals:
            warning(where, "no step requires this approval")
        for dep in approval.after:
            if dep == approval.id:
                error(where, "is after itself")
            elif dep not in approval_ids:
                error(where, f"is after unknown approval {dep!r}")

    graph = {a.id: [d for d in a.after if d in approval_ids and d != a.id] for a in spec.approvals}
    for cycle in _find_cycles(graph):
        error("approvals", "approvals wait on each other in a loop: " + " -> ".join(cycle))

    for cycle in _cycles(spec):
        error("steps", "steps wait on each other in a loop: " + " -> ".join(cycle))

    return issues


def _check_shape(step: Step, where: str, error, warning) -> None:
    run = step.run
    if step.type == StepType.IAC:
        if not run.path:
            error(where, "iac steps need run.path (the Terraform directory)")
        if run.entrypoint:
            error(where, "iac steps run Terraform; use run.path, not run.entrypoint")
    elif not run.entrypoint:
        error(where, f"{step.type} steps need run.entrypoint")

    if step.mutating:
        rollback = step.effective_rollback
        if rollback is None:
            error(where, f"{step.type} steps change things, so they need a rollback")
        elif step.type == StepType.IAC and rollback.entrypoint:
            error(where, "iac steps roll back with terraform destroy; remove rollback.entrypoint")
        elif step.type != StepType.IAC and not rollback.entrypoint:
            error(where, "rollback needs an entrypoint (only iac steps can use action: destroy)")
    elif step.rollback not in (None, "none"):
        error(where, "check steps don't change anything, so they can't have a rollback")

    if step.type == StepType.DB_MIGRATION:
        if step.verify is None:
            error(where, "db_migration steps need verify (e.g. row counts after the copy)")
        if step.when != "manual":
            warning(where, "db_migration steps should be when: manual, so a person starts the copy")


def _cycles(spec: Spec) -> list[list[str]]:
    known = {s.id for s in spec.steps}
    return _find_cycles({s.id: [n for n in s.needs if n in known and n != s.id] for s in spec.steps})


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done
    found: list[list[str]] = []

    def visit(node, path):
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                found.append(path[path.index(nxt):] + [nxt])
            elif nxt not in state:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return found


def execution_order(spec: Spec) -> list[Step]:
    """Stages left to right; inside a stage, `needs` first, then the order the file lists them.

    Only call this on a spec with no validation errors.
    """
    order: list[Step] = []
    done: set[str] = set()
    for stage in spec.stages:
        remaining = [s for s in spec.steps if s.stage == stage]
        while remaining:
            ready = next(s for s in remaining if all(n in done for n in s.needs))
            order.append(ready)
            done.add(ready.id)
            remaining.remove(ready)
    return order


def follows_a_change(spec: Spec, step: Step) -> bool:
    """Whether anything that changes state runs before this step. Build only runs checks that
    don't, because a check after a deploy has nothing to check until the deploy happens."""
    for earlier in execution_order(spec):
        if earlier.id == step.id:
            return False
        if earlier.mutating:
            return True
    return False
