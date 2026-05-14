from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from . import db
from .models import Todo


VALID_STATUSES = {"pending", "done", "cancelled"}


def add_todo(
    title: str,
    due_at: str | datetime | None = None,
    description: str | None = None,
    priority: int = 2,
    db_path: str | None = None,
) -> Todo:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Todo title cannot be empty")
    due_iso = _normalize_due_at(due_at)
    now = _now_iso()
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO todos(title, description, due_at, status, priority, created_at, updated_at, angry_level)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, 0)
                """,
                (clean_title, description, due_iso, priority, now, now),
            )
            todo_id = int(cur.lastrowid)
        return get_todo(todo_id, db_path=db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise


def get_todo(todo_id: int, db_path: str | None = None) -> Todo:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if row is None:
        raise ValueError(f"Todo {todo_id} not found")
    return _row_to_todo(row)


def list_todos(include_done: bool = False, db_path: str | None = None) -> list[Todo]:
    db.init_db(db_path)
    where = "" if include_done else "WHERE status = 'pending'"
    with db.connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM todos
            {where}
            ORDER BY
                CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                due_at ASC,
                priority ASC,
                id ASC
            """
        ).fetchall()
    return [_row_to_todo(row) for row in rows]


def mark_done(todo_id: int, db_path: str | None = None) -> Todo:
    now = _now_iso()
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            cur = conn.execute(
                """
                UPDATE todos
                SET status = 'done', updated_at = ?, completed_at = ?, angry_level = 0
                WHERE id = ? AND status != 'done'
                """,
                (now, now, todo_id),
            )
            if cur.rowcount == 0:
                exists = conn.execute("SELECT 1 FROM todos WHERE id = ?", (todo_id,)).fetchone()
                if exists is None:
                    raise ValueError(f"Todo {todo_id} not found")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise
    return get_todo(todo_id, db_path=db_path)


def cancel_todo(todo_id: int, db_path: str | None = None) -> Todo:
    now = _now_iso()
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            cur = conn.execute(
                """
                UPDATE todos
                SET status = 'cancelled', updated_at = ?, angry_level = 0
                WHERE id = ? AND status != 'cancelled'
                """,
                (now, todo_id),
            )
            if cur.rowcount == 0:
                exists = conn.execute("SELECT 1 FROM todos WHERE id = ?", (todo_id,)).fetchone()
                if exists is None:
                    raise ValueError(f"Todo {todo_id} not found")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise
    return get_todo(todo_id, db_path=db_path)


def delete_todo(todo_id: int, db_path: str | None = None) -> Todo:
    todo = get_todo(todo_id, db_path=db_path)
    db.init_db(db_path)
    try:
        with db.connect(db_path) as conn:
            conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RuntimeError("Database is busy. Try again in a moment.") from exc
        raise
    return todo


def get_overdue_todos(now: datetime, db_path: str | None = None) -> list[Todo]:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM todos
            WHERE status = 'pending' AND due_at IS NOT NULL AND due_at <= ?
            ORDER BY due_at ASC, priority ASC, id ASC
            """,
            (_to_iso(now),),
        ).fetchall()
    todos = [_row_to_todo(row) for row in rows]
    return [todo for todo in todos if calculate_angry_level(todo, now) > 0]


def calculate_angry_level(todo: Todo, now: datetime) -> int:
    if todo.status != "pending" or not todo.due_at:
        return 0
    due = _parse_datetime(todo.due_at)
    late_by = now - due
    if late_by < timedelta(0):
        return 0
    minutes = late_by.total_seconds() / 60
    if minutes >= 120:
        return 5
    if minutes >= 60:
        return 4
    if minutes >= 30:
        return 3
    if minutes >= 10:
        return 2
    return 1


def refresh_angry_levels(now: datetime | None = None, db_path: str | None = None) -> None:
    current = now or datetime.now()
    pending = list_todos(include_done=False, db_path=db_path)
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        for todo in pending:
            level = calculate_angry_level(todo, current)
            if level != todo.angry_level:
                conn.execute("UPDATE todos SET angry_level = ?, updated_at = ? WHERE id = ?", (level, _to_iso(current), todo.id))


def recently_completed(now: datetime, minutes: int = 10, db_path: str | None = None) -> bool:
    cutoff = now - timedelta(minutes=minutes)
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM todos
            WHERE status = 'done' AND completed_at IS NOT NULL AND completed_at >= ?
            LIMIT 1
            """,
            (_to_iso(cutoff),),
        ).fetchone()
    return row is not None


def due_soon(now: datetime, minutes: int = 10, db_path: str | None = None) -> bool:
    until = now + timedelta(minutes=minutes)
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM todos
            WHERE status = 'pending' AND due_at IS NOT NULL AND due_at > ? AND due_at <= ?
            LIMIT 1
            """,
            (_to_iso(now), _to_iso(until)),
        ).fetchone()
    return row is not None


def _row_to_todo(row) -> Todo:
    return Todo(
        id=int(row["id"]),
        title=row["title"],
        description=row["description"],
        due_at=row["due_at"],
        status=row["status"],
        priority=int(row["priority"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        angry_level=int(row["angry_level"]),
    )


def _normalize_due_at(value: str | datetime | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _to_iso(value)
    return _to_iso(_parse_datetime(value))


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Date must use ISO format like 2026-05-14 21:00") from exc


def _to_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _now_iso() -> str:
    return _to_iso(datetime.now())
