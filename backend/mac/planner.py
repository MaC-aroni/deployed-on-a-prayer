"""The planner: turns "Migrate <service> to AWS" into a migration.yaml, from the knowledge base.

A ReAct-style loop against MaC's own rules: the LLM writes the spec, code checks it (schema,
`mac validate`, citations, and only repos and approvers the knowledge graph knows), and every
problem goes back to the LLM to fix. Output is a pull request into mac-migrations that
engineers review. The planner never runs anything.
"""

from dataclasses import dataclass, field

from .graph import Graph, context_for
from .llm import LLM, extract_block
from .sources import Section
from .spec import Spec, SpecError, parse_spec
from .validate import validate

MAX_ITERATIONS = 4

SYSTEM_PROMPT = """You are MaC's planner. Using only the company documentation and knowledge graph
given, write the migration pipeline for the goal as a migration.yaml (schema mac/v0.3).

Schema:
apiVersion: mac/v0.3
kind: Migration
metadata: {name: <lowercase-dashes>, service: <service name>, owner_team: <team>, generated_by: mac-planner}
target: {provider: aws, account: "000000000000", region: <region from the docs>}
stages: [<stage names, in the order the docs give>]
approvals:
  - {id: <APPR-...>, type: <approval type from the docs>, approver: <approver name from the docs>,
     summary: <ticket title>, justification: <why, from the docs>, after: [<ids that must approve first>],
     design_doc: <true if the policy requires a design document>, sources: [<section ids>]}
steps:
  - id: <snake_case>
    stage: <one of stages>
    type: check | iac | db_migration | script
    requires_approval: [<approval ids>]
    when: manual            # only where the docs say a person must start it
    codegen: engineer
    run: {repo: github.com/<owner>/<repo>, path: <terraform dir>}       # iac
    run: {repo: github.com/<owner>/<repo>, entrypoint: <file>}          # other types
    verify: {entrypoint: <file>}            # db_migration steps
    rollback: {entrypoint: <file>}          # script and db_migration steps; check steps: rollback: none
    sources: [<section ids>]

Rules:
- Use only repositories, paths, files, approvers and approval types that the documentation names.
- Every step and every approval has `sources`: the section ids (as shown after "id:") it follows.
- Every step that changes production requires the approvals the policies demand. Chain
  approvals with `after` where the docs give an order.
- Output only the YAML, in one ```yaml block."""


@dataclass
class PlanResult:
    yaml: str
    spec: Spec | None
    problems: list[str]  # empty when the plan passed every check
    iterations: int
    history: list[list[str]] = field(default_factory=list)  # problems found at each attempt

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.problems


def check_plan(text: str, sections: list[Section], graph: Graph) -> tuple[Spec | None, list[str]]:
    """Everything that makes a generated plan unacceptable, found by code."""
    try:
        spec = parse_spec(text, source="migration.yaml")
    except SpecError as e:
        return None, e.problems
    problems = [str(i) for i in validate(spec) if i.level == "error"]
    known_sections = {s.id for s in sections}
    known_repos = {name.lower() for name in graph.names("repo")}
    known_approvers = {name.strip("`").lower() for name in graph.names("approver")}
    for kind, items in (("step", spec.steps), ("approval", spec.approvals)):
        for item in items:
            if not item.sources:
                problems.append(f"{kind} {item.id}: has no sources; cite the sections it follows")
            for sid in item.sources:
                if sid not in known_sections:
                    problems.append(f"{kind} {item.id}: cites {sid!r}, which isn't a section of the docs")
    for ref in spec.repos().values():
        if known_repos and ref.slug.lower() not in known_repos:
            problems.append(f"repo {ref.slug} isn't in the documentation; use only documented repositories")
    for approval in spec.approvals:
        if known_approvers and approval.approver.lower() not in known_approvers:
            problems.append(f"approval {approval.id}: approver {approval.approver!r} isn't in the directory")
    return spec, problems


def plan(goal: str, graph: Graph, sections: list[Section], llm: LLM,
         max_iterations: int = MAX_ITERATIONS, log=print) -> PlanResult:
    sub, chosen = context_for(graph, sections, goal)
    docs = "\n\n".join(f"(id: {s.id}) {s.doc_title} > {s.heading}\n{s.text}" for s in chosen)
    user = f"Goal: {goal}\n\nKnowledge graph:\n{sub.facts()}\n\nDocumentation:\n{docs}"
    history: list[list[str]] = []
    text, spec, problems = "", None, ["no attempt yet"]
    for attempt in range(1, max_iterations + 1):
        prompt = user if attempt == 1 else (
            f"{user}\n\nYour previous migration.yaml:\n```yaml\n{text}\n```\n\n"
            "It has these problems. Fix all of them and return the whole file:\n- " + "\n- ".join(problems))
        text = extract_block(llm.complete(SYSTEM_PROMPT, prompt, max_tokens=6000), "ya?ml")
        spec, problems = check_plan(text, sections, graph)
        history.append(problems)
        log(f"attempt {attempt}: " + ("valid" if not problems else f"{len(problems)} problems"))
        if not problems:
            break
    return PlanResult(text, spec, problems, len(history), history)


def pr_body(result: PlanResult, goal: str, sections: list[Section]) -> str:
    by_id = {s.id: s for s in sections}
    spec = result.spec
    lines = [f"Generated by MaC's planner from the company knowledge base for: **{goal}**", "",
             f"Checked by code in {result.iterations} attempt(s): schema, `mac validate`, citations, and "
             "only documented repos and approvers. **Review it like any other change**, including which "
             "steps the LLM may write code for (`codegen: llm`).", "", "## Approvals"]
    for a in spec.approvals:
        chain = f", after {', '.join(a.after)}" if a.after else ""
        lines.append(f"- **{a.id}** from `{a.approver}`{chain}: {a.summary}")
    lines += ["", "## Steps"]
    for s in spec.steps:
        lines.append(f"- `{s.id}` ({s.stage}, {s.type}){' manual' if s.when == 'manual' else ''}: "
                     f"{s.run.repo.slug} {s.run.path or s.run.entrypoint}")
    cited = sorted({sid for item in [*spec.steps, *spec.approvals] for sid in item.sources})
    lines += ["", "## Sources"]
    for sid in cited:
        s = by_id[sid]
        lines.append(f"- [{s.doc_title} > {s.heading}]({s.url})" if s.url else f"- {s.doc_title} > {s.heading} (`{sid}`)")
    return "\n".join(lines)
