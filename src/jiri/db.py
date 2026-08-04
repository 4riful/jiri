from __future__ import annotations

from pathlib import Path
import sqlite3

from .config import load_config


SCHEMA_VERSION = "4"


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
                event_key TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_type, event_key)
            );

            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('focus', 'break')),
                status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed', 'cancelled')),
                title TEXT NOT NULL,
                todo_id INTEGER,
                duration_seconds INTEGER NOT NULL,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                paused_at TEXT,
                completed_at TEXT,
                cancelled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS water_log (
                id INTEGER PRIMARY KEY,
                day TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                amount_ml INTEGER NOT NULL CHECK (amount_ml > 0)
            );

            CREATE INDEX IF NOT EXISTS idx_todos_status_due ON todos(status, due_at);
            CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
            CREATE INDEX IF NOT EXISTS idx_weather_location_fetched ON weather_cache(location, fetched_at);
            CREATE INDEX IF NOT EXISTS idx_focus_status_updated ON focus_sessions(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_water_log_day_recorded ON water_log(day, recorded_at);
            """
        )
        current_ver = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
        current_ver = str(current_ver["value"]) if current_ver else "0"
        if current_ver != SCHEMA_VERSION:
            _migrate(conn, current_ver)
            conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )


def _migrate(conn, current_ver: str) -> None:
    if current_ver == "2" or (current_ver < "3" and current_ver != "0"):
        conn.executescript("DROP TABLE IF EXISTS events_log;")
        conn.execute(
            """CREATE TABLE events_log (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_key TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_type, event_key)
            )"""
        )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS water_log (
            id INTEGER PRIMARY KEY,
            day TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            amount_ml INTEGER NOT NULL CHECK (amount_ml > 0)
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_water_log_day_recorded ON water_log(day, recorded_at)")


def count_rows(table: str, db_path: str | None = None) -> int:
    if table not in {"todos", "notes", "weather_cache", "settings", "events_log", "focus_sessions", "water_log"}:
        raise ValueError("Unsupported table")
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def get_setting(key: str, db_path: str | None = None) -> str | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_setting(key: str, value: str, db_path: str | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
            (key, value),
        )


def delete_setting(key: str, db_path: str | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
