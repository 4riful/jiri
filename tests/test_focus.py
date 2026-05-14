from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jiri import db, focus


def test_focus_start_pause_resume_complete_without_tick_writes(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    start = datetime(2026, 5, 15, 9, 0, 0)

    session = focus.start_focus(25, title="Deep work", db_path=db_path, now=start)
    assert session.status == "running"
    assert session.duration_seconds == 1500

    snapshot = focus.active_snapshot(db_path=db_path, now=start + timedelta(minutes=5))
    assert snapshot["remaining_seconds"] == 1200
    assert snapshot["remaining_text"] == "20:00"

    paused = focus.pause_session(db_path=db_path, now=start + timedelta(minutes=5))
    assert paused.status == "paused"
    assert paused.elapsed_seconds == 300

    still_paused = focus.active_snapshot(db_path=db_path, now=start + timedelta(minutes=10))
    assert still_paused["remaining_seconds"] == 1200

    resumed = focus.resume_session(db_path=db_path, now=start + timedelta(minutes=11))
    assert resumed.status == "running"

    completed = focus.complete_session(db_path=db_path, now=start + timedelta(minutes=31))
    assert completed.status == "completed"
    assert completed.elapsed_seconds == 1500
    assert focus.active_snapshot(db_path=db_path)["active"] is False


def test_focus_rejects_second_active_session(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    focus.start_focus(25, db_path=db_path)
    with pytest.raises(ValueError, match="already active"):
        focus.start_break(5, db_path=db_path)


def test_focus_cancel_and_history(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    session = focus.start_break(5, db_path=db_path)
    cancelled = focus.cancel_session(db_path=db_path)
    assert cancelled.id == session.id
    assert cancelled.status == "cancelled"
    history = focus.list_sessions(db_path=db_path)
    assert len(history) == 1
    assert history[0].status == "cancelled"


def test_schema_includes_focus_sessions(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    db.init_db(db_path)
    assert db.count_rows("focus_sessions", db_path=db_path) == 0
