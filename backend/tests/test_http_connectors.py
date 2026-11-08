"""The real Jira, Confluence, NVIDIA and GitHub connectors, against a local HTTP server that
records every request: the exact calls MaC makes, without needing the real accounts."""

import base64

import pytest

from mac.design import NIMDesignWriter
from mac.integrations import ConfluencePages, GitHubAPI, IntegrationError, JiraApprovals, TicketRequest
from mac.spec import Guardrails, RepoRef

REQUEST = TicketRequest(
    approval_id="APPR-TR-001", summary="Tech Risk: move it", paragraphs=["Why we do it.", "", "Second."],
    approver="tech-risk", labels=["mac", "claims adjudication", "APPR-TR-001"],
    links=[("Design page", "https://site/wiki/p/1")])


def basic(email, token):
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


# ---- Jira -----------------------------------------------------------------------------------

def test_jira_raises_a_ticket(http):
    http.route("POST", "/rest/api/3/issue", {"id": "10001", "key": "MAC-7"}, status=201)
    jira = JiraApprovals(http.url, "me@x.com", "tok", project="MAC", assignees={"tech-risk": "acct-123"})
    raised = jira.raise_ticket(REQUEST)
    assert (raised.key, raised.url) == ("MAC-7", f"{http.url}/browse/MAC-7")
    [req] = http.requests
    assert req["headers"]["Authorization"] == basic("me@x.com", "tok")
    fields = req["body"]["fields"]
    assert fields["project"] == {"key": "MAC"} and fields["issuetype"] == {"name": "Task"}
    assert fields["summary"] == "Tech Risk: move it" and fields["assignee"] == {"accountId": "acct-123"}
    assert fields["labels"] == ["mac", "claims-adjudication", "APPR-TR-001"]  # no spaces in labels
    doc = fields["description"]
    assert doc["type"] == "doc" and doc["version"] == 1
    texts = [p["content"][0]["text"] for p in doc["content"]]
    assert texts == ["Why we do it.", "Second.", "Design page: "]  # empty paragraphs dropped
    link = doc["content"][-1]["content"][1]
    assert link["marks"] == [{"type": "link", "attrs": {"href": "https://site/wiki/p/1"}}]


def test_jira_without_an_assignee_mapping_leaves_it_unassigned(http):
    http.route("POST", "/rest/api/3/issue", {"key": "MAC-8"}, status=201)
    JiraApprovals(http.url, "e", "t").raise_ticket(REQUEST)
    assert "assignee" not in http.requests[0]["body"]["fields"]


@pytest.mark.parametrize("name,expected", [("Approved", "approved"), ("Done", "approved"),
                                           ("Rejected", "rejected"), ("Won't Do", "rejected"),
                                           ("To Do", "pending"), ("In Review", "pending")])
def test_jira_status_by_name(http, name, expected):
    http.route("GET", "/rest/api/3/issue/MAC-7?fields=status", {"fields": {"status": {"name": name}}})
    assert JiraApprovals(http.url, "e", "t").status("MAC-7") == expected


def test_jira_errors_carry_the_status_code(http):
    http.route("POST", "/rest/api/3/issue", {"errors": {"project": "valid project is required"}}, status=400)
    with pytest.raises(IntegrationError, match="HTTP 400.*valid project") as e:
        JiraApprovals(http.url, "e", "t").raise_ticket(REQUEST)
    assert e.value.status == 400


# ---- Confluence ----------------------------------------------------------------------------------

def test_confluence_creates_a_new_page(http):
    http.route("GET", "/wiki/api/v2/spaces?keys=MAC", {"results": [{"id": "98", "key": "MAC"}]})
    http.route("GET", "/wiki/api/v2/pages?space-id=98&title=My+page", {"results": []})
    http.route("POST", "/wiki/api/v2/pages", {"id": "555", "_links": {"webui": "/spaces/MAC/pages/555/My+page"}})
    page_id, url = ConfluencePages(http.url, "e", "t", "MAC").publish("My page", "<p>hi</p>", None)
    assert (page_id, url) == ("555", f"{http.url}/wiki/spaces/MAC/pages/555/My+page")
    body = http.requests[-1]["body"]
    assert body == {"spaceId": "98", "status": "current", "title": "My page",
                    "body": {"representation": "storage", "value": "<p>hi</p>"}}


