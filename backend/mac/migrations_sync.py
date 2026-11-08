"""The migrations the console shows come from the mac-migrations repo.

`migrations/<name>/migration.yaml` on the repo's main branch is the reviewed, merged truth
(the Planner's PRs land there). This module mirrors those files into a folder on disk, which the
runner API then reads like any migrations directory. Nothing else writes that folder: a
manifest (`.sync.json`) remembers what was written so a migration deleted from the repo is
removed here too, and nothing that isn't ours is ever touched. Every problem (GitHub down, a
bad token) keeps the last good copy and is reported, never raised.
"""

import base64
import json
import logging
import shutil
import time
from pathlib import Path

from .integrations import IntegrationError, _request

log = logging.getLogger("mac.sync")

MANIFEST = ".sync.json"
GITHUB_API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _headers(token: str | None) -> dict[str, str]:
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_manifest(dest: Path) -> dict:
    path = dest / MANIFEST
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def file_url(repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{repo}/blob/{branch}/{path}"


def sync_migrations(repo: str, branch: str, dest: Path, token: str | None, api: str = GITHUB_API) -> dict:
    """One mirror pass. Returns the manifest written (or the previous one plus `error`)."""
    dest.mkdir(parents=True, exist_ok=True)
    previous = read_manifest(dest)
    headers = _headers(token)
    try:
        head = _request(f"{api}/repos/{repo}/git/ref/heads/{branch}", headers) or {}
        commit = head.get("object", {}).get("sha")
        if not commit:
            raise IntegrationError(f"{repo}@{branch}: no such branch")
        if commit == previous.get("commit") and all(
                (dest / folder / "migration.yaml").is_file() for folder in previous.get("files", {})):
            result = {**previous, "checked": time.time(), "error": None}
            _write_manifest(dest, result)
            return result
        tree = _request(f"{api}/repos/{repo}/git/trees/{commit}?recursive=1", headers) or {}
        wanted = {}
        for item in tree.get("tree", []):
            parts = item.get("path", "").split("/")
            if item.get("type") == "blob" and len(parts) == 3 and parts[0] == "migrations" and parts[2] == "migration.yaml":
                wanted[parts[1]] = item
        files = {}
        for folder, item in sorted(wanted.items()):
            known = previous.get("files", {}).get(folder)
            target = dest / folder / "migration.yaml"
            if known and known.get("blob") == item["sha"] and target.is_file():
                files[folder] = known
                continue
            blob = _request(f"{api}/repos/{repo}/git/blobs/{item['sha']}", headers) or {}
            text = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            files[folder] = {"blob": item["sha"], "path": item["path"]}
    except (IntegrationError, OSError, ValueError) as e:
        log.warning("migrations sync from %s failed: %s", repo, e)
        result = {**previous, "repo": repo, "branch": branch, "checked": time.time(), "error": str(e)[:300]}
        _write_manifest(dest, result)
        return result
    # Folders we wrote before that the repo no longer has.
    for folder in previous.get("files", {}):
        if folder not in files and (dest / folder).is_dir():
            shutil.rmtree(dest / folder, ignore_errors=True)
    result = {"repo": repo, "branch": branch, "commit": commit, "synced": time.time(), "checked": time.time(),
              "files": files, "error": None}
    _write_manifest(dest, result)
    log.info("migrations synced from %s@%s: %d file(s)", repo, commit[:7], len(files))
    return result


def _write_manifest(dest: Path, manifest: dict) -> None:
    try:
        (dest / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        pass
