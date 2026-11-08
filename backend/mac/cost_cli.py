"""CLI glue for the cost estimate: `mac prices`, `mac usage <spec>`, `mac cost <spec>`.

    mise run mac prices [--refresh]   AWS's prices the estimate uses (--refresh saves the live ones)
    mise run mac usage <spec>         the usage reader (LLM): figures from the knowledge base
    mise run mac cost <spec>          the estimate from the last Build's plan, recalculated now
"""

import sys
from pathlib import Path

from .cost import as_markdown, estimate
from .knowledge import KnowledgeError, load_pages
from .pricing import PricingError, load_prices, refresh_snapshot
from .sources import sections_from_pages
from .spec import Spec, SpecError, load_spec
from .usage import load_usage, run_usage


class CostInputError(Exception):
    """What's needed before the usage reader or the estimate can run."""


def build_resources(runner, spec: Spec) -> dict[str, list[dict]]:
    """What the latest Build's Terraform plans create. The usage reader and the estimate both start here."""
    build = runner.store.latest(spec.metadata.name, "build")
    resources = (build.report.get("resources") if build else None) or {}
    if not resources:
        raise CostInputError(f"No Build of {spec.metadata.name} has recorded what Terraform creates yet. "
                             "Run Build first (its plans list the resources).")
    return resources


def knowledge(runner, directory: Path, extra_pages: list | None = None):
    """(sections, owners) of the knowledge base, with Confluence URLs where it's published."""
    pages = load_pages(directory) + list(extra_pages or [])
    urls = {page: ids[1] for page, ids in runner.store.knowledge_pages().items()}
    return sections_from_pages(pages, urls), {p.id: p.owner for p in pages}


def run_agent(args, runner) -> int:
    try:
        if args.command == "prices":
            return _prices(args.refresh)
        spec = load_spec(args.spec)
        if args.command == "usage":
            return _usage(args, runner, spec)
        return _cost(runner, spec)
    except (CostInputError, PricingError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except (KnowledgeError, SpecError) as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1


def _prices(refresh: bool) -> int:
    if refresh:
        prices, notes = refresh_snapshot(), ["saved to the snapshot"]
    else:
        prices, notes = load_prices()
    for name, price in sorted(prices.items()):
        print(f"{name:<26} {price.rate_text():<60} SKU {price.sku}, effective {price.effective_date[:10]} ({price.source})")
    for note in notes:
        print(f"  {note}")
    return 0


def _usage(args, runner, spec: Spec) -> int:
    from .agents_cli import _llm  # the same LLM settings as the other agents
    resources = build_resources(runner, spec)
    sections, owners = knowledge(runner, args.knowledge)
    llm = _llm()
    usage = run_usage(spec.metadata.name, spec.metadata.service, resources, sections, owners, llm,
                      runner.data_dir, runner.approvals, log=print, model=getattr(llm, "model", None))
    print(f"{len(usage['facts'])} figures, {len(usage['rejected'])} rejected, {len(usage['missing'])} missing")
    for item in usage["missing"]:
        q = item["question"] or {}
        print(f"  missing {item['subject']} {item['metric']}: " + (q.get("ticket") or q.get("status") or "not asked"))
    print("Run Build again to put the estimate in the report and on the design page.")
    return 0


def _cost(runner, spec: Spec) -> int:
    prices, notes = load_prices(spec.target.region)
    view = estimate(build_resources(runner, spec), load_usage(runner.data_dir, spec.metadata.name), prices, notes)
    print(as_markdown(view))
    return 0 if view["status"] != "unavailable" else 1
