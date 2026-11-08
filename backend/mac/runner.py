"""The deterministic runner. No model is in this path: AI only reads what happened.

Build     checks everything without changing anything, and locks each repo's main to a commit.
Rehearse  runs the whole pipeline in the rehearsal environment, then undoes all of it.
Deploy    runs it for real, using the commits the passing Rehearse used.

Any step failing undoes every step that finished, newest first. Runs pause at approvals and
manual steps; play / resume continue them later, from the state saved in the Store.

Every action has two halves, so a web request can answer at once and do the slow part in the
background: `start_*` / `request_*` check the rules and record what should happen next
(raising GateError if it's not allowed), then `execute(run_id)` does it. The plain methods
(`build`, `rehearse`, `play`, ...) do both, for the CLI and tests.
"""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .cost import estimate as estimate_cost, summary as cost_summary
from .design import DesignWriter, facts, page_title, render_page
from .diagnostics import Diagnostician, Failure, Mode, NotConfigured
from .executors import Executor, StepContext, StepFailed, resources_path
from .integrations import Approvals, GitHub, IntegrationError, Pages, TicketRequest
from .pricing import load_prices
from .spec import SELF_ROLLBACK_ON_FAILURE, Approval, Spec, SpecError, Step, StepType, load_spec, parse_spec
from .store import ApprovalRecord, DesignPage, RunRecord, RunStatus, StepState, Store, Ticket
from .usage import load_usage
from .validate import execution_order, follows_a_change, validate


class GateError(Exception):
    """The runner refused to start or continue. The message says what to do instead."""


