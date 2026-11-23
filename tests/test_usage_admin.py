"""/admin/usage: push token management, source monitor, display toggles."""
from __future__ import annotations

import re

import pytest

from jiri import db, usage
from jiri.web import create_app
from conftest import login_client


def _report(**overrides):
    base = {
        "provider": "claude",
        "context_pct": 42.0,
        "five_hour_pct": 12.5,
        "five_hour_resets_at": 1_800_000_000,
        "weekly_pct": 33.3,
        "weekly_resets_at": 1_800_500_000,
        "label": "Opus 4.5",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "jiri.db")


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", db_path)
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    monkeypatch.delenv("JIRI_USAGE_TOKEN", raising=False)
    return create_app().test_client()


def _push(client, token, **overrides):
    return client.post("/api/usage", json=_report(**overrides), headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------- token module


def test_generate_rotate_and_mask(db_path):
    assert usage.db_push_token(db_path) is None
    assert usage.push_enabled(db_path) is False
    first = usage.generate_push_token(db_path)
    assert len(first) >= 32
    assert usage.db_push_token(db_path) == first
    assert usage.check_push_token(first, db_path=db_path)

    second = usage.generate_push_token(db_path)
    assert second != first
    assert not usage.check_push_token(first, db_path=db_path)
    assert usage.check_push_token(second, db_path=db_path)
    assert not usage.check_push_token("", db_path=db_path)

    status = usage.token_status(db_path)
    assert status["db_token_masked"] == "••••" + second[-4:]
    assert second not in str(status)


def test_env_token_still_accepted(db_path, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "legacy-env-token")
    assert usage.push_enabled(db_path)
    assert usage.check_push_token("legacy-env-token", db_path=db_path)
    usage.generate_push_token(db_path)
    assert usage.check_push_token("legacy-env-token", db_path=db_path)  # env fallback survives rotation


# ---------------------------------------------------------------- /api/usage


def test_push_with_db_token_and_rotation(client, db_path):
    assert _push(client, "anything").status_code == 503  # no token anywhere -> disabled
    token = usage.generate_push_token(db_path)
    assert _push(client, "wrong").status_code == 401
    assert _push(client, token).status_code == 200

    new = usage.generate_push_token(db_path)
    assert _push(client, token, weekly_pct=50).status_code == 401  # old one is dead
    assert _push(client, new, weekly_pct=51).status_code == 200


def test_push_with_old_env_token(client, db_path, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "s3cret-token")
    assert _push(client, "s3cret-token").status_code == 200
    usage.generate_push_token(db_path)
    assert _push(client, "s3cret-token", weekly_pct=40).status_code == 200


# ---------------------------------------------------------------- page


def test_page_requires_login(client):
    response = client.get("/admin/usage")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]
    assert client.get("/api/usage/sources").status_code == 302
    assert client.post("/admin/usage/token").status_code in (302, 400)  # no session: login or CSRF wall


def test_page_renders_sources_and_snippets(client, db_path):
    login_client(client)
    token = usage.generate_push_token(db_path)
    _push(client, token, source="claude-statusline")
    _push(client, token, provider="chatgpt", label="gpt-5-codex", source="opencode")

    html = client.get("/admin/usage").get_data(as_text=True)
    assert "AI Usage" in html
    assert "Claude Code statusline" in html and "OpenCode plugin" in html and "Codex logs (legacy)" in html
    assert "fresh" in html and "never" in html
    assert "Opus 4.5" in html and "gpt-5-codex" in html
    assert "JIRI_URL=http://localhost" in html
    assert "claude-statusline --then" in html
    assert "cp -r" in html and "integrations/opencode/jiri-usage ~/.config/opencode/plugins/" in html
    assert "*/5 * * * *" in html
    assert token not in html  # masked after the one-time reveal
    assert "••••" + token[-4:] in html
    assert 'href="/admin/usage"' in html  # nav link


def test_generate_reveals_once(client, db_path):
    login_client(client)
    response = client.post("/admin/usage/token")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    token = usage.db_push_token(db_path)
    assert token and token in html
    assert f"JIRI_USAGE_TOKEN={token}" in html
    again = client.get("/admin/usage").get_data(as_text=True)
    assert token not in again

    client.post("/admin/usage/token")
    assert usage.db_push_token(db_path) != token


