from __future__ import annotations

import pytest

from conftest import TEST_ADMIN_PASSWORD, csrf_token_for, login_client
from jiri import db, telegram
from jiri.web import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    monkeypatch.delenv("JIRI_WEB_SECRET_KEY", raising=False)
    return db_path


def _post_login(client, password):
    return client.post("/admin/login", data={"password": password, "csrf_token": csrf_token_for(client)})


@pytest.mark.parametrize("password", ["", "   ", "test"])
def test_default_or_missing_password_refuses_every_login(env, monkeypatch, password):
    monkeypatch.setenv("JIRI_ADMIN_PASSWORD", password)
    client = create_app().test_client()

    page = client.get("/admin/login")
    assert page.status_code == 200
    assert b"Set <code>JIRI_ADMIN_PASSWORD</code> in <code>.env</code> and restart" in page.data
    assert b'name="password"' not in page.data

    for attempt in ("test", "", password):
        response = _post_login(client, attempt)
        assert response.status_code == 503
    assert client.get("/admin").status_code == 302


def test_unset_password_refuses_login(env, monkeypatch):
    monkeypatch.delenv("JIRI_ADMIN_PASSWORD", raising=False)
    client = create_app().test_client()
    assert _post_login(client, "test").status_code == 503
    assert client.get("/admin").status_code == 302


def test_configured_password_logs_in(env):
    client = create_app().test_client()
    assert _post_login(client, "wrong").status_code == 200
    assert client.get("/admin").status_code == 302
    response = _post_login(client, TEST_ADMIN_PASSWORD)
    assert response.status_code == 302
    assert client.get("/admin").status_code == 200


def test_secret_key_is_random_persisted_and_stable(env):
    first = create_app()
    second = create_app()
    assert first.secret_key == second.secret_key
    assert first.secret_key != "jiri-dev-web-secret-change-me"
    assert len(first.secret_key) == 64
    assert db.get_setting("web.secret_key", db_path=str(env)) == first.secret_key

    # A session cookie minted by one process is valid in the next.
    client = first.test_client()
    login_client(client)
    cookie = client.get_cookie("session")
    other = second.test_client()
    other.set_cookie("session", cookie.value)
    assert other.get("/admin").status_code == 200


def test_secret_key_differs_per_install(tmp_path, monkeypatch, env):
    a = create_app()
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "other.db"))
    b = create_app()
    assert a.secret_key != b.secret_key


def test_secret_key_env_override(env, monkeypatch):
    monkeypatch.setenv("JIRI_WEB_SECRET_KEY", "from-env-secret")
    assert create_app().secret_key == "from-env-secret"


def test_post_requires_csrf_token(env):
    client = create_app().test_client()
    token = csrf_token_for(client)
    # Login itself is CSRF-protected.
    assert client.post("/admin/login", data={"password": TEST_ADMIN_PASSWORD}).status_code == 400
    assert client.post("/admin/login", data={"password": TEST_ADMIN_PASSWORD, "csrf_token": token}).status_code == 302
    token = csrf_token_for(client)  # rotated with the fresh session

    assert client.post("/admin/todos", data={"title": "no token"}).status_code == 400
    assert client.post("/admin/todos", data={"title": "bad", "csrf_token": "nope"}).status_code == 400
    assert client.post("/api/todos", json={"title": "no header"}).status_code == 400

    ok_form = client.post("/admin/todos", data={"title": "with token", "csrf_token": token})
    assert ok_form.status_code == 302
    ok_json = client.post("/api/todos", json={"title": "with header"}, headers={"X-CSRF-Token": token})
    assert ok_json.status_code == 201 or ok_json.status_code == 200
    titles = [t["title"] for t in client.get("/api/todos").get_json()]
    assert "with token" in titles and "with header" in titles
    assert "no token" not in titles


