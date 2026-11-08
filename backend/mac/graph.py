"""The knowledge graph: facts an LLM extracts from the knowledge base, each with the section it
came from. Code keeps only facts whose citations point at real sections of that page, and
merges duplicates across pages. Stored as JSON (MAC.md: a JSON graph, not Neo4j)."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .integrations import IntegrationError
from .llm import LLM, parse_json
from .sources import Catalog, Section, relevant

NODE_TYPES = ("service", "mcp_tool", "repo", "team", "approver", "approval_type", "policy",
              "standard", "aws_service", "datastore", "stage")
EDGE_TYPES = ("owns", "uses", "depends_on", "has_repo", "requires_approval_from", "approves",
              "applies_to", "approved_for", "deploys", "grants_access_to", "runs_before")

EXTRACT_PROMPT = f"""You build a knowledge graph from a company's internal engineering documentation.
From the sources given, extract every service, MCP tool, repository, team, approver, approval
type, policy, standard, approved AWS service, datastore and pipeline stage, and how they relate.

Return only JSON:
{{"nodes": [{{"type": ..., "name": ..., "description": ..., "sources": ["S1"]}}],
  "edges": [{{"from": <node name>, "to": <node name>, "type": ..., "detail": ..., "sources": ["S2"]}}]}}

Node types: {", ".join(NODE_TYPES)}.
Edge types: {", ".join(EDGE_TYPES)}.
Use names exactly as written in the sources (repositories as owner/name, approvers as written
in backticks). Every node and edge must cite the sources it comes from. Only state what the
sources say."""


@dataclass
class Node:
    type: str
    name: str
    description: str = ""
    sources: list[str] = field(default_factory=list)  # section ids

    @property
    def key(self) -> str:
        return f"{self.type}:{self.name.lower()}"


@dataclass
class Edge:
    source: str  # node key
    target: str
    type: str
    detail: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.key)
        if existing is None:
            self.nodes[node.key] = node
            return node
        existing.sources = sorted(set(existing.sources) | set(node.sources))
        if len(node.description) > len(existing.description):
            existing.description = node.description
        return existing

    def find(self, name: str) -> Node | None:
        lowered = name.lower()
        return next((n for n in self.nodes.values() if n.name.lower() == lowered), None)

    def names(self, node_type: str) -> set[str]:
        return {n.name for n in self.nodes.values() if n.type == node_type}

    def neighbors(self, key: str, depth: int = 1) -> "Graph":
        keep, frontier = {key}, {key}
        for _ in range(depth):
            frontier = {e.target if e.source in frontier else e.source
                        for e in self.edges if e.source in frontier or e.target in frontier} - keep
            keep |= frontier
        return Graph({k: n for k, n in self.nodes.items() if k in keep},
                     [e for e in self.edges if e.source in keep and e.target in keep])

    def facts(self) -> str:
        """The graph as cited lines, for prompts."""
        lines = [f"- {n.type} {n.name}: {n.description} (sources: {', '.join(n.sources)})"
                 for n in sorted(self.nodes.values(), key=lambda n: (n.type, n.name))]
        for e in self.edges:
            a, b = self.nodes[e.source].name, self.nodes[e.target].name
            lines.append(f"- {a} --{e.type}--> {b}" + (f": {e.detail}" if e.detail else "")
                         + f" (sources: {', '.join(e.sources)})")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({"nodes": [vars(n) for n in self.nodes.values()],
                           "edges": [{"from": e.source, "to": e.target, "type": e.type, "detail": e.detail,
                                      "sources": e.sources} for e in self.edges]}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Graph":
        data = json.loads(text)
        graph = cls()
        for n in data["nodes"]:
            graph.add_node(Node(**n))
        graph.edges = [Edge(e["from"], e["to"], e["type"], e.get("detail", ""), e["sources"]) for e in data["edges"]]
        return graph

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json(), encoding="utf-8")


def _cited(refs, catalog: Catalog) -> list[str] | None:
    """Section ids for ["S1", ...], or None if any reference isn't a real source."""
    ids = []
    for ref in refs or []:
        number = str(ref).strip().lstrip("[S").rstrip("]")
        section = catalog.get(int(number)) if number.isdigit() else None
        if section is None:
            return None
        ids.append(section.id)
    return ids or None


