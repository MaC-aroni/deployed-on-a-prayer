"""The assistant: the model picks tools, code runs them (read-only), answers stream back."""

import json

from mac.assistant import MAX_CALLS, MAX_ROUNDS, Assistant, _adf_text

from .test_api import NAME, api  # noqa: F401 - the api fixture


class ToolLLM:
    """Replies in order: dicts are assistant messages; records what it was sent."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools=None, *, max_tokens=2048):
        self.sent.append((list(messages), tools))
        return self.replies.pop(0) if self.replies else {"content": "done"}


def call(name, **args):
    return {"content": None, "tool_calls": [{"id": f"c-{name}", "type": "function",
                                              "function": {"name": name, "arguments": json.dumps(args)}}]}


class FakeAtlassian:
    def __init__(self):
        self.calls = []

    def search_jira(self, jql):
        self.calls.append(("jira", jql))
        return [{"key": "MAC-6", "url": "https://x/browse/MAC-6", "summary": "Tech Risk", "status": "To Do"}]

    def read_jira_issue(self, key):
        self.calls.append(("issue", key))
        return {"key": key, "status": "To Do", "comments": []}

    def search_confluence(self, query):
        self.calls.append(("conf", query))
        return [{"id": "1", "title": "Data migration", "url": "https://x/wiki/1", "excerpt": "DD-MON-YY"}]

    def read_confluence_page(self, page_id):
        return {"id": page_id, "title": "Data migration", "text": "Convert to ISO 8601."}


def run_chat(assistant, question):
    return list(assistant.run([{"role": "user", "content": question}]))


def test_tools_run_and_the_answer_comes_back(env):
    llm = ToolLLM(call("search_jira", jql="project = MAC"), call("read_jira_issue", key="MAC-6"),
                  {"content": "MAC-6 is waiting on Tech Risk ([MAC-6](https://x/browse/MAC-6))."})
    atl = FakeAtlassian()
    events = run_chat(Assistant(llm, env.store, atl), "What is Tech Risk waiting on?")
    assert [e.kind for e in events] == ["tool", "tool", "answer"]
    assert events[0].data == {"name": "search_jira", "args": {"jql": "project = MAC"}, "ok": True, "summary": "1 result(s)"}
    assert "MAC-6" in events[-1].data["content"] and atl.calls == [("jira", "project = MAC"), ("issue", "MAC-6")]
    roles = [m["role"] for m in llm.sent[-1][0]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool"]


def test_mac_status_reads_the_runs(env, spec_path):
    env.runner.build(spec_path)
    llm = ToolLLM(call("mac_status"), {"content": "The latest Build passed."})
    events = run_chat(Assistant(llm, env.store, None), "How is the migration doing?")
    tool_result = json.loads(llm.sent[-1][0][-1]["content"])
    assert tool_result[NAME]["latest_runs"]["build"]["status"] == "succeeded"
    assert events[-1].kind == "answer"


def test_unknown_tools_and_missing_atlassian_are_reported_not_fatal(env):
    llm = ToolLLM(call("delete_everything"), call("search_jira", jql="x"), {"content": "I can't do that."})
    events = run_chat(Assistant(llm, env.store, None), "delete it all")
    assert [e.data["ok"] for e in events if e.kind == "tool"] == [False, False]
    assert events[-1].kind == "answer"


def test_tool_rounds_are_capped(env):
    llm = ToolLLM(*[call("mac_status")] * (MAX_ROUNDS + 3))
    events = run_chat(Assistant(llm, env.store, None), "loop forever")
    assert sum(e.kind == "tool" for e in events) == MAX_ROUNDS
    assert events[-1].kind == "answer"
    assert llm.sent[-1][1] is None  # the last round offers no tools, so it must answer
    assert "Answer the question now" in llm.sent[-1][0][-1]["content"]


def test_total_lookups_are_capped_even_in_one_round(env):
    many = {"content": None, "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
        "name": "mac_status", "arguments": "{}"}} for i in range(20)]}
    llm = ToolLLM(many, {"content": "Here is what I found."})
    events = run_chat(Assistant(llm, env.store, None), "read everything")
    assert sum(e.kind == "tool" for e in events) == MAX_CALLS
    tool_msgs = [m for m in llm.sent[-1][0] if m["role"] == "tool"]
    assert len(tool_msgs) == 20  # every call answered, the extra ones with "budget used up"
    assert events[-1].data["content"] == "Here is what I found."


def test_mac_status_names_the_approvers(env, spec_path):
    from mac.assistant import mac_status
    env.runner.build(spec_path)
    approvals = mac_status(env.store, None)[NAME]["approvals"]
    assert approvals["APPR-MCP-001"]["approver"] == "claims-mcp-team" and approvals["APPR-MCP-001"]["after"] == ["APPR-MGR-001"]


def test_adf_to_text():
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Approve "},
                                                                      {"type": "text", "text": "this."}]}]}
    assert _adf_text(doc).strip() == "Approve this."


def test_chat_endpoint_streams_events(api):  # noqa: F811
    client, env, state = api
    llm = ToolLLM(call("mac_status"), {"content": "All quiet."})
    state.assistant = lambda store: Assistant(llm, store, None)
    resp = client.post("/api/mac/chat", json={"messages": [{"role": "user", "content": "status?"}]})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    kinds = [line.split(": ", 1)[1] for line in resp.text.splitlines() if line.startswith("event: ")]
    assert kinds == ["tool", "answer", "end"] and "All quiet." in resp.text
    assert client.post("/api/mac/chat", json={"messages": []}).status_code == 422


def test_chat_needs_an_llm(api, monkeypatch):  # noqa: F811
    client, _, state = api
    state.assistant = None
    monkeypatch.delenv("MAC_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    resp = client.post("/api/mac/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 503