def test_confluence_updates_a_known_page_with_the_next_version(http):
    http.route("GET", "/wiki/api/v2/pages/555", {"id": "555", "version": {"number": 3}})
    http.route("PUT", "/wiki/api/v2/pages/555", {"id": "555", "_links": {"webui": "/spaces/MAC/pages/555"}})
    ConfluencePages(http.url, "e", "t", "MAC").publish("My page", "<p>v4</p>", "555")
    put = http.requests[-1]
    assert put["method"] == "PUT" and put["body"]["version"]["number"] == 4
    assert put["body"]["body"]["value"] == "<p>v4</p>"
    assert not any(r["path"].startswith("/wiki/api/v2/spaces") for r in http.requests)


def test_confluence_reuses_a_page_with_the_same_title_if_our_record_is_lost(http):
    http.route("GET", "/wiki/api/v2/spaces?keys=MAC", {"results": [{"id": "98"}]})
    http.route("GET", "/wiki/api/v2/pages?space-id=98&title=My+page", {"results": [{"id": "555"}]})
    http.route("GET", "/wiki/api/v2/pages/555", {"id": "555", "version": {"number": 1}})
    http.route("PUT", "/wiki/api/v2/pages/555", {"id": "555", "_links": {"webui": "/x"}})
    page_id, _ = ConfluencePages(http.url, "e", "t", "MAC").publish("My page", "<p/>", None)
    assert page_id == "555" and not any(r["method"] == "POST" for r in http.requests)


def test_confluence_missing_space_is_a_clear_error(http):
    http.route("GET", "/wiki/api/v2/spaces?keys=NOPE", {"results": []})
    with pytest.raises(IntegrationError, match="space 'NOPE' not found"):
        ConfluencePages(http.url, "e", "t", "NOPE").publish("t", "<p/>", None)


# ---- The LLM (NVIDIA NIM) --------------------------------------------------------------------------

