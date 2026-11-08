"""`mac`: drive the runner from a terminal. The web UI calls the same Runner methods.

Configuration (environment variables; see docs/runner.md):
  MAC_DATA_DIR            run history, logs and work dirs (default: ./.mac)
  GITHUB_TOKEN            read access to the pipeline's repos (guardrails + checkout)
  ATLASSIAN_SITE, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN   Jira approvals + Confluence pages
  JIRA_PROJECT (default MAC), JIRA_ISSUE_TYPE (default Task), MAC_JIRA_ASSIGNEES (JSON)
  CONFLUENCE_SPACE_KEY    where the design page goes
  NVIDIA_API_KEY, MAC_LLM_MODEL, MAC_LLM_BASE_URL   the LLM that writes the design page
  MAC_TF_STATE_BUCKET, MAC_TF_STATE_REGION   S3 bucket for Terraform state
  AWS credentials as usual (AWS_PROFILE or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .aihelp import LLMDiagnostician, autofix_cycle
from .design import NIMDesignWriter
from .executors import Executor, TerraformState
from .integrations import ConfluencePages, GitCheckout, GitHubAPI, IntegrationError, JiraApprovals
from .knowledge import KnowledgeError, load_pages, publish
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, NIMChat
from .runner import GateError, Runner
from .sources import sections_from_pages
from .spec import SpecError, load_spec
from .store import Event, RunRecord, RunStatus, Store
from .validate import execution_order, validate

class _NoJira:
    """Without Jira, approval steps wait with this message instead of failing."""

    message = "Jira isn't configured (ATLASSIAN_SITE, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)"

    def status(self, ticket: str):
        raise IntegrationError(self.message)

    def raise_ticket(self, request):
        raise IntegrationError(self.message)


def _env(*names: str) -> str | None:
    """The first of these variables that's set. JIRA_* still works from before ATLASSIAN_*."""
    return next((os.environ[n] for n in names if os.environ.get(n)), None)


REPO_ROOT = Path(__file__).resolve().parents[2]


def knowledge_sections(store: Store) -> list:
    """The company knowledge base, for grounding diagnoses. Empty if the folder isn't there."""
    directory = Path(os.environ.get("MAC_KNOWLEDGE_DIR") or REPO_ROOT / "demo-data" / "confluence")
    if not directory.is_dir():
        return []
    try:
        urls = {page: ids[1] for page, ids in store.knowledge_pages().items()} if hasattr(store, "knowledge_pages") else {}
        return sections_from_pages(load_pages(directory), urls)
    except (KnowledgeError, OSError, IndexError, TypeError):
        return []