def test_forms_carry_csrf(client):
    login_client(client)
    html = client.get("/admin/usage").get_data(as_text=True)
    forms = re.findall(r"<form[^>]*method=\"post\"[^>]*>.*?</form>", html, re.S)
    assert len(forms) >= 6
    for form in forms:
        assert 'name="csrf_token"' in form
    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)
    assert client.post("/admin/usage/token").status_code == 400


def test_sources_api_never_includes_token(client, db_path, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "legacy-env-token")
    login_client(client)
    token = usage.generate_push_token(db_path)
    _push(client, token)
    data = client.get("/api/usage/sources").get_json()
    body = str(data)
    assert token not in body and "legacy-env-token" not in body
    by_id = {s["id"]: s for s in data["sources"]}
    assert by_id["claude-statusline"]["freshness"] == "fresh"  # no source field -> provider default
    assert by_id["claude-statusline"]["weekly_pct"] == 33.3
    assert by_id["codex"]["freshness"] == "never"
    assert data["push"]["env_token_set"] is True


def test_source_attribution_and_freshness(db_path):
    usage.record(_report(provider="chatgpt", source="codex"), db_path=db_path, now=1000.0)
    usage.record(_report(provider="chatgpt", source="opencode"), db_path=db_path, now=2000.0)
    usage.record(_report(provider="chatgpt", source="claude-statusline"), db_path=db_path, now=2100.0)  # mismatched -> default
    entries = {s["id"]: s for s in usage.sources_status(db_path, now=2100.0 + 20 * 60)}
    assert entries["codex"]["freshness"] == "stale"
    assert entries["opencode"]["last_push_at"] == 2100.0
    assert entries["opencode"]["feeds_display"] is True
    assert entries["codex"]["feeds_display"] is False
    assert entries["claude-statusline"]["freshness"] == "never"
    fresh = {s["id"]: s for s in usage.sources_status(db_path, now=2200.0)}
    assert fresh["opencode"]["freshness"] == "fresh"


# ---------------------------------------------------------------- toggles + clear


def test_visible_latest_respects_toggles(client, db_path):
    usage.record(_report(), db_path=db_path)
    usage.record(_report(provider="chatgpt"), db_path=db_path)
    assert set(usage.visible_latest(db_path)) == {"claude", "chatgpt"}

    login_client(client)
    client.post("/admin/usage/visibility", data={"show_claude": "1"})
    assert usage.shown_providers(db_path) == {"claude": True, "chatgpt": False}
    assert set(usage.visible_latest(db_path)) == {"claude"}
    assert set(usage.latest(db_path)) == {"claude", "chatgpt"}  # data kept, only hidden

    client.post("/admin/usage/visibility", data={"show_chatgpt": "1"})
    assert set(usage.visible_latest(db_path)) == {"chatgpt"}


def test_visible_latest_missing_db_is_empty(tmp_path):
    missing = tmp_path / "nope.db"
    assert usage.visible_latest(str(missing)) == {}
    assert not missing.exists()


def test_clear_button(client, db_path):
    usage.record(_report(source="claude-statusline"), db_path=db_path)
    usage.record(_report(provider="chatgpt", source="opencode"), db_path=db_path)
    login_client(client)
    response = client.post("/admin/usage/clear", data={"provider": "chatgpt"})
    assert response.status_code == 302
    assert set(usage.latest(db_path)) == {"claude"}
    assert set(usage.source_reports(db_path)) == {"claude-statusline"}
    assert client.post("/admin/usage/clear", data={"provider": "bard"}).status_code == 400


def test_repo_path_setting_updates_snippets(client, db_path):
    login_client(client)
    client.post("/admin/usage/repo", data={"repo_path": "~/code/jiri"})
    assert db.get_setting("usage.laptop_repo", db_path=db_path) == "~/code/jiri"
    html = client.get("/admin/usage").get_data(as_text=True)
    assert "python3 ~/code/jiri/scripts/jiri_usage_push.py opencode --quiet" in html
