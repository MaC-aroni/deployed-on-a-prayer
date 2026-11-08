"""The code writer: for steps marked `codegen: llm`, an LLM writes the step's code from the
company's standards, and it arrives as a pull request in the step's repo.

The limits are code, not instructions: only steps the engineers marked `codegen: llm`; only
files inside that step's own folder; never tests, CI, CODEOWNERS, secrets or lock files; at
most 10 files of 100 KB. The repo's own rules (CI, an approving review) still apply to the PR.
"""

import posixpath
from dataclasses import dataclass, field

from .diagnostics import autofix_violations
from .llm import LLM, parse_json
from .sources import Section, relevant
from .spec import Spec, Step, StepType

MAX_FILES = 10
MAX_BYTES = 100_000

SYSTEM_PROMPT = """You write the code for one step of a migration pipeline, following the company's
standards exactly. You are given the step, the standards that apply, and the files currently in
the step's folder. Change or add files only inside that folder.

Return only JSON:
{"summary": "<what you changed and why, citing the standards by their id>",
 "files": [{"path": "<repo-relative path>", "content": "<the whole file>"}]}"""


class CodegenRefused(Exception):
    pass


@dataclass
class CodegenResult:
    files: dict[str, str]
    summary: str
    rejected: list[str] = field(default_factory=list)  # paths the limits threw out, and why


def allowed_prefix(step: Step) -> str:
    """The one folder this step's code may live in."""
    if step.type == StepType.IAC:
        return step.run.path.strip("/") + "/"
    folder = posixpath.dirname(step.run.entrypoint)
    return folder + "/" if folder else ""


def _allowed_root_files(step: Step) -> set[str]:
    """Top-level steps may only touch their own entrypoints, not the whole repo root."""
    names = {step.run.entrypoint}
    rollback = step.effective_rollback
    if rollback and rollback.entrypoint:
        names.add(rollback.entrypoint)
    if step.verify and step.verify.repo is None:
        names.add(step.verify.entrypoint)
    return names


def check_files(spec: Spec, step: Step, files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    prefix, kept, rejected = allowed_prefix(step), {}, []
    for raw_path, content in files.items():
        path = posixpath.normpath(raw_path.replace("\\", "/")).lstrip("/")
        if path.startswith("..") or "/../" in f"/{path}/":
            rejected.append(f"{raw_path}: outside the repo")
        elif prefix and not path.startswith(prefix):
            rejected.append(f"{path}: outside the step's folder {prefix}")
        elif not prefix and path not in _allowed_root_files(step):
            rejected.append(f"{path}: not one of this step's files")
        elif path.endswith(".terraform.lock.hcl"):
            rejected.append(f"{path}: provider lock files are updated by engineers")
        elif len(content.encode("utf-8")) > MAX_BYTES:
            rejected.append(f"{path}: larger than {MAX_BYTES} bytes")
        elif problems := autofix_violations(spec, step.run.repo.key, [path]):
            rejected.append(f"{path}: {problems[0]}")
        else:
            kept[path] = content
    if len(kept) > MAX_FILES:
        rejected += [f"{p}: more than {MAX_FILES} files" for p in list(kept)[MAX_FILES:]]
        kept = dict(list(kept.items())[:MAX_FILES])
    return kept, rejected


def generate(spec: Spec, step: Step, sections: list[Section], current: dict[str, str], llm: LLM) -> CodegenResult:
    if step.codegen != "llm":
        raise CodegenRefused(f"{step.id} is codegen: {step.codegen}; the engineers write its code")
    standards = relevant(sections, f"{step.type} {step.stage} {step.id} terraform lambda naming tagging "
                         f"{step.run.repo.name}", k=8, must=step.sources)
    existing = "\n\n".join(f"--- {path}\n{text}" for path, text in current.items()) or "(the folder is empty)"
    user = (f"Step: {step.id} (type {step.type}, stage {step.stage}) in {step.run.repo.slug}, folder "
            f"{allowed_prefix(step) or '(repo root: ' + ', '.join(sorted(_allowed_root_files(step))) + ')'}\n"
            f"Migration: {spec.metadata.name}\n\nStandards:\n\n"
            + "\n\n".join(f"(id: {s.id}) {s.doc_title} > {s.heading}\n{s.text}" for s in standards)
            + f"\n\nCurrent files:\n\n{existing}")
    reply = parse_json(llm.complete(SYSTEM_PROMPT, user, max_tokens=8000))
    proposed = {f["path"]: f["content"] for f in reply.get("files", []) if isinstance(f, dict)
                and isinstance(f.get("path"), str) and isinstance(f.get("content"), str)}
    files, rejected = check_files(spec, step, proposed)
    return CodegenResult(files, str(reply.get("summary", "")), rejected)


def pr_body(step: Step, result: CodegenResult, guide_url: str | None) -> str:
    lines = [f"Written by MaC's code writer for step `{step.id}`, which the engineers marked `codegen: llm`.",
             "", "**Review it like any other change.** This repo's CI and review rules apply.", "",
             "## What changed", result.summary or "(no summary)", "", "## Files"]
    lines += [f"- `{path}`" for path in result.files]
    if result.rejected:
        lines += ["", "## Thrown out by MaC's limits"] + [f"- {r}" for r in result.rejected]
    if guide_url:
        lines += ["", f"Guide: {guide_url}"]
    return "\n".join(lines)