def test_every_post_form_carries_csrf_field(env):
    client = create_app().test_client()
    login_client(client)
    pages = ["/admin", "/admin/todos", "/admin/notes", "/admin/focus", "/admin/water", "/admin/weather",
             "/admin/telegram", "/admin/persona", "/admin/ai"]
    for page in pages:
        html = client.get(page).get_data(as_text=True)
        forms = html.lower().count('method="post"')
        assert forms, page
        assert html.count('name="csrf_token"') >= forms, page
        assert '<meta name="csrf-token"' in html


def test_usage_push_uses_bearer_not_csrf(env, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "s3cret-token")
    client = create_app().test_client()
    payload = {"provider": "claude", "weekly_pct": 10.0, "label": "x"}
    assert client.post("/api/usage", json=payload).status_code == 401
    ok = client.post("/api/usage", json=payload, headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


PRIVATE_ENDPOINTS = [
    "/screen",
    "/screen.png",
    "/api/screen",
    "/api/ai/status",
    "/api/water",
    "/api/focus",
    "/api/weather",
]


@pytest.mark.parametrize("path", PRIVATE_ENDPOINTS)
def test_personal_endpoints_need_login(env, path):
    client = create_app().test_client()
    logged_out = client.get(path)
    assert logged_out.status_code in (302, 401)
    if logged_out.status_code == 302:
        assert "/admin/login" in logged_out.headers["Location"]
    login_client(client)
    assert client.get(path).status_code == 200


def test_screen_surface_stays_open_for_localhost_preview(env):
    client = create_app(surface="screen").test_client()
    for path in ("/screen", "/screen.png", "/api/screen", "/api/focus", "/api/weather"):
        assert client.get(path).status_code == 200, path


def test_public_status_is_stripped(env):
    client = create_app().test_client()
    public = client.get("/api/status")
    assert public.status_code == 200
    assert set(public.get_json()) == {"ok", "app_version", "database_writable"}
    login_client(client)
    full = client.get("/api/status").get_json()
    assert "todos_count" in full and "database_path" in full


def test_login_rate_limited_after_five_failures(env):
    app = create_app()
    client = app.test_client()
    for _ in range(5):
        assert _post_login(client, "wrong").status_code == 200
    blocked = _post_login(client, "wrong")
    assert blocked.status_code == 429
    assert b"Too many failed logins" in blocked.data
    # Even the right password waits out the window.
    assert _post_login(client, TEST_ADMIN_PASSWORD).status_code == 429
    # Another client address is unaffected.
    other = app.test_client()
    other.environ_base["REMOTE_ADDR"] = "10.0.0.9"
    assert _post_login(other, TEST_ADMIN_PASSWORD).status_code == 302


def test_db_browser_masks_secrets(env):
    client = create_app().test_client()  # app start seeds telegram settings first
    db.set_setting(telegram.BOT_TOKEN_KEY, "123456:ABCDEFsupersecretWXYZ", db_path=str(env))
    db.set_setting("ai.api_key", "sk-live-abcdefgh1234", db_path=str(env))
    db.set_setting("water.goal_ml", "2500", db_path=str(env))
    login_client(client)
    html = client.get("/admin/db-browser?table=settings").get_data(as_text=True)
    assert "supersecret" not in html
    assert "123456:ABCDEF" not in html
    assert "••••WXYZ" in html
    assert "sk-live" not in html
    assert "••••1234" in html
    assert "2500" in html  # ordinary settings stay visible
    # The persisted web secret key is masked too.
    secret = db.get_setting("web.secret_key", db_path=str(env))
    assert secret and secret not in html


def test_security_headers_on_every_response(env):
    client = create_app().test_client()
    for path in ("/admin/login", "/api/status", "/admin", "/static/style.css"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "same-origin"


def test_session_cookie_flags(env):
    app = create_app()
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    client = app.test_client()
    response = client.get("/admin/login")
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_template_auto_reload_only_in_dev(env, monkeypatch):
    monkeypatch.delenv("JIRI_DEV", raising=False)
    assert create_app().config["TEMPLATES_AUTO_RELOAD"] is False
    monkeypatch.setenv("JIRI_DEV", "1")
    assert create_app().config["TEMPLATES_AUTO_RELOAD"] is True
