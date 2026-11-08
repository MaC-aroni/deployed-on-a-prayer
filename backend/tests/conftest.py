"""Stand-ins for GitHub, Jira, Confluence, the LLM and step execution, so runner logic is
tested without AWS. The real connectors are tested against real processes (test_executors.py)
and a local HTTP server that records requests (test_http_connectors.py)."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from mac.executors import StepFailed
from mac.integrations import Check, IntegrationError, RaisedTicket
from mac.runner import Runner
from mac.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SPEC = REPO_ROOT / "examples" / "claims-adjudication" / "migration.yaml"

IAC = "github.com/MaC-aroni/claims-service-iac"
DB = "github.com/MaC-aroni/claims-db-migrate"
SMOKE = "github.com/MaC-aroni/claims-smoke-tests"
MCP = "github.com/MaC-aroni/claims-mcp-server"

ALL_STEPS = ["preflight", "provision_storage", "provision_iam", "db_migrate", "deploy_mcp_server",
             "deploy_service", "grant_mcp_access", "smoke_test"]
MUTATING = [s for s in ALL_STEPS if s not in ("preflight", "smoke_test")]
TR, MGR, OWNER = "APPR-TR-001", "APPR-MGR-001", "APPR-MCP-001"


def demo_data() -> dict:
    return yaml.safe_load(DEMO_SPEC.read_text(encoding="utf-8"))


def write_spec(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class FakeGitHub:
    def __init__(self):
        self.shas = {IAC: "a" * 40, DB: "b" * 40, SMOKE: "c" * 40, MCP: "f" * 40}
        self.branches: dict[tuple[str, str], str] = {}  # (repo key, branch) -> sha
        self.failing: set[str] = set()

    def resolve(self, repo):
        if repo.ref != "main":
            return self.branches[(repo.key, repo.ref)]
        return self.shas[repo.key]

    def guardrails(self, repo, sha, rules):
        passed = repo.key not in self.failing and repo.ref == "main"
        return [Check("ci_green", passed, "fake")]


class FakeApprovals:
    """Jira: raises MAC-1, MAC-2, ... and answers status per approval id."""

    def __init__(self, default="approved"):
        self.default = default
        self.by_approval: dict[str, str] = {}  # approval id -> approved | pending | rejected
        self.raised = []  # TicketRequests, in order
        self.key_to_approval: dict[str, str] = {}
        self.down: str | None = None  # set to make every call fail

    def raise_ticket(self, request):
        if self.down:
            raise IntegrationError(self.down)
        self.raised.append(request)
        key = f"MAC-{len(self.raised)}"
        self.key_to_approval[key] = request.approval_id
        return RaisedTicket(key=key, url=f"https://example.atlassian.net/browse/{key}")

    def status(self, ticket):
        if self.down:
            raise IntegrationError(self.down)
        return self.by_approval.get(self.key_to_approval[ticket], self.default)

    def raised_ids(self):
        return [r.approval_id for r in self.raised]


class FakeDesignWriter:
    def __init__(self):
        self.calls: list[str] = []
        self.fail: str | None = None

    def write(self, facts):
        self.calls.append(facts)
        if self.fail:
            raise IntegrationError(self.fail)
        return "## Overview\nMoves the claims service to AWS.\n\n## Rollback plan\n- Undo everything."


class FakePages:

    def __init__(self):
        self.published = []  # (title, html, page_id passed in, parent_id)
        self._ids: dict[str, str] = {}

    def publish(self, title, storage_html, page_id, parent_id=None):
        self.published.append((title, storage_html, page_id, parent_id))
        page_id = page_id or self._ids.setdefault(title, f"page-{len(self._ids) + 1}")
        return page_id, f"https://example.atlassian.net/wiki/spaces/MAC/pages/{page_id.split('-')[-1]}"


class FakeExecutor:
    """Records (step, action, env) and fails where told to."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.fail: dict[tuple[str, str], str] = {}
        self.withhold: set[tuple[str, str]] = set()  # (step, output) not to produce

    def execute(self, ctx, action):
        self.calls.append((ctx.step.id, action, ctx.env_name))
        ctx.log(f"{action} {ctx.step.id}")
        if (ctx.step.id, action) in self.fail:
            raise StepFailed(self.fail[(ctx.step.id, action)])
        if action != "run":
            return {}
        return {o.name: f"https://{ctx.step.id.replace('_', '')}{ctx.env_name}.lambda-url.us-east-1.on.aws/"
                for o in ctx.step.outputs if (ctx.step.id, o.name) not in self.withhold}

    def actions(self, action):
        return [step for step, act, _ in self.calls if act == action]


class RecordingDiagnostician:
    def __init__(self):
        self.calls = []

    def diagnose(self, spec, failure, mode):
        self.calls.append((failure, mode))
        return f"diagnosed {failure.step_id} ({mode})"


@pytest.fixture
def spec_path(tmp_path):
    path = tmp_path / "migration.yaml"
    shutil.copy(DEMO_SPEC, path)
    return path


@pytest.fixture
def env(tmp_path):
    class Env:
        github = FakeGitHub()
        approvals = FakeApprovals()
        executor = FakeExecutor()
        diagnostician = RecordingDiagnostician()
        writer = FakeDesignWriter()
        pages = FakePages()
        store = Store(":memory:")
        runner = Runner(store, github, approvals, executor, tmp_path / "data", diagnostician,
                        design_writer=writer, pages=pages)

    return Env()


class FakeHTTP:
    """A local HTTP server: answers (method, path) from `routes` and records every request."""

    def __init__(self):
        self.routes: dict[tuple[str, str], tuple[int, object]] = {}
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                fake.requests.append({"method": self.command, "path": self.path,
                                      "headers": dict(self.headers),
                                      "body": json.loads(raw) if raw else None})
                status, body = fake.routes.get((self.command, self.path), (404, {"message": "Not Found"}))
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = _serve

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def route(self, method, path, body, status=200):
        self.routes[(method, path)] = (status, body)

    def close(self):
        self.server.shutdown()


@pytest.fixture
def http():
    server = FakeHTTP()
    yield server
    server.close()