def extract(sections: list[Section], llm: LLM, log=print, workers: int | None = None,
            on_start=None) -> tuple[Graph, list[str]]:
    """One LLM call per page, several pages at a time (MAC_INGEST_WORKERS, default 6: a reasoning
    model takes a minute or more per page). Returns the graph and what was dropped, and why. The
    graph is assembled in page order whatever order the replies arrive in, so it's deterministic.
    `on_start(doc_id)` is called in the worker right before a page is sent to the model."""
    graph, dropped = Graph(), []
    pending_edges: list[tuple[dict, list[str]]] = []
    doc_ids = list(dict.fromkeys(s.doc_id for s in sections))
    catalogs = {doc_id: Catalog([s for s in sections if s.doc_id == doc_id]) for doc_id in doc_ids}
    workers = workers or int(os.environ.get("MAC_INGEST_WORKERS", "6"))

    def read(doc_id: str):
        if on_start is not None:
            on_start(doc_id)  # the console's Reader card turns "running" for this page
        try:
            return parse_json(llm.complete(EXTRACT_PROMPT, catalogs[doc_id].prompt_block(), max_tokens=4096))
        except ValueError as e:
            return f"{doc_id}: unreadable reply ({e})"
        except IntegrationError as e:
            # One page the model couldn't read mustn't lose the other pages' facts; the page is
            # reported as dropped and the next ingest picks it up.
            log(f"skipped {doc_id}: {e}")
            return f"{doc_id}: skipped, the model didn't answer ({str(e)[:160]})"

    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(doc_ids) or 1)), thread_name_prefix="mac-ingest")
    futures = {doc_id: pool.submit(read, doc_id) for doc_id in doc_ids}
    results = {}
    try:
        for doc_id in doc_ids:  # page order, so the graph is the same whatever finished first
            results[doc_id] = futures[doc_id].result()
            if isinstance(results[doc_id], dict):
                log(f"extracted {doc_id}")
    except BaseException:  # a Cancel (or a crash): pages not started yet are dropped, in-flight ones finish alone
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    for doc_id in doc_ids:
        data, catalog = results[doc_id], catalogs[doc_id]
        if not isinstance(data, dict):
            dropped.append(str(data) if isinstance(data, str) else f"{doc_id}: unreadable reply (not an object)")
            continue
        for raw in data.get("nodes", []):
            ids = _cited(raw.get("sources"), catalog)
            if raw.get("type") not in NODE_TYPES or not raw.get("name") or ids is None:
                dropped.append(f"{doc_id}: node {raw.get('name')!r} ({raw.get('type')}): bad type or citation")
                continue
            graph.add_node(Node(raw["type"], str(raw["name"]).strip(), str(raw.get("description", "")), ids))
        for raw in data.get("edges", []):
            ids = _cited(raw.get("sources"), catalog)
            if raw.get("type") not in EDGE_TYPES or ids is None:
                dropped.append(f"{doc_id}: edge {raw.get('from')!r}->{raw.get('to')!r}: bad type or citation")
                continue
            pending_edges.append((raw, ids))
    seen = set()
    for raw, ids in pending_edges:  # after every page, so edges can link nodes from other pages
        a, b = graph.find(str(raw.get("from", ""))), graph.find(str(raw.get("to", "")))
        if a is None or b is None:
            dropped.append(f"edge {raw.get('from')!r}->{raw.get('to')!r}: names no extracted node")
            continue
        key = (a.key, b.key, raw["type"])
        if key in seen:
            next(e for e in graph.edges if (e.source, e.target, e.type) == key).sources += ids
            continue
        seen.add(key)
        graph.edges.append(Edge(a.key, b.key, raw["type"], str(raw.get("detail", "")), ids))
    return graph, dropped


def context_for(graph: Graph, sections: list[Section], goal: str, k: int = 14) -> tuple[Graph, list[Section]]:
    """What a planner needs for a goal: the services it names and their 2-hop neighbourhood,
    plus the most relevant sections, including every section those facts cite."""
    hits = [n for n in graph.nodes.values() if n.name.lower() in goal.lower()]
    sub = Graph()
    for node in hits:
        part = graph.neighbors(node.key, depth=2)
        sub.nodes.update(part.nodes)
        sub.edges += [e for e in part.edges if e not in sub.edges]
    if not hits:
        sub = graph
    must = tuple({sid for n in sub.nodes.values() for sid in n.sources})
    return sub, relevant(sections, goal + " " + " ".join(n.name for n in sub.nodes.values()), k=k, must=must)
