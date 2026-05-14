from __future__ import annotations

from pathlib import Path
import sqlite3

from .config import load_config


SCHEMA_VERSION = "1"


def get_db_path(db_path: str | None = None) -> str:
    return db_path or load_config().database.path


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = Path(get_db_path(db_path))
    if path.parent and str(path.parent) != ".":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                due_at TEXT,
                status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'cancelled')),
                priority INTEGER DEFAULT 2,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                angry_level INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS weather_cache (
                id INTEGER PRIMARY KEY,
                location TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                temperature_c REAL,
                condition TEXT,
                humidity INTEGER,
                rain_chance INTEGER,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_todos_status_due ON todos(status, due_at);
            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
            CREATE INDEX IF NOT EXISTS idx_weather_location_fetched ON weather_cache(location, fetched_at);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def count_rows(table: str, db_path: str | None = None) -> int:
    if table not in {"todos", "notes", "weather_cache", "settings", "events_log"}:
        raise ValueError("Unsupported table")
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])
