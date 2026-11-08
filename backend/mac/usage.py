"""The usage reader: finds, in the knowledge base, the figures the cost estimate needs.

What Terraform will create (from Build's plan) decides which figures are needed: a Lambda
function needs how often it runs and for how long, a DynamoDB table how often it's read and
written and how much it stores. An LLM reads the pages and returns each figure with the section
it comes from and the sentence it quotes. **Code checks every one**: the section must exist, the
quote must be in it, the number must be in the quote, and the unit must be one the figure can
have. Unit conversions are done by code, never by the model.

A figure the pages don't give is never guessed: it becomes a question to the page's owner, as
one Jira ticket per figure, raised once. When the owner adds it to the page, the next read
picks it up. The result is saved per migration in `<data dir>/usage/<migration>.json`, and
Build's cost estimate reads it from there, so no model is ever called during Build.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .integrations import IntegrationError, TicketRequest
from .llm import LLM, parse_json
from .sources import Section

DAYS_PER_MONTH = 365.25 / 12  # 30.4375: the average month

# Units each kind of figure may be given in, and the factor to the kind's base unit.
UNITS: dict[str, dict[str, float]] = {
    "rate": {"per_second": 86400 * DAYS_PER_MONTH, "per_minute": 1440 * DAYS_PER_MONTH,
             "per_hour": 24 * DAYS_PER_MONTH, "per_day": DAYS_PER_MONTH, "per_month": 1.0,
             "per_year": 1 / 12},  # base: per month
    "count": {"count": 1.0},
    "duration": {"ms": 1.0, "s": 1000.0},  # base: ms
    "size": {"B": 1 / 1024, "KB": 1.0, "MB": 1024.0, "GB": 1024.0 ** 2},  # base: KB
    "days": {"days": 1.0},
    "money": {"usd_per_month": 1.0, "usd_per_year": 1 / 12},  # base: USD per month
}
BASE_UNIT = {"rate": "per month", "count": "", "duration": "ms", "size": "KB", "days": "days",
             "money": "USD per month"}


@dataclass(frozen=True)
class Metric:
    name: str
    kind: str  # a key of UNITS
    question: str  # what it means, for the prompt and the Jira question
    required: bool = True  # optional figures count as none when the pages don't mention any
    many: bool = False  # several labelled facts allowed (on-prem cost lines)


# Figures about the business service as a whole.
SERVICE_METRICS = (
    Metric("requests_per_month", "rate", "how many business requests (for example claims) the service "
           "handles, on average"),
)
LOG_METRICS = (
    Metric("log_retention_days", "days", "how many days CloudWatch log groups keep logs"),
)
ONPREM_METRICS = (
    Metric("onprem_cost", "money", "a cost of running the system on-prem today; one fact per cost line, "
           "with a short label", required=False, many=True),
)
# Figures each kind of resource needs, by Terraform resource type.
RESOURCE_METRICS: dict[str, tuple[Metric, ...]] = {
    "aws_lambda_function": (
        Metric("invocations_per_request", "count", "how many times this function runs per business request"),
        Metric("other_invocations", "rate", "invocations that don't come from requests, such as health "
               "checks", required=False),
        Metric("avg_billed_duration_ms", "duration", "the average billed duration of one invocation on Lambda "
               "(measured on Lambda, not on another platform)"),
        Metric("log_kb_per_invocation", "size", "how much log data one invocation writes"),
    ),
    "aws_dynamodb_table": (
        Metric("reads_per_request", "count", "how many items this table reads per business request"),
        Metric("writes_per_request", "count", "how many items this table writes per business request"),
        Metric("items_stored", "count", "how many items the table holds"),
        Metric("avg_item_kb", "size", "the average size of one item"),
        Metric("items_loaded_once", "count", "how many items the migration loads into the table once",
               required=False),
    ),
}


@dataclass(frozen=True)
class Subject:
    """What a figure is about: "service", "logs", "onprem", or one resource Terraform creates."""
    id: str  # "service" | "logs" | "onprem" | "<step id>/<terraform address>"
    description: str
    metrics: tuple[Metric, ...]


def subjects_for(resources: dict[str, list[dict]], service: str) -> list[Subject]:
    """The figures the cost estimate needs for these resources (Build's report["resources"])."""
    subjects = [Subject("service", f"{service}, the business service being migrated", SERVICE_METRICS)]
    has_lambda = False
    for step_id, items in resources.items():
        for res in items:
            metrics = RESOURCE_METRICS.get(res["type"])
            if not metrics:
                continue
            has_lambda = has_lambda or res["type"] == "aws_lambda_function"
            name = res.get("name") or ""
            subjects.append(Subject(f"{step_id}/{res['address']}",
                                    f"{res['type']} {name!r}, created by step {step_id}", metrics))
    if has_lambda:
        subjects.append(Subject("logs", "the CloudWatch log groups the Lambda functions write to", LOG_METRICS))
    subjects.append(Subject("onprem", f"what {service} costs to run on-prem today", ONPREM_METRICS))
    return subjects


SYSTEM_PROMPT = """You read one page of a company's engineering documentation and pick out usage
and cost figures, for a cloud cost estimate that must be justified line by line.

Reply with JSON only: {"facts": [{"subject": "<subject id>", "metric": "<metric>",
"label": "<only for onprem_cost: what the cost is for>", "value": <number>, "unit": "<unit>",
"section": "<section id>", "quote": "<the exact sentence from that section that states it>"}]}

Rules:
- Only figures the page states. Never estimate, convert, add up or assume one. If the page doesn't
  give a figure, leave it out: a missing figure becomes a question to its owner.
- value is the number exactly as written in the quote (40,000 is 40000). unit is one of the units
  listed for that metric, matching what the quote says ("per day" -> per_day).
- quote is copied word for word from the section, and contains the number.
- A figure measured on a different platform (for example on-prem timings) is not the same figure
  on AWS: leave it out.
- Return {"facts": []} if the page has none of the figures."""


def _prompt(subjects: list[Subject], sections: list[Section]) -> str:
    lines = ["Subjects and the figures they need (metric: kind, allowed units: meaning):"]
    for subject in subjects:
        lines.append(f"- subject {subject.id}: {subject.description}")
        for m in subject.metrics:
            lines.append(f"    - {m.name}: units {', '.join(UNITS[m.kind])}: {m.question}")
    lines.append("\nThe page's sections:")
    for s in sections:
        lines.append(f"\n(section id: {s.id}) {s.doc_title} > {s.heading}\n{s.text}")
    return "\n".join(lines)


# ---- Checking what the model said ---------------------------------------------------------------

def _plain(text: str) -> str:
    """Markdown emphasis and code marks removed, whitespace collapsed, lowercase."""
    return re.sub(r"\s+", " ", re.sub(r"[*`_]", "", text)).strip().lower()


def numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def check_fact(raw: dict, subjects: dict[str, Subject], sections: dict[str, Section]) -> tuple[dict | None, str | None]:
    """(fact, None) when it holds up, else (None, why not)."""
    subject = subjects.get(str(raw.get("subject", "")))
    if subject is None:
        return None, f"unknown subject {raw.get('subject')!r}"
    metric = next((m for m in subject.metrics if m.name == raw.get("metric")), None)
    if metric is None:
        return None, f"{subject.id} has no figure {raw.get('metric')!r}"
    section = sections.get(str(raw.get("section", "")))
    if section is None:
        return None, f"{metric.name}: cites {raw.get('section')!r}, which isn't a section of the page"
    quote = str(raw.get("quote") or "")
    if len(_plain(quote)) < 8 or _plain(quote) not in _plain(section.text):
        return None, f"{metric.name}: the quote isn't in section {section.id}"
    try:
        value = float(raw.get("value"))
    except (TypeError, ValueError):
        return None, f"{metric.name}: value {raw.get('value')!r} isn't a number"
    if not any(abs(n - value) <= 1e-9 * max(1.0, abs(value)) for n in numbers_in(quote)):
        return None, f"{metric.name}: {value:g} isn't a number the quote states"
    unit = str(raw.get("unit", ""))
    if unit not in UNITS[metric.kind]:
        return None, f"{metric.name}: unit {unit!r} isn't one of {', '.join(UNITS[metric.kind])}"
    label = str(raw.get("label") or "").strip() if metric.many else ""
    if metric.many and not label:
        return None, f"{metric.name}: needs a label saying what the cost is for"
    return {
        "subject": subject.id, "metric": metric.name, "label": label or None, "value": value, "unit": unit,
        "normalized": value * UNITS[metric.kind][unit], "base_unit": BASE_UNIT[metric.kind],
        "section": section.id, "page": section.doc_title, "heading": section.heading, "url": section.url,
        "quote": quote.strip(),
    }, None


# ---- The reader ---------------------------------------------------------------------------------

Trace = Callable[..., None]  # trace(agent, phase, text, **kw), as planning_api._Trace


def _pages_to_read(sections: list[Section], limit: int = 8) -> list[str]:
    """Pages that state figures at all, most cost-related first. Code decides; no model call."""
    words = ("per day", "per month", "per year", "per minute", "kb", "mb", "ms", "$", "claims",
             "items", "invocation", "logs", "cost", "capacity", "usage")
    score: dict[str, float] = {}
    for s in sections:
        text = s.text.lower()
        if not re.search(r"\d", text):
            continue
        score[s.doc_id] = score.get(s.doc_id, 0) + sum(text.count(w) for w in words)
    return [doc for doc, sc in sorted(score.items(), key=lambda kv: -kv[1]) if sc > 0][:limit]


def knowledge_digest(sections: list[Section]) -> str:
    return hashlib.sha256("\n".join(f"{s.id}\n{s.text}" for s in sections).encode()).hexdigest()


MAX_TOKENS = 8000  # reasoning models think before answering; a smaller budget cuts the JSON off
ATTEMPTS = 2
RETRY = ("\n\nYour previous reply was cut off or wasn't valid JSON ({error}). Reply again with only the "
         "JSON object, nothing before or after it, and keep each quote to the one sentence that states the figure.")


def _ask(llm: LLM, prompt: str, doc_id: str, log: Callable[[str], None], trace: Trace, agent: str) -> list | None:
    """The facts the model returns for one page, asking again once if the reply isn't JSON."""
    error = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            text = llm.complete(SYSTEM_PROMPT, prompt + (RETRY.format(error=error) if error else ""),
                                max_tokens=MAX_TOKENS)
            reply = parse_json(text)
            facts = reply.get("facts") if isinstance(reply, dict) else None
            if not isinstance(facts, list):
                raise ValueError('no "facts" list in the reply')
            return facts
        except Exception as e:  # noqa: BLE001 - a bad reply is retried, then loses one page, not the run
            error = str(e)[:200]
            log(f"{doc_id}: attempt {attempt}: the model's reply wasn't usable: {error}")
    trace(agent, "outcome", f"reply not usable after {ATTEMPTS} attempts: {error}", parent="usage", status="failed")
    return None


def read_usage(subjects: list[Subject], sections: list[Section], llm: LLM, *,
               log: Callable[[str], None] = print, trace: Trace | None = None,
               model: str | None = None) -> dict:
    """Asks the LLM page by page and keeps only facts that pass check_fact."""
    trace = trace or (lambda *a, **k: None)
    by_subject = {s.id: s for s in subjects}
    by_section = {s.id: s for s in sections}
    pages = _pages_to_read(sections)
    needed = sum(len(s.metrics) for s in subjects)
    trace("usage", "observation", f"Terraform will create {len(subjects) - 2 - ('logs' in by_subject)} priced "
          f"resources; the estimate needs {needed} figures. {len(pages)} pages state figures.",
          role="Usage reader", model=model, status="running")
    trace("usage", "reasoning", "each page is read on its own so every figure keeps its section and quote; "
          "code then checks every quote against the page and converts the units")
    facts, rejected = [], []
    seen: set[tuple] = set()
    for doc_id in pages:
        page_sections = [s for s in sections if s.doc_id == doc_id]
        agent = f"usage:{doc_id}"
        trace(agent, "action", f"reading “{page_sections[0].doc_title}” for usage figures", parent="usage",
              role="Reader", model=model, status="running")
        raw_facts = _ask(llm, _prompt(subjects, page_sections), doc_id, log, trace, agent)
        if raw_facts is None:
            continue
        kept = 0
        for raw in raw_facts if isinstance(raw_facts, list) else []:
            fact, why = check_fact(raw if isinstance(raw, dict) else {}, by_subject, by_section)
            if fact is None:
                rejected.append({"page": doc_id, "fact": raw, "reason": why})
                log(f"{doc_id}: rejected: {why}")
                continue
            key = (fact["subject"], fact["metric"], fact["label"])
            if key in seen:
                rejected.append({"page": doc_id, "fact": raw, "reason": "already found on an earlier page"})
                continue
            seen.add(key)
            facts.append(fact)
            kept += 1
            log(f"{doc_id}: {fact['subject']} {fact['metric']} = {fact['value']:g} {fact['unit']}")
        trace(agent, "outcome", f"{kept} figures kept, each with its quote", parent="usage", status="succeeded")
    return {"facts": facts, "rejected": rejected}


def missing_metrics(subjects: list[Subject], facts: list[dict]) -> list[tuple[Subject, Metric]]:
    have = {(f["subject"], f["metric"]) for f in facts}
    return [(s, m) for s in subjects for m in s.metrics if m.required and (s.id, m.name) not in have]


def question_key(subject: Subject, metric: Metric) -> str:
    return f"{subject.id}:{metric.name}"


def owner_for(metric: Metric, subject: Subject, sections: list[Section], owners: dict[str, str]) -> tuple[str, str | None]:
    """(team, page title) to ask: the owner of the page most about this figure."""
    from .sources import relevant  # local: keeps this module's import list short
    best = relevant(sections, f"{metric.question} {subject.description} usage capacity", k=1)
    if best:
        return owners.get(best[0].doc_id) or "", best[0].doc_title
    return "", None


def ask_owners(migration: str, service: str, missing: list[tuple[Subject, Metric]], sections: list[Section],
               owners: dict[str, str], approvals, known: dict[str, dict], log: Callable[[str], None] = print,
               trace: Trace | None = None) -> dict[str, dict]:
    """One Jira question per missing figure, raised once: `known` holds the ones already asked."""
    trace = trace or (lambda *a, **k: None)
    questions = dict(known)
    for subject, metric in missing:
        key = question_key(subject, metric)
        if key in questions and questions[key].get("ticket"):
            log(f"{key}: already asked in {questions[key]['ticket']}")
            continue
        team, page = owner_for(metric, subject, sections, owners)
        entry = {"subject": subject.id, "metric": metric.name, "owner": team or None, "page": page,
                 "ticket": None, "url": None}
        if approvals is None:
            entry["status"] = "not raised: Jira isn't configured"
        else:
            request = TicketRequest(
                approval_id=f"COST-{metric.name}",
                summary=f"Cost estimate for {service}: what is {metric.name.replace('_', ' ')} for {subject.id}?",
                paragraphs=[
                    f"MaC is estimating what {service} will cost on AWS for migration {migration}, and "
                    f"needs a figure the documentation doesn't give: {metric.question}.",
                    f"It's for: {subject.description}.",
                    "MaC never guesses a figure. Please measure it and add it to "
                    + (f"“{page}”" if page else "the service's Capacity and Usage page")
                    + ", with its unit. The next usage read picks it up, and the estimate is recalculated "
                      "at the next Build.",
                    "Until then the estimate is shown as partial, with this line unpriced.",
                ],
                approver=team or "",
                labels=["mac", "cost-question", migration, metric.name],
                links=[],
            )
            try:
                raised = approvals.raise_ticket(request)
                entry.update(ticket=raised.key, url=raised.url, status="asked")
                log(f"{key}: asked {team or 'the owner'} in {raised.key}")
                trace("usage", "action", f"no page gives {metric.name} for {subject.id}: asked {team or 'the owner'} "
                      f"in {raised.key} instead of guessing", parent=None)
            except IntegrationError as e:
                entry["status"] = f"not raised: {e}"
                log(f"{key}: couldn't raise the question: {e}")
        questions[key] = entry
    return questions


def asked_note(missing: list[dict]) -> str:
    """How the missing figures were followed up: only tickets that exist count as asked."""
    if not missing:
        return ""
    asked = sum(1 for m in missing if (m.get("question") or {}).get("ticket"))
    if asked == len(missing):
        return " (asked in Jira)"
    return f" ({asked} asked in Jira, {len(missing) - asked} not raised)" if asked else " (not raised in Jira)"


def usage_path(data_dir: Path, migration: str) -> Path:
    return Path(data_dir) / "usage" / f"{migration}.json"


def load_usage(data_dir: Path, migration: str) -> dict | None:
    path = usage_path(data_dir, migration)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def run_usage(migration: str, service: str, resources: dict[str, list[dict]], sections: list[Section],
              owners: dict[str, str], llm: LLM, data_dir: Path, approvals=None,
              log: Callable[[str], None] = print, trace: Trace | None = None, model: str | None = None) -> dict:
    """Reads the figures, asks for the missing ones, and saves the result for Build."""
    subjects = subjects_for(resources, service)
    previous = load_usage(data_dir, migration) or {}
    result = read_usage(subjects, sections, llm, log=log, trace=trace, model=model)
    missing = missing_metrics(subjects, result["facts"])
    questions = ask_owners(migration, service, missing, sections, owners, approvals,
                           previous.get("questions", {}), log=log, trace=trace)
    open_keys = {question_key(s, m) for s, m in missing}
    for key, q in questions.items():
        q["open"] = key in open_keys  # answered questions stay recorded, marked closed
    usage = {
        "version": 1, "migration": migration, "service": service, "read_at": time.time(),
        "model": model, "knowledge": {"digest": knowledge_digest(sections), "sections": len(sections)},
        "subjects": [{"id": s.id, "description": s.description, "metrics": [m.name for m in s.metrics]}
                     for s in subjects],
        "facts": result["facts"], "rejected": result["rejected"],
        "missing": [{"subject": s.id, "metric": m.name, "question": questions.get(question_key(s, m))}
                    for s, m in missing],
        "questions": questions,
    }
    path = usage_path(data_dir, migration)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage, indent=2) + "\n", encoding="utf-8")
    if trace:
        trace("usage", "outcome", f"{len(result['facts'])} figures found and checked, {len(result['rejected'])} "
              f"rejected, {len(missing)} missing" + asked_note(usage["missing"]), status="succeeded")
    return usage
