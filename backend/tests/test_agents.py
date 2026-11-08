"""The agents with a scripted LLM, including one that misbehaves, to prove the code-enforced
rules (citations, documented repos and approvers, the code writer's limits) hold."""

import json
import re

import pytest

from mac.codegen import CodegenRefused, check_files, generate
from mac.graph import Graph, Node, extract
from mac.guide import plan_pages, render, write_guide, write_page
from mac.integrations import GitHubAPI, open_pull_request
from mac.knowledge import load_pages
from mac.planner import check_plan, plan, pr_body
from mac.sources import (Catalog, check_citations, drop_uncited, sections_from_markdown, sections_from_pages,
                         storage_to_markdown)
from mac.spec import parse_spec

from .conftest import DEMO_SPEC, REPO_ROOT

SECTIONS = sections_from_pages(load_pages(REPO_ROOT / "demo-data" / "confluence"))
DEMO_TEXT = DEMO_SPEC.read_text(encoding="utf-8")
SPEC = parse_spec(DEMO_TEXT)


class ScriptedLLM:
    """Answers in order; records every prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system, user, *, max_tokens=4096):
        self.prompts.append((system, user))
        reply = self.replies.pop(0) if self.replies else self.default(user)
        return reply(user) if callable(reply) else reply

    def default(self, user):
        raise AssertionError("no scripted reply left")


def demo_graph() -> Graph:
    graph = Graph()
    for repo in SPEC.repos().values():
        graph.add_node(Node("repo", repo.slug, "", ["service-claims-adjudication#repositories"]))
    for approver in ("tech-risk", "manager", "claims-mcp-team"):
        graph.add_node(Node("approver", f"`{approver}`", "", ["directory-approvers#approvers"]))
    graph.add_node(Node("service", "ClaimsAdjudicationService", "", ["service-claims-adjudication#what-it-does"]))
    return graph


# ---- Sources and citations -------------------------------------------------------------------------

def test_knowledge_sections_have_stable_ids():
    ids = {s.id for s in SECTIONS}
    assert {"data-migration#converting-the-data", "access-mcp#approvals-in-order",
            "platform-terraform#layout"} <= ids


def test_every_citation_in_the_demo_spec_is_a_real_section():
    known = {s.id for s in SECTIONS}
    cited = {sid for item in [*SPEC.steps, *SPEC.approvals] for sid in item.sources}
    assert cited and cited <= known, cited - known
    assert all(item.sources for item in [*SPEC.steps, *SPEC.approvals])


def test_check_citations():
    catalog = Catalog(SECTIONS[:3])
    good = "## Title\nThe table is DynamoDB. [S1]\n\n- Names include the env. [S2][S3]"
    assert check_citations(good, catalog) == []
    bad = "Unsupported claim.\n\n- Made-up source. [S9]"
    problems = check_citations(bad, catalog)
    assert any("no citation" in p for p in problems) and any("[S9] isn't one of the sources" in p for p in problems)


def test_drop_uncited_keeps_only_grounded_text():
    text, dropped = drop_uncited("## H\nGrounded. [S1]\n\nNot grounded.\n\n- Fake. [S7]", Catalog(SECTIONS[:2]))
    assert dropped == 2 and "Grounded. [S1]" in text and "Fake" not in text and "## H" in text


def test_confluence_storage_back_to_sections():
    md = storage_to_markdown("<h2>Rules</h2><p>Use <strong>Lambda</strong>.</p><ul><li>one</li></ul><h2>More</h2><p>x</p>")
    sections = sections_from_markdown("doc", "Doc", md, "https://c/1")
    assert [s.id for s in sections] == ["doc#rules", "doc#more"] and "- one" in sections[0].text


# ---- Knowledge graph -----------------------------------------------------------------------------

def test_extract_keeps_only_cited_facts_and_links_across_pages():
    pages = [s for s in SECTIONS if s.doc_id in ("service-claims-mcp", "directory-approvers")]
    first = json.dumps({"nodes": [
        {"type": "mcp_tool", "name": "Claims MCP tool", "description": "eligibility", "sources": ["S1"]},
        {"type": "repo", "name": "MaC-aroni/claims-mcp-server", "sources": ["S99"]},  # fake citation
        {"type": "spaceship", "name": "x", "sources": ["S1"]}],  # unknown type
        "edges": [{"from": "claims-mcp-team", "to": "Claims MCP tool", "type": "owns", "sources": ["S1"]}]})
    second = "```json\n" + json.dumps({"nodes": [
        {"type": "team", "name": "claims-mcp-team", "description": "owns the MCP tool", "sources": ["S1"]},
        {"type": "mcp_tool", "name": "claims mcp tool", "description": "a longer description of it", "sources": ["S2"]}],
        "edges": []}) + "\n```"
    graph, dropped = extract(pages, ScriptedLLM(first, second), log=lambda _: None)
    assert set(graph.nodes) == {"mcp_tool:claims mcp tool", "team:claims-mcp-team"}  # merged by name
    tool = graph.nodes["mcp_tool:claims mcp tool"]
    assert len(tool.sources) == 2 and tool.description == "a longer description of it"
    assert [(e.source, e.type) for e in graph.edges] == [("team:claims-mcp-team", "owns")]  # cross-page edge
    assert len(dropped) == 2


def test_unreadable_reply_is_dropped_not_fatal():
    graph, dropped = extract(SECTIONS[:2], ScriptedLLM("not json at all"), log=lambda _: None)
    assert not graph.nodes and "unreadable" in dropped[0]


def test_graph_round_trips_and_answers_neighbors():
    graph = demo_graph()
    graph.edges.append(__import__("mac.graph", fromlist=["Edge"]).Edge(
        "service:claimsadjudicationservice", "repo:mac-aroni/claims-service-iac", "has_repo", "", ["s#x"]))
    again = Graph.from_json(graph.to_json())
    assert set(again.nodes) == set(graph.nodes)
    near = again.neighbors("service:claimsadjudicationservice")
    assert set(near.nodes) == {"service:claimsadjudicationservice", "repo:mac-aroni/claims-service-iac"}
    assert "--has_repo-->" in near.facts()


# ---- Planner ------------------------------------------------------------------------------------

def test_the_demo_spec_passes_every_planner_check():
    spec, problems = check_plan(DEMO_TEXT, SECTIONS, demo_graph())
    assert spec is not None and problems == []


def test_planner_feeds_problems_back_until_the_plan_is_valid():
    bad = re.sub(r"\n\s+sources: \[.*?\]", "", DEMO_TEXT).replace("MaC-aroni/claims-db-migrate", "someone/random-repo")
    llm = ScriptedLLM(f"```yaml\n{bad}\n```", f"Here you go:\n```yaml\n{DEMO_TEXT}\n```")
    result = plan("Migrate ClaimsAdjudicationService to AWS", demo_graph(), SECTIONS, llm, log=lambda _: None)
    assert result.ok and result.iterations == 2
    first = result.history[0]
    assert any("has no sources" in p for p in first) and any("someone/random-repo" in p for p in first)
    retry_prompt = llm.prompts[1][1]
    assert "someone/random-repo isn't in the documentation" in retry_prompt and "Your previous migration.yaml" in retry_prompt


def test_planner_gives_up_after_the_limit():
    llm = ScriptedLLM(*["```yaml\nnot: a spec\n```"] * 4)
    result = plan("Migrate ClaimsAdjudicationService to AWS", demo_graph(), SECTIONS, llm, log=lambda _: None)
    assert not result.ok and result.iterations == 4 and result.problems


def test_planner_rejects_undocumented_approvers_and_fake_citations():
    text = DEMO_TEXT.replace("approver: claims-mcp-team", "approver: the-ceo").replace(
        "qa-smoke-testing#after-a-migration-smoke-test", "qa-smoke-testing#made-up")
    _, problems = check_plan(text, SECTIONS, demo_graph())
    assert any("'the-ceo' isn't in the directory" in p for p in problems)
    assert any("'qa-smoke-testing#made-up', which isn't a section" in p for p in problems)


def test_planner_prompt_includes_graph_facts_and_cited_docs():
    llm = ScriptedLLM(f"```yaml\n{DEMO_TEXT}\n```")
    plan("Migrate ClaimsAdjudicationService to AWS", demo_graph(), SECTIONS, llm, log=lambda _: None)
    user = llm.prompts[0][1]
    assert "Knowledge graph:" in user and "(id: service-claims-adjudication#what-it-does)" in user


def test_plan_pr_body_lists_approvals_steps_and_sources():
    result = plan("Migrate ClaimsAdjudicationService to AWS", demo_graph(), SECTIONS,
                  ScriptedLLM(f"```yaml\n{DEMO_TEXT}\n```"), log=lambda _: None)
    body = pr_body(result, "Migrate ClaimsAdjudicationService to AWS", SECTIONS)
    assert "**APPR-MCP-001** from `claims-mcp-team`, after APPR-MGR-001" in body
    assert "`db_migrate` (data, db_migration) manual" in body
    assert "Data: Claims Data Handling and Migration Procedure > Converting the data" in body


# ---- Migration guide ------------------------------------------------------------------------------

def cite_everything(user):
    numbers = sorted(set(re.findall(r"^\[S(\d+)\]", user, re.M)), key=int)[:2]
    marks = "".join(f"[S{n}]" for n in numbers)
    return f"## What happens\nThis stage creates the claims table. {marks}\n\n- It is undone by destroy. {marks}"


def test_guide_has_a_page_per_stage():
    keys = [p.key for p in plan_pages(SPEC)]
    assert keys == ["root", "approvals"] + [f"stage-{s}" for s in SPEC.stages] + ["setup"]


def test_guide_page_is_retried_until_grounded():
    page = plan_pages(SPEC)[3]  # stage infrastructure
    llm = ScriptedLLM("Uncited statement about Terraform.", cite_everything)
    markdown, catalog, attempts, dropped = write_page(page, SPEC, SECTIONS, {}, llm, None)
    assert attempts == 2 and dropped == 0 and check_citations(markdown, catalog) == []
    assert "It isn't properly grounded" in llm.prompts[1][1]
    assert "(id: platform-terraform#layout)" in llm.prompts[0][1]  # the step's cited standards are given


def test_guide_drops_what_stays_ungrounded():
    page = plan_pages(SPEC)[0]
    llm = ScriptedLLM(*["## Intro\nGrounded. [S1]\n\nInvented claim."] * 3)
    markdown, _, attempts, dropped = write_page(page, SPEC, SECTIONS, {}, llm, None)
    assert attempts == 3 and dropped == 1 and "Invented" not in markdown


def test_render_turns_citations_into_numbered_links():
    catalog = Catalog([s for s in SECTIONS if s.doc_id == "data-migration"][:2])
    catalog.sections[0] = catalog.sections[0].__class__(**{**vars(catalog.sections[0]), "url": "https://c/p/9"})
    html = render("Dates must be ISO. [S1]\n\n- Counts must match. [S2][S1]", catalog, dropped=1)
    assert '<sup><a href="https://c/p/9">[1]</a></sup>' in html and "[2]" in html
    assert "<h2>Sources</h2><ol><li>[1] <a href=\"https://c/p/9\">" in html
    assert "1 statement(s) were removed" in html and "[S1]" not in html


def test_write_guide_publishes_a_tree_with_the_design_page_linked(env):
    llm = ScriptedLLM()
    llm.default = cite_everything
    published = write_guide(SPEC, SECTIONS, {}, llm, env.pages, design_url="https://c/design", log=lambda _: None)
    assert len(published) == len(plan_pages(SPEC))
    calls = env.pages.published
    root_id = published["root"][0]
    assert calls[0][3] is None and all(parent == root_id for *_, parent in calls[1:])
    assert 'href="https://c/design"' in calls[0][1]
    assert all("<h2>Sources</h2>" in html for _, html, _, _ in calls)


# ---- Code writer ----------------------------------------------------------------------------------

def test_codegen_only_for_steps_the_engineers_marked():
    with pytest.raises(CodegenRefused, match="engineers write its code"):
        generate(SPEC, SPEC.step("provision_iam"), SECTIONS, {}, ScriptedLLM())


def test_codegen_limits():
    step = SPEC.step("provision_storage")  # codegen: llm, path terraform/storage
    files = {"terraform/storage/main.tf": "ok", "terraform/storage/../iam/main.tf": "sneaky",
             "terraform/iam/main.tf": "other step", "terraform/storage/.terraform.lock.hcl": "lock",
             ".github/workflows/ci.yml": "ci", "../escape.tf": "x", "terraform/storage/big.tf": "x" * 100_001}
    kept, rejected = check_files(SPEC, step, files)
    assert kept == {"terraform/storage/main.tf": "ok"} and len(rejected) == 6


def test_codegen_writes_only_allowed_files(env):
    reply = json.dumps({"summary": "Table per platform-naming#resource-names",
                        "files": [{"path": "terraform/storage/main.tf", "content": "resource ..."},
                                  {"path": "tests/test_x.py", "content": "cheat"}]})
    llm = ScriptedLLM(reply)
    result = generate(SPEC, SPEC.step("provision_storage"), SECTIONS, {"terraform/storage/main.tf": "old"}, llm)
    assert list(result.files) == ["terraform/storage/main.tf"] and result.rejected
    assert "--- terraform/storage/main.tf\nold" in llm.prompts[0][1]
    assert "(id: platform-naming#resource-names)" in llm.prompts[0][1]


# ---- Pull requests ---------------------------------------------------------------------------------

def test_open_pull_request_makes_branch_files_and_pr(http):
    http.route("GET", "/repos/o/r/git/ref/heads/main", {"object": {"sha": "base123"}})
    http.route("POST", "/repos/o/r/git/refs", {"ref": "refs/heads/b"}, status=201)
    http.route("GET", "/repos/o/r/contents/migrations/x/migration.yaml?ref=b", {"message": "Not Found"}, status=404)
    http.route("PUT", "/repos/o/r/contents/migrations/x/migration.yaml", {"content": {}}, status=201)
    http.route("POST", "/repos/o/r/pulls", {"html_url": "https://github.com/o/r/pull/1"}, status=201)
    url = open_pull_request(GitHubAPI("tok", api=http.url), "o/r", "main", "b",
                            {"migrations/x/migration.yaml": "apiVersion: mac/v0.3\n"}, "Plan", "body", "msg")
    assert url == "https://github.com/o/r/pull/1"
    ref, put, pull = (next(r for r in http.requests if (r["method"], r["path"].split("?")[0]) == k)
                      for k in [("POST", "/repos/o/r/git/refs"), ("PUT", "/repos/o/r/contents/migrations/x/migration.yaml"),
                                ("POST", "/repos/o/r/pulls")])
    assert ref["body"] == {"ref": "refs/heads/b", "sha": "base123"}
    assert put["body"]["branch"] == "b" and "sha" not in put["body"]
    assert pull["body"] == {"title": "Plan", "head": "b", "base": "main", "body": "body"}


def test_ingest_skips_a_page_the_model_would_not_read_and_keeps_the_rest():
    from mac.integrations import IntegrationError

    class Flaky(ScriptedLLM):
        def default(self, user):
            if "Prayerwell Health Engineering Handbook" in user:
                raise IntegrationError("the LLM returned an empty response (finish_reason=length)")
            return json.dumps({"nodes": [{"type": "service", "name": "ClaimsAdjudicationService", "sources": ["S1"]}],
                               "edges": []})

    logs = []
    graph, dropped = extract(SECTIONS, Flaky(), log=logs.append)
    assert graph.find("ClaimsAdjudicationService") is not None
    assert [d for d in dropped if d.startswith("handbook: skipped")]
    assert any(m.startswith("skipped handbook") for m in logs)
