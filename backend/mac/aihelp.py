"""The AI behind Explain · Report · Auto-fix, through the shared LLM client.

  explain  - the failing step, its logs, and the standards it follows go to the model; it says
             what went wrong, the likely cause, where, and what to do. One event on the run.
  report   - also reads the failing step's code at the exact commit that ran, and writes a full
             Markdown report for a developer's coding agent (GET /runs/{id}/report.md).
  autofix  - also asks for the changed files, keeps only what the guardrails allow
             (mac/diagnostics.py), pushes them to the branch mac/autofix/<run>, and re-runs Build and
             Rehearse with that branch, up to MAX_AUTOFIX_ATTEMPTS. A passing rehearsal opens the PR.

The model only ever returns text. Code decides what reaches GitHub: which files, which branch,
and that nothing it writes is ever deployed (Deploy refuses any rehearsal that used a branch).
"""

import json
import posixpath
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from . import integrations
from .codegen import MAX_BYTES, MAX_FILES, allowed_prefix
from .diagnostics import MAX_AUTOFIX_ATTEMPTS, Failure, Mode, autofix_branch, autofix_violations
from .llm import LLM, parse_json
from .sources import Catalog, Section, relevant
from .spec import Spec, Step, StepType
from .store import Store

CODE_EXTENSIONS = (".py", ".tf", ".tfvars", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".md", ".txt", ".sh")
SKIP_DIRS = ("tests/", "test/", ".github/", "data/", ".terraform/", "node_modules/", "__pycache__/")
FILE_CHARS = 12_000
TOTAL_CHARS = 60_000
LOG_LINES = 120

EXPLAIN_SYSTEM = """You are MaC's diagnostician. A step of a migration pipeline failed while running
for real. You get the step, its log, and the company standards it follows (numbered sources).
Write Markdown with exactly these headings: "What went wrong", "Likely cause", "Where", "What to do".
Be concrete: quote the decisive log line, name the file and function if the log shows them, and
cite a standard as [S1], [S2]… only where it really applies. If the cause is in the migration's own
code rather than the environment, say which. Under 250 words. No preamble."""

REPORT_SYSTEM = """You are MaC's diagnostician writing a report for a developer's coding agent. You get the
failed step, its log, the company standards it follows (numbered sources), and the step's code at the
exact commit that ran. Write a complete Markdown report:
# <one-line title>
## Failure            (what ran, the decisive log lines)
## Root cause         (the specific code or configuration, with file and line references)
## Fix                (the exact change to make, as a unified diff or before/after snippets)
## Why this is right  (cite the standards as [S1]… where they apply)
## How to verify      (the pipeline steps or commands that prove it)
Only reference files you were shown. No preamble after the title."""

FIX_SYSTEM = """You are MaC's auto-fix. Given a failed pipeline step, its log, the company standards (numbered
sources) and the step's code at the commit that ran, change the code so the step passes while
following the standards. Change as little as possible. Never touch tests, CI, verify or check scripts.
Return only JSON:
{"summary": "<one paragraph: the root cause and what you changed, citing standards as [S1]…>",
 "files": [{"path": "<repo-relative path exactly as shown>", "content": "<the whole new file>"}]}"""


CULPRIT_SYSTEM = """A check in a migration pipeline failed. Checks only observe; the cause is in the code of
one of the steps that ran before it. From the log and the list of those steps, pick the step whose
code most likely caused the failure. Return only JSON: {"step": "<one id from the list, exactly as written>", "why": "<at most 20 words>"}"""


@dataclass
class Outcome:
    summary: str
    report: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    branch: str | None = None
    next_attempt: int | None = None


