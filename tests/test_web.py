from __future__ import annotations

from jiri import weather
from jiri.web import create_app


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
        "/todos",
        data={"title": "Browser todo", "due_at": "2026-05-14 21:00", "description": "From the web", "priority": "2"},
        follow_redirects=True,
    )
    assert todo_page.status_code == 200
    assert b"Browser todo" in todo_page.data

    done_page = client.post("/todos/1/done", follow_redirects=True)
    assert done_page.status_code == 200
    assert b"done" in done_page.data

    update_page = client.post(
        "/todos/1/update",
        data={"title": "Updated browser todo", "due_at": "2026-05-15 09:30", "description": "Edited from the web", "priority": "1"},
        follow_redirects=True,
    )
    assert update_page.status_code == 200
    assert b"Updated browser todo" in update_page.data

    note_page = client.post(
        "/notes",
        data={"title": "Browser note", "body": "Keep the Pi footprint small.", "tags": "browser,pi"},
        follow_redirects=True,
    )
    assert note_page.status_code == 200
    assert b"Browser note" in note_page.data

    note_update = client.post(
        "/notes/1/update",
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

    search_page = client.post("/weather/search", data={"query": "panchagarh", "country": "BD"}, follow_redirects=True)
    assert search_page.status_code == 200
    assert b"Panchagarh" in search_page.data

    coords_page = client.post(
        "/weather/set-coords",
        data={"name": "Home", "lat": "26.1167", "lon": "88.85"},
        follow_redirects=True,
    )
    assert coords_page.status_code == 200
    assert b"Home" in coords_page.data

    refresh_page = client.post("/weather/refresh", follow_redirects=True)
    assert refresh_page.status_code == 200
    assert b"Fake partly cloudy" in refresh_page.data

    weather_page = client.get("/weather")
    assert weather_page.status_code == 200
    assert b"Current Weather" in weather_page.data


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

    client.post("/weather/set-coords", data={"name": "Home", "lat": "26.1167", "lon": "88.85"})
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

    admin_start = client.post("/focus/start", data={"title": "Browser focus", "minutes": "1"}, follow_redirects=True)
    assert admin_start.status_code == 200
    assert b"Browser focus" in admin_start.data

    screen = client.get("/screen?panel=focus")
    assert screen.status_code == 200
    assert b"Browser focus" in screen.data

    admin_cancel = client.post("/focus/cancel", follow_redirects=True)
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

    bad_todo = client.post("/api/todos", json={"title": "   "})
    assert bad_todo.status_code == 400
    assert "title" in bad_todo.json["error"]

    bad_note = client.post("/api/notes", json={"title": "Note", "body": "   "})
    assert bad_note.status_code == 400
    assert "body" in bad_note.json["error"]
