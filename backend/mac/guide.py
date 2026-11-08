"""The migration guide: a Confluence page tree an LLM writes for the engineers, grounded in the
knowledge base. One page per stage says what each step does, how to write its code to the
company's standards, how to run, verify and undo it.

Citations are enforced by code, not requested: every paragraph and list item must cite a
source the writer was given ([S1]...). A page that fails goes back to the LLM with the problems;
after the retries, ungrounded text is removed and the page says how much. Citations render as
links to the Confluence pages they came from.
"""

import html
import re
from dataclasses import dataclass

from .design import facts, markdown_to_storage
from .integrations import Pages
from .llm import LLM
from .sources import Catalog, Section, check_citations, cited_sections, drop_uncited, relevant
from .spec import Spec
from .validate import execution_order

RETRIES = 2

SYSTEM_PROMPT = """You write one page of a migration guide for the engineers doing the migration.
Be concrete and practical: what each step does, which repository and files hold its code, how
that code must be written to the company's standards, how to run it, how to check it worked
and how to undo it. Plain English, short paragraphs and bullet lists, ## headings.

Grounding is mandatory: end EVERY paragraph and EVERY bullet with the citation(s) of the
sources it comes from, like [S2] or [S1][S4]. Use only the sources given. If the sources
don't say something, don't write it. Output Markdown only."""


@dataclass(frozen=True)
class GuidePage:
    key: str  # stable: "root", "approvals", "stage-<name>", "setup"
    title: str
    brief: str  # what this page must cover


def plan_pages(spec: Spec) -> list[GuidePage]:
    service = spec.metadata.service
    pages = [GuidePage("root", f"Migration guide: {service}",
                       "An overview: what is migrated, from where to where, the stages in order, the "
                       "approvals, and how Build, Rehearse and Deploy are used."),
             GuidePage("approvals", f"{service} guide: Approvals",
                       "Every approval: who gives it, why it's required, in what order, and what the "
                       "request contains.")]
    for stage in spec.stages:
        steps = ", ".join(s.id for s in spec.steps if s.stage == stage)
        pages.append(GuidePage(f"stage-{stage}", f"{service} guide: Stage {spec.stages.index(stage) + 1}, {stage}",
                               f"The {stage} stage, steps {steps}: for each step, what it does, where its "
                               "code lives, how to write that code to the standards, how to run, verify and "
                               "undo it, and who writes it (engineer or LLM)."))
    pages.append(GuidePage("setup", f"{service} guide: Setting it up from scratch",
                           "Everything needed before the first Build: repositories, accounts, approvals "
                           "process, and the order to do it in."))
    return pages


def spec_source(spec: Spec, shas: dict[str, str], url: str | None, stage: str | None = None) -> Section:
    """migration.yaml itself, as a citable source, so the exact steps can be cited too."""
    text = facts(spec, shas)
    if stage:
        keep = {s.id for s in spec.steps if s.stage == stage}
        text = "\n".join(line for line in text.splitlines()
                         if not line.startswith("- ") or any(line.startswith(f"- {k} ") for k in keep)
                         or not any(line.startswith(f"- {s.id} ") for s in spec.steps))
    return Section("migration-yaml", "migration-yaml", f"migration.yaml ({spec.metadata.name})",
                   "Pipeline facts", text, url)


def write_page(page: GuidePage, spec: Spec, sections: list[Section], shas: dict[str, str], llm: LLM,
               spec_url: str | None) -> tuple[str, Catalog, int, int]:
    """(markdown, catalog, attempts, blocks dropped)."""
    stage = page.key.removeprefix("stage-") if page.key.startswith("stage-") else None
    steps = [s for s in execution_order(spec) if s.stage == stage] if stage else list(spec.steps)
    must = tuple(sid for s in steps for sid in s.sources) + (
        tuple(sid for a in spec.approvals for sid in a.sources) if page.key in ("approvals", "root") else ())
    query = page.brief + " " + " ".join(f"{s.id} {s.type} {s.run.repo.name} {s.run.path or s.run.entrypoint}" for s in steps)
    catalog = Catalog([spec_source(spec, shas, spec_url, stage)] + relevant(sections, query, k=8, must=must))
    user = f"Page: {page.title}\nCover: {page.brief}\n\nSources:\n\n{catalog.prompt_block()}"
    text, problems = "", []
    for attempt in range(1, RETRIES + 2):
        prompt = user if attempt == 1 else (
            f"{user}\n\nYour previous draft:\n{text}\n\nIt isn't properly grounded. Fix every problem "
            "and return the whole page:\n- " + "\n- ".join(problems[:20]))
        text = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=4096)
        problems = check_citations(text, catalog)
        if not problems:
            return text, catalog, attempt, 0
    text, dropped = drop_uncited(text, catalog)
    return text, catalog, RETRIES + 1, dropped


def render(markdown: str, catalog: Catalog, dropped: int) -> str:
    """Citations become numbered links; a Sources list closes the page."""
    numbering = {id(s): i for i, s in enumerate(cited_sections(markdown, catalog), 1)}

    def link(match):
        section = catalog.get(int(match.group(1)))
        n = numbering.get(id(section), "?")
        return f"MACCITE{n}MACEND" if section else ""

    body = markdown_to_storage(re.sub(r"\[S(\d+)\]", link, markdown))

    def anchor(match):
        n = int(match.group(1))
        section = cited_sections(markdown, catalog)[n - 1]
        target = html.escape(section.url or "#", quote=True)
        return f'<sup><a href="{target}">[{n}]</a></sup>'

    body = re.sub(r"MACCITE(\d+)MACEND", anchor, body)
    sources = "".join(
        f'<li>[{i}] <a href="{html.escape(s.url, quote=True)}">{html.escape(s.doc_title)}</a>, {html.escape(s.heading)}</li>'
        if s.url else f"<li>[{i}] {html.escape(s.doc_title)}, {html.escape(s.heading)}</li>"
        for i, s in enumerate(cited_sections(markdown, catalog), 1))
    note = (f"<p><em>{dropped} statement(s) were removed because they couldn't be tied to a source.</em></p>"
            if dropped else "")
    return body + note + (f"<h2>Sources</h2><ol>{sources}</ol>" if sources else "")


def write_guide(spec: Spec, sections: list[Section], shas: dict[str, str], llm: LLM, pages: Pages,
                known: dict[str, str] | None = None, spec_url: str | None = None,
                design_url: str | None = None, log=print) -> dict[str, tuple[str, str]]:
    """Writes and publishes every page. known: page key -> Confluence page id from last time.
    Returns page key -> (page id, url)."""
    known = known or {}
    published: dict[str, tuple[str, str]] = {}
    for page in plan_pages(spec):
        markdown, catalog, attempts, dropped = write_page(page, spec, sections, shas, llm, spec_url)
        storage = render(markdown, catalog, dropped)
        if page.key == "root" and design_url:
            storage = (f'<p><strong>Architecture and risk review (Tech Risk):</strong> '
                       f'<a href="{html.escape(design_url, quote=True)}">design page</a></p>') + storage
        parent = published["root"][0] if page.key != "root" else None
        published[page.key] = pages.publish(page.title, storage, known.get(page.key), parent_id=parent)
        log(f"{page.title}: {attempts} attempt(s)" + (f", {dropped} ungrounded statement(s) removed" if dropped else ""))
    return published
