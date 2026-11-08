"""Shared by the cost tests: what the demo's Terraform plans create, and a scripted usage reader
that answers from the real knowledge pages, quoting them word for word."""

import json

from mac.knowledge import load_pages
from mac.sources import sections_from_pages

from .conftest import REPO_ROOT

PAGES = load_pages(REPO_ROOT / "demo-data" / "confluence")
SECTIONS = sections_from_pages(PAGES)
OWNERS = {p.id: p.owner for p in PAGES}
SERVICE = "ClaimsAdjudicationService"

SVC = "deploy_service/aws_lambda_function.service"
MCPF = "deploy_mcp_server/aws_lambda_function.mcp"
TABLE = "provision_storage/aws_dynamodb_table.claims"


def _res(address, rtype, label=None, **attributes):
    return {"address": address, "type": rtype, "name": label, "actions": ["create"], "attributes": attributes}


# As executors.plan_resources returns them for the demo repos.
DEMO_RESOURCES = {
    "provision_storage": [_res("aws_dynamodb_table.claims", "aws_dynamodb_table", "mac-claims-production-claims",
                               name="mac-claims-production-claims", billing_mode="PAY_PER_REQUEST")],
    "provision_iam": [_res("aws_iam_role.service", "aws_iam_role", "mac-claims-production-service"),
                      _res("aws_iam_role_policy.service", "aws_iam_role_policy", "claims-table")],
    "deploy_mcp_server": [_res("aws_lambda_function.mcp", "aws_lambda_function", "mac-claims-production-mcp",
                               function_name="mac-claims-production-mcp", memory_size=256, timeout=15),
                          _res("aws_lambda_function_url.mcp", "aws_lambda_function_url")],
    "deploy_service": [_res("aws_lambda_function.service", "aws_lambda_function", "mac-claims-production-service",
                            function_name="mac-claims-production-service", memory_size=256, timeout=15),
                       _res("aws_lambda_function_url.service", "aws_lambda_function_url")],
    "grant_mcp_access": [_res("aws_lambda_permission.invoke", "aws_lambda_permission")],
}

CAPACITY = "service-claims-capacity"
FINANCE = "finance-onprem-costs"


def _f(subject, metric, value, unit, heading, quote, label=None):
    fact = {"subject": subject, "metric": metric, "value": value, "unit": unit,
            "section": f"{heading}", "quote": quote}
    if label:
        fact["label"] = label
    return fact


# What a careful reader finds, page by page. Every quote is copied from the page.
FACTS = {
    CAPACITY: [
        _f("service", "requests_per_month", 40000, "per_day", f"{CAPACITY}#claims-volume",
           "decides an average of 40,000 claims per day"),
        _f(SVC, "invocations_per_request", 1, "count", f"{CAPACITY}#how-each-claim-uses-aws",
           "Each claim invokes the service function `mac-claims-<env>-service` 1 time"),
        _f(MCPF, "invocations_per_request", 1, "count", f"{CAPACITY}#how-each-claim-uses-aws",
           "which invokes the tool's function `mac-claims-<env>-mcp` 1 time"),
        _f(SVC, "other_invocations", 1, "per_minute", f"{CAPACITY}#how-each-claim-uses-aws",
           "Monitoring calls `GET /health` on each of the two functions 1 time per minute."),
        _f(MCPF, "other_invocations", 1, "per_minute", f"{CAPACITY}#how-each-claim-uses-aws",
           "Monitoring calls `GET /health` on each of the two functions 1 time per minute."),
        _f(TABLE, "reads_per_request", 1, "count", f"{CAPACITY}#how-each-claim-uses-aws",
           "Each claim reads its record from the claims table `mac-claims-<env>-claims` 1 time."),
        _f(TABLE, "writes_per_request", 1, "count", f"{CAPACITY}#how-each-claim-uses-aws",
           "Each claim writes to the claims table 1 time"),
        _f(TABLE, "items_stored", 14600000, "count", f"{CAPACITY}#claims-table-size",
           "The claims table keeps the last 12 months of claims: 14,600,000 claims."),
        _f(TABLE, "avg_item_kb", 1.2, "KB", f"{CAPACITY}#claims-table-size",
           "An average claim record is 1.2 KB in DynamoDB format"),
        _f(TABLE, "items_loaded_once", 14600000, "count", f"{CAPACITY}#claims-table-size",
           "The data migration loads all 14,600,000 claims into the table 1 time."),
        _f(MCPF, "avg_billed_duration_ms", 60, "ms", f"{CAPACITY}#lambda-measurements",
           "its average billed duration is 60 ms per invocation"),
        _f(SVC, "log_kb_per_invocation", 2, "KB", f"{CAPACITY}#logs",
           "Each invocation of either function writes about 2 KB of logs to CloudWatch Logs"),
        _f(MCPF, "log_kb_per_invocation", 2, "KB", f"{CAPACITY}#logs",
           "Each invocation of either function writes about 2 KB of logs to CloudWatch Logs"),
        _f("logs", "log_retention_days", 30, "days", f"{CAPACITY}#logs", "Log groups keep logs for 30 days."),
    ],
    FINANCE: [
        _f("onprem", "onprem_cost", 1150, "usd_per_month", f"{FINANCE}#what-it-costs-today",
           "Application VMs for the service (2 VMs, 8 vCPU and 32 GB each): $1,150 per month.", "Application VMs"),
        _f("onprem", "onprem_cost", 50400, "usd_per_year", f"{FINANCE}#what-it-costs-today",
           "Oracle Database 12c Enterprise Edition licence support for CLAIMS_DB: $50,400 per year.", "Oracle licence support"),
        _f("onprem", "onprem_cost", 590, "usd_per_month", f"{FINANCE}#what-it-costs-today",
           "SAN storage and backups for CLAIMS_DB: $590 per month.", "SAN storage and backups"),
        _f("onprem", "onprem_cost", 420, "usd_per_month", f"{FINANCE}#what-it-costs-today",
           "The service's share of data-centre space, power and cooling: $420 per month.", "Data-centre share"),
        _f("onprem", "onprem_cost", 1900, "usd_per_month", f"{FINANCE}#what-it-costs-today",
           "DBA and operations time: $1,900 per month", "DBA and operations time"),
        _f("onprem", "onprem_cost", 380, "usd_per_month", f"{FINANCE}#what-it-costs-today",
           "The Claims MCP tool's on-prem server, which moves to AWS in the same migration: $380 per month.",
           "Claims MCP tool server"),
    ],
}


def page_of(prompt: str) -> str | None:
    """Which page a usage prompt is about, from the section ids in it."""
    for line in prompt.splitlines():
        if line.startswith("(section id: "):
            return line[len("(section id: "):].split("#", 1)[0]
    return None


class ScriptedReader:
    """The LLM: answers each page from FACTS (or `override`), and records the pages it read."""

    def __init__(self, override: dict[str, list[dict]] | None = None, model: str = "scripted"):
        self.facts = {**FACTS, **(override or {})}
        self.read: list[str] = []
        self.model = model

    def complete(self, system, user, *, max_tokens=4096):
        page = page_of(user)
        self.read.append(page)
        return "```json\n" + json.dumps({"facts": self.facts.get(page, [])}) + "\n```"
