import re

import pytest

from mac.cli import cmd_publish_knowledge
from mac.integrations import ConfluencePages
from mac.knowledge import KnowledgeError, KnowledgePage, load_pages, publish, render
from mac.spec import parse_spec

from .conftest import DEMO_SPEC, REPO_ROOT

KNOWLEDGE = REPO_ROOT / "demo-data" / "confluence"
SPEC = parse_spec(DEMO_SPEC.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pages():
    return load_pages(KNOWLEDGE)


def text_of(pages, page_id):
    return next(p for p in pages if p.id == page_id).body


def everything(pages):
    return "\n".join(p.body for p in pages)


# ---- The demo knowledge base is well formed -----------------------------------------------------

def test_demo_pages_load_as_one_tree(pages):
    assert len(pages) == 16 and pages[0].id == "handbook" and pages[0].parent is None
    assert all(p.parent == "handbook" for p in pages[1:])


def test_demo_pages_use_only_what_the_converter_supports(pages):
    for page in pages:
        assert not re.search(r"^\s*\|", page.body, re.M), f"{page.source}: tables aren't supported"
        assert "<" not in page.body or "&lt;" in render(page), page.source


# ---- The knowledge base agrees with the demo pipeline --------------------------------------------
# If someone changes the pipeline or the docs, these keep them from drifting apart, since an LLM
# that reads the docs is meant to arrive at this pipeline.

def test_every_repo_the_pipeline_uses_is_documented(pages):
    for ref in SPEC.repos().values():
        assert ref.slug in everything(pages), ref.slug


def test_every_approver_and_approval_type_is_in_the_directory(pages):
    directory = text_of(pages, "directory-approvers")
    for approval in SPEC.approvals:
        assert f"`{approval.approver}`" in directory, approval.approver
        assert f"`{approval.type}`" in directory, approval.type


def test_the_access_chain_order_is_documented(pages):
    access = text_of(pages, "access-mcp")
    assert access.index("requester's manager") < access.index("team that owns the MCP tool")
    assert ["APPR-MGR-001"] == list(SPEC.approval("APPR-MCP-001").after)


def test_stages_are_documented_in_pipeline_order(pages):
    doc = text_of(pages, "eng-change-management")
    positions = [doc.index(f"**{stage}:**") for stage in SPEC.stages]
    assert positions == sorted(positions)


def test_every_step_path_and_entrypoint_is_documented(pages):
    text = everything(pages)
    for step in SPEC.steps:
        where = step.run.path or step.run.entrypoint
        assert where.split("/")[-1] in text, f"{step.id}: {where}"


def test_the_rules_the_planted_bug_breaks_are_written_down(pages):
    data = text_of(pages, "data-migration")
    assert "DD-MON-YY" in data and "ISO 8601" in data and "01-JAN-24" in data
    assert "when: manual" in data and SPEC.step("db_migrate").when == "manual"


def test_tech_risk_requires_the_design_page(pages):
    assert "design document" in text_of(pages, "techrisk-cloud-migration")
    assert SPEC.approval("APPR-TR-001").design_doc is True


# ---- Loading rules -------------------------------------------------------------------------------

def write(tmp_path, name, front, body="Body."):
    (tmp_path / name).write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")


def test_problems_are_all_reported(tmp_path):
    write(tmp_path, "a.md", "id: root\ntitle: Root")
    write(tmp_path, "b.md", "id: root\ntitle: Root")
    write(tmp_path, "c.md", "id: c\ntitle: C\nparent: nowhere")
    (tmp_path / "d.md").write_text("no front matter", encoding="utf-8")
    write(tmp_path, "e.md", "title: no id")
    with pytest.raises(KnowledgeError) as e:
        load_pages(tmp_path)
    problems = "\n".join(e.value.problems)
    for expected in ("duplicate page id 'root'", "duplicate title 'Root'", "parent 'nowhere' doesn't exist",
                     "d.md: needs YAML front matter", "e.md: front matter needs id"):
        assert expected in problems


def test_exactly_one_root(tmp_path):
    write(tmp_path, "a.md", "id: a\ntitle: A")
    write(tmp_path, "b.md", "id: b\ntitle: B")
    with pytest.raises(KnowledgeError, match="exactly one root"):
        load_pages(tmp_path)


def test_children_come_after_parents_whatever_the_file_order(tmp_path):
    write(tmp_path, "1-grandchild.md", "id: g\ntitle: G\nparent: c")
    write(tmp_path, "2-child.md", "id: c\ntitle: C\nparent: r")
    write(tmp_path, "3-root.md", "id: r\ntitle: R")
    assert [p.id for p in load_pages(tmp_path)] == ["r", "c", "g"]


def test_render_escapes_and_adds_owner_footer():
    page = KnowledgePage(id="x", title="X", body="## Rules\n- use <script>", owner="team & co", labels=("a", "b"))
    html = render(page)
    assert "&lt;script&gt;" in html and "<script" not in html
    assert html.endswith("<p><em>Owner: team &amp; co · Labels: a, b</em></p>")


# ---- Publishing ---------------------------------------------------------------------------------

def test_publish_puts_children_under_their_parents(pages, env):
    published = publish(pages, env.pages, log=lambda _: None)
    calls = env.pages.published
    assert calls[0][0] == "Prayerwell Health Engineering Handbook" and calls[0][3] is None
    root_id = published["handbook"][0]
    assert all(parent == root_id for _, _, _, parent in calls[1:])
    assert len(published) == 16


def test_cli_records_pages_and_updates_them_in_place(env, capsys):
    assert cmd_publish_knowledge(env.runner, KNOWLEDGE) == 0
    recorded = env.store.knowledge_pages()
    assert set(recorded) == {p.id for p in load_pages(KNOWLEDGE)}
    env.pages.published.clear()
    assert cmd_publish_knowledge(env.runner, KNOWLEDGE) == 0
    assert all(page_id is not None for _, _, page_id, _ in env.pages.published)  # updates, not new pages
    assert "published 16 pages" in capsys.readouterr().out


def test_cli_without_confluence(env, capsys):
    env.runner.pages = None
    assert cmd_publish_knowledge(env.runner, KNOWLEDGE) == 2
    assert "isn't configured" in capsys.readouterr().err


def test_confluence_creates_child_pages_under_the_parent(http):
    http.route("GET", "/wiki/api/v2/spaces?keys=MAC", {"results": [{"id": "98"}]})
    http.route("GET", "/wiki/api/v2/pages?space-id=98&title=Child", {"results": []})
    http.route("POST", "/wiki/api/v2/pages", {"id": "7", "_links": {"webui": "/spaces/MAC/pages/7"}})
    ConfluencePages(http.url, "e", "t", "MAC").publish("Child", "<p/>", None, parent_id="5")
    assert http.requests[-1]["body"]["parentId"] == "5"