class LLMDiagnostician:
    """Explain, Report and Auto-fix, with every rule that matters enforced here, not in prompts."""

    def __init__(self, llm: LLM, github, store: Store, sections: list[Section] | None = None,
                 read_files: Callable = integrations.read_files, push_branch: Callable = integrations.push_branch,
                 open_pr: Callable = integrations.open_pr, continue_with: Callable | None = None,
                 max_attempts: int = MAX_AUTOFIX_ATTEMPTS):
        self.llm, self.github, self.store = llm, github, store
        self.sections = sections or []
        self.read_files, self.push_branch, self.open_pr = read_files, push_branch, open_pr
        # continue_with(spec_path, overrides, autofix): starts the next Build + Rehearse. The CLI runs
        # it inline; the server queues it. None: auto-fix pushes the branch and stops there.
        self.continue_with = continue_with
        self.max_attempts = max_attempts
        self.last: Outcome | None = None

    # ---- the Diagnostician protocol ------------------------------------------------------------

    def diagnose(self, spec: Spec, failure: Failure, mode: Mode) -> str:
        step = spec.step(failure.step_id)
        catalog = self._catalog(step)
        facts = self._facts(spec, step, failure, catalog)
        explanation = self.llm.complete(EXPLAIN_SYSTEM, facts, max_tokens=900).strip()
        outcome = Outcome(summary=explanation)
        if mode == Mode.EXPLAIN:
            self.last = outcome
            return explanation

        # A failing check only observes the problem; the code to read (and fix) is the step that caused it.
        culprit, why = self._culprit(spec, step, failure, facts, explanation)
        if culprit is not step:
            facts += (f"\n## Step whose code is suspected\n{culprit.id} ({culprit.type}) in {culprit.run.repo.slug}"
                      f" @ {failure.shas.get(culprit.run.repo.key, '')[:12]}: {why}\n")
            failure = replace(failure, repo=culprit.run.repo.key, sha=failure.shas.get(culprit.run.repo.key, failure.sha))
        code = self._code(culprit, failure)
        report = self.llm.complete(REPORT_SYSTEM, facts + self._code_block(code), max_tokens=3000).strip()
        self.store.save_report(failure.run_id, culprit.id, mode, report)
        outcome.report = report
        summary = explanation + f"\n\nReport ready: GET /api/mac/runs/{failure.run_id}/report.md"
        if mode == Mode.REPORT:
            self.last = outcome
            return summary

        summary += "\n\n" + self._autofix(spec, culprit, failure, facts, code, report, outcome)
        self.last = outcome
        return summary

    def autofix_passed(self, spec: Spec, autofix: dict, run_id: str) -> str | None:
        """Called by the runner when an auto-fix branch rehearsed cleanly: opens the PR."""
        repo_key, branch = autofix.get("repo"), autofix.get("branch")
        if not repo_key or not branch:
            return None
        ref = spec.repos()[repo_key]
        parent_report = self.store.report(autofix.get("parent") or "")
        body = (f"Auto-fix by MaC for `{spec.metadata.name}` (rehearsal `{run_id}` passed with this branch, "
                f"attempt {autofix.get('attempt', '?')}).\n\n"
                + (parent_report["markdown"] if parent_report else "")
                + "\n\n---\nEvery step ran in the rehearsal environment and was undone. Review, merge, then "
                  "Build and Rehearse `main` before Deploy: MaC never deploys a branch.")
        return self.open_pr(self.github, ref.slug, ref.ref, branch,
                            f"MaC auto-fix: {spec.metadata.service} rehearsal failure", body)

    # ---- pieces --------------------------------------------------------------------------------

    def _culprit(self, spec: Spec, step: Step, failure: Failure, facts: str, explanation: str = "") -> tuple[Step, str]:
        """The step whose code to read. The failed step itself, unless it's a check: then the model
        picks from the steps that ran before it, and code accepts only one of those. A pick that names
        the step's file, folder or repo instead of its id still counts; failing that, the step the
        explanation points at most clearly is used."""
        if step.type != StepType.CHECK:
            return step, ""
        candidates = [s for s in spec.steps if s.id in failure.completed and s.type != StepType.CHECK]
        if not candidates:
            return step, ""
        listing = "\n".join(f"- {s.id}: {s.type} in {s.run.repo.slug}, {s.run.path or s.run.entrypoint}" for s in candidates)
        why, raw = "", ""
        try:
            raw = self.llm.complete(CULPRIT_SYSTEM, facts + "\n## Steps that ran before the check\n" + listing, max_tokens=1000)
            pick = parse_json(raw)
            raw, why = str(pick.get("step", "")), str(pick.get("why", "")).strip()
        except (ValueError, AttributeError, TypeError):
            pass
        chosen = next((s for s in candidates if s.id == raw.strip()), None) \
            or _best_match(candidates, raw) or _best_match(candidates, explanation + " " + why)
        if chosen is None:
            return step, ""
        return chosen, why or "the explanation points at its code"

    def _catalog(self, step: Step) -> Catalog:
        if not self.sections:
            return Catalog([])
        query = f"{step.type} {step.stage} {step.id} {step.run.entrypoint or step.run.path or ''}"
        return Catalog(relevant(self.sections, query, k=6, must=step.sources))

    def _facts(self, spec: Spec, step: Step, failure: Failure, catalog: Catalog) -> str:
        where = step.run.path or step.run.entrypoint or ""
        lines = [
            f"Migration: {spec.metadata.name} ({spec.metadata.service}); run {failure.run_id}, mode {failure.mode}.",
            f"Failed step: {step.id} (stage {step.stage}, type {step.type}) in {step.run.repo.slug} @ {failure.sha[:12]}"
            + (f", {where}" if where else "") + ".",
            f"Reason: {failure.reason}",
        ]
        if step.verify:
            lines.append(f"Verified by: {step.verify.entrypoint}")
        if failure.attempt:
            lines.append(f"This is auto-fix attempt {failure.attempt} on branch {failure.branch}; it failed again.")
        logs = failure.logs[-LOG_LINES:]
        text = "\n".join(lines) + "\n\n## Log (last lines)\n```\n" + "\n".join(logs) + "\n```\n"
        if catalog.sections:
            text += "\n## Company standards this step follows\n" + catalog.prompt_block() + "\n"
        return text

    def _code(self, step: Step, failure: Failure) -> dict[str, str]:
        if not failure.sha:
            return {}
        prefix = allowed_prefix(step)
        try:
            files = self.read_files(self.github, step.run.repo.slug, failure.sha, prefix)
        except Exception:  # noqa: BLE001 - no code is still a usable report
            return {}
        wanted = set(_root_files(step))
        kept, total = {}, 0
        for path in sorted(files, key=lambda p: (p not in wanted, p)):
            if not path.endswith(CODE_EXTENSIONS) or any(part in path for part in SKIP_DIRS):
                continue
            if prefix == "" and posixpath.dirname(path) and path not in wanted:
                continue  # a root-level step only shows the repo's top level
            text = files[path][:FILE_CHARS]
            if total + len(text) > TOTAL_CHARS:
                break
            kept[path], total = text, total + len(text)
        return kept

    @staticmethod
    def _code_block(code: dict[str, str]) -> str:
        if not code:
            return "\n## Code\n(the repository couldn't be read)\n"
        parts = ["\n## Code at the commit that ran"]
        for path, text in code.items():
            parts.append(f"\n### {path}\n```\n{text}\n```")
        return "\n".join(parts) + "\n"

    def _autofix(self, spec: Spec, step: Step, failure: Failure, facts: str, code: dict[str, str],
                 report: str, outcome: Outcome) -> str:
        if failure.attempt >= self.max_attempts:
            url = None
            if failure.branch:
                try:
                    url = self.open_pr(self.github, step.run.repo.slug, step.run.repo.ref, failure.branch,
                                       f"MaC auto-fix (not passing yet): {spec.metadata.service}",
                                       f"After {failure.attempt} attempts the rehearsal still fails.\n\n{report}")
                except Exception as e:  # noqa: BLE001
                    return f"Auto-fix stopped after {failure.attempt} attempts; opening its PR failed: {e}"
            return (f"Auto-fix stopped after {failure.attempt} attempts without a passing rehearsal."
                    + (f" Its branch is in a PR for a person to finish: {url}" if url else ""))

        if step.type == StepType.CHECK:
            return "Auto-fix can't act: the failing step is a check, and checks are off limits to it."
        reply = self.llm.complete(FIX_SYSTEM, facts + self._code_block(code) + "\n## Diagnosis\n" + report, max_tokens=6000)
        try:
            proposal = parse_json(reply)
            proposed = {str(f["path"]).replace("\\", "/").removeprefix("./"): str(f["content"])
                        for f in proposal.get("files", [])}
            summary = str(proposal.get("summary", "")).strip()
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return f"Auto-fix produced nothing usable ({e}); the report stands."

        files, rejected = self._filter(spec, step, code, proposed)
        outcome.files, outcome.rejected = files, rejected
        if not files:
            why = "; ".join(rejected) or "the model proposed no file changes"
            return f"Auto-fix made no allowed change: {why}. The report stands."

        branch = failure.branch or autofix_branch(failure.parent or failure.run_id)
        attempt = failure.attempt + 1
        self.push_branch(self.github, step.run.repo.slug, failure.sha, branch, files,
                         f"MaC auto-fix attempt {attempt}: {step.id}\n\n{summary}"[:1000])
        outcome.branch, outcome.next_attempt = branch, attempt
        note = (f"Auto-fix attempt {attempt}: changed {', '.join(files)} on {step.run.repo.slug}@{branch}. {summary}"
                + (f" Not changed (guardrails): {'; '.join(rejected)}." if rejected else ""))
        if self.continue_with is None:
            return note + " Re-run Build and Rehearse with --branch to test it."
        autofix = {"parent": failure.parent or failure.run_id, "branch": branch, "attempt": attempt,
                   "repo": step.run.repo.key}
        self.continue_with(failure.spec_path, {step.run.repo.key: branch}, autofix)
        return note + f" Re-running Build and Rehearse with that branch ({attempt} of {self.max_attempts})."

    def _filter(self, spec: Spec, step: Step, code: dict[str, str], proposed: dict[str, str]) \
            -> tuple[dict[str, str], list[str]]:
        kept, rejected = {}, []
        prefix = allowed_prefix(step)
        roots = set(_root_files(step))
        for path, content in list(proposed.items())[:MAX_FILES + 5]:
            problems = autofix_violations(spec, step.run.repo.key, [path])
            if ".." in path.split("/"):
                problems.append(f"{path} escapes the repository")
            if not (path.startswith(prefix) if prefix else (path in roots or path in code)):
                problems.append(f"{path} is outside the step's own files")
            if len(content.encode("utf-8")) > MAX_BYTES:
                problems.append(f"{path} is over {MAX_BYTES // 1000} KB")
            if content == code.get(path):
                problems.append(f"{path} is unchanged")
            if problems:
                rejected.extend(problems)
            elif len(kept) < MAX_FILES:
                kept[path] = content
            else:
                rejected.append(f"{path}: more than {MAX_FILES} files")
        return kept, rejected