class Runner:
    def __init__(self, store: Store, github: GitHub, approvals: Approvals, executor: Executor,
                 data_dir: Path, diagnostician: Diagnostician | None = None,
                 design_writer: DesignWriter | None = None, pages: Pages | None = None,
                 price_loader: Callable | None = None):
        self.store = store
        self.github = github
        self.approvals = approvals
        self.executor = executor
        self.data_dir = Path(data_dir)
        self.diagnostician = diagnostician or NotConfigured()
        self.diagnosing: set[str] = set()  # runs whose AI help is still working
        self.design_writer = design_writer  # the LLM that writes the design page (text only)
        self.pages = pages  # where the design page is published (Confluence)
        # (region) -> (prices, notes) for the cost estimate: AWS's Price List, or its saved copy
        self.price_loader = price_loader or load_prices
        # Rule checks and state changes happen under this lock, so two clicks can't both start
        # a run or both press play. The slow work in execute() runs outside it.
        self._lock = threading.Lock()
        # Never raise the same approval ticket twice. Re-entrant: deciding whether an approval's turn
        # has come looks at its predecessors, which takes the lock again on the same thread.
        self._ticket_lock = threading.RLock()

    # ---- One-call versions (CLI, tests) ----------------------------------------------------

    def build(self, spec_path: Path, overrides: dict[str, str] | None = None,
              autofix: dict | None = None) -> RunRecord:
        return self.execute(self.start_build(spec_path, overrides, autofix).id)

    def rehearse(self, spec_path: Path, diagnostics_mode: str | None = None,
                 overrides: dict[str, str] | None = None) -> RunRecord:
        return self.execute(self.start_rehearse(spec_path, diagnostics_mode, overrides).id)

    def deploy(self, spec_path: Path, diagnostics_mode: str | None = None) -> RunRecord:
        return self.execute(self.start_deploy(spec_path, diagnostics_mode).id)

    def play(self, run_id: str, step_id: str) -> RunRecord:
        return self.execute(self.request_play(run_id, step_id).id)

    def resume(self, run_id: str) -> RunRecord:
        return self.execute(self.request_resume(run_id).id)

    def undo(self, run_id: str) -> RunRecord:
        return self.execute(self.request_undo(run_id).id)

    # ---- Starting runs (quick: rule checks only) ---------------------------------------------

    def start_build(self, spec_path: Path, overrides: dict[str, str] | None = None,
                    autofix: dict | None = None) -> RunRecord:
        """overrides: RepoRef.key -> branch, used by auto-fix to test its own branch. Guardrails
        on an overridden repo are reported but don't block, and Deploy never accepts the result.
        autofix: {parent, branch, attempt, repo} when this Build is one of auto-fix's attempts."""
        with self._lock:
            spec, text = self._load(spec_path)
            overrides = overrides or {}
            unknown = sorted(set(overrides) - set(spec.repos()))
            if unknown:
                raise GateError(f"overrides name repos this pipeline doesn't use: {', '.join(unknown)}")
            run = self._new_run(spec, text, spec_path, "build", overrides=overrides, autofix=autofix or {},
                                next_action="build")
            self._event(run, "run", "Build started")
            return run

    def start_rehearse(self, spec_path: Path, diagnostics_mode: str | None = None,
                       overrides: dict[str, str] | None = None) -> RunRecord:
        with self._lock:
            spec, text = self._load(spec_path)
            self._refuse_if_active(spec)
            build = self.store.latest(spec.metadata.name, "build")
            if build is None or build.status != RunStatus.SUCCEEDED or build.spec_digest != spec.digest():
                raise GateError("Rehearse needs a passing Build of this exact migration.yaml. Run Build first.")
            if build.overrides != (overrides or {}):
                raise GateError("The last Build used different branches than this Rehearse. "
                                "Build again with the same ones.")
            run = self._new_run(spec, text, spec_path, "rehearse", overrides=build.overrides, shas=build.shas,
                                autofix=build.autofix, based_on=build.id, diagnostics_mode=diagnostics_mode,
                                next_action="advance")
            self._event(run, "run", "Rehearse started in the rehearsal environment; everything is undone at the end")
            return run

    def start_deploy(self, spec_path: Path, diagnostics_mode: str | None = None) -> RunRecord:
        with self._lock:
            spec, text = self._load(spec_path)
            self._refuse_if_active(spec)
            rehearsal = self.store.latest(spec.metadata.name, "rehearse")
            if rehearsal is None or rehearsal.status != RunStatus.SUCCEEDED or rehearsal.spec_digest != spec.digest():
                raise GateError("Deploy needs a passing Rehearse of this exact migration.yaml. Run Rehearse first.")
            if rehearsal.overrides:
                raise GateError("The last Rehearse ran auto-fix branches. "
                                "Merge them into main, then Build and Rehearse again.")
            try:
                current = {key: self.github.resolve(ref) for key, ref in spec.repos().items()}
            except IntegrationError as e:
                raise GateError(f"Couldn't check the repos on GitHub: {e}") from e
            changed = sorted(key for key, sha in current.items() if rehearsal.shas.get(key) != sha)
            if changed:
                raise GateError("Changed since the last Rehearse: " + ", ".join(changed)
                                + ". Run Build and Rehearse again so Deploy runs code that was rehearsed.")
            run = self._new_run(spec, text, spec_path, "deploy", shas=rehearsal.shas, based_on=rehearsal.id,
                                diagnostics_mode=diagnostics_mode, next_action="advance")
            self._event(run, "run", "Deploy started in production")
            return run

    # ---- Continuing runs (quick: rule checks only) -------------------------------------------

    def request_play(self, run_id: str, step_id: str) -> RunRecord:
        with self._lock:
            run, _ = self._existing(run_id)
            if run.status != RunStatus.WAITING or run.steps.get(step_id) != StepState.WAITING:
                raise GateError(f"{step_id} isn't waiting for play "
                                f"(run is {run.status}, step is {run.steps.get(step_id)})")
            run.played.append(step_id)
            return self._queue(run, "advance", f"{step_id}: play pressed", step_id)

    def request_resume(self, run_id: str) -> RunRecord:
        """Checks approvals again, e.g. after a Jira ticket moved."""
        with self._lock:
            run, _ = self._existing(run_id)
            if run.status != RunStatus.WAITING:
                raise GateError(f"run {run_id} is {run.status}, not waiting")
            return self._queue(run, "advance", "Resumed: checking approvals again")

    def request_undo(self, run_id: str) -> RunRecord:
        """Undo a waiting run, a finished Deploy, or retry the undo of a run whose undo didn't finish
        (rollback scripts are safe to run again; Terraform destroy is idempotent)."""
        with self._lock:
            run, _ = self._existing(run_id)
            allowed = (RunStatus.WAITING, RunStatus.SUCCEEDED, RunStatus.ROLLBACK_FAILED)
            if run.mode == "build" or run.status not in allowed \
                    or (run.mode == "rehearse" and run.status == RunStatus.SUCCEEDED):
                raise GateError(f"nothing to undo: {run.mode} run {run_id} is {run.status}")
            message = "Retrying the undo" if run.status == RunStatus.ROLLBACK_FAILED else "Undo requested"
            return self._queue(run, "undo", message)

    def request_cancel(self, run_id: str) -> RunRecord:
        """Stop a run and undo everything it did. A waiting run is undone at once (queued; the
        caller executes it). A run mid-step finishes that step, then undoes; a running script is
        killed, a running Terraform command is allowed to finish first."""
        with self._lock:
            run, _ = self._existing(run_id)
            if run.status == RunStatus.ROLLING_BACK:
                raise GateError(f"run {run_id} is already undoing itself")
            if not run.status.active:
                raise GateError(f"nothing to cancel: {run.mode} run {run_id} is {run.status}")
            self.store.request_cancel(run.id)
            if run.status == RunStatus.WAITING:
                return self._queue(run, "undo", "Cancelled: undoing everything this run did")
            self._event(run, "run", "Cancel requested: stopping after the current step, then undoing everything")
            return run

    # ---- Doing the work (slow) ----------------------------------------------------------------

    def execute(self, run_id: str) -> RunRecord:
        """Does what the last start_* / request_* call queued. Safe to call from a worker thread."""
        with self._lock:
            run, spec = self._existing(run_id)
            action, run.next_action = run.next_action, None
            if action is None:
                raise GateError(f"run {run_id} has nothing queued")
            self.store.save(run)
        if action == "build":
            return self._do_build(run, spec)
        if action == "undo":
            self._skip_unreached(run)
            ok = self._rollback(run, spec, failed=None)
            cancelled = self.store.cancel_requested(run.id)
            self.store.clear_cancel(run.id)
            done = RunStatus.CANCELLED if cancelled else RunStatus.UNDONE
            return self._finish(run, done if ok else RunStatus.ROLLBACK_FAILED,
                                ("cancelled" if cancelled else None) if ok else "undo didn't finish; see the log for what's left")
        return self._advance(run, spec)

    def recover(self) -> list[str]:
        """After a restart: returns runs that were queued but never picked up (execute them again),
        and marks runs that were mid-work as rollback_failed, since what they left behind is unknown.
        A Build changes nothing, so one cut short is just failed."""
        queued = []
        for run in self.store.runs(limit=500):
            if run.mode not in ("build", "rehearse", "deploy"):
                if run.status.active:  # an agent job (ingest, plan, …): nothing in AWS to undo
                    self._finish(run, RunStatus.FAILED, "the server restarted while this was running; start it again")
                continue
            if run.next_action is not None and run.status.active:
                queued.append(run.id)
            elif run.status in (RunStatus.RUNNING, RunStatus.ROLLING_BACK) and run.mode == "build":
                self.settle(run)
                self._finish(run, RunStatus.FAILED, "the runner restarted in the middle of this Build; run it again")
            elif run.status in (RunStatus.RUNNING, RunStatus.ROLLING_BACK):
                self.settle(run, RunStatus.ROLLBACK_FAILED)
                self._finish(run, RunStatus.ROLLBACK_FAILED,
                             "the runner restarted in the middle of this run; undoing what it left behind")
                queued.append(self.request_undo(run.id).id)  # the caller executes it, like other queued work
            elif not run.status.active and self._unsettled(run):
                self.settle(run, run.status)  # a finished run from before this repair existed
        return queued

    def _unsettled(self, run: RunRecord) -> bool:
        return any(s in (StepState.RUNNING, StepState.PENDING, StepState.BLOCKED, StepState.WAITING)
                   for s in run.steps.values())

    def settle(self, run: RunRecord, status: RunStatus = RunStatus.FAILED) -> None:
        """A run that died mid-work can't leave steps running or pending: the step that was running
        is failed (or rollback_failed, if the run was undoing), and the rest were never reached."""
        for step_id, state in run.steps.items():
            if state == StepState.RUNNING:
                run.steps[step_id] = StepState.ROLLBACK_FAILED if status == RunStatus.ROLLBACK_FAILED else StepState.FAILED
                run.failed_step = run.failed_step or step_id
                self._event(run, "step", f"{step_id}: {run.steps[step_id]}", step_id)
            elif state in (StepState.PENDING, StepState.BLOCKED, StepState.WAITING):
                run.steps[step_id] = StepState.SKIPPED
        self.store.save(run)

    def _do_build(self, run: RunRecord, spec: Spec) -> RunRecord:
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
            self._write_design(run, spec)
            self._report_approvals(run, spec)
            for step in execution_order(spec):
                if self.store.cancel_requested(run.id):
                    self.store.clear_cancel(run.id)
                    return self._finish(run, RunStatus.CANCELLED, "cancelled")  # a Build changes nothing
                if step.type == StepType.IAC:
                    self._build_action(run, spec, step, "plan")
                elif step.type == StepType.CHECK and not follows_a_change(spec, step):
                    self._build_action(run, spec, step, "run")
        except _BuildStepFailed as e:
            return self._finish(run, RunStatus.FAILED, str(e))
        except IntegrationError as e:
            return self._finish(run, RunStatus.FAILED, str(e))
        self._estimate_cost(run, spec)
        return self._finish(run, RunStatus.SUCCEEDED)

    # ---- The state machine ----------------------------------------------------------------

    def _advance(self, run: RunRecord, spec: Spec) -> RunRecord:
        run.status, run.reason = RunStatus.RUNNING, None
        self.store.save(run)
        for step in execution_order(spec):
            if run.steps[step.id] == StepState.SUCCEEDED:
                continue
            if self.store.cancel_requested(run.id):
                return self._cancel(run, spec)

            if run.mode == "deploy" and step.requires_approval:
                try:
                    log = lambda m: self._event(run, "log", m)  # noqa: E731
                    states = {a: self._approval_state(run.migration, run.spec_digest, spec, spec.approval(a), log)
                              for a in step.requires_approval}
                except IntegrationError as e:
                    return self._wait(run, step, StepState.BLOCKED, f"couldn't check approvals: {e}")
                rejected = [f"{a} ({detail})" for a, (status, detail) in states.items() if status == "rejected"]
                if rejected:
                    return self._fail(run, spec, step, f"approval rejected: {', '.join(rejected)}", ran=False)
                pending = [f"{a} ({detail})" for a, (status, detail) in states.items() if status != "approved"]
                if pending:
                    return self._wait(run, step, StepState.BLOCKED, "waiting for approval: " + ", ".join(pending))

            if step.when == "manual" and step.id not in run.played:
                return self._wait(run, step, StepState.WAITING, f"{step.id} is manual: press play to run it")

            self._set(run, step, StepState.RUNNING)
            try:
                ctx = self._context(run, spec, step)
                produced = self.executor.execute(ctx, "run") or {}
                self._record_outputs(run, step, produced)
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
            run = self._finish(run, RunStatus.SUCCEEDED if ok else RunStatus.ROLLBACK_FAILED,
                               None if ok else "the rehearsal passed, but cleaning it up didn't finish")
            if ok and run.autofix:
                self._autofix_passed(run, spec)
            return run
        return self._finish(run, RunStatus.SUCCEEDED)

    def _cancel(self, run: RunRecord, spec: Spec) -> RunRecord:
        self._event(run, "run", "Cancelled. Undoing everything this run did.")
        self._skip_unreached(run)
        ok = self._rollback(run, spec, failed=None)
        self.store.clear_cancel(run.id)
        return self._finish(run, RunStatus.CANCELLED if ok else RunStatus.ROLLBACK_FAILED,
                            "cancelled" if ok else "cancelled, but the undo didn't finish; see the log")

    def _fail(self, run: RunRecord, spec: Spec, step: Step, reason: str, ran: bool) -> RunRecord:
        if self.store.cancel_requested(run.id):  # the step was killed by a cancel, not broken
            run.steps[step.id] = StepState.SKIPPED if not ran else StepState.FAILED
            run.failed_step = None
            return self._cancel(run, spec)
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
        targets = [spec.step(i) for i in reversed(run.completed)
                   if run.steps.get(i) != StepState.ROLLED_BACK]  # a retried undo skips what's done
        if failed is None and run.failed_step and run.steps.get(run.failed_step) == StepState.ROLLBACK_FAILED:
            failed = spec.step(run.failed_step)  # a retried undo redoes the failed step's own cleanup
        if failed is not None and failed.type in SELF_ROLLBACK_ON_FAILURE and failed not in targets:
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
            if step is not failed or run.steps.get(step.id) == StepState.ROLLBACK_FAILED:
                self._set(run, step, StepState.ROLLED_BACK)
            else:
                self._event(run, "log", "undid this step's partial changes", step.id)
        undone = [s.id for s in targets if s.mutating and run.steps.get(s.id) == StepState.ROLLED_BACK]
        if ok and undone:
            self._event(run, "run", f"Undo verified: {len(undone)} step(s) undone and checked empty "
                        f"({', '.join(undone)}). Nothing this run created is left.")
        elif not ok:
            left = [s.id for s in targets if run.steps.get(s.id) == StepState.ROLLBACK_FAILED]
            self._event(run, "run", f"Undo NOT complete: {', '.join(left)} could not be undone or verified. "
                        "Press Undo to retry; see each step's log for what's left.")
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
        """Raises every ticket whose turn has come, and records each approval's status."""
        run.report["approvals"] = {}
        log = lambda m: self._event(run, "log", m)  # noqa: E731
        for approval in spec.approvals:
            try:
                status, detail = self._approval_state(run.migration, run.spec_digest, spec, approval, log)
            except IntegrationError as e:
                status, detail = "unknown", str(e)
            ticket = self.store.ticket(run.migration, run.spec_digest, approval.id)
            run.report["approvals"][approval.id] = {
                "status": status, "detail": detail,
                "ticket": ticket.key if ticket else None, "url": ticket.url if ticket else None}
            self.store.save_approval_record(run.migration, run.spec_digest,
                                            ApprovalRecord(approval=approval.id, status=status, detail=detail, checked=time.time()))
            self._event(run, "log", f"approval {approval.id}: {status} ({detail})")
        self.store.save(run)

    def sync_approvals(self, spec_path: Path) -> dict:
        """Checks every approval of this migration's current plan against Jira: raises the tickets
        whose turn has come (the next link of an `after` chain, once its predecessor is approved),
        records each status, and queues every run that was waiting on an approval so it continues.
        Called by the server's poller and the Jira webhook; the caller executes the queued runs.
        Does nothing until a Build has raised the first tickets."""
        spec = load_spec(spec_path)
        migration, digest = spec.metadata.name, spec.digest()
        tickets_before = set(self.store.tickets(migration, digest))
        if not tickets_before:
            return {"migration": migration, "changed": [], "raised": [], "resumed": [], "statuses": {}}
        before = self.store.approval_records(migration, digest)
        notes: list[str] = []
        statuses: dict[str, dict] = {}
        for approval in spec.approvals:
            try:
                status, detail = self._approval_state(migration, digest, spec, approval, notes.append)
            except IntegrationError as e:
                status, detail = "unknown", str(e)
            statuses[approval.id] = {"status": status, "detail": detail}
            self.store.save_approval_record(migration, digest,
                                            ApprovalRecord(approval=approval.id, status=status, detail=detail, checked=time.time()))
        changed = [a for a, s in statuses.items() if a not in before or before[a].status != s["status"]]
        raised = sorted(set(self.store.tickets(migration, digest)) - tickets_before)
        resumed: list[str] = []
        if changed or raised:
            latest = self.store.latest(migration)
            if latest is not None:  # tell the console, on the run people are looking at
                for note in notes:
                    self._event(latest, "log", note)
                summary = ", ".join(f"{a} {statuses[a]['status']}" for a in changed)
                self._event(latest, "log", "approvals changed in Jira: " + summary)
                # A non-log event makes every console watching this run refetch the approvals at once.
                parts = ([summary] if changed else []) + ([f"raised {', '.join(raised)}"] if raised else [])
                self._event(latest, "approval", "approvals: " + "; ".join(parts))
            for run in self.store.runs(migration):
                if run.status == RunStatus.WAITING and StepState.BLOCKED in run.steps.values():
                    resumed.append(self.request_resume(run.id).id)
        return {"migration": migration, "changed": changed, "raised": raised, "resumed": resumed, "statuses": statuses}

    # ---- Approvals: tickets raised by code, one per approval per spec version ---------------

    def _approval_state(self, migration: str, digest: str, spec: Spec, approval: Approval,
                        log: Callable[[str], None]) -> tuple[str, str]:
        """(approved | pending | rejected, detail). Raises the ticket if its turn has come:
        everything in `after` approved, and the design page written if it needs one."""
        ticket = self.store.ticket(migration, digest, approval.id)
        if ticket is None:
            # The poller, the Jira webhook and Build can all get here at once. Deciding "is it this
            # approval's turn, and does it already have a ticket?" and raising the ticket is one step,
            # so two callers can't both raise it or both comment on the old one.
            with self._ticket_lock:
                ticket = self.store.ticket(migration, digest, approval.id)  # another caller may have just done it
                if ticket is None:
                    waiting, ticket = self._ticket_or_wait(migration, digest, spec, approval, log)
                    if waiting is not None:
                        return waiting
        return self.approvals.status(ticket.key), ticket.key

    def _ticket_or_wait(self, migration: str, digest: str, spec: Spec, approval: Approval,
                        log: Callable[[str], None]) -> tuple[tuple[str, str] | None, Ticket | None]:
        """Only called holding the ticket lock. (None, ticket) when the approval has a ticket for this
        plan version (reused from an earlier version, or raised now); otherwise ((status, detail), None)
        because it isn't requested yet: a predecessor in `after` isn't approved, or the page is missing."""
        previous = self.store.latest_ticket(migration, approval.id)
        if previous is not None:
            # The plan changed but the approval is the same ask: keep the ticket, tell the approver.
            self.store.save_ticket(migration, digest, previous)
            comment = getattr(self.approvals, "comment", None)
            if comment is not None:
                try:
                    comment(previous.key, f"MaC: the migration plan was updated (version {digest[:12]}). "
                                          "This ticket still covers this approval; the design page is updated in place.")
                except IntegrationError as e:
                    log(f"couldn't comment on {previous.key}: {e}")
            log(f"{previous.key} still covers {approval.id} for the updated plan")
            return None, previous
        for dep in approval.after:
            dep_status, _ = self._approval_state(migration, digest, spec, spec.approval(dep), log)
            if dep_status == "rejected":
                return ("rejected", f"{dep} was rejected, so this was never requested"), None
            if dep_status != "approved":
                return ("pending", f"not requested until {dep} is approved"), None
        if approval.design_doc:
            page = self.store.design(migration)
            if page is None or page.digest != digest:
                return ("pending", "not requested until the design page is written (run Build)"), None
        return None, self._raise_ticket(migration, digest, spec, approval, log)

    def _raise_ticket(self, migration: str, digest: str, spec: Spec, approval: Approval,
                      log: Callable[[str], None]) -> Ticket:
        with self._ticket_lock:
            existing = self.store.ticket(migration, digest, approval.id)
            if existing:
                return existing
            unblocks = [s.id for s in execution_order(spec) if approval.id in s.requires_approval]
            links = []
            if approval.design_doc:
                links.append(("Design page", self.store.design(migration).url))
            request = TicketRequest(
                approval_id=approval.id,
                summary=approval.summary,
                paragraphs=[
                    (approval.justification or "").strip(),
                    f"Requested by MaC for migration {spec.metadata.name} ({spec.metadata.service}), "
                    f"plan version {digest[:12]}.",
                    "Deploy waits for this approval before running: " + ", ".join(unblocks) + ".",
                    "To approve, move this ticket to Approved (or Done). To reject, move it to Rejected.",
                ],
                approver=approval.approver,
                labels=["mac", spec.metadata.name, approval.type, approval.id],
                links=links,
            )
            raised = self.approvals.raise_ticket(request)
            ticket = Ticket(approval=approval.id, key=raised.key, url=raised.url)
            self.store.save_ticket(migration, digest, ticket)
            log(f"raised {ticket.key} for approval {approval.id} ({approval.approver})")
            return ticket

    # ---- The design page: an LLM writes prose; code publishes it ----------------------------

    def _write_design(self, run: RunRecord, spec: Spec) -> None:
        """Never fails the Build: without a page, only the Tech Risk ticket has to wait."""
        existing = self.store.design(run.migration)
        if existing and existing.digest == run.spec_digest:
            return self._design_report(run, existing.url, "up to date")
        if self.design_writer is None or self.pages is None:
            return self._design_report(run, None, "not written: the LLM or Confluence isn't configured")
        self._event(run, "log", "asking the LLM to write the design page")
        try:
            markdown = self.design_writer.write(facts(spec, run.shas))
            page_id, url = self.pages.publish(page_title(spec), render_page(spec, run.shas, markdown, run.id),
                                              existing.page_id if existing else None)
        except Exception as e:  # noqa: BLE001 - the LLM or Confluence failing must never fail the Build
            return self._design_report(run, None, f"not written: {e}")
        self.store.save_design(run.migration, DesignPage(page_id=page_id, url=url, digest=run.spec_digest))
        self._design_markdown_path(run.migration).parent.mkdir(parents=True, exist_ok=True)
        self._design_markdown_path(run.migration).write_text(markdown, encoding="utf-8")  # to add the cost later
        self._design_report(run, url, "written")

    def _design_report(self, run: RunRecord, url: str | None, status: str) -> None:
        run.report["design_page"] = {"url": url, "status": status}
        self._event(run, "log", f"design page: {status}" + (f" ({url})" if url else ""))
        self.store.save(run)

    def _build_action(self, run: RunRecord, spec: Spec, step: Step, action: str) -> None:
        self._set(run, step, StepState.RUNNING)
        try:
            self.executor.execute(self._context(run, spec, step), action)
        except Exception as e:  # noqa: BLE001
            self._set(run, step, StepState.FAILED)
            run.failed_step = step.id
            raise _BuildStepFailed(f"{step.id} ({'terraform plan' if action == 'plan' else 'check'}): {_reason(e)}") from e
        if action == "plan":
            self._record_resources(run, step)
        self._set(run, step, StepState.SUCCEEDED)

    # ---- The cost estimate: code multiplies the plan, the documented usage and AWS's prices ----

    def _record_resources(self, run: RunRecord, step: Step) -> None:
        path = resources_path(self.data_dir / "runs" / run.id, step.id)
        if path.exists():
            try:
                run.report.setdefault("resources", {})[step.id] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass

    def _estimate_cost(self, run: RunRecord, spec: Spec) -> None:
        """Never fails the Build: a cost problem only shows in the report."""
        try:
            prices, notes = self.price_loader(spec.target.region)
            view = estimate_cost(run.report.get("resources", {}), load_usage(self.data_dir, run.migration),
                                 prices, notes)
        except Exception as e:  # noqa: BLE001
            view = {"status": "unavailable", "reason": f"couldn't calculate the cost: {e}", "notes": []}
        run.report["cost"] = view
        self._event(run, "log", cost_summary(view))
        self.store.save(run)
        if view["status"] in ("complete", "partial"):
            self._share_cost(run, spec, view)

    def _design_markdown_path(self, migration: str) -> Path:
        return self.data_dir / "designs" / f"{migration}.md"

    def _share_cost(self, run: RunRecord, spec: Spec, view: dict) -> None:
        """Puts the estimate on the design page and tells the design-page approvers, once per
        change of the estimate. Code writes both; failures are logged, never fatal."""
        record_path = self.data_dir / "designs" / f"{run.migration}.cost.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        except ValueError:
            record = {}
        page = self.store.design(run.migration)
        markdown_path = self._design_markdown_path(run.migration)
        shared = record.get("digest") == view["digest"] and record.get("spec") == run.spec_digest
        if not shared and page and page.digest == run.spec_digest and self.pages and markdown_path.exists():
            try:
                self.pages.publish(page_title(spec), render_page(spec, run.shas, markdown_path.read_text(encoding="utf-8"),
                                                                 run.id, cost=view), page.page_id)
                self._event(run, "log", f"design page: cost estimate added ({page.url})")
                record["page"] = view["digest"]
            except Exception as e:  # noqa: BLE001
                self._event(run, "log", f"design page: couldn't add the cost estimate: {e}")
        told = set(record.get("told", [])) if record.get("digest") == view["digest"] else set()
        comment = getattr(self.approvals, "comment", None)
        for approval in spec.approvals:
            ticket = self.store.ticket(run.migration, run.spec_digest, approval.id)
            if not approval.design_doc or ticket is None or ticket.key in told or comment is None:
                continue
            try:
                comment(ticket.key, f"MaC: {cost_summary(view)} Every line, with its formula and sources, is on "
                                    f"the design page" + (f": {page.url}" if page else "."))
                told.add(ticket.key)
                self._event(run, "log", f"cost estimate sent to {ticket.key}")
            except IntegrationError as e:
                self._event(run, "log", f"couldn't comment the cost on {ticket.key}: {e}")
        record.update(digest=view["digest"], spec=run.spec_digest, told=sorted(told))
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record), encoding="utf-8")

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

    def _record_outputs(self, run: RunRecord, step: Step, produced: dict[str, str]) -> None:
        """Keeps the outputs the plan declared. One that wasn't produced fails the step: the
        planner said this step would hand it back, and the probes depend on it."""
        if not step.outputs:
            return
        missing = [o.name for o in step.outputs if not produced.get(o.name)]
        if missing:
            raise StepFailed(f"{step.id} didn't produce its declared output(s): {', '.join(missing)}")
        run.outputs[step.id] = {o.name: produced[o.name] for o in step.outputs}
        self.store.save(run)
        for o in step.outputs:
            self._event(run, "log", f"output {o.name} = {produced[o.name]}", step.id)

    def _context(self, run: RunRecord, spec: Spec, step: Step) -> StepContext:
        run_dir = self.data_dir / "runs" / run.id
        run_dir.mkdir(parents=True, exist_ok=True)
        return StepContext(spec=spec, step=step, mode=run.mode, run_id=run.id, shas=run.shas, run_dir=run_dir,
                           log=lambda line: self.store.add_event(run.id, "log", line, step.id),
                           cancelled=lambda: self.store.cancel_requested(run.id))

    def _set(self, run: RunRecord, step: Step, state: StepState) -> None:
        run.steps[step.id] = state
        self.store.save(run)
        self._event(run, "step", f"{step.id}: {state}", step.id)

    def _queue(self, run: RunRecord, action: str, message: str, step: str | None = None) -> RunRecord:
        # Marked running straight away, so a second click is refused while the work is queued.
        run.next_action, run.status, run.reason = action, RunStatus.RUNNING, None
        self.store.save(run)
        self._event(run, "step" if step else "run", message, step)
        return run

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
                          repo=repo, sha=run.shas.get(repo, ""), spec_path=run.spec_path,
                          completed=tuple(run.completed), shas=dict(run.shas),
                          attempt=int(run.autofix.get("attempt", 0)), branch=run.autofix.get("branch"),
                          parent=run.autofix.get("parent"))
        self.diagnosing.add(run.id)  # counts as busy: a deploy waits rather than cut the AI off
        try:
            summary = self.diagnostician.diagnose(spec, failure, Mode(run.diagnostics_mode))
        except Exception as e:  # noqa: BLE001 - AI help failing must never change the run's outcome
            summary = f"AI help failed: {_reason(e)}"
        finally:
            self.diagnosing.discard(run.id)
        self._event(run, "diagnosis", summary, step.id)

    def request_ai(self, run_id: str, mode: str) -> RunRecord:
        """Run AI help again on a finished, failed run (e.g. switch it to Auto-fix) from its stored
        logs, without repeating the run. The caller executes rerun_ai() in the background."""
        with self._lock:
            run, _ = self._existing(run_id)
            if run.mode not in ("rehearse", "deploy") or run.status.active or not run.failed_step:
                raise GateError(f"AI help needs a finished Rehearse or Deploy with a failed step ({run.mode} {run.status})")
            if run.id in self.diagnosing:
                raise GateError("AI help is already working on this run")
            if mode == Mode.AUTOFIX and run.mode == "deploy":
                raise GateError("Auto-fix only acts on rehearsals; use Explain or Report for a Deploy")
            run.diagnostics_mode = Mode(mode)
            self.store.save(run)
            self._event(run, "run", f"AI help ({mode}) requested again")
            return run

    def rerun_ai(self, run_id: str) -> None:
        run, spec = self._existing(run_id)
        step = spec.step(run.failed_step)
        self._diagnose(run, spec, step, run.reason or "")

    def _autofix_passed(self, run: RunRecord, spec: Spec) -> None:
        """An auto-fix branch rehearsed cleanly: the diagnostician opens the PR. People merge it."""
        hook = getattr(self.diagnostician, "autofix_passed", None)
        if hook is None:
            return
        try:
            url = hook(spec, run.autofix, run.id)
        except Exception as e:  # noqa: BLE001
            self._event(run, "diagnosis", f"auto-fix passed, but opening its pull request failed: {_reason(e)}")
            return
        if url:
            run.autofix = {**run.autofix, "pr": url}
            self.store.save(run)
            self._event(run, "diagnosis", f"Auto-fix passed: every step ran and was undone with the fix on "
                        f"{run.autofix.get('branch')}. Pull request: {url}. Merge it, then Build and Rehearse main.")


class _BuildStepFailed(Exception):
    pass


def _reason(error: Exception) -> str:
    if isinstance(error, (StepFailed, IntegrationError)):
        return str(error)
    return f"runner error: {type(error).__name__}: {error}"
