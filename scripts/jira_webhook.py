"""Turn on instant Jira approvals: one command, no secret ever printed.

Usage: mise run mac-jira-webhook
  1. makes a new random webhook secret
  2. stores it on Fly as MAC_JIRA_WEBHOOK_SECRET (this restarts the app)
  3. registers (or updates) a Jira webhook "MaC approvals" that calls
     https://deployed-on-a-prayer.fly.dev/api/mac/jira/webhook?token=<secret>
     whenever an issue in the MAC project is updated.
Needs ATLASSIAN_* in backend/.env (an account that is a Jira admin) and the fly CLI logged in.
Running it again rotates the secret and updates the same webhook.

Not a Jira admin? `mise run mac-jira-webhook --manual` stores the secret on Fly and copies the
webhook URL to the clipboard (never printing it), for a Jira admin to paste into
Jira settings -> System -> WebHooks.
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


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["clip"], ["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, input=text, text=True).returncode == 0
    return False


def store_secret(fly: str, secret: str) -> bool:
    # Stdin, not argv, so the secret never shows up in a process list.
    result = subprocess.run([fly, "secrets", "import", "-a", APP], input=f"MAC_JIRA_WEBHOOK_SECRET={secret}\n",
                            text=True, capture_output=True)
    if result.returncode != 0:
        print("fly secrets import failed:\n" + result.stderr[-500:])
        return False
    print(f"stored MAC_JIRA_WEBHOOK_SECRET on Fly ({APP}); the app restarts with it in about 30 seconds")
    return True


def manual(fly: str, secret: str, project: str) -> int:
    url = f"{BASE}/api/mac/jira/webhook?token={secret}"
    if not copy_to_clipboard(url):
        print("no clipboard tool found (pbcopy, clip, wl-copy or xclip); nothing was changed")
        return 1
    if not store_secret(fly, secret):
        return 1
    print(f"""
The webhook URL is on your clipboard. Send it privately to a Jira admin (not in a public channel),
who creates the webhook at {os.environ.get("ATLASSIAN_SITE", "").rstrip("/")}/plugins/servlet/webhooks :
  Name:   {NAME}
  URL:    (paste)
  Events: Issue -> updated
  JQL:    project = {project}
Until then, approvals still arrive through the 30-second check.""")
    return 0


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
    if "--manual" in sys.argv[1:]:
        return manual(fly, secret, project)

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
        print(f"Jira refused: {e}\nManaging webhooks needs Jira admin rights. Nothing was changed.\n"
              "Either get Jira admin for this account, or run `mise run mac-jira-webhook --manual`.")
        return 1
    return 0 if store_secret(fly, secret) else 1


if __name__ == "__main__":
    sys.exit(main())
