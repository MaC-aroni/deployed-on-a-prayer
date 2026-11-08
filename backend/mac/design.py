"""The design page: the one place MaC calls an LLM, and only to write prose.

Build sends the facts of the migration (from migration.yaml and the commits Build locked) to
an LLM API, gets back a design document in Markdown, and publishes it to Confluence. The
Tech Risk ticket links to it. What the model writes is only ever text on that page: it never
changes the spec, picks steps or runs anything. Code converts the Markdown to Confluence's
format with everything escaped, and appends a factual appendix generated from the spec, so
the steps and approvals on the page are always exactly what will run.
"""

import html
import re
from typing import Protocol

from .llm import NIMChat
from .spec import Spec
from .validate import execution_order

SECTIONS = ["Overview", "Current architecture", "Target architecture", "Migration plan",
            "Risks and mitigations", "Rollback plan", "Approvals"]

SYSTEM_PROMPT = (
    "You are a principal cloud architect writing a migration design document for a Tech Risk "
    "review board at a US healthcare payer. Write in clear, plain English for reviewers who "
    "are not engineers. Use only the facts you are given; if something isn't stated, say it "
    "isn't specified rather than inventing it. Output Markdown only, using exactly these "
    "second-level headings in this order: " + ", ".join(SECTIONS) + ". Use short paragraphs "
    "and bullet lists. Do not include code blocks, tables, HTML, or links."
)


class DesignWriter(Protocol):
    def write(self, facts: str) -> str:
        """Returns the design document as Markdown."""


def page_title(spec: Spec) -> str:
    return f"MaC design: {spec.metadata.service} ({spec.metadata.name})"


def facts(spec: Spec, shas: dict[str, str]) -> str:
    """The only input the model gets: plain facts from the spec, built by code."""
    target = spec.target
    lines = [
        f"Migration: {spec.metadata.name}",
        f"Service: {spec.metadata.service} (owned by {spec.metadata.owner_team})",
        f"Target: {target.provider.upper()} account {target.account}, region {target.region}",
        "Process: every change is first rehearsed end to end in a separate rehearsal environment and "
        "fully undone; production runs only the exact code versions that passed the rehearsal. If any "
        "step fails, every completed step is automatically undone in reverse order.",
        "",
        "Steps, in order:",
    ]
    for step in execution_order(spec):
        rollback = step.effective_rollback
        undo = "nothing to undo (read-only check)" if rollback is None else (
            f"undo with {rollback.entrypoint}" if rollback.entrypoint else "undo with terraform destroy")
        what = step.run.entrypoint or f"Terraform in {step.run.path}"
        extra = []
        if step.when == "manual":
            extra.append("a person must start it")
        if step.requires_approval:
            extra.append("needs approval " + ", ".join(step.requires_approval))
        if step.verify:
            extra.append(f"verified by {step.verify.entrypoint}")
        lines.append(f"- {step.id} (stage {step.stage}, {step.type}): runs {what} from {step.run.repo.slug}"
                     f" at commit {shas.get(step.run.repo.key, 'unknown')[:7]}; {undo}"
                     + (f"; {'; '.join(extra)}" if extra else ""))
    lines += ["", "Approvals:"]
    for approval in spec.approvals:
        chain = f", only after {', '.join(approval.after)}" if approval.after else ""
        lines.append(f"- {approval.id} ({approval.type}) from {approval.approver}{chain}: {approval.summary}")
        if approval.justification:
            lines.append(f"  Justification: {approval.justification.strip()}")
    return "\n".join(lines)


class NIMDesignWriter:
    """Writes the design page through the shared LLM client (mac/llm.py)."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://integrate.api.nvidia.com/v1",
                 timeout: int = 120):
        self.chat = NIMChat(api_key, model, base_url, timeout)

    def write(self, facts_text: str) -> str:
        return self.chat.complete(SYSTEM_PROMPT, "Write the design document for this migration.\n\n" + facts_text)


def render_page(spec: Spec, shas: dict[str, str], markdown: str, run_id: str) -> str:
    """Confluence storage format: the model's prose (escaped), then the factual appendix."""
    appendix = ["<h2>Appendix: exactly what will run (generated from migration.yaml)</h2>",
                "<table><tbody><tr><th>Order</th><th>Step</th><th>Stage</th><th>Type</th><th>Code</th>"
                "<th>Undo</th><th>Approvals</th></tr>"]
    for i, step in enumerate(execution_order(spec), 1):
        rollback = step.effective_rollback
        undo = "—" if rollback is None else (rollback.entrypoint or "terraform destroy")
        code = f"{step.run.repo.slug}@{shas.get(step.run.repo.key, '?')[:7]} {step.run.entrypoint or step.run.path}"
        cells = [str(i), step.id + (" (manual)" if step.when == "manual" else ""), step.stage, step.type,
                 code, undo, ", ".join(step.requires_approval) or "—"]
        appendix.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    appendix.append("</tbody></table>")
    approvals = "".join(
        f"<li><strong>{html.escape(a.id)}</strong> from {html.escape(a.approver)}"
        + (f", after {html.escape(', '.join(a.after))}" if a.after else "") + f": {html.escape(a.summary)}</li>"
        for a in spec.approvals)
    appendix.append(f"<h3>Approvals</h3><ul>{approvals}</ul>" if approvals else "")
    appendix.append(f"<p><em>Written by an LLM from the facts above for spec version "
                    f"{html.escape(spec.digest()[:12])} (MaC run {html.escape(run_id)}). "
                    f"The appendix is generated by code and is authoritative.</em></p>")
    return markdown_to_storage(markdown) + "".join(appendix)


def markdown_to_storage(markdown: str) -> str:
    """A small, strict Markdown subset -> Confluence storage XHTML. Everything is escaped,
    so nothing the model writes can become markup, macros or links."""
    out: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None

    def flush_paragraph():
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if not line.strip() or line.strip().startswith("```"):
            flush_paragraph()
            close_list()
        elif heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2).strip('# '))}</h{level}>")
        elif bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline((bullet or numbered).group(1))}</li>")
        else:
            close_list()
            paragraph.append(line.strip())
    flush_paragraph()
    close_list()
    return "".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
