from __future__ import annotations

import time

from jiri import db, telegram, weather
from jiri.web import create_app


def login(client):
    return client.post("/admin/login", data={"password": "test"}, follow_redirects=True)


def test_browser_driven_web_surface(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")

    app = create_app()
    client = app.test_client()

    locked = client.get("/admin")
    assert locked.status_code == 302
    assert "/admin/login" in locked.headers["Location"]

    logged_in = login(client)
    assert logged_in.status_code == 200
    assert b"Dashboard" in logged_in.data
    assert b"Focus" in logged_in.data
    assert b"Weather" in logged_in.data
    assert b"Water" in logged_in.data
    assert b"Telegram" in logged_in.data
    assert b"Token/chat allowlist needed" in logged_in.data

    screen = client.get("/screen")
    assert screen.status_code == 200
    assert b'data-width="480" data-height="320"' in screen.data
    # JIRI guards five things and shows all five, always
    assert screen.data.count(b'class="watch-cell') == 5
    assert b'class="device-speech"' in screen.data
    # the reason line is shown unless it would restate the panel, and then the
    # voice takes the freed row instead of leaving a gap
    assert b'class="device-reason"' in screen.data or b"device-voice is-solo" in screen.data
    # the face is a readout, not a toy: no tap-to-change-mood, no random asides
    assert b"cycle" not in screen.data
    assert b"asides" not in screen.data
    assert b"Math.random" not in screen.data
    assert b'id="device-face"' in screen.data
    assert b'id="device-face-mark"' in screen.data
    assert b'class="mascot mascot-' in screen.data
    assert b'id="device-ascii-face"' not in screen.data
    assert b'id="device-eye-left"' not in screen.data
    assert b'id="device-mouth"' not in screen.data
    assert b'class="device-hero-value' in screen.data
    # the vitals bar and the panel-nav footer were removed; AUTO rotation is the default
    assert b'class="device-glance"' not in screen.data
    assert b'aria-label="Previous panel"' not in screen.data
    assert b'aria-label="Next panel"' not in screen.data

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.is_json
    assert status.json["database_writable"] is True

    screen_api = client.get("/api/screen")
    assert screen_api.status_code == 200
    assert screen_api.is_json
    assert screen_api.json["app_name"] == "JIRI"

    display_api = client.get("/api/display")
    assert display_api.status_code == 200
    assert display_api.is_json
    assert display_api.json["panel"]
    assert display_api.json["face"]["state"]

    todo_page = client.post(
        "/admin/todos",
        data={"title": "Browser todo", "due_at": "2026-05-14 21:00", "description": "From the web", "priority": "2"},
        follow_redirects=True,
    )
    assert todo_page.status_code == 200
    assert b"Browser todo" in todo_page.data

    done_page = client.post("/admin/todos/1/done", follow_redirects=True)
    assert done_page.status_code == 200
    assert b"done" in done_page.data

    water_page = client.post("/admin/water/add", data={"amount_ml": "250"}, follow_redirects=True)
    assert water_page.status_code == 200
    assert b"250ml" in water_page.data

    water_view = client.get("/admin/water")
    assert water_view.status_code == 200
    assert b"Weekly Intake" in water_view.data
    assert b"stored in SQLite" in water_view.data

    water_api = client.get("/api/water")
    assert water_api.status_code == 200
    assert len(water_api.json["week"]) == 7

    water_goal = client.post("/admin/water/age", data={"age": "30", "sex": "male"}, follow_redirects=True)
    assert water_goal.status_code == 200
    assert b"3000ml" in water_goal.data

    telegram_page = client.get("/admin/telegram")
    assert telegram_page.status_code == 200
    assert b"Telegram Binding" in telegram_page.data
    assert b"Save Telegram" in telegram_page.data
    assert b"Missing setup" in telegram_page.data
    assert b"Check Bot API" in telegram_page.data
    assert b"/todo add" in telegram_page.data
    assert b"/summary" in telegram_page.data

    telegram_api = client.get("/api/telegram/status")
    assert telegram_api.status_code == 200
    assert telegram_api.json["configured"] is False

    telegram_save = client.post(
        "/admin/telegram/save",
        data={
            "enabled": "1",
            "bot_token": "123456:test-token",
            "allowed_chat_ids": "123456789,-1001234567890",
            "command_chat_id": "123456789",
            "polling_timeout_seconds": "5",
        },
        follow_redirects=True,
    )
    assert telegram_save.status_code == 200
    assert b"Telegram settings saved" in telegram_save.data
    assert db.get_setting(telegram.BOT_TOKEN_KEY, db_path=str(db_path)) == "123456:test-token"
    assert db.get_setting(telegram.ALLOWED_CHAT_IDS_KEY, db_path=str(db_path)) == "123456789,-1001234567890"

    telegram_api = client.get("/api/telegram/status")
    assert telegram_api.status_code == 200
    assert telegram_api.json["configured"] is True
    assert telegram_api.json["enabled"] is True

    add_chat = client.post("/admin/telegram/allowed/add", data={"chat_id": "-100222"}, follow_redirects=True)
    assert add_chat.status_code == 200
    assert b"-100222" in add_chat.data

    remove_chat = client.post("/admin/telegram/allowed/remove", data={"chat_id": "-100222"}, follow_redirects=True)
    assert remove_chat.status_code == 200
    assert b"Allowed chat removed" in remove_chat.data

    disable_page = client.post("/admin/telegram/disable", follow_redirects=True)
    assert disable_page.status_code == 200
    assert client.get("/api/telegram/status").json["enabled"] is False

    clear_token = client.post("/admin/telegram/clear-token", follow_redirects=True)
    assert clear_token.status_code == 200
    assert b"Telegram token cleared" in clear_token.data
    assert db.get_setting(telegram.BOT_TOKEN_KEY, db_path=str(db_path)) == ""

    update_page = client.post(
        "/admin/todos/1/update",
        data={"title": "Updated browser todo", "due_at": "2026-05-15 09:30", "description": "Edited from the web", "priority": "1"},
        follow_redirects=True,
    )
    assert update_page.status_code == 200
    assert b"Updated browser todo" in update_page.data

    note_page = client.post(
        "/admin/notes",
        data={"title": "Browser note", "body": "Keep the Pi footprint small.", "tags": "browser,pi"},
        follow_redirects=True,
    )
    assert note_page.status_code == 200
    assert b"Browser note" in note_page.data

    note_update = client.post(
        "/admin/notes/1/update",
        data={"title": "Updated browser note", "body": "Still keep the Pi footprint small.", "tags": "edited,pi"},
        follow_redirects=True,
    )
    assert note_update.status_code == 200
    assert b"Updated browser note" in note_update.data

    monkeypatch.setattr(
        weather,
        "search_locations",
        lambda query, country=None, timeout_seconds=3: [
            {
                "name": "Panchagarh",
                "latitude": 26.1167,
                "longitude": 88.85,
                "timezone": "Asia/Dhaka",
                "country": "Bangladesh",
                "country_code": "BD",
                "admin1": "Rangpur Division",
                "admin2": "Panchagarh District",
                "admin3": "Panchagarh Sadar",
                "admin4": "",
                "population": 50000,
            }
        ],
    )

    search_page = client.post("/admin/weather/search", data={"query": "panchagarh", "country": "BD"}, follow_redirects=True)
    assert search_page.status_code == 200
    assert b"Panchagarh" in search_page.data

    coords_page = client.post(
        "/admin/weather/set-coords",
        data={"name": "Home", "lat": "26.1167", "lon": "88.85"},
        follow_redirects=True,
    )
    assert coords_page.status_code == 200
    assert b"Home" in coords_page.data

    refresh_page = client.post("/admin/weather/refresh", follow_redirects=True)
    assert refresh_page.status_code == 200
    assert b"Fake partly cloudy" in refresh_page.data

    weather_page = client.get("/admin/weather")
    assert weather_page.status_code == 200
    assert b"Next 12 Hours" in weather_page.data
    assert b"7-Day Forecast" in weather_page.data
    assert b"Saved Locations" in weather_page.data


def test_json_api_crud_surface(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")

    app = create_app()
    client = app.test_client()

    locked_api = client.post("/api/todos", json={"title": "blocked"})
    assert locked_api.status_code == 302

    login(client)

    created_todo = client.post("/api/todos", json={"title": "API todo", "priority": 2})
    assert created_todo.status_code == 201
    assert created_todo.json["title"] == "API todo"

    updated_todo = client.put(
        "/api/todos/1",
        json={"title": "API todo edited", "due_at": "2026-05-15 10:00", "description": "API edit", "priority": 1},
    )
    assert updated_todo.status_code == 200
    assert updated_todo.json["title"] == "API todo edited"
    assert updated_todo.json["priority"] == 1

    todo_list = client.get("/api/todos?all=true")
    assert todo_list.status_code == 200
    assert todo_list.json[0]["title"] == "API todo edited"

    done_todo = client.post("/api/todos/1/done")
    assert done_todo.status_code == 200
    assert done_todo.json["status"] == "done"

    created_note = client.post("/api/notes", json={"title": "API note", "body": "Plain API note", "tags": "api"})
    assert created_note.status_code == 201
    assert created_note.json["title"] == "API note"

    updated_note = client.put("/api/notes/1", json={"title": "API note edited", "body": "Edited note", "tags": "api,edited"})
    assert updated_note.status_code == 200
    assert updated_note.json["title"] == "API note edited"

    notes = client.get("/api/notes")
    assert notes.status_code == 200
    assert notes.json[0]["title"] == "API note edited"

    client.post("/admin/weather/set-coords", data={"name": "Home", "lat": "26.1167", "lon": "88.85"})
    weather_refresh = client.post("/api/weather/refresh")
    assert weather_refresh.status_code == 200
    assert weather_refresh.json["condition"] == "Fake partly cloudy"

    weather_snapshot = client.get("/api/weather")
    assert weather_snapshot.status_code == 200
    assert weather_snapshot.json["location"] == "Home"

    focus_start = client.post("/api/focus/start", json={"title": "API focus", "minutes": 1})
    assert focus_start.status_code == 201
    assert focus_start.json["title"] == "API focus"

    focus_status = client.get("/api/focus")
    assert focus_status.status_code == 200
    assert focus_status.json["active"] is True
    assert focus_status.json["remaining_seconds"] <= 60

    focus_pause = client.post("/api/focus/pause")
    assert focus_pause.status_code == 200
    assert focus_pause.json["status"] == "paused"

    focus_resume = client.post("/api/focus/resume")
    assert focus_resume.status_code == 200
    assert focus_resume.json["status"] == "running"

    focus_complete = client.post("/api/focus/complete")
    assert focus_complete.status_code == 200
    assert focus_complete.json["status"] == "completed"

    deleted_note = client.delete("/api/notes/1")
    assert deleted_note.status_code == 200
    assert deleted_note.json["title"] == "API note edited"

    deleted_todo = client.delete("/api/todos/1")
    assert deleted_todo.status_code == 200
    assert deleted_todo.json["title"] == "API todo edited"


def test_browser_focus_controls_render_on_admin_and_screen(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()

    login(client)

    admin_start = client.post("/admin/focus/start", data={"title": "Browser focus", "minutes": "1"}, follow_redirects=True)
    assert admin_start.status_code == 200
    assert b"Browser focus" in admin_start.data
    assert b"Focus Sessions" in admin_start.data

    screen = client.get("/screen?panel=focus")
    assert screen.status_code == 200
    assert b"Browser focus" in screen.data

    admin_cancel = client.post("/admin/focus/cancel", follow_redirects=True)
    assert admin_cancel.status_code == 200
    assert b"Cancelled focus" in admin_cancel.data


def test_json_api_validation_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    bad_todo = client.post("/api/todos", json={"title": "   "})
    assert bad_todo.status_code == 400
    assert "title" in bad_todo.json["error"]

    bad_note = client.post("/api/notes", json={"title": "Note", "body": "   "})
    assert bad_note.status_code == 400
    assert "body" in bad_note.json["error"]


def test_admin_and_screen_surfaces_are_distinct(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    admin_client = create_app(surface="admin").test_client()
    admin_root = admin_client.get("/")
    assert admin_root.status_code == 302
    assert admin_root.headers["Location"].endswith("/admin")
    assert admin_client.get("/screen").status_code == 404
    assert admin_client.get("/api/display").status_code == 404
    assert admin_client.get("/admin").status_code == 302
    assert login(admin_client).status_code == 200
    assert admin_client.get("/admin").status_code == 200
    assert admin_client.get("/admin/focus").status_code == 200

    screen_client = create_app(surface="screen").test_client()
    screen_root = screen_client.get("/")
    assert screen_root.status_code == 302
    assert screen_root.headers["Location"].endswith("/screen")
    assert screen_client.get("/screen").status_code == 200
    assert screen_client.get("/api/display").status_code == 200
    assert screen_client.get("/admin").status_code == 404
    assert screen_client.post("/api/todos", json={"title": "blocked"}).status_code == 404


def test_persona_web_page_renders(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()

    locked = client.get("/admin/persona")
    assert locked.status_code == 302

    login(client)
    page = client.get("/admin/persona")
    assert page.status_code == 200
    assert b"Persona Settings" in page.data
    assert b"Quiet Hours" in page.data
    assert b"todo_rage" in page.data
    assert b"water" in page.data
    assert b"ambient" in page.data


def test_persona_web_save(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    save = client.post(
        "/admin/persona/save",
        data={
            "quiet_start": "22:00",
            "quiet_end": "08:00",
            "interval_water": "60",
            "enabled_water": "1",
            "interval_todo_rage": "5",
            "enabled_todo_rage": "1",
            "interval_ambient": "15",
            "enabled_ambient": "0",
        },
        follow_redirects=True,
    )
    assert save.status_code == 200
    assert b"Persona settings saved" in save.data

    from jiri import persona_settings
    assert persona_settings.get_quiet_start(db_path=str(db_path)) == "22:00"
    assert persona_settings.get_quiet_end(db_path=str(db_path)) == "08:00"
    assert persona_settings.get_interval("water", db_path=str(db_path)) == 60
    assert persona_settings.get_interval("todo_rage", db_path=str(db_path)) == 5
    assert persona_settings.get_interval("ambient", db_path=str(db_path)) == 15
    assert persona_settings.is_enabled("ambient", db_path=str(db_path)) is False


def test_persona_web_rejects_invalid_values(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    save = client.post(
        "/admin/persona/save",
        data={
            "quiet_start": "99:00",
            "quiet_end": "07:00",
            "interval_water": "60",
            "enabled_water": "1",
        },
        follow_redirects=True,
    )
    assert save.status_code == 200
    assert b"Persona settings saved" not in save.data
    assert b"Time must be between" in save.data or b"error" in save.data


def test_persona_web_nav_link_in_base(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    page = client.get("/admin")
    assert page.status_code == 200
    assert b"/admin/persona" in page.data


def test_db_browser_page_renders(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()

    locked = client.get("/admin/db-browser")
    assert locked.status_code == 302

    login(client)
    page = client.get("/admin/db-browser")
    assert page.status_code == 200
    assert b"Database Browser" in page.data
    assert b"todos" in page.data
    assert b"notes" in page.data
    assert b"settings" in page.data


def test_db_browser_shows_table_data(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    from jiri import todos
    todos.add_todo("Browser test todo", db_path=str(db_path))

    app = create_app()
    client = app.test_client()
    login(client)

    page = client.get("/admin/db-browser?table=todos")
    assert page.status_code == 200
    assert b"Browser test todo" in page.data
    assert b"pending" in page.data


def test_db_browser_handles_bad_limit(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    bad_limit = client.get("/admin/db-browser?table=todos&limit=bad")
    assert bad_limit.status_code == 200
    assert b"limit 100" in bad_limit.data

    negative_limit = client.get("/admin/db-browser?table=todos&limit=-20")
    assert negative_limit.status_code == 200
    assert b"limit 1" in negative_limit.data


def test_db_browser_nav_link_in_base(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")

    app = create_app()
    client = app.test_client()
    login(client)

    page = client.get("/admin")
    assert page.status_code == 200
    assert b"/admin/db-browser" in page.data


def test_ai_page_reports_required_provider_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    app = create_app()
    client = app.test_client()
    login(client)
    page = client.get("/admin/ai", follow_redirects=True)
    assert page.status_code == 200
    assert b"AI Wording" in page.data
    assert b"setup required" in page.data
    assert b"required for a production-ready JIRI" in page.data



def test_web_response_budget_smoke(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")

    app = create_app()
    client = app.test_client()
    login(client)

    budget_ms = {
        "/api/status": 500,
        "/admin/todos": 500,
        "/screen?panel=system": 500,
        "/api/display?panel=system": 500,
    }
    for path, max_ms in budget_ms.items():
        start = time.perf_counter()
        response = client.get(path)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert response.status_code == 200
        assert elapsed_ms < max_ms, f"{path} took {elapsed_ms:.2f}ms"


def test_voice_never_claims_an_empty_list_while_tasks_are_pending(tmp_path):
    """JIRI must not say "zero tasks" next to a watch strip reading 2."""
    from jiri import todos
    from jiri.views import build_screen_snapshot

    db_path = str(tmp_path / "jiri.db")
    todos.add_todo("Verify persistence", db_path=db_path)
    todos.add_todo("Call the bank", db_path=db_path)

    for panel in ("todos", "notes", "system"):
        snapshot = build_screen_snapshot(db_path=db_path, panel=panel)
        spoken = snapshot.headline.lower()
        assert snapshot.face_state == "idle"
        for lie in ("no tasks", "zero tasks", "nothing pending", "list is empty", "all done"):
            assert lie not in spoken, f"{panel} panel said {snapshot.headline!r}"
