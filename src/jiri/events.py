from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from . import db


FOCUS_HALFWAY = "focus.halfway"
FOCUS_ALMOST_DONE = "focus.almost_done"
TODO_OVERDUE = "todo.overdue"
TODO_CRITICAL_OVERDUE = "todo.critical_overdue"


ALL_TYPES = {FOCUS_HALFWAY, FOCUS_ALMOST_DONE, TODO_OVERDUE, TODO_CRITICAL_OVERDUE}


def emit(event_type: str, event_key: str, message: str, db_path: str | None = None) -> bool:
    if event_type not in ALL_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    db.init_db(db_path)
    now = datetime.now().replace(microsecond=0).isoformat()
    with db.connect(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO events_log(event_type, event_key, message, created_at) VALUES (?, ?, ?, ?)",
                (event_type, event_key, message, now),
            )
            return True
        except sqlite3.IntegrityError:
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
    return int(cur.rowcount)
