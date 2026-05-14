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

    note_page = client.post(
        "/notes",
        data={"title": "Browser note", "body": "Keep the Pi footprint small.", "tags": "browser,pi"},
        follow_redirects=True,
    )
    assert note_page.status_code == 200
    assert b"Browser note" in note_page.data

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