def make_runner(data_dir: Path, submit=None) -> Runner:
    """submit(fn, *args): how auto-fix's next Build and Rehearse are started. None runs them inline
    (the CLI); the server passes its worker pool."""
    token = os.environ.get("GITHUB_TOKEN")
    site = _env("ATLASSIAN_SITE", "JIRA_SITE")
    email = _env("ATLASSIAN_EMAIL", "JIRA_EMAIL")
    api_token = _env("ATLASSIAN_API_TOKEN", "JIRA_API_TOKEN")
    approvals, pages = _NoJira(), None
    if site and email and api_token:
        assignees = json.loads(os.environ.get("MAC_JIRA_ASSIGNEES") or "{}")
        approvals = JiraApprovals(site, email, api_token, project=os.environ.get("JIRA_PROJECT", "MAC"),
                                  issue_type=os.environ.get("JIRA_ISSUE_TYPE", "Task"), assignees=assignees)
        if os.environ.get("CONFLUENCE_SPACE_KEY"):
            pages = ConfluencePages(site, email, api_token, os.environ["CONFLUENCE_SPACE_KEY"])
    writer = None
    llm_key = os.environ.get("MAC_LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if llm_key:
        writer = NIMDesignWriter(llm_key, os.environ.get("MAC_LLM_MODEL", DEFAULT_MODEL),
                                 os.environ.get("MAC_LLM_BASE_URL", DEFAULT_BASE_URL))
    bucket = os.environ.get("MAC_TF_STATE_BUCKET")
    tf_state = TerraformState(bucket, os.environ.get("MAC_TF_STATE_REGION", "us-east-1")) if bucket else None
    executor = Executor(GitCheckout(token), data_dir / "work", tf_state)
    store, github = Store(data_dir / "mac.db"), GitHubAPI(token)
    diagnostician = None
    if llm_key:
        llm = NIMChat(llm_key, os.environ.get("MAC_LLM_MODEL", DEFAULT_MODEL), os.environ.get("MAC_LLM_BASE_URL", DEFAULT_BASE_URL))
        diagnostician = LLMDiagnostician(llm, github, store, knowledge_sections(store))
    runner = Runner(store, github, approvals, executor, data_dir, diagnostician, design_writer=writer, pages=pages)
    if diagnostician is not None:
        if submit is None:
            diagnostician.continue_with = lambda path, overrides, autofix: autofix_cycle(runner, path, overrides, autofix)
        else:
            diagnostician.continue_with = lambda path, overrides, autofix: submit(autofix_cycle, runner, path, overrides, autofix)
    return runner


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


def cmd_publish_knowledge(runner: Runner, directory: Path) -> int:
    try:
        pages = load_pages(directory)
    except KnowledgeError as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1
    if runner.pages is None:
        print("Confluence isn't configured (ATLASSIAN_* and CONFLUENCE_SPACE_KEY)", file=sys.stderr)
        return 2
    known = {page: ids[0] for page, ids in runner.store.knowledge_pages().items()}
    try:
        published = publish(pages, runner.pages, known)
    except IntegrationError as e:
        print(f"Publishing failed: {e}", file=sys.stderr)
        return 1
    by_id = {page.id: page for page in pages}
    for page, (page_id, url) in published.items():
        runner.store.save_knowledge_page(page, page_id, url, by_id[page].title)
    print(f"published {len(published)} pages")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Local secrets (backend/.env, gitignored). Real environment variables win, so Fly secrets
    # and CI settings are never overridden by a stray file.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
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
    p = sub.add_parser("publish-knowledge", help="publish a folder of knowledge-base pages to Confluence")
    p.add_argument("directory", type=Path)
    for name, text in (("ingest", "build the knowledge graph from the knowledge base"),
                       ("plan", "write a migration.yaml for a goal, from the knowledge graph"),
                       ("guide", "write the cited migration guide into Confluence"),
                       ("codegen", "write a codegen: llm step's code, as a PR")):
        p = sub.add_parser(name, help=text)
        if name == "plan":
            p.add_argument("goal")
        elif name != "ingest":
            p.add_argument("spec", type=Path)
        if name == "codegen":
            p.add_argument("step")
        p.add_argument("--knowledge", type=Path, default=Path("demo-data/confluence"))
        if name in ("plan", "codegen"):
            p.add_argument("--pr", action="store_true", help="open a pull request with the result")

    p = sub.add_parser("prices", help="the AWS prices the cost estimate uses")
    p.add_argument("--refresh", action="store_true", help="save AWS's current prices as the snapshot")
    p = sub.add_parser("usage", help="read the usage figures the cost estimate needs from the knowledge base")
    p.add_argument("spec", type=Path)
    p.add_argument("--knowledge", type=Path, default=Path("demo-data/confluence"))
    p = sub.add_parser("cost", help="the cost estimate, from the last Build's plan, the usage figures and AWS's prices")
    p.add_argument("spec", type=Path)

    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)

    runner = make_runner(Path(os.environ.get("MAC_DATA_DIR", ".mac")).resolve())
    if args.command == "publish-knowledge":
        return cmd_publish_knowledge(runner, args.directory)
    if args.command in ("prices", "usage", "cost"):
        from .cost_cli import run_agent as run_cost  # keeps the runner commands free of agent imports
        return run_cost(args, runner)
    if args.command in ("ingest", "plan", "guide", "codegen"):
        from .agents_cli import run_agent  # keeps the runner commands free of agent imports
        return run_agent(args, runner)
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
