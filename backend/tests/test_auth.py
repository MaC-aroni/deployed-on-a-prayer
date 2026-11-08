import pytest

from app import auth
from mac.integrations import IntegrationError

from .test_api import NAME, api  # noqa: F401 - the api fixture


class FakeGitHub:
    def __init__(self, login="ob1-can-obi", members=("ob1-can-obi",), broken=False):
        self.login, self.members, self.broken = login, set(members), broken

    def authorize_url(self, state):
        return f"https://github.example/authorize?state={state}"

    def login_for(self, code):
        if self.broken:
            raise IntegrationError("GitHub is down")
        assert code == "good-code"
        return self.login

    def can_push(self, repo, login):
        assert repo == "MaC-aroni/deployed-on-a-prayer"
        return login in self.members


@pytest.fixture
def prod(api):  # noqa: F811
    client, env, state = api
    clock = {"t": 1_000_000.0}
    config = auth.AuthConfig(required=True, repo="MaC-aroni/deployed-on-a-prayer", github=FakeGitHub(), key=b"k" * 32,
                             secure_cookies=False, now=lambda: clock["t"])
    auth.configure(config)
    return client, env, config, clock


def sign_in(client, code="good-code"):
    resp = client.get("/api/auth/login", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"].startswith("https://github.example/")
    state = resp.headers["location"].split("state=")[1]
    return client.get("/api/auth/callback", params={"code": code, "state": state}, follow_redirects=False)


def test_reading_is_open_but_buttons_need_sign_in(prod):
    client, *_ = prod
    assert client.get("/api/mac/migrations").status_code == 200
    resp = client.post(f"/api/mac/migrations/{NAME}/build")
    assert resp.status_code == 401 and "Sign in with GitHub" in resp.json()["detail"]
    assert client.get("/api/auth/me").json() == {"login": None, "required": True, "available": True, "repo": "MaC-aroni/deployed-on-a-prayer"}


def test_someone_with_repo_access_signs_in_and_their_name_is_on_the_run(prod):
    client, env, _, _ = prod
    resp = sign_in(client)
    assert resp.status_code == 302 and resp.headers["location"] == "/"
    assert client.get("/api/auth/me").json()["login"] == "ob1-can-obi"
    run = client.post(f"/api/mac/migrations/{NAME}/build").json()
    assert run["status"] == "running" or client.get(f"/api/mac/runs/{run['id']}").json()["status"] == "succeeded"
    messages = [e["message"] for e in client.get(f"/api/mac/runs/{run['id']}/events").json()]
    assert "requested by @ob1-can-obi" in messages


def test_someone_without_repo_access_is_turned_away(prod):
    client, _, config, _ = prod
    config.github = FakeGitHub(login="stranger")
    resp = sign_in(client)
    assert resp.headers["location"] == "/?signin=no-access"
    assert client.get("/api/auth/me").json()["login"] is None
    assert client.post(f"/api/mac/migrations/{NAME}/build").status_code == 401


def test_callback_needs_the_state_from_this_browser(prod):
    client, *_ = prod
    client.get("/api/auth/login", follow_redirects=False)
    resp = client.get("/api/auth/callback", params={"code": "good-code", "state": "forged"}, follow_redirects=False)
    assert resp.headers["location"] == "/?signin=expired"
    assert client.get("/api/auth/me").json()["login"] is None


def test_github_failing_is_a_failed_sign_in_not_a_crash(prod):
    client, _, config, _ = prod
    config.github = FakeGitHub(broken=True)
    assert sign_in(client).headers["location"] == "/?signin=failed"


def test_forged_or_expired_sessions_are_ignored(prod):
    client, _, config, clock = prod
    sign_in(client)
    good = client.cookies.get(auth.SESSION_COOKIE)

    def me_with(cookie):
        client.cookies.clear()
        client.cookies.set(auth.SESSION_COOKIE, cookie)
        return client.get("/api/auth/me").json()["login"]

    body, sig = good.rsplit(".", 1)
    assert me_with(body + "." + "0" * len(sig)) is None
    other_key = auth.AuthConfig(required=True, repo="x", github=None, key=b"other" * 8)
    assert me_with(auth._sign(other_key, {"login": "ob1-can-obi", "exp": 9e12})) is None
    assert me_with(good) == "ob1-can-obi"
    clock["t"] += auth.SESSION_DAYS * 86400 + 1
    assert client.get("/api/auth/me").json()["login"] is None


def test_sign_out(prod):
    client, *_ = prod
    sign_in(client)
    client.post("/api/auth/logout", follow_redirects=False)
    assert client.get("/api/auth/me").json()["login"] is None


def test_production_without_an_oauth_app_keeps_buttons_off(prod):
    client, _, config, _ = prod
    config.github = None
    resp = client.post(f"/api/mac/migrations/{NAME}/build")
    assert resp.status_code == 503 and "GITHUB_OAUTH_CLIENT_ID" in resp.json()["detail"]
    assert client.get("/api/mac/migrations").status_code == 200


def test_locally_nothing_is_required(api):  # noqa: F811
    client, *_ = api
    assert client.post(f"/api/mac/migrations/{NAME}/build").status_code == 202


def test_default_config_reads_the_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    config = auth._default_config()
    assert config.required and config.github is None and config.repo == "MaC-aroni/deployed-on-a-prayer"
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")
    assert auth._default_config().github is not None
    assert auth._default_config().key == auth._default_config().key  # stable across restarts
