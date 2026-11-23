"""Direct Claude / ChatGPT sign-in (usage_accounts.py). No real network:
every request goes through a fake `_urlopen`."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import urllib.error
import urllib.parse

import pytest

from jiri import db, usage, usage_accounts
from jiri.web import create_app
from conftest import login_client


def _jwt(claims: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeNet:
    """Routes requests by URL to queued responses; records every request."""

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.requests: list = []

    def add(self, url: str, payload=None, status: int = 200):
        self.routes.setdefault(url, []).append((status, payload))

    def __call__(self, request, timeout=None):
        assert timeout == usage_accounts.HTTP_TIMEOUT_SECONDS
        self.requests.append(request)
        queue = self.routes.get(request.full_url)
        if not queue:
            raise urllib.error.URLError(ConnectionRefusedError("no route"))
        status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
        body = json.dumps(payload or {}).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(body))
        return FakeResponse(body)


CHATGPT_ID_TOKEN = _jwt(
    {
        "email": "owner@example.com",
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-123", "chatgpt_plan_type": "plus"},
    }
)
CLAUDE = usage_accounts.PROVIDERS["claude"]
CHATGPT = usage_accounts.PROVIDERS["chatgpt"]


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "jiri.db")


@pytest.fixture()
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(usage_accounts, "_urlopen", fake)
    return fake


def _connect_chatgpt(db_path, net, now=1000.0):
    login = usage_accounts.start_login("chatgpt")
    net.add(
        CHATGPT["token_url"],
        {"access_token": "at-1", "refresh_token": "rt-1", "id_token": CHATGPT_ID_TOKEN, "expires_in": 3600},
    )
    pasted = f"http://localhost:1455/auth/callback?code=the-code&state={login['state']}"
    usage_accounts.complete_login(
        "chatgpt", pasted, expected_state=login["state"], verifier=login["verifier"], db_path=db_path, now=now
    )
    return login


def _connect_claude(db_path, net, now=1000.0):
    login = usage_accounts.start_login("claude")
    net.add(
        CLAUDE["token_url"],
        {
            "access_token": "cat-1",
            "refresh_token": "crt-1",
            "expires_in": 28800,
            "account": {"uuid": "u-1", "email_address": "owner@example.com"},
            "organization": {"name": "Max"},
        },
    )
    usage_accounts.complete_login(
        "claude", f"the-code#{login['state']}", expected_state=login["state"], verifier=login["verifier"],
        db_path=db_path, now=now,
    )
    return login


# ---------------------------------------------------------------- login flow


def test_start_login_builds_pkce_authorize_urls():
    for provider in ("claude", "chatgpt"):
        login = usage_accounts.start_login(provider)
        spec = usage_accounts.PROVIDERS[provider]
        url = urllib.parse.urlsplit(login["url"])
        params = dict(urllib.parse.parse_qsl(url.query))
        assert login["url"].startswith(spec["authorize_url"] + "?")
        assert params["client_id"] == spec["client_id"]
        assert params["redirect_uri"] == spec["redirect_uri"]
        assert params["response_type"] == "code"
        assert params["code_challenge_method"] == "S256"
        assert params["state"] == login["state"]
        expected = base64.urlsafe_b64encode(hashlib.sha256(login["verifier"].encode()).digest()).rstrip(b"=").decode()
        assert params["code_challenge"] == expected
        assert 43 <= len(login["verifier"]) <= 128
    assert "code=true" in usage_accounts.start_login("claude")["url"]
    assert "codex_cli_simplified_flow=true" in usage_accounts.start_login("chatgpt")["url"]


def test_parse_pasted_variants():
    assert usage_accounts.parse_pasted("http://localhost:1455/auth/callback?code=abc&state=xyz") == ("abc", "xyz")
    assert usage_accounts.parse_pasted("  abc#xyz ") == ("abc", "xyz")
    assert usage_accounts.parse_pasted("code=abc&state=xyz") == ("abc", "xyz")
    assert usage_accounts.parse_pasted("abc") == ("abc", None)
    for bad in ("", "abc#", "http://localhost:1455/auth/callback?error=access_denied&code="):
        with pytest.raises(ValueError):
            usage_accounts.parse_pasted(bad)


def test_chatgpt_login_stores_tokens_and_identity(db_path, net):
    _connect_chatgpt(db_path, net)
    sent = net.requests[0]
    body = dict(urllib.parse.parse_qsl(sent.data.decode()))
    assert sent.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert body["grant_type"] == "authorization_code" and body["code"] == "the-code"
    assert body["client_id"] == CHATGPT["client_id"] and body["code_verifier"]

    status = usage_accounts.status("chatgpt", db_path=db_path)
    assert status["connected"] and status["email"] == "owner@example.com" and status["plan"] == "plus"
    assert "at-1" not in str(status) and "rt-1" not in str(status)
    assert db.get_setting("usage.account.chatgpt.account_id", db_path=db_path) == "acct-123"
    assert db.get_setting("usage.account.chatgpt.refresh_token", db_path=db_path) == "rt-1"


def test_claude_login_sends_json_with_state(db_path, net):
    login = _connect_claude(db_path, net)
    body = json.loads(net.requests[0].data)
    assert body == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": CLAUDE["redirect_uri"],
        "client_id": CLAUDE["client_id"],
        "code_verifier": body["code_verifier"],
        "state": login["state"],
    }
    assert usage_accounts.status("claude", db_path=db_path)["email"] == "owner@example.com"


def test_state_mismatch_and_rejected_code(db_path, net):
    login = usage_accounts.start_login("claude")
    with pytest.raises(ValueError, match="different sign-in"):
        usage_accounts.complete_login(
            "claude", "code#other-state", expected_state=login["state"], verifier=login["verifier"], db_path=db_path
        )
    net.add(CLAUDE["token_url"], {"error": "invalid_grant"}, status=400)
    with pytest.raises(ValueError, match="rejected that code"):
        usage_accounts.complete_login(
            "claude", f"code#{login['state']}", expected_state=login["state"], verifier=login["verifier"], db_path=db_path
        )
    assert not usage_accounts.is_connected("claude", db_path=db_path)


# ---------------------------------------------------------------- polling


def test_chatgpt_check_records_usage(db_path, net):
    _connect_chatgpt(db_path, net, now=1000.0)
    net.add(
        CHATGPT["usage_url"],
        {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {"used_percent": 23, "limit_window_seconds": 18000, "reset_at": 1_800_000_000},
                "secondary_window": {"used_percent": 41, "limit_window_seconds": 604800, "reset_after_seconds": 600},
            },
        },
    )
    status = usage_accounts.check_now("chatgpt", db_path=db_path, now=1100.0)
    assert status["last_error"] == "" and status["last_ok_at"] == 1100.0
    request = net.requests[-1]
    assert request.get_header("Authorization") == "Bearer at-1"
    assert request.get_header("Chatgpt-account-id") == "acct-123"
    report = usage.latest(db_path)["chatgpt"]
    assert (report.five_hour_pct, report.five_hour_resets_at) == (23.0, 1_800_000_000.0)
    assert (report.weekly_pct, report.weekly_resets_at) == (41.0, 1700.0)
    assert "chatgpt-account" in usage.source_reports(db_path)


def test_claude_check_parses_iso_resets(db_path, net):
    _connect_claude(db_path, net, now=1000.0)
    net.add(
        CLAUDE["usage_url"],
        {
            "five_hour": {"utilization": 12.0, "resets_at": "2027-01-15T10:00:00.123456789+00:00"},
            "seven_day": {"utilization": 55.5, "resets_at": "2027-01-20T00:00:00Z"},
        },
    )
    usage_accounts.check_now("claude", db_path=db_path, now=1100.0)
    request = net.requests[-1]
    assert request.get_header("Anthropic-beta") == usage_accounts.CLAUDE_OAUTH_BETA
    assert request.get_header("Authorization") == "Bearer cat-1"
    report = usage.latest(db_path)["claude"]
    assert report.five_hour_pct == 12.0 and report.weekly_pct == 55.5
    assert report.five_hour_resets_at == pytest.approx(1800007200.123, abs=0.01)
    assert report.weekly_resets_at == 1800403200.0


def test_expired_token_is_refreshed_and_rotation_persisted(db_path, net):
    _connect_chatgpt(db_path, net, now=1000.0)
    net.routes.clear()
    net.add(CHATGPT["token_url"], {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600})
    net.add(CHATGPT["usage_url"], {"rate_limit": {}})
    status = usage_accounts.check_now("chatgpt", db_path=db_path, now=1000.0 + 7200)
    assert status["last_error"] == ""
    refresh = dict(urllib.parse.parse_qsl(net.requests[-2].data.decode()))
    assert refresh == {"grant_type": "refresh_token", "refresh_token": "rt-1", "client_id": CHATGPT["client_id"]}
    assert db.get_setting("usage.account.chatgpt.refresh_token", db_path=db_path) == "rt-2"
    assert db.get_setting("usage.account.chatgpt.account_id", db_path=db_path) == "acct-123"  # identity kept
    assert net.requests[-1].get_header("Authorization") == "Bearer at-2"


def test_401_marks_reconnect_needed_and_poll_skips(db_path, net):
    _connect_claude(db_path, net, now=1000.0)
    net.routes.clear()
    net.add(CLAUDE["usage_url"], status=401)
    net.add(CLAUDE["token_url"], {"error": "invalid_grant"}, status=400)
    status = usage_accounts.check_now("claude", db_path=db_path, now=1100.0)
    assert status["needs_reconnect"] is True
    assert "reconnect needed" in status["last_error"]
    count = len(net.requests)
    assert usage_accounts.poll_all(db_path) == {"claude": "reconnect needed"}
    assert len(net.requests) == count  # no network while waiting for a reconnect


def test_network_error_is_recorded_not_raised(db_path, net):
    _connect_claude(db_path, net, now=1000.0)
    net.routes.clear()  # every request now fails with URLError
    status = usage_accounts.check_now("claude", db_path=db_path, now=1100.0)
    assert "unreachable" in status["last_error"]
    assert status["needs_reconnect"] is False


def test_poll_all_without_accounts_does_nothing(db_path, net):
    assert usage_accounts.poll_all(db_path) == {}
    assert net.requests == []


def test_disconnect_clears_everything(db_path, net):
    _connect_chatgpt(db_path, net)
    usage_accounts.disconnect("chatgpt", db_path=db_path)
    assert not usage_accounts.is_connected("chatgpt", db_path=db_path)
    assert db.get_setting("usage.account.chatgpt.refresh_token", db_path=db_path) is None


def test_fresher_row_wins_between_push_and_poll(db_path, net):
    _connect_claude(db_path, net, now=1000.0)
    net.add(CLAUDE["usage_url"], {"five_hour": {"utilization": 10, "resets_at": None}})
    usage_accounts.check_now("claude", db_path=db_path, now=2000.0)
    usage.record({"provider": "claude", "five_hour_pct": 70, "source": "claude-statusline"}, db_path=db_path, now=2100.0)
    assert usage.latest(db_path)["claude"].five_hour_pct == 70.0
    usage_accounts.check_now("claude", db_path=db_path, now=2400.0)
    assert usage.latest(db_path)["claude"].five_hour_pct == 10.0


# ---------------------------------------------------------------- admin routes


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", db_path)
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    return create_app().test_client()


def test_connect_flow_through_admin(client, db_path, net):
    login_client(client)
    assert client.post("/admin/usage/account/chatgpt/connect").status_code == 302
    with client.session_transaction() as sess:
        # PKCE verifier stays server-side: only an opaque nonce is in the cookie.
        assert all("verifier" not in str(value) for value in sess.values())
    html = client.get("/admin/usage").get_data(as_text=True)
    match = __import__("re").search(r'href="(https://auth\.openai\.com/oauth/authorize\?[^"]+)"', html)
    assert match
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(match.group(1).replace("&amp;", "&")).query))["state"]

    net.add(CHATGPT["token_url"], {"access_token": "at-1", "refresh_token": "rt-1", "id_token": CHATGPT_ID_TOKEN})
    net.add(CHATGPT["usage_url"], {"rate_limit": {"primary_window": {"used_percent": 5, "limit_window_seconds": 18000}}})
    response = client.post(
        "/admin/usage/account/chatgpt/complete",
        data={"pasted": f"http://localhost:1455/auth/callback?code=c&state={state}"},
    )
    assert response.status_code == 302
    page = client.get("/admin/usage").get_data(as_text=True)
    assert "owner@example.com" in page and "connected" in page
    assert "at-1" not in page and "rt-1" not in page
    assert usage.latest(db_path)["chatgpt"].five_hour_pct == 5.0

    sources = client.get("/api/usage/sources").get_json()
    assert sources["accounts"]["chatgpt"]["connected"] is True
    assert "at-1" not in json.dumps(sources) and "rt-1" not in json.dumps(sources)

    net.add(CHATGPT["usage_url"], status=401)
    net.add(CHATGPT["token_url"], {"error": "invalid_grant"}, status=400)
    net.routes[CHATGPT["usage_url"]] = [(401, None)]
    net.routes[CHATGPT["token_url"]] = [(400, {"error": "invalid_grant"})]
    client.post("/admin/usage/account/chatgpt/check")
    assert "reconnect needed" in client.get("/admin/usage").get_data(as_text=True)

    client.post("/admin/usage/account/chatgpt/disconnect")
    assert not usage_accounts.is_connected("chatgpt", db_path=db_path)


def test_complete_without_pending_login_is_rejected(client, net):
    login_client(client)
    response = client.post("/admin/usage/account/claude/complete", data={"pasted": "a#b"})
    assert response.status_code == 400
    assert "expired" in response.get_data(as_text=True)
    assert net.requests == []


def test_db_browser_masks_account_tokens(client, db_path, net):
    _connect_claude(db_path, net)
    login_client(client)
    html = client.get("/admin/db-browser?table=settings").get_data(as_text=True)
    assert "usage.account.claude.refresh_token" in html
    assert "cat-1" not in html and "crt-1" not in html
