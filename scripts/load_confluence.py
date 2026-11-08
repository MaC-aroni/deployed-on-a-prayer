"""Load the demo Confluence pages from a folder of markdown files into a space.

Usage: python scripts/load_confluence.py [folder] [space-key]
Defaults: examples/claims-adjudication/confluence, CLAIMS.

Reads ATLASSIAN_SITE, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN (JIRA_* still works) from the
environment or backend/.env. Safe to re-run: a page with the same title is updated.
"""

import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOLDER = ROOT / "examples" / "claims-adjudication" / "confluence"


def load_env() -> dict:
    env = dict(os.environ)
    path = ROOT / "backend" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip())
    return env


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def to_storage(markdown: str) -> str:
    """Convert the small markdown subset the pages use (headings, bullets, lists, tables)."""
    out, lines, i = [], markdown.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 6)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            table = "<table><tbody><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
            for row in body:
                table += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
            out.append(table + "</tbody></table>")
        elif re.match(r"(- |\d+\. )", line):
            tag = "ul" if line.startswith("- ") else "ol"
            items = []
            while i < len(lines) and re.match(r"(- |\d+\. |\s+\S)", lines[i]):
                if re.match(r"(- |\d+\. )", lines[i]):
                    items.append(re.sub(r"^(- |\d+\. )", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
        else:
            para = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||- |\d+\. )", lines[i]):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return "".join(out)


class Confluence:
    def __init__(self, env: dict):
        def pick(name: str) -> str:
            return env.get(f"ATLASSIAN_{name}") or env[f"JIRA_{name}"]

        self.site = pick("SITE").rstrip("/")
        token = base64.b64encode(f"{pick('EMAIL')}:{pick('API_TOKEN')}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json",
                        "Content-Type": "application/json"}

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.site + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            raise SystemExit(f"{method} {path} failed: HTTP {err.code} {err.read()[:300].decode()}")


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FOLDER
    space = sys.argv[2] if len(sys.argv) > 2 else "CLAIMS"
    api = Confluence(load_env())
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        body = to_storage("\n".join(text.splitlines()[1:]))
        found = api.call("GET", f"/wiki/rest/api/content?spaceKey={space}&type=page&limit=1"
                                f"&title={urllib.parse.quote(title)}&expand=version")["results"]
        payload = {"type": "page", "title": title, "space": {"key": space},
                   "body": {"storage": {"value": body, "representation": "storage"}}}
        if found:
            payload["version"] = {"number": found[0]["version"]["number"] + 1}
            api.call("PUT", f"/wiki/rest/api/content/{found[0]['id']}", payload)
            print(f"updated  {title}")
        else:
            api.call("POST", "/wiki/rest/api/content", payload)
            print(f"created  {title}")


if __name__ == "__main__":
    main()
