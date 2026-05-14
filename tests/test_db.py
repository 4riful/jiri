from __future__ import annotations

from jiri import db


def test_database_initializes_and_recreates(tmp_path):
    db_path = tmp_path / "jiri.db"
    db.init_db(str(db_path))
    assert db_path.exists()
    assert db.count_rows("todos", str(db_path)) == 0

    db_path.unlink()
    db.init_db(str(db_path))
    assert db_path.exists()
    assert db.count_rows("settings", str(db_path)) == 1


def test_schema_tables_exist(tmp_path):
    db_path = tmp_path / "jiri.db"
    db.init_db(str(db_path))
    with db.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {row["name"] for row in rows}
    assert {"todos", "notes", "weather_cache", "settings", "events_log"}.issubset(names)
