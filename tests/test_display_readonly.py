"""The display path must not touch the network or write SQLite (AGENTS.md).

`JiriRuntime.screen_snapshot()` is polled by the pygame frame loop and the
/screen mirror. Those side effects live in `JiriRuntime.tick_background()`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import socket
import sqlite3

import pytest
import requests

from jiri import ai, events, focus, messages, persona, todos, weather
from jiri.config import AppConfig, DisplayConfig
from jiri.runtime import JiriRuntime
from jiri.views import SCREEN_PANELS


def _forbid_network(monkeypatch, error: type[BaseException] = AssertionError) -> list[str]:
    calls: list[str] = []

    def boom(*args, **kwargs):
        calls.append(repr(args[:2]))
        raise error("network access from the display path")

    monkeypatch.setattr(requests.sessions.Session, "request", boom)
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    return calls


def _quiet_ai(monkeypatch) -> None:
    # ai.line()/ai.pick() record cache misses with an UPSERT (owned by ai.py, out of scope
    # here). Stub it so this test measures the modules that build the snapshot.
    monkeypatch.setattr(ai, "line", lambda *a, **k: None)
    monkeypatch.setattr(ai, "pick", lambda *a, **k: None)


def _db_fingerprint(db_path: str) -> tuple[str, float]:
    conn = sqlite3.connect(db_path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()
    return dump, os.stat(db_path).st_mtime_ns


def _data_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA data_version").fetchone()[0])


@pytest.fixture()
def busy_runtime(tmp_path, monkeypatch):
    """A world where every side effect *would* fire if the display allowed it."""
    # CI sets JIRI_WEATHER_FAKE=true, which would stop the background tick from
    # ever trying the network; this test is about that attempt.
    monkeypatch.delenv("JIRI_WEATHER_FAKE", raising=False)
    db_path = str(tmp_path / "jiri.db")
    cfg = AppConfig(display=DisplayConfig(driver="mock", fullscreen=False, width=480, height=320))
    runtime = JiriRuntime.load(config=cfg, db_path=db_path)
    ai.ensure_schema(db_path)
    now = datetime.now().replace(microsecond=0)
    todos.add_todo("Way late", due_at=now - timedelta(minutes=150), db_path=db_path)
    todos.add_todo("Bit late", due_at=now - timedelta(minutes=12), db_path=db_path)
    focus.start_focus(1, title="Short sprint", db_path=db_path)
    weather.set_coordinates("Testville", 23.8, 90.4, db_path=db_path)
    location = weather.get_active_location(db_path=db_path, config=cfg)
    stale = (now - timedelta(days=2)).isoformat()
    weather.save_weather_cache(
        weather.location_label(location),
        {"available": True, "temperature_c": 30.0, "condition": "Clear", "rain_chance": 10, "fetched_at": stale},
        db_path=db_path,
    )
    return runtime, now


def test_screen_snapshot_makes_no_http_request_and_no_db_write(busy_runtime, monkeypatch):
    runtime, now = busy_runtime
    calls = _forbid_network(monkeypatch)
    _quiet_ai(monkeypatch)

    watcher = sqlite3.connect(runtime.db_path)
    before_version = _data_version(watcher)
    before = _db_fingerprint(runtime.db_path)

    # Every panel, plus a moment when the focus session has expired and the water
    # day has rolled over: both used to trigger writes from the snapshot.
    for panel in SCREEN_PANELS:
        snap = runtime.screen_snapshot(panel=panel)
    later = runtime.screen_snapshot(now=now + timedelta(days=1, minutes=5))

    assert calls == []
    assert _data_version(watcher) == before_version
    assert _db_fingerprint(runtime.db_path) == before
    watcher.close()

    # The stale cache is shown as-is rather than refreshed.
    assert snap.weather.get("available") is True
    assert snap.weather.get("source") == "cache"
    assert snap.face_state == "rage"
    assert later.focus.get("just_finished") is True
    assert events.list_recent(db_path=runtime.db_path) == []


def test_tick_background_does_the_side_effects_once(busy_runtime, monkeypatch):
    runtime, now = busy_runtime
    # Offline: the worker is allowed to try the network; it must survive failing.
    calls = _forbid_network(monkeypatch, requests.ConnectionError)
    _quiet_ai(monkeypatch)

    first = runtime.tick_background(now=now)
    assert calls, "the background tick is where stale weather gets refreshed"
    assert first["weather_source"] == "cache"
    assert first["events_written"] == 2  # todo.overdue + todo.critical_overdue
    kinds = {row["event_type"] for row in events.list_recent(db_path=runtime.db_path)}
    assert kinds == {events.TODO_OVERDUE, events.TODO_CRITICAL_OVERDUE}

    # Unchanged state -> the second tick writes nothing at all (events are
    # deduplicated; the failed weather refresh is inside its retry window).
    watcher = sqlite3.connect(runtime.db_path)
    before_version = _data_version(watcher)
    second = runtime.tick_background(now=now)
    assert second["events_written"] == 0
    assert _data_version(watcher) == before_version
    watcher.close()


def test_dashboard_path_still_refreshes_weather(busy_runtime, monkeypatch):
    runtime, _now = busy_runtime
    seen: list[str] = []

    def fake_fetch(location, timeout_seconds=3):
        seen.append(str(location.get("name")))
        return {
            "available": True, "location": "Testville", "source": "open-meteo",
            "temperature_c": 31.0, "condition": "Cloudy", "rain_chance": 20,
            "fetched_at": datetime.now().replace(microsecond=0).isoformat(),
        }

    monkeypatch.setattr(weather, "fetch_open_meteo_weather", fake_fetch)
    _quiet_ai(monkeypatch)
    snap = runtime.dashboard_snapshot(panel="weather")
    assert seen, "admin dashboard should keep auto-updating stale weather"
    assert snap.weather.get("condition") == "Cloudy"


# --- The one overdue -> mood table ------------------------------------------

@pytest.mark.parametrize(
    ("late_minutes", "level", "mood", "persona_category"),
    [
        (-5, 0, None, "todo_due_soon"),
        (0, 1, "alert", "todo_late"),
        (9, 1, "alert", "todo_late"),
        (10, 2, "annoyed", "todo_annoyed"),
        (29, 2, "annoyed", "todo_annoyed"),
        (30, 3, "angry", "todo_angry"),
        (60, 4, "angry", "todo_angry"),
        (119, 4, "angry", "todo_angry"),
        (120, 5, "rage", "todo_rage"),
        (600, 5, "rage", "todo_rage"),
    ],
)
def test_overdue_threshold_table_matches_handbook(tmp_path, late_minutes, level, mood, persona_category):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todo = todos.add_todo("Thing", due_at=now - timedelta(minutes=late_minutes), db_path=db_path)

    assert todos.calculate_angry_level(todo, now) == level
    assert todos.overdue_mood(todo, now) == mood
    if mood is not None:
        assert todos.mood_for_level(level) == mood
        assert messages.mood_for_level(level) == mood  # alias, not a second table
        assert todos.calculate_mood(now, db_path=db_path) == mood
    else:
        assert todos.calculate_mood(now, db_path=db_path) == "alert"  # due soon

    moment = persona.screen_moment(now=now, db_path=db_path, emit_events=False)
    assert moment.category == persona_category
    assert moment.face_state == (mood or "alert")


def test_calculate_mood_idle_and_happy(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    assert todos.calculate_mood(datetime(2026, 5, 14, 21, 0), db_path=db_path) == "idle"
    done = todos.add_todo("Done", db_path=db_path)
    todos.mark_done(done.id, db_path=db_path)
    assert todos.calculate_mood(datetime.now().replace(microsecond=0), db_path=db_path) == "happy"


def test_screen_moment_without_emit_is_read_only(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late", due_at=now - timedelta(minutes=200), db_path=db_path)
    persona.screen_moment(now=now, db_path=db_path, emit_events=False)
    assert events.list_recent(db_path=db_path) == []
    persona.screen_moment(now=now, db_path=db_path)  # default keeps old behaviour
    assert len(events.list_recent(db_path=db_path)) == 2
