"""Turn on instant Jira approvals: one command, no secret ever printed.

Usage: mise run mac-jira-webhook
  1. makes a new random webhook secret
  2. stores it on Fly as MAC_JIRA_WEBHOOK_SECRET (this restarts the app)
  3. registers (or updates) a Jira webhook "MaC approvals" that calls
     https://deployed-on-a-prayer.fly.dev/api/mac/jira/webhook?token=<secret>
     whenever an issue in the MAC project is updated.
Needs ATLASSIAN_* in backend/.env (an account that is a Jira admin) and the fly CLI logged in.
Running it again rotates the secret and updates the same webhook.
"""

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")
from mac.integrations import IntegrationError, _Atlassian  # noqa: E402

APP = os.environ.get("FLY_APP", "deployed-on-a-prayer")
BASE = os.environ.get("MAC_PUBLIC_URL", f"https://{APP}.fly.dev")
NAME = "MaC approvals"


def main() -> int:
    site, email, token = (os.environ.get(k) for k in ("ATLASSIAN_SITE", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"))
    if not (site and email and token):
        print("ATLASSIAN_SITE, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN must be set in backend/.env")
        return 1
    fly = shutil.which("fly") or shutil.which("flyctl")
    if not fly:
        print("the fly CLI isn't installed")
        return 1
    project = os.environ.get("JIRA_PROJECT", "MAC")
    secret = secrets.token_urlsafe(32)

    jira = _Atlassian(site, email, token)
    body = {
        "name": NAME,
        "url": f"{BASE}/api/mac/jira/webhook?token={secret}",
        "events": ["jira:issue_updated"],
        "filters": {"issue-related-events-section": f"project = {project}"},
        "excludeBody": False,
    }
    try:
        existing = [w for w in jira.call("/rest/webhooks/1.0/webhook") or [] if w.get("name") == NAME]
        if existing:
            path = existing[0]["self"].split(site.rstrip("/"), 1)[1]
            jira.call(path, method="PUT", body=body)
            print(f"updated the Jira webhook '{NAME}' (project {project}, issue updated)")
        else:
            jira.call("/rest/webhooks/1.0/webhook", method="POST", body=body)
            print(f"created the Jira webhook '{NAME}' (project {project}, issue updated)")
    except IntegrationError as e:
        print(f"Jira refused: {e}\nThe account needs Jira admin rights to manage webhooks.")
        return 1

    # Stdin, not argv, so the secret never shows up in a process list.
    result = subprocess.run([fly, "secrets", "import", "-a", APP], input=f"MAC_JIRA_WEBHOOK_SECRET={secret}\n",
                            text=True, capture_output=True)
    if result.returncode != 0:
        print("fly secrets import failed:\n" + result.stderr[-500:])
        return 1
    print(f"stored MAC_JIRA_WEBHOOK_SECRET on Fly ({APP}); the app restarts with it in about 30 seconds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
