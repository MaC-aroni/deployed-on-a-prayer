"""CLI glue for the agents: `mac ingest`, `mac plan`, `mac guide`, `mac codegen`.

Knowledge comes from the published Confluence pages when they've been published (so citations
link to Confluence), otherwise from the local drafts in demo-data/confluence.
"""

import os
import sys
import time
from pathlib import Path

from .codegen import CodegenRefused, generate, pr_body as codegen_pr_body
from .graph import Graph, extract
from .guide import write_guide
from .integrations import GitHubAPI, IntegrationError, open_pull_request, read_files
from .knowledge import KnowledgeError, load_pages
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, NIMChat
from .planner import plan, pr_body as plan_pr_body
from .sources import sections_from_pages
from .spec import SpecError, load_spec

MIGRATIONS_REPO = os.environ.get("MAC_MIGRATIONS_REPO", "MaC-aroni/mac-migrations")


def _llm():
    if not os.environ.get("NVIDIA_API_KEY"):
        raise SystemExit("NVIDIA_API_KEY isn't set (see docs/cloud-setup.md)")
    return NIMChat(os.environ["NVIDIA_API_KEY"], os.environ.get("MAC_LLM_MODEL", DEFAULT_MODEL),
                   os.environ.get("MAC_LLM_BASE_URL", DEFAULT_BASE_URL))


def _sections(runner, directory: Path):
    urls = {page: url for page, (_, url, _) in runner.store.knowledge_pages().items()}
    return sections_from_pages(load_pages(directory), urls)


def _graph(runner, sections, llm) -> Graph:
    path = runner.data_dir / "graph.json"
    if path.exists():
        return Graph.from_json(path.read_text(encoding="utf-8"))
    graph, dropped = extract(sections, llm)
    graph.save(path)
    return graph


def run_agent(args, runner) -> int:
    try:
        sections = _sections(runner, args.knowledge)
        if args.command == "ingest":
            graph, dropped = extract(sections, _llm())
            graph.save(runner.data_dir / "graph.json")
            print(f"{len(graph.nodes)} facts, {len(graph.edges)} relations -> {runner.data_dir / 'graph.json'}")
            for reason in dropped:
                print(f"  dropped: {reason}")
            return 0
        if args.command == "plan":
            return _plan(args, runner, sections)
        spec = load_spec(args.spec)
        if args.command == "guide":
            return _guide(runner, spec, sections)
        return _codegen(args, runner, spec, sections)
    except (KnowledgeError, SpecError) as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1
    except IntegrationError as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1


def _plan(args, runner, sections) -> int:
    llm = _llm()
    result = plan(args.goal, _graph(runner, sections, llm), sections, llm)
    name = result.spec.metadata.name if result.spec else f"plan-{int(time.time())}"
    out = runner.data_dir / "plans" / name / "migration.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.yaml + "\n", encoding="utf-8")
    print(f"{'valid' if result.ok else 'NOT valid'} after {result.iterations} attempt(s): {out}")
    for problem in result.problems:
        print(f"  {problem}")
    if not result.ok or not args.pr:
        return 0 if result.ok else 1
    api = GitHubAPI(os.environ.get("GITHUB_TOKEN"))
    url = open_pull_request(api, MIGRATIONS_REPO, "main", f"mac/plan/{name}-{int(time.time())}",
                            {f"migrations/{name}/migration.yaml": result.yaml + "\n"},
                            f"Plan: {result.spec.metadata.service} ({name})",
                            plan_pr_body(result, args.goal, sections), f"Plan {name} with MaC's planner")
    print(f"opened {url}")
    return 0


def _guide(runner, spec, sections) -> int:
    if runner.pages is None:
        print("Confluence isn't configured (ATLASSIAN_* and CONFLUENCE_SPACE_KEY)", file=sys.stderr)
        return 2
    name = spec.metadata.name
    build = runner.store.latest(name, "build")
    shas = build.shas if build else {}
    design = runner.store.design(name)
    known = {key: ids[0] for key, ids in runner.store.guide_pages(name).items()}
    published = write_guide(spec, sections, shas, _llm(), runner.pages, known,
                            spec_url=f"https://github.com/{MIGRATIONS_REPO}/blob/main/migrations/{name}/migration.yaml",
                            design_url=design.url if design else None)
    for key, (page_id, url) in published.items():
        runner.store.save_guide_page(name, key, page_id, url)
    print(f"guide: {published['root'][1]}")
    return 0


def _codegen(args, runner, spec, sections) -> int:
    step = spec.step(args.step)
    api = GitHubAPI(os.environ.get("GITHUB_TOKEN"))
    sha = api.resolve(step.run.repo)
    from .codegen import allowed_prefix
    current = read_files(api, step.run.repo.slug, sha, allowed_prefix(step))
    try:
        result = generate(spec, step, sections, current, _llm())
    except CodegenRefused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    print(result.summary)
    for path in result.files:
        print(f"  write {path}")
    for reason in result.rejected:
        print(f"  thrown out: {reason}")
    if args.pr and result.files:
        guide = runner.store.guide_pages(spec.metadata.name).get("root")
        url = open_pull_request(api, step.run.repo.slug, "main", f"mac/codegen/{step.id}-{int(time.time())}",
                                result.files, f"MaC code writer: {step.id}",
                                codegen_pr_body(step, result, guide[1] if guide else None),
                                f"Write {step.id} with MaC's code writer")
        print(f"opened {url}")
    return 0
