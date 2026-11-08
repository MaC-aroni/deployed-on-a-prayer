"""The MaC assistant: answers questions from Jira, Confluence and MaC's own records.

The LLM decides which tools to call; the tools are code, and all of them only read. It can't
raise, move or comment on tickets, edit pages, or start runs: answering is all it does. Every
tool result is size-capped, the number of tool rounds is capped, and the answer is asked to link
the pages and tickets it used.
"""

import json
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .integrations import IntegrationError, _Atlassian
from .sources import storage_to_markdown
from .spec import SpecError, parse_spec
from .store import Store

MAX_ROUNDS = 6
MAX_CALLS = 12  # lookups per question, across rounds
RESULT_CHARS = 6000
FINAL = ("You have used your lookups. Answer the question now from what you found, citing it; "
         "say what you couldn't confirm. Don't promise further lookups.")

SYSTEM = """You are the MaC assistant for Prayerwell Health's migration team. MaC (Migration as Code)
plans cloud migrations from the company's Confluence knowledge base, raises the approvals as Jira
tickets, and runs pipelines (Build, Rehearse, Deploy) that undo everything if a step fails.

Answer using the tools: search Confluence and Jira, read pages and issues, and read MaC's runs and
approvals. Look things up rather than guessing, and say plainly when you couldn't find something.
For approvals (which tickets, who approves, their status) start with mac_status: it has them all.
A Jira search already gives each issue's status; read single issues only when you need their
description or comments. You have about 12 lookups per question, so be economical.
Cite what you used as Markdown links: the Confluence page or Jira issue URL the tool gave you.
You can only read. If asked to change something (approve, comment, run a pipeline), explain how a
person does it instead. Keep answers short and concrete; use lists for steps."""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_confluence",
        "description": "Full-text search of the company's Confluence knowledge base. Returns page titles, ids, URLs and excerpts.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_confluence_page",
        "description": "The text of one Confluence page, by the id search_confluence returned.",
        "parameters": {"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}}},
    {"type": "function", "function": {
        "name": "search_jira",
        "description": "Jira issues matching a JQL query, e.g. 'project = MAC AND status != Done ORDER BY updated DESC' or 'text ~ \"Tech Risk\"'.",
        "parameters": {"type": "object", "properties": {"jql": {"type": "string"}}, "required": ["jql"]}}},
    {"type": "function", "function": {
        "name": "read_jira_issue",
        "description": "One Jira issue with its status, assignee, description and comments, by key (e.g. MAC-6).",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "mac_status",
        "description": "MaC's own records for a migration (or all): latest Build/Rehearse/Deploy with status and reason, approvals with Jira tickets and status, and recorded service URLs.",
        "parameters": {"type": "object", "properties": {"migration": {"type": "string", "description": "migration name; omit for all"}}}}},
]


@dataclass
class ChatEvent:
    kind: str  # tool | answer | error
    data: dict


