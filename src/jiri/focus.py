from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from . import db
from .models import FocusSession


ACTIVE_STATUSES = {"running", "paused"}
VALID_KINDS = {"focus", "break"}


def start_focus(
    minutes: int,
    title: str = "Focus session",
    todo_id: int | None = None,
    db_path: str | None = None,
    now: datetime | None = None,
) -> FocusSession:
    return start_session("focus", minutes, title=title, todo_id=todo_id, db_path=db_path, now=now)


def start_break(minutes: int, title: str = "Break", db_path: str | None = None, now: datetime | None = None) -> FocusSession:
    return start_session("break", minutes, title=title, todo_id=None, db_path=db_path, now=now)


def start_session(
    kind: str,
    minutes: int,
    title: str,
    todo_id: int | None = None,
    db_path: str | None = None,
    now: datetime | None = None,
) -> FocusSession:
    clean_kind = kind.strip().lower()
    if clean_kind not in VALID_KINDS:
        raise ValueError("Focus kind must be focus or break")
    clean_title = title.strip() or ("Break" if clean_kind == "break" else "Focus session")
    if minutes < 1:
        raise ValueError("Focus duration must be at least 1 minute")
    current = now or datetime.now()
    now_iso = _to_iso(current)
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            active = conn.execute("SELECT id FROM focus_sessions WHERE status IN ('running', 'paused') LIMIT 1").fetchone()
            if active is not None:
                raise ValueError(f"Focus session {active['id']} is already active")
            cur = conn.execute(
                """
                INSERT INTO focus_sessions(kind, status, title, todo_id, duration_seconds, elapsed_seconds, started_at, created_at, updated_at)
                VALUES (?, 'running', ?, ?, ?, 0, ?, ?, ?)
                """,
                (clean_kind, clean_title, todo_id, minutes * 60, now_iso, now_iso, now_iso),
            )
            session_id = int(cur.lastrowid)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise
    return get_session(session_id, db_path=db_path)


def get_session(session_id: int, db_path: str | None = None) -> FocusSession:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise ValueError(f"Focus session {session_id} not found")
    return _row_to_session(row)


def get_active_session(db_path: str | None = None) -> FocusSession | None:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM focus_sessions
            WHERE status IN ('running', 'paused')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_session(row) if row is not None else None


def list_sessions(limit: int = 20, db_path: str | None = None) -> list[FocusSession]:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM focus_sessions
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_session(row) for row in rows]


def pause_session(session_id: int | None = None, db_path: str | None = None, now: datetime | None = None) -> FocusSession:
    session = _target_session(session_id, db_path=db_path)
    if session.status != "running":
        raise ValueError("Only a running focus session can be paused")
    current = now or datetime.now()
    elapsed = _elapsed_seconds(session, current)
    now_iso = _to_iso(current)
    _update_session(
        session.id,
        "SET status = 'paused', elapsed_seconds = ?, paused_at = ?, started_at = NULL, updated_at = ?",
        (elapsed, now_iso, now_iso),
        db_path=db_path,
    )
    return get_session(session.id, db_path=db_path)


def resume_session(session_id: int | None = None, db_path: str | None = None, now: datetime | None = None) -> FocusSession:
    session = _target_session(session_id, db_path=db_path)
    if session.status != "paused":
        raise ValueError("Only a paused focus session can be resumed")
    if remaining_seconds(session, now=now) <= 0:
        return complete_session(session.id, db_path=db_path, now=now)
    now_iso = _to_iso(now or datetime.now())
    _update_session(
        session.id,
        "SET status = 'running', started_at = ?, paused_at = NULL, updated_at = ?",
        (now_iso, now_iso),
        db_path=db_path,
    )
    return get_session(session.id, db_path=db_path)


def complete_session(session_id: int | None = None, db_path: str | None = None, now: datetime | None = None) -> FocusSession:
    session = _target_session(session_id, db_path=db_path)
    if session.status not in ACTIVE_STATUSES:
        raise ValueError("Only an active focus session can be completed")
    current = now or datetime.now()
    elapsed = min(session.duration_seconds, _elapsed_seconds(session, current))
    now_iso = _to_iso(current)
    _update_session(
        session.id,
        "SET status = 'completed', elapsed_seconds = ?, completed_at = ?, started_at = NULL, paused_at = NULL, updated_at = ?",
        (elapsed, now_iso, now_iso),
        db_path=db_path,
    )
    return get_session(session.id, db_path=db_path)


def cancel_session(session_id: int | None = None, db_path: str | None = None, now: datetime | None = None) -> FocusSession:
    session = _target_session(session_id, db_path=db_path)
    if session.status not in ACTIVE_STATUSES:
        raise ValueError("Only an active focus session can be cancelled")
    current = now or datetime.now()
    elapsed = min(session.duration_seconds, _elapsed_seconds(session, current))
    now_iso = _to_iso(current)
    _update_session(
        session.id,
        "SET status = 'cancelled', elapsed_seconds = ?, cancelled_at = ?, started_at = NULL, paused_at = NULL, updated_at = ?",
        (elapsed, now_iso, now_iso),
        db_path=db_path,
    )
    return get_session(session.id, db_path=db_path)


def active_snapshot(db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    session = get_active_session(db_path=db_path)
    if session is None:
        return {"active": False, "message": "No active focus session."}
    remaining = remaining_seconds(session, now=now)
    elapsed = current_elapsed_seconds(session, now=now)
    progress = 1.0 if session.duration_seconds <= 0 else min(1.0, elapsed / session.duration_seconds)
    return {
        "active": True,
        "id": session.id,
        "kind": session.kind,
        "status": session.status,
        "title": session.title,
        "todo_id": session.todo_id,
        "duration_seconds": session.duration_seconds,
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "remaining_text": format_seconds(remaining),
        "progress": round(progress, 3),
        "message": "Focus running." if session.status == "running" else "Focus paused.",
    }


def current_elapsed_seconds(session: FocusSession, now: datetime | None = None) -> int:
    return min(session.duration_seconds, _elapsed_seconds(session, now or datetime.now()))


def remaining_seconds(session: FocusSession, now: datetime | None = None) -> int:
    return max(0, session.duration_seconds - current_elapsed_seconds(session, now=now))


def format_seconds(seconds: int) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def _target_session(session_id: int | None, db_path: str | None = None) -> FocusSession:
    if session_id is not None:
        return get_session(session_id, db_path=db_path)
    session = get_active_session(db_path=db_path)
    if session is None:
        raise ValueError("No active focus session")
    return session


def _elapsed_seconds(session: FocusSession, now: datetime) -> int:
    elapsed = session.elapsed_seconds
    if session.status == "running" and session.started_at:
        elapsed += max(0, int((now - datetime.fromisoformat(session.started_at)).total_seconds()))
    return max(0, elapsed)


def _update_session(session_id: int, set_clause: str, params: tuple[object, ...], db_path: str | None = None) -> None:
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            conn.execute(f"UPDATE focus_sessions {set_clause} WHERE id = ?", (*params, session_id))
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise


def _row_to_session(row) -> FocusSession:
    return FocusSession(
        id=int(row["id"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        title=str(row["title"]),
        todo_id=int(row["todo_id"]) if row["todo_id"] is not None else None,
        duration_seconds=int(row["duration_seconds"]),
        elapsed_seconds=int(row["elapsed_seconds"]),
        started_at=row["started_at"],
        paused_at=row["paused_at"],
        completed_at=row["completed_at"],
        cancelled_at=row["cancelled_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()
