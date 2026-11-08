"""The page that describes a migration: what it moves, how, and what it needs.

A migration.yaml is exact but terse. This writes the Confluence page a person reads first: an
LLM turns the facts (the spec, the repositories' READMEs, the knowledge-base sections the spec
cites) into prose, and code appends the authoritative appendix generated from the spec. Without
an LLM the page is the facts alone, so the button always produces a page.
"""

import html
from datetime import date

import yaml

from .sources import Section
from .spec import Spec
from .validate import execution_order

TITLE = "Migration: {service} ({name})"
PAGE_ID = "migration-{name}"

SECTIONS = ["Summary", "What moves and why", "How it runs", "Approvals", "Risks and rollback"]

SYSTEM_PROMPT = (
    "You write the Confluence page that introduces a cloud migration to the team that owns the "
    "service and to the people who approve it: engineers, a DBA, Tech Risk reviewers. Write plain, "
    "concrete English. Use only the facts you are given; where something isn't stated, say so "
    "instead of inventing it. Output Markdown only, with exactly these second-level headings in "
    "this order: " + ", ".join(SECTIONS) + ". Summary is two or three sentences. Use short "
    "paragraphs and bullet lists; no tables, code blocks, HTML or links. Under 500 words."
)


def page_id(spec: Spec) -> str:
    return PAGE_ID.format(name=spec.metadata.name)


def page_title(spec: Spec) -> str:
    return TITLE.format(service=spec.metadata.service, name=spec.metadata.name)


def facts(spec: Spec, repos: dict[str, dict], sections: list[Section], source_url: str | None) -> str:
    """Everything the model may use, built by code: the spec, each repository's own description,
    and the knowledge-base sections the spec cites."""
    target = spec.target
    lines = [
        f"Migration: {spec.metadata.name}" + (f" (defined in {source_url})" if source_url else ""),
        f"Service: {spec.metadata.service}, owned by {spec.metadata.owner_team}",
        f"Target: {target.provider.upper()} account {target.account}, region {target.region}",
        f"Stages, in order: {', '.join(spec.stages)}",
        "Process: Build checks the plan and locks the code; Rehearse runs the whole pipeline in a "
        "rehearsal environment and undoes it; Deploy runs the same locked code in production. A failing "
        "step undoes every completed step in reverse order.",
        "",
        "Steps, in order:",
    ]
    for step in execution_order(spec):
        rollback = step.effective_rollback
        undo = "nothing to undo (read-only check)" if rollback is None else (
            f"undone by {rollback.entrypoint}" if rollback.entrypoint else "undone by terraform destroy")
        what = step.run.entrypoint or f"Terraform in {step.run.path}"
        extra = []
        if step.when == "manual":
            extra.append("a person starts it (breakpoint)")
        if step.requires_approval:
            extra.append("needs approval " + ", ".join(step.requires_approval))
        if step.verify:
            extra.append(f"verified by {step.verify.entrypoint}")
        if step.outputs:
            extra.append("produces " + ", ".join(f"{o.name} ({o.description})" for o in step.outputs))
        lines.append(f"- {step.id} (stage {step.stage}, {step.type}): runs {what} from {step.run.repo.slug}; {undo}"
                     + (f"; {'; '.join(extra)}" if extra else ""))
    lines += ["", "Approvals:"]
    for approval in spec.approvals:
        chain = f", raised only after {', '.join(approval.after)}" if approval.after else ""
        lines.append(f"- {approval.id} ({approval.type}) from {approval.approver}{chain}: {approval.summary}")
        if approval.justification:
            lines.append(f"  Justification: {approval.justification.strip()}")
    if repos:
        lines += ["", "Repositories the steps run code from:"]
        for slug, repo in repos.items():
            readme = " ".join((repo.get("readme") or "").split())[:1500]
            lines.append(f"- {slug}: {repo.get('description') or '(no description)'}"
                         + (f". README: {readme}" if readme else ""))
    if sections:
        lines += ["", "Knowledge-base sections the plan cites:"]
        for section in sections:
            lines.append(f"- {section.doc_title} › {section.heading}: {' '.join(section.text.split())[:600]}")
    return "\n".join(lines)


