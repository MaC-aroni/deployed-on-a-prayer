"""The deterministic runner. No model is in this path: AI only reads what happened.

Build     checks everything without changing anything, and locks each repo's main to a commit.
Rehearse  runs the whole pipeline in the rehearsal environment, then undoes all of it.
Deploy    runs it for real, using the commits the passing Rehearse used.

Any step failing undoes every step that finished, newest first. Runs pause at approvals and
manual steps; play / resume continue them later, from the state saved in the Store.
"""

from pathlib import Path

from .diagnostics import Diagnostician, Failure, Mode, NotConfigured
from .executors import Executor, StepContext, StepFailed
from .integrations import Approvals, GitHub, IntegrationError
from .spec import SELF_ROLLBACK_ON_FAILURE, Spec, SpecError, Step, StepType, parse_spec
from .store import RunRecord, RunStatus, StepState, Store
from .validate import execution_order, follows_a_change, validate


class GateError(Exception):
    """The runner refused to start or continue. The message says what to do instead."""


class Runner:
    def __init__(self, store: Store, github: GitHub, approvals: Approvals, executor: Executor,
                 data_dir: Path, diagnostician: Diagnostician | None = None):
        self.store = store
        self.github = github
        self.approvals = approvals
        self.executor = executor
        self.data_dir = Path(data_dir)
        self.diagnostician = diagnostician or NotConfigured()

    # ---- Starting runs -------------------------------------------------------------------

    def build(self, spec_path: Path, overrides: dict[str, str] | None = None) -> RunRecord:
        """overrides: RepoRef.key -> branch, used by auto-fix to test its own branch. Guardrails
        on an overridden repo are reported but don't block, and Deploy never accepts the result."""
        spec, text = self._load(spec_path)
        overrides = overrides or {}
        unknown = sorted(set(overrides) - set(spec.repos()))
        if unknown:
            raise GateError(f"overrides name repos this pipeline doesn't use: {', '.join(unknown)}")
        run = self._new_run(spec, text, spec_path, "build", overrides=overrides)
        self._event(run, "run", "Build started")

        issues = validate(spec)
        run.report["issues"] = [str(i) for i in issues]
        for issue in issues:
            self._event(run, "log", str(issue))
        if any(i.level == "error" for i in issues):
            return self._finish(run, RunStatus.FAILED, "migration.yaml has errors")

        try:
            self._lock_commits(run, spec)
            if not self._check_guardrails(run, spec):
                return self._finish(run, RunStatus.FAILED, "guardrail checks failed")
            self._report_approvals(run, spec)
            for step in execution_order(spec):
                if step.type == StepType.IAC:
                    self._build_action(run, spec, step, "plan")
                elif step.type == StepType.CHECK and not follows_a_change(spec, step):
                    self._build_action(run, spec, step, "run")
        except _BuildStepFailed as e:
            return self._finish(run, RunStatus.FAILED, str(e))
        except IntegrationError as e:
            return self._finish(run, RunStatus.FAILED, str(e))
        return self._finish(run, RunStatus.SUCCEEDED)

    def rehearse(self, spec_path: Path, diagnostics_mode: str | None = None,
                 overrides: dict[str, str] | None = None) -> RunRecord:
        spec, text = self._load(spec_path)
        self._refuse_if_active(spec)
        build = self.store.latest(spec.metadata.name, "build")
        if build is None or build.status != RunStatus.SUCCEEDED or build.spec_digest != spec.digest():
            raise GateError("Rehearse needs a passing Build of this exact migration.yaml. Run Build first.")
        if build.overrides != (overrides or {}):
            raise GateError("The last Build used different branches than this Rehearse. Build again with the same ones.")
        run = self._new_run(spec, text, spec_path, "rehearse", overrides=build.overrides,
                            shas=build.shas, based_on=build.id, diagnostics_mode=diagnostics_mode)
        self._event(run, "run", "Rehearse started in the rehearsal environment; everything is undone at the end")
        return self._advance(run, spec)

    def deploy(self, spec_path: Path, diagnostics_mode: str | None = None) -> RunRecord:
        spec, text = self._load(spec_path)
        self._refuse_if_active(spec)
        rehearsal = self.store.latest(spec.metadata.name, "rehearse")
        if rehearsal is None or rehearsal.status != RunStatus.SUCCEEDED or rehearsal.spec_digest != spec.digest():
            raise GateError("Deploy needs a passing Rehearse of this exact migration.yaml. Run Rehearse first.")
        if rehearsal.overrides:
            raise GateError("The last Rehearse ran auto-fix branches. Merge them into main, then Build and Rehearse again.")
        try:
            current = {key: self.github.resolve(ref) for key, ref in spec.repos().items()}
        except IntegrationError as e:
            raise GateError(f"Couldn't check the repos on GitHub: {e}") from e
        changed = sorted(key for key, sha in current.items() if rehearsal.shas.get(key) != sha)
        if changed:
            raise GateError("Changed since the last Rehearse: " + ", ".join(changed)
                            + ". Run Build and Rehearse again so Deploy runs code that was rehearsed.")
        run = self._new_run(spec, text, spec_path, "deploy", shas=rehearsal.shas, based_on=rehearsal.id,
                            diagnostics_mode=diagnostics_mode)
        self._event(run, "run", "Deploy started in production")
        return self._advance(run, spec)

    # ---- Continuing runs ----------------------------------------------------------------

    def play(self, run_id: str, step_id: str) -> RunRecord:
        run, spec = self._existing(run_id)
        if run.status != RunStatus.WAITING or run.steps.get(step_id) != StepState.WAITING:
            raise GateError(f"{step_id} isn't waiting for play (run is {run.status}, step is {run.steps.get(step_id)})")
        run.played.append(step_id)
        self._event(run, "step", f"{step_id}: play pressed", step_id)
        return self._advance(run, spec)

    def resume(self, run_id: str) -> RunRecord:
        """Checks approvals again, e.g. after a Jira ticket moved."""
        run, spec = self._existing(run_id)
        if run.status != RunStatus.WAITING:
            raise GateError(f"run {run_id} is {run.status}, not waiting")
        return self._advance(run, spec)

    def undo(self, run_id: str) -> RunRecord:
        run, spec = self._existing(run_id)
        if run.mode == "build" or run.status not in (RunStatus.WAITING, RunStatus.SUCCEEDED) \
                or (run.mode == "rehearse" and run.status == RunStatus.SUCCEEDED):
            raise GateError(f"nothing to undo: {run.mode} run {run_id} is {run.status}")
        self._event(run, "run", "Undo requested")
        self._skip_unreached(run)
        ok = self._rollback(run, spec, failed=None)
        return self._finish(run, RunStatus.UNDONE if ok else RunStatus.ROLLBACK_FAILED,
                            None if ok else "undo didn't finish; see the log for what's left")

    # ---- The state machine ----------------------------------------------------------------

    def _advance(self, run: RunRecord, spec: Spec) -> RunRecord:
        run.status, run.reason = RunStatus.RUNNING, None
        self.store.save(run)
        for step in execution_order(spec):
            if run.steps[step.id] == StepState.SUCCEEDED:
                continue

            if run.mode == "deploy" and step.requires_approval:
                try:
                    statuses = {a: self.approvals.status(spec.approval(a).jira) for a in step.requires_approval}
                except IntegrationError as e:
                    return self._wait(run, step, StepState.BLOCKED, f"couldn't check approvals: {e}")
                rejected = [a for a, s in statuses.items() if s == "rejected"]
                if rejected:
                    return self._fail(run, spec, step, f"approval rejected: {', '.join(rejected)}", ran=False)
                pending = [f"{a} ({spec.approval(a).jira})" for a, s in statuses.items() if s != "approved"]
                if pending:
                    return self._wait(run, step, StepState.BLOCKED, "waiting for approval: " + ", ".join(pending))

            if step.when == "manual" and step.id not in run.played:
                return self._wait(run, step, StepState.WAITING, f"{step.id} is manual: press play to run it")

            self._set(run, step, StepState.RUNNING)
            try:
                ctx = self._context(run, spec, step)
                self.executor.execute(ctx, "run")
                if step.verify:
                    self.executor.execute(ctx, "verify")
            except Exception as e:  # noqa: BLE001 - any failure, even a runner bug, must trigger undo
                self._set(run, step, StepState.FAILED)
                return self._fail(run, spec, step, _reason(e), ran=True)
            run.completed.append(step.id)
            self._set(run, step, StepState.SUCCEEDED)

        if run.mode == "rehearse":
            self._event(run, "run", "Every step passed. Undoing the rehearsal.")
            ok = self._rollback(run, spec, failed=None)
            return self._finish(run, RunStatus.SUCCEEDED if ok else RunStatus.ROLLBACK_FAILED,
                                None if ok else "the rehearsal passed, but cleaning it up didn't finish")
        return self._finish(run, RunStatus.SUCCEEDED)

    def _fail(self, run: RunRecord, spec: Spec, step: Step, reason: str, ran: bool) -> RunRecord:
        run.failed_step, run.reason = step.id, reason
        if not ran:
            self._set(run, step, StepState.FAILED)
        self._event(run, "run", f"{step.id} failed: {reason}. Undoing everything this run did.", step.id)
        self._skip_unreached(run)
        ok = self._rollback(run, spec, failed=step if ran else None)
        self._finish(run, RunStatus.FAILED if ok else RunStatus.ROLLBACK_FAILED, reason)
        if ran:
            self._diagnose(run, spec, step, reason)
        return run

    def _rollback(self, run: RunRecord, spec: Spec, failed: Step | None) -> bool:
        run.status = RunStatus.ROLLING_BACK
        self.store.save(run)
        targets = [spec.step(i) for i in reversed(run.completed)]
        if failed is not None and failed.type in SELF_ROLLBACK_ON_FAILURE:
            targets.insert(0, failed)  # its half-finished work goes first
        ok = True
        for step in targets:
            if not step.mutating:
                continue  # checks didn't change anything
            try:
                self.executor.execute(self._context(run, spec, step), "rollback")
            except Exception as e:  # noqa: BLE001 - keep undoing the rest
                ok = False
                self._event(run, "log", f"rollback failed: {_reason(e)}", step.id)
                self._set(run, step, StepState.ROLLBACK_FAILED)
                continue
            if step is not failed:
                self._set(run, step, StepState.ROLLED_BACK)
            else:
                self._event(run, "log", "undid this step's partial changes", step.id)
        return ok

    # ---- Build helpers ------------------------------------------------------------------------

    def _lock_commits(self, run: RunRecord, spec: Spec) -> None:
        for key, ref in spec.repos().items():
            if key in run.overrides:
                ref = ref.model_copy(update={"ref": run.overrides[key]})
            run.shas[key] = self.github.resolve(ref)
            self._event(run, "log", f"{ref} -> {run.shas[key][:7]}")
        self.store.save(run)

    def _check_guardrails(self, run: RunRecord, spec: Spec) -> bool:
        ok = True
        run.report["guardrails"] = {}
        for key, ref in spec.repos().items():
            branch_ref = ref.model_copy(update={"ref": run.overrides.get(key, ref.ref)})
            checks = self.github.guardrails(branch_ref, run.shas[key], spec.guardrails)
            run.report["guardrails"][key] = [vars(c) for c in checks]
            blocking = key not in run.overrides
            for check in checks:
                mark = "ok" if check.passed else ("FAIL" if blocking else "not blocking (auto-fix branch)")
                self._event(run, "log", f"{key} {check.name}: {mark}: {check.detail}")
                ok = ok and (check.passed or not blocking)
        self.store.save(run)
        return ok

    def _report_approvals(self, run: RunRecord, spec: Spec) -> None:
        run.report["approvals"] = {}
        for approval in spec.approvals:
            try:
                status = self.approvals.status(approval.jira)
            except IntegrationError as e:
                status = f"unknown ({e})"
            run.report["approvals"][approval.id] = status
            self._event(run, "log", f"approval {approval.id} ({approval.jira}): {status}")
        self.store.save(run)

    def _build_action(self, run: RunRecord, spec: Spec, step: Step, action: str) -> None:
        self._set(run, step, StepState.RUNNING)
        try:
            self.executor.execute(self._context(run, spec, step), action)
        except Exception as e:  # noqa: BLE001
            self._set(run, step, StepState.FAILED)
            run.failed_step = step.id
            raise _BuildStepFailed(f"{step.id} ({'terraform plan' if action == 'plan' else 'check'}): {_reason(e)}") from e
        self._set(run, step, StepState.SUCCEEDED)

    # ---- Plumbing -----------------------------------------------------------------------------

    def _load(self, spec_path: Path) -> tuple[Spec, str]:
        path = Path(spec_path)
        try:
            text = path.read_text(encoding="utf-8")
            return parse_spec(text, source=str(path)), text
        except OSError as e:
            raise GateError(f"can't read {path}: {e.strerror}") from e
        except SpecError as e:
            raise GateError(str(e)) from e

    def _existing(self, run_id: str) -> tuple[RunRecord, Spec]:
        try:
            run = self.store.get(run_id)
        except KeyError as e:
            raise GateError(str(e)) from e
        # The spec as it was when the run started, so undo matches what actually ran.
        return run, parse_spec(run.spec_text, source=run.spec_path)

    def _new_run(self, spec: Spec, text: str, spec_path: Path, mode: str, **fields) -> RunRecord:
        diagnostics = fields.pop("diagnostics_mode", None) or spec.diagnostics.mode
        if mode == "deploy" and diagnostics == Mode.AUTOFIX:
            diagnostics = Mode.REPORT  # auto-fix only ever acts on rehearsals
        run = RunRecord(migration=spec.metadata.name, mode=mode, spec_path=str(spec_path),
                        spec_digest=spec.digest(), spec_text=text, diagnostics_mode=Mode(diagnostics),
                        **fields)
        if mode != "build":
            run.steps = {s.id: StepState.PENDING for s in spec.steps}
        self.store.save(run)
        return run

    def _refuse_if_active(self, spec: Spec) -> None:
        for run in self.store.runs(spec.metadata.name):
            if run.status.active:
                raise GateError(f"{run.mode} run {run.id} is still {run.status}. Finish or undo it first.")

    def _context(self, run: RunRecord, spec: Spec, step: Step) -> StepContext:
        run_dir = self.data_dir / "runs" / run.id
        run_dir.mkdir(parents=True, exist_ok=True)
        return StepContext(spec=spec, step=step, mode=run.mode, run_id=run.id, shas=run.shas, run_dir=run_dir,
                           log=lambda line: self.store.add_event(run.id, "log", line, step.id))

    def _set(self, run: RunRecord, step: Step, state: StepState) -> None:
        run.steps[step.id] = state
        self.store.save(run)
        self._event(run, "step", f"{step.id}: {state}", step.id)

    def _wait(self, run: RunRecord, step: Step, state: StepState, reason: str) -> RunRecord:
        run.steps[step.id] = state
        run.status, run.reason = RunStatus.WAITING, reason
        self.store.save(run)
        self._event(run, "run", reason, step.id)
        return run

    def _finish(self, run: RunRecord, status: RunStatus, reason: str | None = None) -> RunRecord:
        run.status = status
        if reason:
            run.reason = reason
        self.store.save(run)
        self._event(run, "run", f"{run.mode} {status}" + (f": {reason}" if reason else ""))
        return run

    def _skip_unreached(self, run: RunRecord) -> None:
        for step_id, state in run.steps.items():
            if state in (StepState.PENDING, StepState.BLOCKED, StepState.WAITING):
                run.steps[step_id] = StepState.SKIPPED
        self.store.save(run)

    def _event(self, run: RunRecord, kind: str, message: str, step: str | None = None) -> None:
        self.store.add_event(run.id, kind, message, step)

    def _diagnose(self, run: RunRecord, spec: Spec, step: Step, reason: str) -> None:
        logs = [e.message for e in self.store.events(run.id, step=step.id) if e.kind == "log"][-200:]
        repo = step.run.repo.key
        failure = Failure(run_id=run.id, mode=run.mode, step_id=step.id, reason=reason, logs=logs,
                          repo=repo, sha=run.shas.get(repo, ""))
        try:
            summary = self.diagnostician.diagnose(spec, failure, Mode(run.diagnostics_mode))
        except Exception as e:  # noqa: BLE001 - AI help failing must never change the run's outcome
            summary = f"AI help failed: {_reason(e)}"
        self._event(run, "diagnosis", summary, step.id)


class _BuildStepFailed(Exception):
    pass


def _reason(error: Exception) -> str:
    if isinstance(error, (StepFailed, IntegrationError)):
        return str(error)
    return f"runner error: {type(error).__name__}: {error}"
