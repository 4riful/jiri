from __future__ import annotations

from jiri import todos
from jiri.config import load_config
from jiri.health import format_health, health_snapshot


def test_health_snapshot_contains_required_fields(tmp_path, monkeypatch):
    db_path = tmp_path / "jiri.db"
    monkeypatch.setenv("JIRI_DB_PATH", str(db_path))
    cfg = load_config()
    todos.add_todo("Health todo", db_path=str(db_path))
    snapshot = health_snapshot(db_path=str(db_path), config=cfg)
    assert snapshot["database_writable"] is True
    assert snapshot["todos_count"] == 1
    assert snapshot["worker"] == "disabled"
    text = format_health(snapshot)
    assert "app version:" in text
    assert "database path:" in text
    assert "display config:" in text
