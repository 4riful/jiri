from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jiri import todos


def test_add_list_and_done_todo(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    todo = todos.add_todo("  Feed the desk gremlin  ", due_at="2026-05-14 21:00", db_path=db_path)
    assert todo.id == 1
    assert todo.title == "Feed the desk gremlin"
    assert todo.status == "pending"

    listed = todos.list_todos(db_path=db_path)
    assert [item.title for item in listed] == ["Feed the desk gremlin"]

    done = todos.mark_done(todo.id, db_path=db_path)
    assert done.status == "done"
    assert done.completed_at is not None
    assert todos.list_todos(db_path=db_path) == []
    assert len(todos.list_todos(include_done=True, db_path=db_path)) == 1


def test_cancel_todo(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    todo = todos.add_todo("Cancel me", db_path=db_path)
    cancelled = todos.cancel_todo(todo.id, db_path=db_path)
    assert cancelled.status == "cancelled"


def test_empty_title_rejected(tmp_path):
    with pytest.raises(ValueError, match="title"):
        todos.add_todo("   ", db_path=str(tmp_path / "jiri.db"))


def test_invalid_due_date_rejected(tmp_path):
    with pytest.raises(ValueError, match="Date"):
        todos.add_todo("Bad date", due_at="next thursday-ish", db_path=str(tmp_path / "jiri.db"))


@pytest.mark.parametrize(
    ("late_minutes", "expected"),
    [(-1, 0), (0, 1), (9, 1), (10, 2), (30, 3), (60, 4), (120, 5)],
)
def test_angry_levels(tmp_path, late_minutes, expected):
    now = datetime(2026, 5, 14, 21, 0, 0)
    due = now - timedelta(minutes=late_minutes)
    todo = todos.add_todo("Time math", due_at=due, db_path=str(tmp_path / "jiri.db"))
    assert todos.calculate_angry_level(todo, now) == expected


def test_get_overdue_todos(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    now = datetime(2026, 5, 14, 21, 0, 0)
    todos.add_todo("Late", due_at=now - timedelta(minutes=11), db_path=db_path)
    todos.add_todo("Future", due_at=now + timedelta(minutes=5), db_path=db_path)
    overdue = todos.get_overdue_todos(now, db_path=db_path)
    assert [todo.title for todo in overdue] == ["Late"]
