"""The cost estimate: hand-checked totals, a source on every input, partial when figures are missing."""

import json

import pytest

from mac.cost import as_markdown, estimate, summary
from mac.design import render_page
from mac.executors import resources_path
from mac.pricing import load_prices
from mac.spec import parse_spec
from mac.usage import DAYS_PER_MONTH, run_usage, usage_path

from .conftest import DEMO_SPEC
from .cost_fixtures import (CAPACITY, DEMO_RESOURCES, FACTS, MCPF, OWNERS, SECTIONS, SERVICE, SVC, TABLE,
                            ScriptedReader)

PRICES, _ = load_prices("us-east-1", live=False)
MONTH = DAYS_PER_MONTH
REQUESTS = 40000 * MONTH
INVOCATIONS = REQUESTS + 1440 * MONTH  # each claim once, plus a health check every minute
SVC_DURATION = {"subject": SVC, "metric": "avg_billed_duration_ms", "value": 60, "unit": "ms",
                "section": f"{CAPACITY}#lambda-measurements", "quote": "its average billed duration is 60 ms per invocation"}


def usage(tmp_path, with_duration=False):
    override = {CAPACITY: FACTS[CAPACITY] + [SVC_DURATION]} if with_duration else None
    return run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, ScriptedReader(override), tmp_path,
                     None, log=lambda _: None)


def line(view, line_id):
    return next(item for item in view["lines"] + view["one_time"] if item["id"] == line_id)


def test_every_line_matches_a_hand_calculation(tmp_path):
    view = estimate(DEMO_RESOURCES, usage(tmp_path, with_duration=True), PRICES)
    assert view["status"] == "complete" and view["unpriced"] == []
    assert line(view, f"{SVC}#requests")["quantity"] == pytest.approx(INVOCATIONS)
    assert line(view, f"{SVC}#requests")["usd"] == pytest.approx(INVOCATIONS * 0.20 / 1e6)
    gb_s = INVOCATIONS * 0.060 * 256 / 1024
    assert line(view, f"{MCPF}#duration")["quantity"] == pytest.approx(gb_s)
    assert line(view, f"{MCPF}#duration")["usd"] == pytest.approx(gb_s * 0.0000166667)
    log_gb = INVOCATIONS * 2 / 1024 ** 2
    assert line(view, f"{SVC}#logs-ingest")["usd"] == pytest.approx(log_gb * 0.50)
    assert line(view, f"{SVC}#logs-storage")["usd"] == pytest.approx(log_gb * 30 / MONTH * 0.03)
    # 1.2 KB items: 1 read unit, 2 write units each.
    assert line(view, f"{TABLE}#reads_per_request")["usd"] == pytest.approx(REQUESTS * 1 * 0.125 / 1e6)
    assert line(view, f"{TABLE}#writes_per_request")["usd"] == pytest.approx(REQUESTS * 2 * 0.625 / 1e6)
    storage = line(view, f"{TABLE}#storage")
    assert storage["quantity"] == pytest.approx(14_600_000 * (1.2 + 100 / 1024) / 1024 ** 2)
    assert storage["usd"] == 0  # under the 25 GB-month free tier in AWS's own price list
    assert line(view, f"{TABLE}#initial-load")["usd"] == pytest.approx(14_600_000 * 2 * 0.625 / 1e6)
    assert view["one_time_usd"] == pytest.approx(18.25)
    assert view["monthly_usd"] == pytest.approx(sum(item["usd"] for item in view["lines"]), abs=1e-3)


def test_onprem_today_and_the_savings(tmp_path):
    view = estimate(DEMO_RESOURCES, usage(tmp_path, with_duration=True), PRICES)
    assert view["onprem"]["monthly_usd"] == 1150 + 50400 / 12 + 590 + 420 + 1900 + 380
    oracle = next(i for i in view["onprem"]["items"] if i["label"] == "Oracle licence support")
    assert oracle["usd_per_month"] == 4200 and oracle["formula"] == "50,400.00 usd per year ÷ 12"
    assert view["savings"]["monthly_usd"] == pytest.approx(8640 - view["monthly_usd"], abs=0.01)
    assert view["savings"]["partial"] is False


def test_every_input_has_a_source(tmp_path):
    view = estimate(DEMO_RESOURCES, usage(tmp_path, with_duration=True), PRICES)
    kinds = set()
    for item in view["lines"] + view["one_time"]:
        assert item["price"]["sku"] and item["price"]["effective_date"] and item["price"]["offer_url"]
        for i in item["inputs"]:
            source = i["source"]
            kinds.add(source["kind"])
            if source["kind"] == "confluence":
                section = next(s for s in SECTIONS if s.id == source["section"])
                assert " ".join(source["quote"].replace("`", "").split()) in " ".join(section.text.replace("`", "").split())
            elif source["kind"] == "terraform":
                assert source["address"] and source["attribute"]
            else:
                assert source["kind"] == "aws-rule" and source["text"]
    assert kinds == {"confluence", "terraform", "aws-rule"}