def _best_match(candidates: list[Step], text: str) -> Step | None:
    """The candidate whose id, files, folder or repo the text mentions most; None if none is mentioned."""
    text = (text or "").lower()
    if not text.strip():
        return None

    def score(s: Step) -> int:
        terms = [s.id, s.run.repo.slug.split("/")[-1], s.run.path or "", s.run.entrypoint or "",
                 *[t for t in _root_files(s)]]
        hits = sum(text.count(t.lower()) * (3 if t == s.id else 1) for t in terms if t)
        return hits * 10 + (1 if s.type == StepType.DB_MIGRATION else 0)  # ties: data steps write what checks read

    best = max(candidates, key=score)
    return best if score(best) >= 10 else None


def _root_files(step: Step) -> list[str]:
    names = [step.run.entrypoint] if step.run.entrypoint else []
    rollback = step.effective_rollback
    if rollback and rollback.entrypoint:
        names.append(rollback.entrypoint)
    if step.verify and step.verify.repo is None:
        names.append(step.verify.entrypoint)
    return [n for n in names if n]


def autofix_cycle(runner, spec_path, overrides: dict[str, str], autofix: dict) -> None:
    """One auto-fix round: Build with the branch, then Rehearse it. The rehearsal's own failure
    (if any) calls the diagnostician again with attempt + 1; its success opens the PR."""
    build = runner.build(spec_path, overrides, autofix=autofix)
    if build.status == "succeeded":
        runner.rehearse(spec_path, "autofix", overrides)


def to_json_safe(outcome: Outcome | None) -> dict:
    return {} if outcome is None else json.loads(json.dumps(outcome.__dict__, default=str))
