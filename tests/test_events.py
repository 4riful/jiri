from __future__ import annotations

from datetime import datetime

from jiri import db, events, focus, todos


def test_emit_new_event_returns_true(tmp_path):
    db_path = str(tmp_path / "test.db")
    result = events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway there.", db_path=db_path)
    assert result is True


def test_emit_duplicate_event_returns_false(tmp_path):
    db_path = str(tmp_path / "test.db")
    events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway there.", db_path=db_path)
    result = events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway there again.", db_path=db_path)
    assert result is False


def test_has_emitted_true_after_emit(tmp_path):
    db_path = str(tmp_path / "test.db")
    assert events.has_emitted(events.FOCUS_HALFWAY, "session_1", db_path=db_path) is False
    events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway there.", db_path=db_path)
    assert events.has_emitted(events.FOCUS_HALFWAY, "session_1", db_path=db_path) is True


def test_emit_different_keys_are_independent(tmp_path):
    db_path = str(tmp_path / "test.db")
    assert events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway.", db_path=db_path) is True
    assert events.emit(events.FOCUS_HALFWAY, "session_2", "Halfway.", db_path=db_path) is True


def test_emit_different_types_same_key_are_independent(tmp_path):
    db_path = str(tmp_path / "test.db")
    assert events.emit(events.FOCUS_HALFWAY, "session_1", "Halfway.", db_path=db_path) is True
    assert events.emit(events.FOCUS_ALMOST_DONE, "session_1", "Almost.", db_path=db_path) is True


def test_emit_unknown_type_raises(tmp_path):
    db_path = str(tmp_path / "test.db")
    try:
        events.emit("unknown.type", "key", "msg", db_path=db_path)
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_list_recent_returns_events_in_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    events.emit(events.FOCUS_HALFWAY, "s1", "First.", db_path=db_path)
    events.emit(events.FOCUS_ALMOST_DONE, "s1", "Second.", db_path=db_path)
    entries = events.list_recent(db_path=db_path)
    assert len(entries) == 2
    assert entries[0]["event_type"] == events.FOCUS_ALMOST_DONE
    assert entries[1]["event_type"] == events.FOCUS_HALFWAY


def test_list_recent_respects_limit(tmp_path):
    db_path = str(tmp_path / "test.db")
    for i in range(5):
        events.emit(events.FOCUS_HALFWAY, f"s{i}", f"Event {i}.", db_path=db_path)
    entries = events.list_recent(limit=3, db_path=db_path)
    assert len(entries) == 3


def test_cleanup_removes_old_events(tmp_path):
    from datetime import timedelta

    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    old = (datetime.now() - timedelta(days=40)).replace(microsecond=0).isoformat()
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events_log(event_type, event_key, message, created_at) VALUES (?, ?, ?, ?)",
            ("test.type", "old_key", "Old event.", old),
        )
    new_count = events.cleanup(max_age_days=30, db_path=db_path)
    assert new_count == 1
    remaining = events.list_recent(db_path=db_path)
    assert len(remaining) == 0


def test_emit_all_event_types(tmp_path):
    db_path = str(tmp_path / "test.db")
    for t in (events.FOCUS_HALFWAY, events.FOCUS_ALMOST_DONE, events.TODO_OVERDUE, events.TODO_CRITICAL_OVERDUE):
        assert events.emit(t, f"key_{t}", f"Event {t}.", db_path=db_path) is True


def test_persona_emits_focus_halfway(tmp_path):
    from jiri import persona

    db_path = str(tmp_path / "test.db")
    start = datetime(2026, 5, 16, 12, 0, 0)
    halfway_at = datetime(2026, 5, 16, 12, 15, 0)
    f = focus.start_focus(30, title="Half focus", db_path=db_path, now=start)
    snap = focus.active_snapshot(db_path=db_path, now=halfway_at)
    persona.screen_moment(now=halfway_at, db_path=db_path, focus_snapshot=snap)
    assert events.has_emitted(events.FOCUS_HALFWAY, f"session_{f.id}", db_path=db_path) is True


def test_persona_emits_focus_almost_done(tmp_path):
    from jiri import persona

    db_path = str(tmp_path / "test.db")
    start = datetime(2026, 5, 16, 12, 0, 0)
    almost_at = datetime(2026, 5, 16, 12, 27, 0)
    f = focus.start_focus(30, title="Almost focus", db_path=db_path, now=start)
    snap = focus.active_snapshot(db_path=db_path, now=almost_at)
    persona.screen_moment(now=almost_at, db_path=db_path, focus_snapshot=snap)
    assert events.has_emitted(events.FOCUS_ALMOST_DONE, f"session_{f.id}", db_path=db_path) is True


def test_persona_emits_todo_overdue(tmp_path):
    from jiri import persona

    db_path = str(tmp_path / "test.db")
    t = todos.add_todo("Overdue task", due_at="2026-05-15T12:00", db_path=db_path)
    persona.screen_moment(now=datetime(2026, 5, 16, 12, 0, 0), db_path=db_path)
    assert events.has_emitted(events.TODO_OVERDUE, f"todo_{t.id}", db_path=db_path) is True


def test_persona_emits_critical_overdue(tmp_path):
    from jiri import persona

    db_path = str(tmp_path / "test.db")
    t = todos.add_todo("Critical task", due_at="2026-05-14T12:00", db_path=db_path)
    persona.screen_moment(now=datetime(2026, 5, 16, 12, 0, 0), db_path=db_path)
    assert events.has_emitted(events.TODO_CRITICAL_OVERDUE, f"todo_{t.id}", db_path=db_path) is True
