from __future__ import annotations

from datetime import datetime

from . import db
from .models import Note


def add_note(title: str, body: str, tags: str | None = None, db_path: str | None = None) -> Note:
    clean_title = title.strip()
    clean_body = body.strip()
    if not clean_title:
        raise ValueError("Note title cannot be empty")
    if not clean_body:
        raise ValueError("Note body cannot be empty")
    now = datetime.now().replace(microsecond=0).isoformat()
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO notes(title, body, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clean_title, clean_body, tags, now, now),
        )
        note_id = int(cur.lastrowid)
    return get_note(note_id, db_path=db_path)


def get_note(note_id: int, db_path: str | None = None) -> Note:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"Note {note_id} not found")
    return _row_to_note(row)


def list_notes(db_path: str | None = None) -> list[Note]:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM notes ORDER BY updated_at DESC, id DESC").fetchall()
    return [_row_to_note(row) for row in rows]


def _row_to_note(row) -> Note:
    return Note(
        id=int(row["id"]),
        title=row["title"],
        body=row["body"],
        tags=row["tags"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
