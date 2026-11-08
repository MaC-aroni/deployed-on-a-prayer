"""`mac`: drive the runner from a terminal. The web UI will call the same Runner methods.

Configuration (environment variables):
  MAC_DATA_DIR            run history, logs and work dirs (default: ./.mac)
  GITHUB_TOKEN            read access to the pipeline's repos (guardrails + checkout)
  JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN   approvals; without them, approval steps wait
  MAC_TF_STATE_BUCKET, MAC_TF_STATE_REGION   S3 bucket for Terraform state
  AWS credentials as usual (AWS_PROFILE or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
"""

import argparse
import os
import sys
from pathlib import Path

from .executors import Executor, TerraformState
from .integrations import GitCheckout, GitHubAPI, IntegrationError, JiraApprovals
from .runner import GateError, Runner
from .spec import SpecError, load_spec
from .store import Event, RunRecord, RunStatus, Store
from .validate import execution_order, validate


class _NoJira:
    def status(self, ticket: str):
        raise IntegrationError("Jira isn't configured (JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN)")


def make_runner(data_dir: Path) -> Runner:
    token = os.environ.get("GITHUB_TOKEN")
    if all(os.environ.get(k) for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN")):
        approvals = JiraApprovals(os.environ["JIRA_SITE"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
    else:
        approvals = _NoJira()
    bucket = os.environ.get("MAC_TF_STATE_BUCKET")
    tf_state = TerraformState(bucket, os.environ.get("MAC_TF_STATE_REGION", "us-east-1")) if bucket else None
    executor = Executor(GitCheckout(token), data_dir / "work", tf_state)
    return Runner(Store(data_dir / "mac.db"), GitHubAPI(token), approvals, executor, data_dir)


def _print_event(event: Event) -> None:
    prefix = f"[{event.step}] " if event.step else ""
    if event.kind == "log":
        print(f"    {prefix}{event.message}")
    elif event.kind != "step":
        print(f"==> {prefix}{event.message}")
    sys.stdout.flush()


def _summary(run: RunRecord) -> None:
    print(f"\n{run.mode} {run.id}: {run.status}" + (f" ({run.reason})" if run.reason else ""))
    for step_id, state in run.steps.items():
        print(f"  {state:<16} {step_id}")
    if run.status == RunStatus.WAITING:
        waiting = [s for s, st in run.steps.items() if st == "waiting"]
        if waiting:
            print(f"\nNext: mac play {run.id} {waiting[0]}")
        else:
            print(f"\nNext: approve the ticket, then mac resume {run.id}")


def _exit_code(run: RunRecord) -> int:
    return 0 if run.status in (RunStatus.SUCCEEDED, RunStatus.WAITING, RunStatus.UNDONE) else 1


def cmd_validate(args) -> int:
    try:
        spec = load_spec(args.spec)
    except SpecError as e:
        print("\n".join(e.problems))
        return 1
    issues = validate(spec)
    for issue in issues:
        print(issue)
    if any(i.level == "error" for i in issues):
        return 1
    print(f"{args.spec}: valid. Order:")
    for stage in spec.stages:
        steps = [s.id + (" (manual)" if s.when == "manual" else "") for s in execution_order(spec) if s.stage == stage]
        print(f"  {stage}: {', '.join(steps)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mac", description="Migration as Code runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a migration.yaml without running anything")
    p.add_argument("spec", type=Path)

    p = sub.add_parser("build", help="check everything and lock commits; changes nothing")
    p.add_argument("spec", type=Path)
    p.add_argument("--branch", action="append", default=[], metavar="REPO=BRANCH",
                   help="use a branch instead of main for one repo (auto-fix testing)")

    for name, text in (("rehearse", "run everything in the rehearsal environment, then undo it"),
                       ("deploy", "run it for real, with the commits the last Rehearse used")):
        p = sub.add_parser(name, help=text)
        p.add_argument("spec", type=Path)
        p.add_argument("--ai", choices=["explain", "report", "autofix"], help="AI help if a step fails")
        if name == "rehearse":
            p.add_argument("--branch", action="append", default=[], metavar="REPO=BRANCH")

    p = sub.add_parser("play", help="run a manual step a run is waiting on")
    p.add_argument("run_id")
    p.add_argument("step")
    for name, text in (("resume", "check approvals again and continue"),
                       ("undo", "roll back everything a run did"),
                       ("status", "show a run's steps")):
        sub.add_parser(name, help=text).add_argument("run_id")
    p = sub.add_parser("logs", help="print a run's event log")
    p.add_argument("run_id")
    p.add_argument("--step")
    p = sub.add_parser("runs", help="list recent runs")
    p.add_argument("--migration")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)

    runner = make_runner(Path(os.environ.get("MAC_DATA_DIR", ".mac")).resolve())
    if args.command in ("build", "rehearse", "deploy", "play", "resume", "undo"):
        runner.store.listeners.append(_print_event)
    try:
        if args.command == "build":
            run = runner.build(args.spec, overrides=_branches(args.branch))
        elif args.command == "rehearse":
            run = runner.rehearse(args.spec, args.ai, overrides=_branches(args.branch))
        elif args.command == "deploy":
            run = runner.deploy(args.spec, args.ai)
        elif args.command == "play":
            run = runner.play(args.run_id, args.step)
        elif args.command == "resume":
            run = runner.resume(args.run_id)
        elif args.command == "undo":
            run = runner.undo(args.run_id)
        elif args.command == "status":
            run = runner.store.get(args.run_id)
        elif args.command == "logs":
            for event in runner.store.events(args.run_id, step=args.step):
                _print_event(event)
            return 0
        else:
            for run in runner.store.runs(args.migration):
                print(f"{run.id}  {run.mode:<9} {run.status:<16} {run.migration}")
            return 0
    except (GateError, KeyError) as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    _summary(run)
    return _exit_code(run)


def _branches(pairs: list[str]) -> dict[str, str]:
    result = {}
    for pair in pairs:
        repo, sep, branch = pair.partition("=")
        if not sep or not branch:
            raise SystemExit(f"--branch expects REPO=BRANCH, got {pair!r}")
        result[repo.split("@")[0]] = branch
    return result
