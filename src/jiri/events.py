from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from . import db


FOCUS_HALFWAY = "focus.halfway"
FOCUS_ALMOST_DONE = "focus.almost_done"
TODO_OVERDUE = "todo.overdue"
TODO_CRITICAL_OVERDUE = "todo.critical_overdue"


ALL_TYPES = {FOCUS_HALFWAY, FOCUS_ALMOST_DONE, TODO_OVERDUE, TODO_CRITICAL_OVERDUE}

# Process-local memo of (db, type, key) already recorded. events_log is unique on
# (type, key), so an event is a one-time state change; once we know it is stored
# there is no reason to touch SQLite again for it. Callers run on a timer, so
# without this every tick would open a write transaction just to hit the UNIQUE
# constraint. Bounded so a long-running process cannot grow it forever.
_RECORDED: set[tuple[str, str, str]] = set()
_RECORDED_MAX = 2048


def _memo_key(event_type: str, event_key: str, db_path: str | None) -> tuple[str, str, str]:
    return (db.get_db_path(db_path), event_type, event_key)


def _remember(key: tuple[str, str, str]) -> None:
    if len(_RECORDED) >= _RECORDED_MAX:
        _RECORDED.clear()
    _RECORDED.add(key)


def emit(event_type: str, event_key: str, message: str, db_path: str | None = None) -> bool:
    """Record an event once. Returns True only when a new row was written."""
    if event_type not in ALL_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    memo = _memo_key(event_type, event_key, db_path)
    if memo in _RECORDED:
        return False
    if has_emitted(event_type, event_key, db_path=db_path):
        _remember(memo)
        return False
    now = datetime.now().replace(microsecond=0).isoformat()
    with db.connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO events_log(event_type, event_key, message, created_at) VALUES (?, ?, ?, ?)",
                (event_type, event_key, message, now),
            )
            _remember(memo)
            return True
        except sqlite3.IntegrityError:
            _remember(memo)
            return False


def has_emitted(event_type: str, event_key: str, db_path: str | None = None) -> bool:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM events_log WHERE event_type = ? AND event_key = ? LIMIT 1",
            (event_type, event_key),
        ).fetchone()
    return row is not None


def list_recent(limit: int = 50, db_path: str | None = None) -> list[dict[str, object]]:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_type, event_key, message, created_at FROM events_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "event_type": str(r["event_type"]),
            "event_key": str(r["event_key"]),
            "message": str(r["message"]),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def cleanup(max_age_days: int = 30, db_path: str | None = None) -> int:
    cutoff = (datetime.now() - timedelta(days=max_age_days)).replace(microsecond=0).isoformat()
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM events_log WHERE created_at < ?", (cutoff,))
    removed = int(cur.rowcount)
    if removed:
        # Deleted keys may legitimately fire again (e.g. a reused todo id).
        _RECORDED.clear()
    return removed