def fallback_markdown(spec: Spec) -> str:
    """The page without a model: the facts, readable."""
    steps = execution_order(spec)
    manual = [s.id for s in steps if s.when == "manual"]
    repos = sorted({s.run.repo.slug for s in steps})
    out = [
        "## Summary",
        f"{spec.metadata.service} moves to {spec.target.provider.upper()} ({spec.target.region}) in "
        f"{len(steps)} steps across {len(spec.stages)} stages, with {len(spec.approvals)} approval(s). "
        "Every step is rehearsed and undone before production runs it.",
        "", "## What moves and why",
        f"- Owner: {spec.metadata.owner_team}",
        f"- Target account: {spec.target.account}",
        "- Code: " + ", ".join(repos),
        "", "## How it runs",
    ]
    for step in steps:
        rollback = step.effective_rollback
        undo = "read-only" if rollback is None else (rollback.entrypoint or "terraform destroy")
        out.append(f"- **{step.id}** ({step.stage}): {step.run.entrypoint or step.run.path} from {step.run.repo.slug}; undo: {undo}"
                   + (" · breakpoint" if step.when == "manual" else ""))
    out += ["", "## Approvals"]
    out += [f"- **{a.id}** from {a.approver}: {a.summary}" for a in spec.approvals] or ["- none"]
    out += ["", "## Risks and rollback",
            "A failing step undoes every completed step in reverse order. "
            + (f"Breakpoints before: {', '.join(manual)}." if manual else "No breakpoints.")]
    return "\n".join(out)


def appendix(spec: Spec, source_url: str | None, run_id: str) -> str:
    """The authoritative part, generated from the spec: exactly what will run."""
    out = ["", "## Appendix: exactly what will run", "",
           "| # | Step | Stage | Type | Code | Undo | Approvals |", "|---|---|---|---|---|---|---|"]
    for i, step in enumerate(execution_order(spec), 1):
        rollback = step.effective_rollback
        undo = "—" if rollback is None else (rollback.entrypoint or "terraform destroy")
        code = f"{step.run.repo.slug} {step.run.entrypoint or step.run.path}"
        out.append(f"| {i} | {step.id}{' (manual)' if step.when == 'manual' else ''} | {step.stage} | {step.type} | "
                   f"{code} | {undo} | {', '.join(step.requires_approval) or '—'} |")
    if spec.approvals:
        out += ["", "### Approvals", ""]
        out += [f"- **{a.id}** from {a.approver}" + (f", after {', '.join(a.after)}" if a.after else "") + f": {a.summary}"
                for a in spec.approvals]
    out += ["", f"_Written by MaC on {date.today().isoformat()} for spec version {spec.digest()[:12]} (run {run_id})."
                + (f" The pipeline is defined in {source_url}." if source_url else "")
                + " The appendix is generated from migration.yaml and is authoritative._"]
    return "\n".join(out)


def compose_page(spec: Spec, markdown: str, source_url: str | None, run_id: str, parent: str | None) -> str:
    """The page file: front matter (so it joins the knowledge base) and the body."""
    front = {"id": page_id(spec), "title": page_title(spec), "parent": parent, "owner": spec.metadata.owner_team,
             "labels": ["migration", "generated"]}
    front = {k: v for k, v in front.items() if v is not None}
    body = markdown.strip() + "\n" + appendix(spec, source_url, run_id) + "\n"
    return "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n" + body


def summary_of(markdown: str) -> str:
    """The first paragraph under Summary: what the card shows."""
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().lower().lstrip("# ").startswith("summary"))
    except StopIteration:
        start = -1
    text = []
    for line in lines[start + 1:]:
        if line.startswith("#") and text:
            break
        if line.startswith("#"):
            continue
        if not line.strip() and text:
            break
        if line.strip():
            text.append(line.strip().lstrip("-* "))
    return html.unescape(" ".join(text))[:400]
