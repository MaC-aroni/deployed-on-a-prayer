"""Grounding: the knowledge base as citable sections, and code that enforces citations.

Every section of every knowledge page has an id like `data-migration#converting-the-data`.
Agents are shown sources as [S1], [S2], ... and must cite them. `check_citations` is the
rule, enforced by code: every paragraph and list item cites at least one source it was given,
and no citation points at anything else.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from .knowledge import KnowledgePage

_MARKER = re.compile(r"\[S(\d+)\]")
_WORD = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class Section:
    id: str  # "<doc id>#<heading slug>", stable across publishes
    doc_id: str
    doc_title: str
    heading: str
    text: str
    url: str | None  # the Confluence page, if published


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def sections_from_markdown(doc_id: str, title: str, body: str, url: str | None) -> list[Section]:
    sections, heading, lines = [], "Introduction", []

    def flush():
        text = "\n".join(lines).strip()
        if text:
            sections.append(Section(f"{doc_id}#{slug(heading)}", doc_id, title, heading, text, url))

    for line in body.splitlines():
        match = re.match(r"^#{1,4}\s+(.*)$", line)
        if match:
            flush()
            heading, lines = match.group(1).strip(), []
        else:
            lines.append(line)
    flush()
    return sections


def sections_from_pages(pages: list[KnowledgePage], urls: dict[str, str] | None = None) -> list[Section]:
    urls = urls or {}
    return [s for p in pages for s in sections_from_markdown(p.id, p.title, p.body, urls.get(p.id))]


class _StorageText(HTMLParser):
    """Confluence storage XHTML -> Markdown-ish text, keeping headings so sections survive."""

    def __init__(self):
        super().__init__()
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "tr", "br"):
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        self.out.append(data)


def storage_to_markdown(storage_html: str) -> str:
    parser = _StorageText()
    parser.feed(storage_html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.out)).strip()


# ---- Choosing sources for a prompt ---------------------------------------------------------------

def relevant(sections: list[Section], query: str, k: int = 8, must: tuple[str, ...] = ()) -> list[Section]:
    """The k sections sharing the most words with the query, plus any whose id is in `must`."""
    terms = set(_WORD.findall(query.lower()))

    def score(s: Section) -> float:
        words = _WORD.findall((s.doc_title + " " + s.heading + " " + s.text).lower())
        return sum(1 for w in words if w in terms) / (1 + len(words) ** 0.5)

    chosen = [s for s in sections if s.id in must]
    for section in sorted(sections, key=score, reverse=True):
        if len(chosen) >= k + len(must):
            break
        if section not in chosen and score(section) > 0:
            chosen.append(section)
    return chosen


class Catalog:
    """The sources one prompt may cite, numbered S1..Sn."""

    def __init__(self, sections: list[Section]):
        self.sections = list(dict.fromkeys(sections))

    def prompt_block(self) -> str:
        return "\n\n".join(f"[S{i}] {s.doc_title} > {s.heading} (id: {s.id})\n{s.text}"
                           for i, s in enumerate(self.sections, 1))

    def get(self, number: int) -> Section | None:
        return self.sections[number - 1] if 1 <= number <= len(self.sections) else None


# ---- Enforcing citations -----------------------------------------------------------------------

def blocks(markdown: str) -> list[tuple[str, str]]:
    """(kind, text) for every heading, paragraph and list item."""
    out, paragraph = [], []

    def flush():
        if paragraph:
            out.append(("paragraph", " ".join(paragraph)))
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            flush()
        elif re.match(r"^#{1,4}\s", line):
            flush()
            out.append(("heading", line))
        elif re.match(r"^([-*+]|\d+[.)])\s", line):
            flush()
            out.append(("item", line))
        else:
            paragraph.append(line)
    flush()
    return out


def check_citations(markdown: str, catalog: Catalog) -> list[str]:
    """Why this text isn't properly grounded. Empty means every claim cites a real source."""
    problems = []
    for kind, text in blocks(markdown):
        if kind == "heading":
            continue
        cited = [int(n) for n in _MARKER.findall(text)]
        short = text if len(text) <= 70 else text[:67] + "..."
        if not cited:
            problems.append(f"no citation: {short!r}")
        for n in cited:
            if catalog.get(n) is None:
                problems.append(f"[S{n}] isn't one of the sources given (S1-S{len(catalog.sections)}): {short!r}")
    return problems


def drop_uncited(markdown: str, catalog: Catalog) -> tuple[str, int]:
    """Last resort after retries: remove every block that still isn't grounded."""
    kept, dropped = [], 0
    for kind, text in blocks(markdown):
        cited = [int(n) for n in _MARKER.findall(text)]
        if kind != "heading" and (not cited or any(catalog.get(n) is None for n in cited)):
            dropped += 1
            continue
        kept.append(text)
    return "\n\n".join(kept), dropped


def cited_sections(markdown: str, catalog: Catalog) -> list[Section]:
    numbers = sorted({int(n) for n in _MARKER.findall(markdown)})
    return [s for n in numbers if (s := catalog.get(n)) is not None]
