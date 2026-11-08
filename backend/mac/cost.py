"""The cost estimate: what Terraform creates × the documented usage × AWS's prices. Code only.

Every line says how it was worked out (a formula a person can redo), and every number in it
points at where it came from: a Confluence section and the sentence it quotes, an attribute of
Terraform's plan, an AWS price with its SKU and date, or a pricing rule AWS documents. Nothing is
estimated. A line whose figures the docs don't give is listed as unpriced, with the Jira
question asking for them, and the total is then marked partial.

Build calls `estimate` after the Terraform plans; it never calls a model, and a problem here
never fails a Build.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field

from .pricing import Price
from .usage import DAYS_PER_MONTH, RESOURCE_METRICS

KB_PER_GB = 1024 ** 2

# Resources AWS doesn't charge for by themselves. Each with AWS's own words on where.
FREE = {
    "aws_iam_role": "IAM is offered at no additional charge",
    "aws_iam_role_policy": "IAM is offered at no additional charge",
    "aws_iam_policy": "IAM is offered at no additional charge",
    "aws_iam_role_policy_attachment": "IAM is offered at no additional charge",
    "aws_lambda_function_url": "function URLs have no additional cost; invocations are billed as Lambda requests",
    "aws_lambda_permission": "a resource policy on the function; no charge of its own",
}
FREE_SOURCES = {
    "aws_iam": "https://aws.amazon.com/iam/faqs/",
    "aws_lambda": "https://aws.amazon.com/lambda/pricing/",
}
# Pricing rules AWS documents that the formulas use.
RULES = {
    "dynamodb_read_unit": ("A strongly consistent read of up to 4 KB uses 1 read request unit (eventually "
                           "consistent reads use half; the estimate uses the higher figure).",
                           "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html"),
    "dynamodb_write_unit": ("A write of up to 1 KB uses 1 write request unit; larger items use 1 per KB, rounded up.",
                            "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html"),
    "dynamodb_item_overhead": ("DynamoDB adds 100 bytes of overhead to each item's stored size.",
                               "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/CapacityUnitCalculations.html"),
    "lambda_gb_seconds": ("Lambda duration is billed in GB-seconds: billed duration × memory configured.",
                          "https://aws.amazon.com/lambda/pricing/"),
    "logs_steady_state": ("At steady state a log group holds `retention` days of logs. CloudWatch bills the "
                          "compressed size, so this is an upper bound.",
                          "https://aws.amazon.com/cloudwatch/pricing/"),
    "month": (f"An average month is 365.25 / 12 = {DAYS_PER_MONTH} days.", None),
}
LAMBDA_DEFAULT_MEMORY_MB = 128  # the provider's default when memory_size isn't set


def _n(x: float) -> str:
    """A number for a formula: thousands separators, at most 4 significant decimals."""
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x):,}"
    return f"{x:,.6g}" if abs(x) >= 1 else f"{x:.4g}"


@dataclass
class Line:
    id: str
    subject: str  # "<step>/<address>"
    resource_type: str
    what: str  # e.g. "Lambda requests"
    price_name: str
    quantity: float
    unit: str
    formula: str
    inputs: list[dict]
    usd: float = 0.0
    price: dict | None = None


@dataclass
class _Facts:
    by_key: dict[tuple[str, str], dict] = field(default_factory=dict)

    def get(self, subject: str, metric: str) -> dict | None:
        return self.by_key.get((subject, metric))


def _confluence_input(name: str, fact: dict) -> dict:
    return {"name": name, "value": fact["normalized"], "unit": fact["base_unit"],
            "as_written": f"{fact['value']:g} {fact['unit']}",
            "source": {"kind": "confluence", "section": fact["section"], "page": fact["page"],
                       "heading": fact["heading"], "url": fact.get("url"), "quote": fact["quote"]}}


def _terraform_input(name: str, value, step: str, address: str, attribute: str, default_rule: str | None = None) -> dict:
    source = {"kind": "terraform", "step": step, "address": address, "attribute": attribute}
    if default_rule:
        source["note"] = default_rule
    return {"name": name, "value": value, "unit": "", "source": source}


def _rule_input(rule: str) -> dict:
    text, url = RULES[rule]
    return {"name": rule, "value": None, "unit": "", "source": {"kind": "aws-rule", "text": text, "url": url}}


def _price_view(price: Price) -> dict:
    return {"name": price.name, "service": price.service, "usagetype": price.usagetype, "unit": price.unit,
            "rate": price.rate_text(), "sku": price.sku, "rate_codes": list(price.rate_codes),
            "description": price.description, "effective_date": price.effective_date,
            "publication_date": price.publication_date, "offer_url": price.offer_url, "source": price.source}


def _requests(facts: _Facts) -> tuple[float, dict] | None:
    fact = facts.get("service", "requests_per_month")
    return (fact["normalized"], fact) if fact else None


def _lambda_lines(subject: str, step: str, res: dict, facts: _Facts, missing: list[str]) -> list[Line]:
    attrs = res.get("attributes") or {}
    arm = "arm64" in (attrs.get("architectures") or [])
    req = _requests(facts)
    per_req = facts.get(subject, "invocations_per_request")
    other = facts.get(subject, "other_invocations")
    duration = facts.get(subject, "avg_billed_duration_ms")
    log_kb = facts.get(subject, "log_kb_per_invocation")
    retention = facts.get("logs", "log_retention_days")
    if req is None:
        missing.append("service:requests_per_month")
    if per_req is None:
        missing.append(f"{subject}:invocations_per_request")
    if req is None or per_req is None:
        return []

    requests, req_fact = req
    invocations = requests * per_req["normalized"] + (other["normalized"] if other else 0)
    inv_inputs = [_confluence_input("requests_per_month", req_fact), _confluence_input("invocations_per_request", per_req)]
    inv_formula = f"{_n(requests)} requests/month × {_n(per_req['normalized'])} invocations/request"
    if other:
        inv_inputs.append(_confluence_input("other_invocations", other))
        inv_formula += f" + {_n(other['normalized'])} other invocations/month"
    inv_inputs.append(_rule_input("month"))
    lines = [Line(f"{subject}#requests", subject, res["type"], "Lambda requests",
                  "lambda.requests_arm" if arm else "lambda.requests", invocations, "requests",
                  f"{inv_formula} = {_n(invocations)} requests", list(inv_inputs))]

    if duration is None:
        missing.append(f"{subject}:avg_billed_duration_ms")
    else:
        memory = attrs.get("memory_size")
        mem_input = _terraform_input("memory_size", memory, step, res["address"], "memory_size") if memory else \
            _terraform_input("memory_size", LAMBDA_DEFAULT_MEMORY_MB, step, res["address"], "memory_size",
                             "not set in the plan: the AWS provider's default")
        memory = memory or LAMBDA_DEFAULT_MEMORY_MB
        gb_s = invocations * duration["normalized"] / 1000 * memory / 1024
        lines.append(Line(f"{subject}#duration", subject, res["type"], "Lambda compute (GB-seconds)",
                          "lambda.gb_seconds_arm" if arm else "lambda.gb_seconds", gb_s, "GB-seconds",
                          f"{_n(invocations)} invocations × {_n(duration['normalized'])} ms ÷ 1,000 × {_n(memory)} MB "
                          f"÷ 1,024 = {_n(gb_s)} GB-seconds",
                          inv_inputs + [_confluence_input("avg_billed_duration_ms", duration), mem_input,
                                        _rule_input("lambda_gb_seconds")]))

    if log_kb is None:
        missing.append(f"{subject}:log_kb_per_invocation")
    else:
        gb = invocations * log_kb["normalized"] / KB_PER_GB
        log_inputs = inv_inputs + [_confluence_input("log_kb_per_invocation", log_kb)]
        lines.append(Line(f"{subject}#logs-ingest", subject, res["type"], "CloudWatch Logs ingestion",
                          "logs.ingest_gb", gb, "GB",
                          f"{_n(invocations)} invocations × {_n(log_kb['normalized'])} KB ÷ 1,048,576 = {_n(gb)} GB",
                          log_inputs))
        if retention is None:
            missing.append("logs:log_retention_days")
        else:
            stored = gb * retention["normalized"] / DAYS_PER_MONTH
            lines.append(Line(f"{subject}#logs-storage", subject, res["type"], "CloudWatch Logs storage",
                              "logs.storage_gb_month", stored, "GB-months",
                              f"{_n(gb)} GB/month × {_n(retention['normalized'])} days ÷ {DAYS_PER_MONTH} days "
                              f"= {_n(stored)} GB-months",
                              log_inputs + [_confluence_input("log_retention_days", retention),
                                            _rule_input("logs_steady_state")]))
    return lines


def _dynamodb_lines(subject: str, step: str, res: dict, facts: _Facts, missing: list[str]) -> tuple[list[Line], list[Line]]:
    attrs = res.get("attributes") or {}
    mode = attrs.get("billing_mode") or "PROVISIONED"
    if mode != "PAY_PER_REQUEST":
        missing.append(f"{subject}:billing_mode {mode} (only on-demand tables are priced)")
        return [], []
    mode_input = _terraform_input("billing_mode", mode, step, res["address"], "billing_mode")
    req = _requests(facts)
    item = facts.get(subject, "avg_item_kb")
    monthly, once = [], []
    if item is None:
        missing.append(f"{subject}:avg_item_kb")
        return [], []
    kb = item["normalized"]
    item_input = _confluence_input("avg_item_kb", item)
    rru, wru = math.ceil(kb / 4), math.ceil(kb)

    for metric, price_name, units, rule, what in (
            ("reads_per_request", "dynamodb.read_units", rru, "dynamodb_read_unit", "DynamoDB reads"),
            ("writes_per_request", "dynamodb.write_units", wru, "dynamodb_write_unit", "DynamoDB writes")):
        per_req = facts.get(subject, metric)
        if per_req is None:
            missing.append(f"{subject}:{metric}")
            continue
        if req is None:
            missing.append("service:requests_per_month")
            continue
        requests, req_fact = req
        qty = requests * per_req["normalized"] * units
        monthly.append(Line(f"{subject}#{metric}", subject, res["type"], what, price_name, qty, "request units",
                            f"{_n(requests)} requests/month × {_n(per_req['normalized'])} per request × {units} "
                            f"unit(s) per {_n(kb)} KB item = {_n(qty)} request units",
                            [_confluence_input("requests_per_month", req_fact), _confluence_input(metric, per_req),
                             item_input, mode_input, _rule_input(rule), _rule_input("month")]))

    stored = facts.get(subject, "items_stored")
    if stored is None:
        missing.append(f"{subject}:items_stored")
    else:
        gb = stored["normalized"] * (kb + 100 / 1024) / KB_PER_GB
        monthly.append(Line(f"{subject}#storage", subject, res["type"], "DynamoDB storage", "dynamodb.storage_gb_month",
                            gb, "GB-months",
                            f"{_n(stored['normalized'])} items × ({_n(kb)} KB + 100 bytes) ÷ 1,048,576 = {_n(gb)} GB",
                            [_confluence_input("items_stored", stored), item_input, mode_input,
                             _rule_input("dynamodb_item_overhead")]))

    loaded = facts.get(subject, "items_loaded_once")
    if loaded is not None:
        qty = loaded["normalized"] * wru
        once.append(Line(f"{subject}#initial-load", subject, res["type"], "DynamoDB writes for the one-time data load",
                         "dynamodb.write_units", qty, "request units",
                         f"{_n(loaded['normalized'])} items × {wru} write unit(s) per {_n(kb)} KB item = {_n(qty)} request units",
                         [_confluence_input("items_loaded_once", loaded), item_input, mode_input,
                          _rule_input("dynamodb_write_unit")]))
    return monthly, once


def _price_lines(lines: list[Line], prices: dict[str, Price], notes: list[str]) -> None:
    """Tiers apply to the account's total per price, so lines sharing a price are added up first
    and the cost is shared out in proportion."""
    by_price: dict[str, list[Line]] = {}
    for line in lines:
        by_price.setdefault(line.price_name, []).append(line)
    for name, group in by_price.items():
        price = prices[name]
        total_qty = sum(line.quantity for line in group)
        total_usd = price.cost(total_qty)
        for line in group:
            line.usd = total_usd * (line.quantity / total_qty) if total_qty else 0.0
            line.price = _price_view(price)
        if len(price.tiers) > 1 and total_qty <= (price.tiers[0].end or 0) and price.tiers[0].usd == 0:
            notes.append(f"{price.description}: this migration's {_n(total_qty)} {price.unit} stay in the free tier")


def _line_view(line: Line) -> dict:
    return {"id": line.id, "subject": line.subject, "resource_type": line.resource_type, "what": line.what,
            "quantity": line.quantity, "unit": line.unit, "formula": line.formula,
            "usd": line.usd, "price": line.price, "inputs": line.inputs}


def _onprem(facts: list[dict]) -> dict | None:
    items = [f for f in facts if f["subject"] == "onprem" and f["metric"] == "onprem_cost"]
    if not items:
        return None
    total = sum(f["normalized"] for f in items)
    return {"monthly_usd": round(total, 2),
            "items": [{"label": f["label"], "usd_per_month": round(f["normalized"], 2),
                       "formula": f"{f['value']:,.2f} {f['unit'].replace('_', ' ')}"
                                  + (" ÷ 12" if f["unit"] == "usd_per_year" else ""),
                       **_confluence_input("onprem_cost", f)} for f in items]}


def estimate(resources: dict[str, list[dict]], usage: dict | None, prices: dict[str, Price],
             price_notes: list[str] | None = None) -> dict:
    """The whole estimate, JSON-ready. resources: Build's report["resources"]; usage: what the
    usage reader saved (None if it never ran)."""
    notes = list(price_notes or [])
    if usage is None:
        return {"status": "unavailable",
                "reason": "No usage figures yet. Run the usage reader (`mise run mac usage <spec>` or "
                          "POST /api/mac/usage), then Build again.", "notes": notes}
    facts = _Facts({(f["subject"], f["metric"]): f for f in usage.get("facts", []) if f["metric"] != "onprem_cost"})
    questions = usage.get("questions", {})
    monthly: list[Line] = []
    once: list[Line] = []
    free, unknown, unpriced = [], [], []
    for step, items in sorted(resources.items()):
        for res in items:
            subject = f"{step}/{res['address']}"
            rtype = res["type"]
            missing: list[str] = []
            if rtype == "aws_lambda_function":
                monthly += _lambda_lines(subject, step, res, facts, missing)
            elif rtype == "aws_dynamodb_table":
                m, o = _dynamodb_lines(subject, step, res, facts, missing)
                monthly += m
                once += o
            elif rtype in FREE:
                family = "aws_iam" if rtype.startswith("aws_iam") else "aws_lambda"
                free.append({"subject": subject, "resource_type": rtype, "reason": FREE[rtype],
                             "url": FREE_SOURCES[family]})
                continue
            else:
                unknown.append({"subject": subject, "resource_type": rtype,
                                "reason": "the calculator has no pricing for this resource type yet"})
                continue
            for item in dict.fromkeys(missing):
                key = item.split(" ", 1)[0]
                q = questions.get(key) or {}
                unpriced.append({"subject": subject, "missing": item,
                                 "question": {"ticket": q.get("ticket"), "url": q.get("url"),
                                              "status": q.get("status")} if q else None})
    try:
        _price_lines(monthly + once, prices, notes)
    except KeyError as e:
        return {"status": "unavailable", "reason": f"no AWS price for {e}", "notes": notes}

    total = sum(line.usd for line in monthly)
    one_time = sum(line.usd for line in once)
    onprem = _onprem(usage.get("facts", []))
    result = {
        "status": "partial" if unpriced or unknown else "complete",
        "currency": "USD", "region": next(iter(prices.values())).offer_url.rsplit("/", 2)[-2] if prices else None,
        "monthly_usd": round(total, 4), "yearly_usd": round(total * 12, 2), "one_time_usd": round(one_time, 4),
        "lines": [_line_view(line) for line in monthly],
        "one_time": [_line_view(line) for line in once],
        "free": free, "unpriced": unpriced, "unknown_resources": unknown,
        "onprem": onprem,
        "savings": None,
        "prices_source": sorted({line.price["source"] for line in monthly + once if line.price}) or None,
        "usage_read_at": usage.get("read_at"), "knowledge_digest": (usage.get("knowledge") or {}).get("digest"),
        "notes": notes + ["AWS Free Tier allowances for Lambda and CloudWatch are not subtracted; the estimate "
                          "is the list price."],
    }
    if onprem:
        saved = onprem["monthly_usd"] - total
        result["savings"] = {"monthly_usd": round(saved, 2), "yearly_usd": round(saved * 12, 2),
                             "percent": round(100 * saved / onprem["monthly_usd"], 2) if onprem["monthly_usd"] else None,
                             "partial": bool(unpriced or unknown)}
    result["digest"] = digest(result)
    return result


def digest(estimate_view: dict) -> str:
    """Changes when any figure, price or line changes; not when it's merely recalculated."""
    keep = {k: estimate_view.get(k) for k in ("status", "lines", "one_time", "unpriced", "onprem")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def summary(view: dict) -> str:
    """One line for a ticket or a log."""
    if view.get("status") == "unavailable":
        return f"Cost estimate unavailable: {view.get('reason')}"
    partial = view["status"] == "partial"
    if partial:
        text = f"Estimated AWS cost so far (partial): ${view['monthly_usd']:,.2f}/month for what can be priced"
    else:
        text = f"Estimated AWS cost: ${view['monthly_usd']:,.2f}/month (${view['yearly_usd']:,.2f}/year)"
    if view.get("one_time_usd"):
        text += f", plus ${view['one_time_usd']:,.2f} once for the data load"
    if view.get("onprem"):
        text += f"; today on-prem: ${view['onprem']['monthly_usd']:,.2f}/month"
        if view.get("savings") and not partial:  # a saving against a partial total isn't justified
            text += f", saving ${view['savings']['yearly_usd']:,.2f}/year"
    if partial:
        text += (f". {len(view['unpriced']) + len(view['unknown_resources'])} item(s) not priced yet, "
                 "so no saving is claimed")
    return text + "."


def as_markdown(view: dict) -> str:
    """The estimate as Markdown, for the CLI and the design page."""
    if view.get("status") == "unavailable":
        return f"Cost estimate unavailable: {view.get('reason')}\n"
    out = [summary(view), ""]
    for title, lines in (("Monthly", view["lines"]), ("One-time", view["one_time"])):
        if not lines:
            continue
        out.append(f"## {title}")
        for line in lines:
            p = line["price"] or {}
            out.append(f"- **{line['what']}** ({line['subject']}): ${line['usd']:,.4f}. {line['formula']}, at "
                       f"{p.get('rate')} (AWS SKU {p.get('sku')}, effective {p.get('effective_date', '')[:10]}, "
                       f"{p.get('source')}).")
            for i in line["inputs"]:
                s = i["source"]
                if s["kind"] == "confluence":
                    out.append(f"    - {i['name']} = {i['as_written']}: “{s['quote']}” ({s['page']} > {s['heading']})")
                elif s["kind"] == "terraform":
                    out.append(f"    - {i['name']} = {i['value']}: Terraform plan, {s['step']} {s['address']}.{s['attribute']}"
                               + (f" ({s['note']})" if s.get("note") else ""))
        out.append("")
    if view["free"]:
        out.append("## No charge")
        out += [f"- {f['subject']}: {f['reason']} ({f['url']})" for f in view["free"]]
        out.append("")
    if view["unpriced"] or view["unknown_resources"]:
        out.append("## Not priced yet")
        for u in view["unpriced"]:
            q = u.get("question") or {}
            out.append(f"- {u['subject']}: missing {u['missing']}" + (f", asked in {q['ticket']}" if q.get("ticket") else ""))
        out += [f"- {u['subject']}: {u['reason']}" for u in view["unknown_resources"]]
        out.append("")
    if view.get("onprem"):
        out.append("## Today on-prem")
        out += [f"- {i['label']}: ${i['usd_per_month']:,.2f}/month: “{i['source']['quote']}”" for i in view["onprem"]["items"]]
        out.append("")
    if view.get("notes"):
        out.append("## Notes")
        out += [f"- {n}" for n in view["notes"]]
    return "\n".join(out) + "\n"


def required_metric_names() -> dict[str, list[str]]:
    """For tests and docs: the figures each priced resource type needs."""
    return {t: [m.name for m in ms if m.required] for t, ms in RESOURCE_METRICS.items()}
