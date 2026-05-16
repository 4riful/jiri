from __future__ import annotations

from datetime import datetime, timedelta

from jiri import db, persona, persona_settings, todos, water


def test_persona_quiet_hours_sleeping(tmp_path):
    moment = persona.screen_moment(now=datetime(2026, 5, 15, 23, 30), db_path=str(tmp_path / "jiri.db"))
    assert moment.category == "sleep"
    assert moment.face_state == "sleeping"
    assert moment.telegram is False


def test_persona_escalates_late_todos_to_telegram(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late task", due_at=now - timedelta(minutes=12), db_path=db_path)

    moment = persona.screen_moment(now=now, db_path=db_path)

    assert moment.category == "todo_annoyed"
    assert moment.face_state == "annoyed"
    assert moment.telegram is True


def test_persona_rate_limits_telegram_categories(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late task", due_at=now - timedelta(minutes=12), db_path=db_path)

    first = persona.due_telegram_moment(now=now, db_path=db_path)
    assert first is not None
    persona.mark_telegram_sent(first.cooldown_key or first.category, now=now, db_path=db_path)
    assert persona.due_telegram_moment(now=now + timedelta(minutes=5), db_path=db_path) is None
    assert persona.due_telegram_moment(now=now + timedelta(minutes=11), db_path=db_path) is not None


def test_persona_uses_per_task_overdue_cooldowns(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todo_one = todos.add_todo("Late one", due_at=now - timedelta(minutes=12), priority=1, db_path=db_path)
    todos.add_todo("Late two", due_at=now - timedelta(minutes=12), priority=2, db_path=db_path)

    first = persona.due_telegram_moment(now=now, db_path=db_path)
    assert first is not None
    persona.mark_telegram_sent(first.cooldown_key or first.category, now=now, db_path=db_path)
    todos.mark_done(todo_one.id, db_path=db_path)

    second = persona.due_telegram_moment(now=now + timedelta(minutes=1), db_path=db_path)
    assert second is not None
    assert second.cooldown_key != first.cooldown_key


def test_persona_focus_priority_beats_non_severe_overdue(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late task", due_at=now - timedelta(minutes=35), db_path=db_path)

    moment = persona.screen_moment(
        now=now,
        db_path=db_path,
        focus_snapshot={"active": True, "status": "running", "title": "Deep work", "remaining_text": "12:00"},
    )

    assert moment.category == "focus"
    assert moment.face_state == "focused"


def test_persona_severe_overdue_beats_focus_and_quiet_hours(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 23, 30)
    todos.add_todo("Very late task", due_at=now - timedelta(minutes=130), db_path=db_path)

    moment = persona.screen_moment(
        now=now,
        db_path=db_path,
        focus_snapshot={"active": True, "status": "running", "title": "Deep work", "remaining_text": "12:00"},
    )

    assert moment.category == "todo_rage"
    assert moment.face_state == "rage"
    assert moment.priority == 90


def test_persona_water_nudge_is_daytime_and_spaced(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    water.set_goal(2000, db_path=db_path, now=datetime(2026, 5, 15, 9, 0))

    moment = persona.screen_moment(now=datetime(2026, 5, 15, 14, 0), db_path=db_path)

    assert moment.category == "water"
    assert "Water check" in moment.headline


def test_persona_screen_check_does_not_reset_water_day(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    db.set_setting(water.WATER_DATE_KEY, "2026-05-14", db_path=db_path)

    persona.screen_moment(now=datetime(2026, 5, 15, 14, 0), db_path=db_path)

    assert db.get_setting(water.WATER_DATE_KEY, db_path=db_path) == "2026-05-14"


def test_persona_weather_hot_and_rain_faces(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    water.add_water(3000, db_path=db_path, now=datetime(2026, 5, 15, 10, 0))

    hot = persona.screen_moment(
        now=datetime(2026, 5, 15, 14, 0),
        db_path=db_path,
        weather_snapshot={"available": True, "temperature_c": 35, "rain_chance": 20},
    )
    rain = persona.screen_moment(
        now=datetime(2026, 5, 15, 14, 0),
        db_path=db_path,
        weather_snapshot={"available": True, "temperature_c": 25, "rain_chance": 75},
    )

    assert hot.category == "weather_hot"
    assert hot.face_state == "weather_hot"
    assert rain.category == "weather_rain"
    assert rain.face_state == "weather_rain"


def test_persona_ambient_face_variation(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    water.add_water(3000, db_path=db_path, now=datetime(2026, 5, 15, 10, 0))
    moment = persona.screen_moment(now=datetime(2026, 5, 15, 10, 23), db_path=db_path, base_face_state="idle")
    assert moment.face_state == "curious"
    assert "Scanning" in moment.headline


def test_persona_settings_defaults(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    settings = persona_settings.load_all(db_path=db_path)
    assert settings["quiet_start"] == "23:00"
    assert settings["quiet_end"] == "07:00"
    for cat in persona_settings.CATEGORIES:
        assert settings["categories"][cat]["enabled"] is True
        assert isinstance(settings["categories"][cat]["interval"], int)


def test_persona_settings_set_and_get_quiet_hours(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    persona_settings.set_quiet_hours("22:00", "08:00", db_path=db_path)
    assert persona_settings.get_quiet_start(db_path=db_path) == "22:00"
    assert persona_settings.get_quiet_end(db_path=db_path) == "08:00"


def test_persona_settings_invalid_time_rejected(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    try:
        persona_settings.set_quiet_hours("25:00", "07:00", db_path=db_path)
        assert False
    except ValueError:
        pass
    try:
        persona_settings.set_quiet_hours("23:00", "99:00", db_path=db_path)
        assert False
    except ValueError:
        pass
    try:
        persona_settings.set_quiet_hours("not-a-time", "07:00", db_path=db_path)
        assert False
    except ValueError:
        pass


def test_persona_settings_set_and_get_interval(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    persona_settings.set_interval("water", 90, db_path=db_path)
    assert persona_settings.get_interval("water", db_path=db_path) == 90


def test_persona_settings_invalid_interval_rejected(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    try:
        persona_settings.set_interval("water", -1, db_path=db_path)
        assert False
    except ValueError:
        pass
    try:
        persona_settings.set_interval("water", 9999, db_path=db_path)
        assert False
    except ValueError:
        pass


def test_persona_settings_unknown_category_raises(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    try:
        persona_settings.get_interval("nonexistent", db_path=db_path)
        assert False
    except ValueError:
        pass


def test_persona_settings_enable_disable(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    assert persona_settings.is_enabled("water", db_path=db_path) is True
    persona_settings.set_enabled("water", False, db_path=db_path)
    assert persona_settings.is_enabled("water", db_path=db_path) is False
    persona_settings.set_enabled("water", True, db_path=db_path)
    assert persona_settings.is_enabled("water", db_path=db_path) is True


def test_persona_disabled_category_suppresses_telegram(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late task", due_at=now - timedelta(minutes=12), db_path=db_path)
    persona_settings.set_enabled("todo_annoyed", False, db_path=db_path)
    moment = persona.due_telegram_moment(now=now, db_path=db_path)
    assert moment is None


def test_persona_overridden_interval_shown_in_moment(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 15, 10, 0)
    todos.add_todo("Late task", due_at=now - timedelta(minutes=12), db_path=db_path)
    persona_settings.set_interval("todo_annoyed", 99, db_path=db_path)
    moment = persona.screen_moment(now=now, db_path=db_path)
    assert moment.category == "todo_annoyed"
    assert moment.interval_minutes == 99


def test_persona_water_interval_override(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    persona_settings.set_interval("water", 45, db_path=db_path)
    from jiri import water
    water.set_goal(2000, db_path=db_path, now=datetime(2026, 5, 15, 9, 0))
    moment = persona.screen_moment(now=datetime(2026, 5, 15, 14, 0), db_path=db_path)
    assert moment.category == "water"
    assert moment.interval_minutes == 45
