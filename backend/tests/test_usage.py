"""The usage reader: only figures the pages state, checked by code; missing ones are asked, once."""

from mac.usage import (DAYS_PER_MONTH, check_fact, load_usage, missing_metrics, run_usage, subjects_for)

from .conftest import FakeApprovals
from .cost_fixtures import (CAPACITY, DEMO_RESOURCES, FACTS, MCPF, OWNERS, SECTIONS, SERVICE, SVC, TABLE,
                            ScriptedReader)

SUBJECTS = {s.id: s for s in subjects_for(DEMO_RESOURCES, SERVICE)}
BY_SECTION = {s.id: s for s in SECTIONS}


def fact(**changes):
    base = dict(FACTS[CAPACITY][0])
    base.update(changes)
    return base


def test_subjects_follow_what_terraform_creates():
    assert set(SUBJECTS) == {"service", SVC, MCPF, TABLE, "logs", "onprem"}
    assert [m.name for m in SUBJECTS[TABLE].metrics][:2] == ["reads_per_request", "writes_per_request"]


def test_a_true_fact_is_kept_and_converted_by_code():
    kept, why = check_fact(fact(), SUBJECTS, BY_SECTION)
    assert why is None
    assert kept["normalized"] == 40000 * DAYS_PER_MONTH and kept["base_unit"] == "per month"
    assert kept["page"] == "Services: ClaimsAdjudicationService Capacity and Usage"


def test_invented_or_misquoted_facts_are_rejected():
    cases = {
        "isn't a number the quote states": fact(value=45000),
        "the quote isn't in section": fact(quote="decides an average of 50,000 claims per day"),
        "isn't a section of the page": fact(section="service-claims-capacity#nowhere"),
        "unit 'per_week'": fact(unit="per_week"),
        "unknown subject": fact(subject="aws_s3_bucket.x"),
        "has no figure": fact(metric="cpu_cores"),
        "isn't a number": fact(value="lots"),
    }
    for expected, raw in cases.items():
        kept, why = check_fact(raw, SUBJECTS, BY_SECTION)
        assert kept is None and expected in why, (expected, why)


def test_onprem_costs_need_a_label():
    raw = dict(FACTS["finance-onprem-costs"][0])
    raw.pop("label")
    kept, why = check_fact(raw, SUBJECTS, BY_SECTION)
    assert kept is None and "label" in why


def test_reader_keeps_checked_facts_and_asks_for_the_missing_duration(tmp_path):
    jira = FakeApprovals()
    reader = ScriptedReader(override={CAPACITY: FACTS[CAPACITY] + [fact(value=99)]})  # one bad fact
    usage = run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, reader, tmp_path, jira, log=lambda _: None)
    assert CAPACITY in reader.read and "finance-onprem-costs" in reader.read
    assert len(usage["facts"]) == len(FACTS[CAPACITY]) + len(FACTS["finance-onprem-costs"])
    assert len(usage["rejected"]) == 1
    # The service has never run on Lambda, so its duration is the one figure nobody wrote down.
    assert [(m["subject"], m["metric"]) for m in usage["missing"]] == [(SVC, "avg_billed_duration_ms")]
    question = jira.raised[0]
    assert question.approver == "claims-platform" and "never guesses" in " ".join(question.paragraphs)
    assert usage["questions"][f"{SVC}:avg_billed_duration_ms"]["ticket"] == "MAC-1"
    assert load_usage(tmp_path, "claims")["facts"] == usage["facts"]


def test_reading_again_never_asks_twice_and_closes_answered_questions(tmp_path):
    jira = FakeApprovals()
    run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, ScriptedReader(), tmp_path, jira, log=lambda _: None)
    run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, ScriptedReader(), tmp_path, jira, log=lambda _: None)
    assert len(jira.raised) == 1
    answered = ScriptedReader(override={CAPACITY: FACTS[CAPACITY] + [
        fact(subject=SVC, metric="avg_billed_duration_ms", value=60, unit="ms",
             section=f"{CAPACITY}#lambda-measurements", quote="its average billed duration is 60 ms per invocation")]})
    usage = run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, answered, tmp_path, jira, log=lambda _: None)
    assert usage["missing"] == [] and len(jira.raised) == 1
    assert usage["questions"][f"{SVC}:avg_billed_duration_ms"]["open"] is False


def test_without_jira_the_question_is_recorded_not_raised(tmp_path):
    usage = run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, ScriptedReader(), tmp_path, None,
                      log=lambda _: None)
    assert usage["missing"][0]["question"]["status"] == "not raised: Jira isn't configured"


def test_an_unusable_reply_loses_one_page_not_the_run(tmp_path):
    class Broken(ScriptedReader):
        def complete(self, system, user, *, max_tokens=4096):
            reply = super().complete(system, user, max_tokens=max_tokens)
            return "not json" if self.read[-1] == "finance-onprem-costs" else reply
    usage = run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, Broken(), tmp_path, None, log=lambda _: None)
    assert not any(f["subject"] == "onprem" for f in usage["facts"])
    assert any(f["subject"] == "service" for f in usage["facts"])


def test_the_knowledge_base_gives_every_figure_but_the_deliberate_gap():
    """test_knowledge's rule for cost: the capacity page must keep agreeing with the calculator."""
    kept = [check_fact(f, SUBJECTS, BY_SECTION)[0] for page in FACTS.values() for f in page]
    assert all(kept), [f for f, k in zip([f for p in FACTS.values() for f in p], kept) if not k]
    gaps = [(s.id, m.name) for s, m in missing_metrics(list(SUBJECTS.values()), kept)]
    assert gaps == [(SVC, "avg_billed_duration_ms")]


def test_a_cut_off_reply_is_asked_again(tmp_path):
    class CutOffOnce(ScriptedReader):
        def complete(self, system, user, *, max_tokens=4096):
            reply = super().complete(system, user, max_tokens=max_tokens)
            if self.read.count(CAPACITY) == 1 and self.read[-1] == CAPACITY:
                return reply[:200]  # the JSON stops mid-string, as a too-small token budget does
            return reply
    llm = CutOffOnce()
    usage = run_usage("claims", SERVICE, DEMO_RESOURCES, SECTIONS, OWNERS, llm, tmp_path, None, log=lambda _: None)
    assert llm.read.count(CAPACITY) == 2
    assert any(f["subject"] == "service" for f in usage["facts"])


def test_only_raised_tickets_count_as_asked():
    from mac.usage import asked_note
    assert asked_note([]) == ""
    assert asked_note([{"question": {"ticket": "MAC-1"}}]) == " (asked in Jira)"
    assert asked_note([{"question": {"ticket": None, "status": "not raised"}}]) == " (not raised in Jira)"
    assert asked_note([{"question": {"ticket": "MAC-1"}}, {"question": None}]) == " (1 asked in Jira, 1 not raised)"