def test_nim_request_and_reply(http):
    http.route("POST", "/v1/chat/completions",
               {"choices": [{"message": {"content": "<think>planning...</think>\n## Overview\nText"}}]})
    writer = NIMDesignWriter("nv-key", "nvidia/nemotron-3-ultra-550b-a55b", base_url=f"{http.url}/v1")
    assert writer.write("the facts") == "## Overview\nText"  # reasoning removed
    req = http.requests[0]
    assert req["headers"]["Authorization"] == "Bearer nv-key"
    assert req["body"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    system, user = req["body"]["messages"]
    assert system["role"] == "system" and "Rollback plan" in system["content"]
    assert user["role"] == "user" and user["content"].endswith("the facts")


@pytest.mark.parametrize("reply", [{"choices": []}, {"choices": [{"message": {"content": "  "}}]}, {}])
def test_nim_bad_replies_are_integration_errors(http, reply):
    http.route("POST", "/v1/chat/completions", reply)
    with pytest.raises(IntegrationError):
        NIMDesignWriter("k", "m", base_url=f"{http.url}/v1").write("x")


# ---- GitHub guardrails ------------------------------------------------------------------------------

REPO = RepoRef(owner="o", name="r")
SHA = "a" * 40


def github(http, check_runs, protected=True, compare="identical", pulls=None, reviews=None):
    http.route("GET", f"/repos/o/r/commits/{SHA}/check-runs?per_page=100", {"check_runs": check_runs})
    http.route("GET", "/repos/o/r/branches/main", {"protected": protected})
    http.route("GET", f"/repos/o/r/compare/{SHA}...main", {"status": compare})
    http.route("GET", f"/repos/o/r/commits/{SHA}/pulls",
               pulls if pulls is not None else [{"number": 5, "merged_at": "2026-11-07", "base": {"ref": "main"}}])
    http.route("GET", "/repos/o/r/pulls/5/reviews?per_page=100",
               reviews if reviews is not None else [{"state": "APPROVED"}])
    return {c.name: c for c in GitHubAPI("gh-token", api=http.url).guardrails(REPO, SHA, Guardrails())}


def test_all_guardrails_pass(http):
    checks = github(http, [{"name": "test", "status": "completed", "conclusion": "success"},
                           {"name": "lint", "status": "completed", "conclusion": "skipped"}])
    assert all(c.passed for c in checks.values())
    assert checks["reviewed"].detail == "approved in PR #5"
    assert http.requests[0]["headers"]["Authorization"] == "Bearer gh-token"


@pytest.mark.parametrize("runs,detail", [
    ([], "no CI ran"),
    ([{"name": "test", "status": "in_progress", "conclusion": None}], "still running: test"),
    ([{"name": "test", "status": "completed", "conclusion": "failure"}], "failed: test (failure)"),
])
def test_ci_not_green(http, runs, detail):
    checks = github(http, runs)
    assert not checks["ci_green"].passed and detail in checks["ci_green"].detail


def test_unprotected_branch_or_commit_not_on_it(http):
    ok_runs = [{"name": "t", "status": "completed", "conclusion": "success"}]
    assert "not a protected branch" in github(http, ok_runs, protected=False)["protected_branch"].detail
    assert "not on main" in github(http, ok_runs, compare="diverged")["protected_branch"].detail


def test_direct_push_or_unapproved_merge_fails_review(http):
    ok_runs = [{"name": "t", "status": "completed", "conclusion": "success"}]
    assert "through a merged PR" in github(http, ok_runs, pulls=[])["reviewed"].detail
    assert "without an approval" in github(http, ok_runs, reviews=[{"state": "COMMENTED"}])["reviewed"].detail


def test_resolve_and_not_found(http):
    http.route("GET", "/repos/o/r/commits/main", {"sha": SHA})
    assert GitHubAPI(None, api=http.url).resolve(REPO) == SHA
    with pytest.raises(IntegrationError, match="repo or branch not found"):
        GitHubAPI(None, api=http.url).resolve(RepoRef(owner="o", name="missing"))


def test_slow_responses_become_integration_errors(http):
    import time as _time

    original = http.server.RequestHandlerClass.do_POST

    def slow(handler):
        _time.sleep(1.5)
        original(handler)

    http.server.RequestHandlerClass.do_POST = slow
    http.route("POST", "/v1/chat/completions", {"choices": [{"message": {"content": "x"}}]})
    from mac.llm import NIMChat
    with pytest.raises(IntegrationError, match="timed out"):
        NIMChat("k", "m", base_url=f"{http.url}/v1", timeout=1).complete("s", "u")
    assert NIMChat("k", "m", base_url=f"{http.url}/v1", timeout=5).complete("s", "u") == "x"  # timeout is honoured


def test_reads_retry_transient_failures_but_writes_never_do(monkeypatch):
    from mac import integrations

    calls = []

    def flaky(url, headers, *, method="GET", body=None, timeout=30):
        calls.append(method)
        if len(calls) < 3:
            raise integrations.IntegrationError(f"{method} {url} -> HTTP 504: gateway", status=504)
        return {"ok": True}

    monkeypatch.setattr(integrations, "_request_once", flaky)
    monkeypatch.setattr(integrations, "RETRY_DELAY", 0)
    assert integrations._request("https://x/y", {}) == {"ok": True}
    assert calls == ["GET", "GET", "GET"]

    calls.clear()
    with pytest.raises(integrations.IntegrationError):
        integrations._request("https://x/y", {}, method="POST", body={})
    assert calls == ["POST"]  # a repeated POST could raise a second ticket

    calls.clear()
    monkeypatch.setattr(integrations, "_request_once",
                        lambda *a, **k: (_ for _ in ()).throw(integrations.IntegrationError("GET x -> HTTP 404: nope", status=404)))
    with pytest.raises(integrations.IntegrationError):
        integrations._request("https://x/y", {})  # a 404 is an answer, not a flake: no retry


def test_llm_posts_are_retried_on_timeouts(monkeypatch):
    from mac import integrations
    from mac.llm import NIMChat

    calls = []

    def slow_then_ok(url, headers, *, method="GET", body=None, timeout=30):
        calls.append(timeout)
        if len(calls) == 1:
            raise integrations.IntegrationError(f"{method} {url} -> TimeoutError: The read operation timed out")
        return {"choices": [{"message": {"content": "hello"}}]}

    monkeypatch.setattr(integrations, "_request_once", slow_then_ok)
    monkeypatch.setattr(integrations, "RETRY_DELAY", 0)
    monkeypatch.delenv("MAC_LLM_TIMEOUT", raising=False)
    assert NIMChat("k").complete("s", "u") == "hello"
    assert calls == [300, 300]