def test_free_resources_say_why_and_unknown_types_are_listed(tmp_path):
    resources = {**DEMO_RESOURCES, "extra": [{"address": "aws_sqs_queue.q", "type": "aws_sqs_queue", "name": "q",
                                              "actions": ["create"], "attributes": {}}]}
    view = estimate(resources, usage(tmp_path, with_duration=True), PRICES)
    assert {f["resource_type"] for f in view["free"]} == {"aws_iam_role", "aws_iam_role_policy",
                                                          "aws_lambda_function_url", "aws_lambda_permission"}
    assert view["unknown_resources"][0]["subject"] == "extra/aws_sqs_queue.q"
    assert view["status"] == "partial"


def test_a_missing_figure_makes_it_partial_and_points_at_the_question(tmp_path):
    data = usage(tmp_path)
    data["questions"][f"{SVC}:avg_billed_duration_ms"].update(ticket="MAC-7", url="https://jira/MAC-7", status="asked")
    view = estimate(DEMO_RESOURCES, data, PRICES)
    assert view["status"] == "partial"
    assert view["unpriced"] == [{"subject": SVC, "missing": f"{SVC}:avg_billed_duration_ms",
                                 "question": {"ticket": "MAC-7", "url": "https://jira/MAC-7", "status": "asked"}}]
    assert f"{SVC}#duration" not in {item["id"] for item in view["lines"]}
    assert f"{SVC}#requests" in {item["id"] for item in view["lines"]}  # the rest is still priced
    assert "partial" in summary(view) and "no saving is claimed" in summary(view)
    assert "saving" not in summary(view).split("no saving")[0] and "asked in MAC-7" in as_markdown(view)


def test_provisioned_tables_are_not_guessed(tmp_path):
    resources = json.loads(json.dumps(DEMO_RESOURCES))
    resources["provision_storage"][0]["attributes"]["billing_mode"] = "PROVISIONED"
    view = estimate(resources, usage(tmp_path, with_duration=True), PRICES)
    assert any("only on-demand tables are priced" in u["missing"] for u in view["unpriced"])


def test_without_usage_figures_there_is_no_estimate():
    view = estimate(DEMO_RESOURCES, None, PRICES)
    assert view["status"] == "unavailable" and "usage" in view["reason"]


def test_the_digest_changes_only_when_a_figure_does(tmp_path):
    data = usage(tmp_path, with_duration=True)
    first, again = estimate(DEMO_RESOURCES, data, PRICES), estimate(DEMO_RESOURCES, data, PRICES)
    assert first["digest"] == again["digest"]
    data["facts"][0]["normalized"] *= 2
    assert estimate(DEMO_RESOURCES, data, PRICES)["digest"] != first["digest"]


def test_the_design_page_shows_the_estimate_with_its_sources(tmp_path):
    view = estimate(DEMO_RESOURCES, usage(tmp_path), PRICES)
    page = render_page(parse_spec(DEMO_SPEC.read_text(encoding="utf-8")), {}, "## Overview\nText.", "run1", cost=view)
    assert "Cost estimate (calculated by code" in page and "Not priced yet" in page and "Today on-prem" in page
    assert "decides an average of 40,000 claims per day" in page and "GU2ZS9HVP6QTQ7KE" in page
    assert "<script" not in page


# ---- In Build ------------------------------------------------------------------------------------

def _plans_write_resources(env):
    """The fake executor's plans save what the demo creates, as the real one does."""
    def write(step):
        def go():
            run = env.store.runs()[0]
            path = resources_path(env.runner.data_dir / "runs" / run.id, step)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(DEMO_RESOURCES[step]), encoding="utf-8")
        return go
    for step in DEMO_RESOURCES:
        env.executor.during[(step, "plan")] = write(step)


def test_build_reports_resources_and_cost_and_tells_tech_risk(env, spec_path):
    _plans_write_resources(env)
    run_usage(parse_spec(spec_path.read_text(encoding="utf-8")).metadata.name, SERVICE, DEMO_RESOURCES, SECTIONS,
              OWNERS, ScriptedReader(), env.runner.data_dir, None, log=lambda _: None)
    run = env.runner.build(spec_path)
    assert run.status == "succeeded", run.reason
    assert run.report["resources"]["provision_storage"][0]["address"] == "aws_dynamodb_table.claims"
    cost = run.report["cost"]
    assert cost["status"] == "partial" and cost["monthly_usd"] > 0 and cost["onprem"]["monthly_usd"] == 8640
    # The design page is republished with the estimate, and Tech Risk's ticket hears about it once.
    assert "Cost estimate (calculated by code" in env.pages.published[-1][1]
    told = [text for key, text in env.approvals.comments if "Estimated AWS cost" in text]
    assert len(told) == 1 and "design page" in told[0]
    env.runner.build(spec_path)
    assert len([t for _, t in env.approvals.comments if "Estimated AWS cost" in t]) == 1


def test_build_without_usage_still_passes_and_says_what_to_do(env, spec_path):
    run = env.runner.build(spec_path)
    assert run.status == "succeeded"
    assert run.report["cost"]["status"] == "unavailable" and "usage" in run.report["cost"]["reason"]


def test_a_pricing_failure_never_fails_the_build(env, spec_path):
    def broken(region):
        raise RuntimeError("price list exploded")
    env.runner.price_loader = broken
    usage_path(env.runner.data_dir, "x").parent.mkdir(parents=True, exist_ok=True)
    run = env.runner.build(spec_path)
    assert run.status == "succeeded"
    assert "price list exploded" in run.report["cost"]["reason"]
