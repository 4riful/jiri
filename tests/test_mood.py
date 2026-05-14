from __future__ import annotations

from datetime import datetime, timedelta

from jiri import mood, todos


def test_no_pending_tasks_idle(tmp_path):
    assert mood.calculate_mood(datetime(2026, 5, 14, 21, 0), db_path=str(tmp_path / "jiri.db")) == "idle"


def test_due_soon_alert(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 14, 21, 0)
    todos.add_todo("Soon", due_at=now + timedelta(minutes=5), db_path=db_path)
    assert mood.calculate_mood(now, db_path=db_path) == "alert"


def test_overdue_mood_mapping(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 14, 21, 0)
    todo = todos.add_todo("Late", due_at=now - timedelta(minutes=11), db_path=db_path)
    assert todos.calculate_angry_level(todo, now) == 2
    assert mood.calculate_mood(now, db_path=db_path) == "angry"


def test_rage_for_level_three_or_more(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 14, 21, 0)
    todos.add_todo("Very late", due_at=now - timedelta(minutes=31), db_path=db_path)
    assert mood.calculate_mood(now, db_path=db_path) == "rage"


def test_recently_completed_happy(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime.now().replace(microsecond=0)
    todo = todos.add_todo("Done", db_path=db_path)
    todos.mark_done(todo.id, db_path=db_path)
    assert mood.calculate_mood(now, db_path=db_path) == "happy"
