"""Connections to GitHub, git and Jira. The runner depends only on the Protocols, so tests
can pass stand-ins; everything else here talks to the real services."""

import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .spec import Guardrails, RepoRef

ApprovalStatus = Literal["approved", "pending", "rejected"]


class IntegrationError(Exception):
    """A service couldn't be reached or answered with an error."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


class GitHub(Protocol):
    def resolve(self, repo: RepoRef) -> str:
        """The commit SHA the repo's ref currently points at."""

    def guardrails(self, repo: RepoRef, sha: str, rules: Guardrails) -> list[Check]:
        """Whether that commit is safe to run, per the spec's guardrails."""


class Workspace(Protocol):
    def checkout(self, repo: RepoRef, sha: str, dest: Path) -> None:
        """Put the repo's files at exactly that commit into dest (an empty directory)."""


class Approvals(Protocol):
    def status(self, ticket: str) -> ApprovalStatus: ...


def _request(url: str, headers: dict[str, str], *, method: str = "GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise IntegrationError(f"{method} {url} -> HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise IntegrationError(f"{method} {url} -> {e.reason}") from e


class GitHubAPI:
    """GitHub REST API. `token` needs read access to every repo the pipelines use."""

    OK_CONCLUSIONS = {"success", "neutral", "skipped"}

    def __init__(self, token: str | None, api: str = "https://api.github.com"):
        self.api = api.rstrip("/")
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str):
        return _request(f"{self.api}{path}", self.headers)

    def resolve(self, repo: RepoRef) -> str:
        ref = urllib.parse.quote(repo.ref, safe="")
        return self._get(f"/repos/{repo.slug}/commits/{ref}")["sha"]

    def guardrails(self, repo: RepoRef, sha: str, rules: Guardrails) -> list[Check]:
        checks = []
        if rules.require_ci_green:
            checks.append(self._ci_green(repo, sha))
        if rules.require_protected_branch:
            checks.append(self._protected(repo, sha))
        if rules.require_review:
            checks.append(self._reviewed(repo, sha))
        return checks

    def _ci_green(self, repo: RepoRef, sha: str) -> Check:
        runs = self._get(f"/repos/{repo.slug}/commits/{sha}/check-runs?per_page=100")["check_runs"]
        if not runs:
            return Check("ci_green", False, "no CI ran on this commit")
        unfinished = [r["name"] for r in runs if r["status"] != "completed"]
        if unfinished:
            return Check("ci_green", False, "still running: " + ", ".join(unfinished))
        failed = [f"{r['name']} ({r['conclusion']})" for r in runs if r["conclusion"] not in self.OK_CONCLUSIONS]
        if failed:
            return Check("ci_green", False, "failed: " + ", ".join(failed))
        return Check("ci_green", True, f"{len(runs)} checks passed")

    def _protected(self, repo: RepoRef, sha: str) -> Check:
        branch = self._get(f"/repos/{repo.slug}/branches/{urllib.parse.quote(repo.ref, safe='')}")
        if not branch.get("protected"):
            return Check("protected_branch", False, f"{repo.ref} is not a protected branch")
        compare = self._get(f"/repos/{repo.slug}/compare/{sha}...{urllib.parse.quote(repo.ref, safe='')}")
        if compare["status"] not in ("identical", "ahead"):
            return Check("protected_branch", False, f"commit is not on {repo.ref}")
        return Check("protected_branch", True, f"on protected branch {repo.ref}")

    def _reviewed(self, repo: RepoRef, sha: str) -> Check:
        pulls = self._get(f"/repos/{repo.slug}/commits/{sha}/pulls")
        merged = [p for p in pulls if p.get("merged_at") and p["base"]["ref"] == repo.ref]
        if not merged:
            return Check("reviewed", False, f"commit didn't reach {repo.ref} through a merged PR")
        for pull in merged:
            reviews = self._get(f"/repos/{repo.slug}/pulls/{pull['number']}/reviews?per_page=100")
            if any(r["state"] == "APPROVED" for r in reviews):
                return Check("reviewed", True, f"approved in PR #{pull['number']}")
        return Check("reviewed", False, f"PR #{merged[0]['number']} was merged without an approval")


class GitCheckout:
    """Fetches exactly one commit with git. Works for any commit GitHub can serve."""

    def __init__(self, token: str | None = None, host: str = "https://github.com"):
        self.host = host.rstrip("/")
        self.token = token

    def checkout(self, repo: RepoRef, sha: str, dest: Path) -> None:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        if self.token:
            # Passed through the environment, not argv, so it doesn't show up in process lists.
            basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraHeader",
                       GIT_CONFIG_VALUE_0=f"Authorization: Basic {basic}")
        url = f"{self.host}/{repo.slug}.git"
        for args in (["init", "-q"], ["fetch", "-q", "--depth", "1", url, sha],
                     ["checkout", "-q", "--detach", "FETCH_HEAD"]):
            result = subprocess.run(["git", *args], cwd=dest, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise IntegrationError(f"git {args[0]} {repo.slug}@{sha[:7]} failed: {result.stderr.strip()}")


class JiraApprovals:
    """Reads approval tickets from Jira Cloud. Status names decide the outcome."""

    def __init__(self, site: str, email: str, token: str,
                 approved=("Approved", "Done"), rejected=("Rejected", "Declined")):
        self.site = site.rstrip("/")
        basic = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {basic}", "Accept": "application/json"}
        self.approved = {s.lower() for s in approved}
        self.rejected = {s.lower() for s in rejected}

    def status(self, ticket: str) -> ApprovalStatus:
        issue = _request(f"{self.site}/rest/api/3/issue/{urllib.parse.quote(ticket)}?fields=status", self.headers)
        return classify_status(issue["fields"]["status"]["name"], self.approved, self.rejected)


def classify_status(name: str, approved: set[str], rejected: set[str]) -> ApprovalStatus:
    lowered = name.lower()
    if lowered in approved:
        return "approved"
    if lowered in rejected:
        return "rejected"
    return "pending"
