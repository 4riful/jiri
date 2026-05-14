from __future__ import annotations

from jiri import cli


def test_cli_init_todo_list_done_status_and_health(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)

    assert cli.main(["init-db"]) == 0
    assert "Initialized database" in capsys.readouterr().out

    assert cli.main(["todo", "add", "Task title", "--due", "2026-05-14 21:00"]) == 0
    assert "Added todo #1" in capsys.readouterr().out

    assert cli.main(["todo", "list"]) == 0
    out = capsys.readouterr().out
    assert "#1 [pending]" in out
    assert "Task title" in out

    assert cli.main(["todo", "done", "1"]) == 0
    assert "Done todo #1" in capsys.readouterr().out

    assert cli.main(["status"]) == 0
    assert "app version:" in capsys.readouterr().out

    assert cli.main(["health"]) == 0
    assert "database writable: yes" in capsys.readouterr().out


def test_cli_note_add_and_list(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)
    assert cli.main(["note", "add", "Title", "--body", "Body"]) == 0
    assert "Added note #1: Title" in capsys.readouterr().out

    assert cli.main(["note", "list"]) == 0
    assert "#1 Title" in capsys.readouterr().out


def test_cli_weather_refresh_uses_cache_fallback_system(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)
    assert cli.main(["location", "set-coords", "--name", "Home", "--lat", "26.1167", "--lon", "88.85"]) == 0
    capsys.readouterr()

    def fake_refresh(db_path=None):
        return {
            "source": "open_meteo",
            "location": "Home",
            "temperature_c": 31.0,
            "feels_like_c": 35.0,
            "condition": "Partly cloudy",
            "humidity": 70,
            "rain_chance": 40,
            "wind_kmh": 12.0,
            "location_meta": {"latitude": 26.1167, "longitude": 88.85, "country": "Bangladesh", "country_code": "BD", "admin1": "Rangpur Division", "admin2": "Panchagarh District", "admin3": "Panchagarh Sadar"},
            "fetched_at": "2026-05-14T21:00:00",
            "message": "Weather online.",
        }

    monkeypatch.setattr(cli.weather, "refresh_weather", fake_refresh)
    assert cli.main(["weather", "refresh"]) == 0
    out = capsys.readouterr().out
    assert "weather source: open_meteo" in out
    assert "location: Home" in out
    assert "coordinates: 26.1167, 88.85" in out
    assert "country: Bangladesh (BD)" in out
    assert "condition: Partly cloudy" in out


def test_cli_location_set_coords_and_current(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)

    assert cli.main(["location", "set-coords", "--name", "Home", "--lat", "26.1167", "--lon", "88.85"]) == 0
    assert "Selected weather coordinates" in capsys.readouterr().out

    assert cli.main(["location", "current"]) == 0
    out = capsys.readouterr().out
    assert "source: settings" in out
    assert "name: Home" in out
    assert "coordinates: 26.1167, 88.85" in out


def test_cli_location_search_and_set(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)

    def fake_search(query, country=None, timeout_seconds=3):
        assert query == "panchagarh"
        assert country == "BD"
        return [
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
        ]

    monkeypatch.setattr(cli.weather, "search_locations", fake_search)
    assert cli.main(["location", "search", "panchagarh", "--country", "BD"]) == 0
    out = capsys.readouterr().out
    assert "1. Panchagarh" in out
    assert "Division: Rangpur Division" in out

    assert cli.main(["location", "set", "1"]) == 0
    out = capsys.readouterr().out
    assert "Selected weather location" in out
    assert "Panchagarh" in out


def test_cli_rejects_empty_todo_title(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)
    assert cli.main(["todo", "add", "   "]) == 2
    err = capsys.readouterr().err
    assert "Error:" in err
    assert "title" in err


def test_cli_rejects_invalid_due_date(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "jiri.db"
    _cli_env(monkeypatch, tmp_path, db_path)
    assert cli.main(["todo", "add", "Bad date", "--due", "tomorrow-ish"]) == 2
    err = capsys.readouterr().err
    assert "Error:" in err
    assert "Date must use ISO format" in err


def _cli_env(monkeypatch, tmp_path, db_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "false")