def _adf_text(node) -> str:
    """Plain text out of Jira's Atlassian Document Format."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        inner = "".join(_adf_text(c) for c in node.get("content", []))
        return inner + ("\n" if node.get("type") in ("paragraph", "heading", "listItem") else "")
    if isinstance(node, list):
        return "".join(_adf_text(n) for n in node)
    return ""


class AtlassianReader(_Atlassian):
    """Read-only Jira and Confluence calls for the assistant."""

    def __init__(self, site: str, email: str, token: str, space_key: str | None):
        super().__init__(site, email, token)
        self.space_key = space_key

    def search_confluence(self, query: str) -> list[dict]:
        cql = f'text ~ "{query.replace(chr(34), " ")}" AND type = page'
        if self.space_key:
            cql += f' AND space = "{self.space_key}"'
        reply = self.call(f"/wiki/rest/api/search?limit=8&cql={urllib.parse.quote(cql)}") or {}
        out = []
        for r in reply.get("results", []):
            content = r.get("content") or {}
            out.append({"id": content.get("id"), "title": content.get("title") or r.get("title"),
                        "url": self.site + "/wiki" + (r.get("url") or content.get("_links", {}).get("webui", "")),
                        "excerpt": (r.get("excerpt") or "").replace("@@@hl@@@", "").replace("@@@endhl@@@", "")[:300]})
        return out

    def read_confluence_page(self, page_id: str) -> dict:
        page = self.call(f"/wiki/api/v2/pages/{urllib.parse.quote(str(page_id))}?body-format=storage")
        body = ((page.get("body") or {}).get("storage") or {}).get("value", "")
        return {"id": page.get("id"), "title": page.get("title"),
                "url": self.site + "/wiki" + (page.get("_links") or {}).get("webui", ""),
                "text": storage_to_markdown(body)}

    def search_jira(self, jql: str) -> list[dict]:
        query = urllib.parse.urlencode({"jql": jql, "maxResults": 15, "fields": "summary,status,assignee,updated"})
        reply = self.call(f"/rest/api/3/search/jql?{query}") or {}
        return [{"key": i["key"], "url": f"{self.site}/browse/{i['key']}",
                 "summary": i["fields"].get("summary"), "status": (i["fields"].get("status") or {}).get("name"),
                 "assignee": ((i["fields"].get("assignee") or {}) or {}).get("displayName"),
                 "updated": i["fields"].get("updated")} for i in reply.get("issues", [])]

    def read_jira_issue(self, key: str) -> dict:
        fields = "summary,status,assignee,reporter,created,updated,description,comment,labels"
        issue = self.call(f"/rest/api/3/issue/{urllib.parse.quote(key)}?fields={fields}")
        f = issue["fields"]
        comments = [{"author": (c.get("author") or {}).get("displayName"), "created": c.get("created"),
                     "text": _adf_text(c.get("body")).strip()} for c in (f.get("comment") or {}).get("comments", [])[-10:]]
        return {"key": issue["key"], "url": f"{self.site}/browse/{issue['key']}", "summary": f.get("summary"),
                "status": (f.get("status") or {}).get("name"), "assignee": (f.get("assignee") or {}).get("displayName"),
                "labels": f.get("labels"), "created": f.get("created"), "updated": f.get("updated"),
                "description": _adf_text(f.get("description")).strip(), "comments": comments}


def mac_status(store: Store, migration: str | None) -> dict:
    runs = store.runs(migration, limit=60)
    names = sorted({r.migration for r in runs if r.mode in ("build", "rehearse", "deploy")})
    out = {}
    for name in names:
        mine = [r for r in runs if r.migration == name]
        latest = {}
        for r in mine:
            if r.mode in ("build", "rehearse", "deploy") and r.mode not in latest:
                latest[r.mode] = {"id": r.id, "status": r.status, "reason": r.reason, "failed_step": r.failed_step,
                                  "steps": r.steps, "outputs": r.outputs, "autofix": r.autofix or None}
        build = next((r for r in mine if r.mode == "build"), None)
        approvals = {}
        if build is not None:
            tickets = store.tickets(name, build.spec_digest)
            records = store.approval_records(name, build.spec_digest)
            try:
                declared = {a.id: a for a in parse_spec(build.spec_text, build.spec_path).approvals}
            except SpecError:
                declared = {}
            for aid in sorted(set(tickets) | set(records) | set(declared)):
                t, rec, a = tickets.get(aid), records.get(aid), declared.get(aid)
                approvals[aid] = {"approver": a.approver if a else None, "summary": a.summary if a else None,
                                  "after": list(a.after) if a else [], "ticket": t.key if t else None,
                                  "url": t.url if t else None, "status": rec.status if rec else None,
                                  "detail": rec.detail if rec else None}
        out[name] = {"latest_runs": latest, "approvals": approvals}
    return out


class Assistant:
    def __init__(self, llm, store: Store, atlassian: AtlassianReader | None):
        self.llm, self.store, self.atlassian = llm, store, atlassian

    def _call(self, name: str, args: dict) -> object:
        if name == "mac_status":
            return mac_status(self.store, args.get("migration") or None)
        if self.atlassian is None:
            return {"error": "Jira and Confluence aren't configured on this server"}
        fn: Callable | None = {"search_confluence": lambda: self.atlassian.search_confluence(str(args["query"])),
                               "read_confluence_page": lambda: self.atlassian.read_confluence_page(str(args["page_id"])),
                               "search_jira": lambda: self.atlassian.search_jira(str(args["jql"])),
                               "read_jira_issue": lambda: self.atlassian.read_jira_issue(str(args["key"]))}.get(name)
        if fn is None:
            return {"error": f"no tool named {name}"}
        return fn()

    def run(self, history: list[dict]) -> Iterator[ChatEvent]:
        """history: [{"role": "user"|"assistant", "content": str}], oldest first. Yields a `tool`
        event per lookup, then one `answer` (or `error`)."""
        messages = [{"role": "system", "content": SYSTEM}]
        messages += [{"role": m["role"], "content": str(m["content"])[:8000]}
                     for m in history[-20:] if m.get("role") in ("user", "assistant") and m.get("content")]
        used = 0
        for round_no in range(MAX_ROUNDS + 1):
            tools = TOOLS if round_no < MAX_ROUNDS and used < MAX_CALLS else None
            if tools is None:
                messages.append({"role": "user", "content": FINAL})
            try:
                message = self.llm.chat(messages, tools)
            except IntegrationError as e:
                yield ChatEvent("error", {"message": f"The LLM didn't answer: {e}"})
                return
            calls = (message.get("tool_calls") or []) if tools else []  # no tools offered: it must answer
            if not calls:
                yield ChatEvent("answer", {"content": (message.get("content") or "").strip()
                                           or "I couldn't put an answer together."})
                return
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for index, call in enumerate(calls):
                if used >= MAX_CALLS:  # every call needs a reply, but past the budget it isn't run
                    messages.append({"role": "tool", "tool_call_id": call.get("id", str(index)),
                                     "content": json.dumps({"error": "lookup budget used up; answer now"})})
                    continue
                used += 1
                name = call.get("function", {}).get("name", "")
                try:
                    args = json.loads(call.get("function", {}).get("arguments") or "{}")
                except ValueError:
                    args = {}
                try:
                    result = self._call(name, args)
                    ok = not (isinstance(result, dict) and "error" in result)
                except (IntegrationError, KeyError, TypeError, ValueError) as e:
                    result, ok = {"error": str(e)[:300]}, False
                text = json.dumps(result, default=str)[:RESULT_CHARS]
                yield ChatEvent("tool", {"name": name, "args": args, "ok": ok,
                                         "summary": _summary(name, result)})
                messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": text})


def _summary(name: str, result) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"failed: {result['error']}"[:200]
    if isinstance(result, list):
        return f"{len(result)} result(s)"
    if isinstance(result, dict):
        return result.get("title") or result.get("key") or f"{len(result)} migration(s)"
    return ""
