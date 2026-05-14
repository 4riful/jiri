from __future__ import annotations

import time

from jiri import weather
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
    assert b"JIRI Status" in logged_in.data
    assert b"Dashboard" in logged_in.data
    assert b"Focus" in logged_in.data

    screen = client.get("/screen")
    assert screen.status_code == 200
    assert b"LIVE SCREEN" in screen.data

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
    assert b"Current Weather" in weather_page.data
    assert b"Hourly Forecast" in weather_page.data
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
