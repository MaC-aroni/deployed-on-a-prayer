"""Sign in with GitHub. Anyone can look at the console; only people who can push to this repo
can press its buttons, because they change real AWS, Jira and Confluence.

The flow: /api/auth/login sends the browser to GitHub, GitHub sends it back to /api/auth/callback
with a code, and the server swaps the code for the user's GitHub login. If that login has write
access to the repo (checked with the server's own GITHUB_TOKEN), it sets a signed session cookie.
Nothing else from GitHub is kept, and the user's GitHub token is thrown away. Write access, not
org membership, because the team are outside collaborators on the repo.

Sign-in is required when APP_ENV=production. Locally it's off and every button works.
Settings: GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET (an OAuth app in the org),
MAC_GITHUB_REPO (default MaC-aroni/deployed-on-a-prayer), and GITHUB_TOKEN for the access check.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from mac.integrations import IntegrationError, _request

SESSION_COOKIE = "mac_session"
STATE_COOKIE = "mac_oauth_state"
SESSION_DAYS = 7
API = "https://api.github.com"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


class GitHubOAuth:
    """The three GitHub calls sign-in needs. Tests swap in a fake."""

    def __init__(self, client_id: str, client_secret: str, server_token: str | None):
        self.client_id, self.client_secret, self.server_token = client_id, client_secret, server_token

    def authorize_url(self, state: str) -> str:
        # No scopes: only the user's public identity is needed.
        query = urllib.parse.urlencode({"client_id": self.client_id, "state": state, "allow_signup": "false"})
        return f"https://github.com/login/oauth/authorize?{query}"

    def login_for(self, code: str) -> str:
        reply = _request("https://github.com/login/oauth/access_token", {"Accept": "application/json"},
                         method="POST", body={"client_id": self.client_id, "client_secret": self.client_secret,
                                              "code": code})
        if not reply or "access_token" not in reply:
            raise IntegrationError(f"GitHub didn't accept the sign-in: {(reply or {}).get('error', 'no token')}")
        user = _request(f"{API}/user", GITHUB_HEADERS | {"Authorization": f"Bearer {reply['access_token']}"})
        return user["login"]

    def can_push(self, repo: str, login: str) -> bool:
        if not self.server_token:
            raise IntegrationError("GITHUB_TOKEN isn't set, so repo access can't be checked")
        try:
            reply = _request(f"{API}/repos/{repo}/collaborators/{urllib.parse.quote(login)}/permission",
                             GITHUB_HEADERS | {"Authorization": f"Bearer {self.server_token}"})
        except IntegrationError as e:
            if e.status == 404:  # not a collaborator (or no such user)
                return False
            raise
        return reply.get("permission") in ("admin", "maintain", "write")


@dataclass
class AuthConfig:
    required: bool
    repo: str  # people who can push to it can run pipelines
    github: GitHubOAuth | None  # None: no OAuth app configured
    key: bytes = field(repr=False)  # signs the session cookie
    secure_cookies: bool = True
    now: Callable[[], float] = time.time


_config: AuthConfig | None = None


def configure(config: AuthConfig | None) -> None:
    global _config
    _config = config


def _default_config() -> AuthConfig:
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID") or ""
    client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET") or ""
    production = os.environ.get("APP_ENV") == "production"
    github = GitHubOAuth(client_id, client_secret, os.environ.get("GITHUB_TOKEN")) if client_id and client_secret else None
    # The cookie key comes from the OAuth secret, so there's no extra secret to manage.
    # Changing the OAuth secret signs everyone out, which is what you'd want anyway.
    key = hmac.new(client_secret.encode() or secrets.token_bytes(32), b"mac-session", hashlib.sha256).digest()
    return AuthConfig(required=production, repo=os.environ.get("MAC_GITHUB_REPO", "MaC-aroni/deployed-on-a-prayer"),
                      github=github, key=key, secure_cookies=production)


def get_config() -> AuthConfig:
    global _config
    if _config is None:
        _config = _default_config()
    return _config


# ---- The session cookie: base64(json).signature ------------------------------------------------


def _sign(config: AuthConfig, payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(config.key, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _read(config: AuthConfig, cookie: str | None) -> dict | None:
    if not cookie or "." not in cookie:
        return None
    body, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(config.key, body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    return payload if payload.get("exp", 0) > config.now() else None


def current_user(config: AuthConfig = Depends(get_config),
                 mac_session: str | None = Cookie(default=None)) -> str | None:
    session = _read(config, mac_session)
    return session["login"] if session else None


def signed_in(config: AuthConfig = Depends(get_config), user: str | None = Depends(current_user)) -> str | None:
    """For endpoints that change things. Returns the GitHub login (None locally, where it's off)."""
    if not config.required:
        return user
    if config.github is None:
        raise HTTPException(503, "Sign-in isn't set up on this server (GITHUB_OAUTH_CLIENT_ID/SECRET)")
    if user is None:
        raise HTTPException(401, "Sign in with GitHub to do this")
    return user


# ---- Routes --------------------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(config: AuthConfig = Depends(get_config), user: str | None = Depends(current_user)):
    return {"login": user, "required": config.required, "available": config.github is not None,
            "repo": config.repo}


@router.get("/login")
def login(config: AuthConfig = Depends(get_config)):
    if config.github is None:
        raise HTTPException(503, "Sign-in isn't set up on this server")
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(config.github.authorize_url(state), status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, secure=config.secure_cookies, samesite="lax")
    return resp


def _back(problem: str | None = None) -> RedirectResponse:
    resp = RedirectResponse("/" + (f"?signin={problem}" if problem else ""), status_code=302)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.get("/callback")
def callback(code: str = Query(default=""), state: str = Query(default=""),
             config: AuthConfig = Depends(get_config), mac_oauth_state: str | None = Cookie(default=None)):
    if config.github is None:
        raise HTTPException(503, "Sign-in isn't set up on this server")
    # The state cookie proves this sign-in started in this browser.
    if not code or not mac_oauth_state or not hmac.compare_digest(state, mac_oauth_state):
        return _back("expired")
    try:
        user = config.github.login_for(code)
        allowed = config.github.can_push(config.repo, user)
    except IntegrationError:
        return _back("failed")
    if not allowed:
        return _back("no-access")
    resp = _back()
    resp.set_cookie(SESSION_COOKIE, _sign(config, {"login": user, "exp": config.now() + SESSION_DAYS * 86400}),
                    max_age=SESSION_DAYS * 86400, httponly=True, secure=config.secure_cookies, samesite="lax")
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
