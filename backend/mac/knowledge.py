"""The company knowledge base: Markdown pages with front matter, published to Confluence as one
page tree. The agents read these pages back, and cite them, when they plan a migration."""

import html
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .design import markdown_to_storage
from .integrations import Pages


class KnowledgeError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class KnowledgePage:
    id: str
    title: str
    body: str  # Markdown
    parent: str | None = None
    owner: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""  # file it came from


def load_pages(directory: Path) -> list[KnowledgePage]:
    """Every *.md with front matter (README.md excluded), parents before children."""
    pages, problems = [], []
    for path in sorted(Path(directory).glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            problems.append(f"{path.name}: needs YAML front matter between --- lines")
            continue
        head, body = text[4:].split("\n---\n", 1)
        meta = yaml.safe_load(head) or {}
        missing = [k for k in ("id", "title") if not meta.get(k)]
        if missing:
            problems.append(f"{path.name}: front matter needs {', '.join(missing)}")
            continue
        pages.append(KnowledgePage(id=str(meta["id"]), title=str(meta["title"]), body=body.strip(),
                                   parent=meta.get("parent"), owner=str(meta.get("owner", "")),
                                   labels=tuple(meta.get("labels") or ()), source=path.name))

    ids = [p.id for p in pages]
    problems += [f"duplicate page id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    titles = [p.title for p in pages]  # Confluence titles must be unique within a space
    problems += [f"duplicate title {t!r}" for t in sorted({t for t in titles if titles.count(t) > 1})]
    known = set(ids)
    problems += [f"{p.source}: parent {p.parent!r} doesn't exist" for p in pages if p.parent and p.parent not in known]
    roots = [p.id for p in pages if not p.parent]
    if len(roots) != 1:
        problems.append(f"expected exactly one root page (no parent), found {len(roots)}: {roots}")
    if problems:
        raise KnowledgeError(problems)
    return _parents_first(pages)


def _parents_first(pages: list[KnowledgePage]) -> list[KnowledgePage]:
    ordered, placed, remaining = [], set(), list(pages)
    while remaining:
        ready = [p for p in remaining if not p.parent or p.parent in placed]
        if not ready:
            raise KnowledgeError(["pages' parents form a loop: " + ", ".join(p.id for p in remaining)])
        for page in ready:
            ordered.append(page)
            placed.add(page.id)
            remaining.remove(page)
    return ordered


def render(page: KnowledgePage) -> str:
    footer = " · ".join(filter(None, [f"Owner: {page.owner}" if page.owner else "",
                                      "Labels: " + ", ".join(page.labels) if page.labels else ""]))
    return markdown_to_storage(page.body) + (f"<p><em>{html.escape(footer)}</em></p>" if footer else "")


def publish(pages: list[KnowledgePage], target: Pages, known: dict[str, str] | None = None,
            log=print) -> dict[str, tuple[str, str]]:
    """Creates or updates every page under its parent. known: page id -> Confluence page id from a
    previous publish. Returns page id -> (Confluence page id, url)."""
    known = known or {}
    published: dict[str, tuple[str, str]] = {}
    for page in pages:
        parent_id = published[page.parent][0] if page.parent else None
        page_id, url = target.publish(page.title, render(page), known.get(page.id), parent_id=parent_id)
        published[page.id] = (page_id, url)
        log(f"published {page.id}: {url}")
    return published
