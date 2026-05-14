from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import __version__, db, todos, weather
from .config import AppConfig, load_config
from .system_info import cpu_temperature_c, free_ram_mb


def health_snapshot(db_path: str | None = None, config: AppConfig | None = None) -> dict[str, object]:
    cfg = config or load_config()
    path = db_path or cfg.database.path
    db.init_db(path)
    overdue = todos.get_overdue_todos(datetime.now(), db_path=path)
    weather_snapshot = weather.get_weather(db_path=path)
    return {
        "app_version": __version__,
        "database_path": path,
        "database_writable": _is_writable(path),
        "todos_count": len(todos.list_todos(include_done=True, db_path=path)),
        "overdue_count": len(overdue),
        "weather_cache_status": "unavailable" if weather_snapshot.unavailable else "available",
        "display": {
            "driver": cfg.display.driver,
            "width": cfg.display.width,
            "height": cfg.display.height,
            "fullscreen": cfg.display.fullscreen,
            "fps": cfg.display.fps,
        },
        "web": {"host": cfg.web.host, "port": cfg.web.port},
        "free_ram_mb": free_ram_mb(),
        "cpu_temperature_c": cpu_temperature_c(),
        "worker": "enabled" if cfg.worker.enabled else "disabled",
    }


def format_health(snapshot: dict[str, object]) -> str:
    display = snapshot["display"]
    web = snapshot["web"]
    assert isinstance(display, dict)
    assert isinstance(web, dict)
    return "\n".join(
        [
            f"app version: {snapshot['app_version']}",
            f"database path: {snapshot['database_path']}",
            f"database writable: {'yes' if snapshot['database_writable'] else 'no'}",
            f"todos count: {snapshot['todos_count']}",
            f"overdue count: {snapshot['overdue_count']}",
            f"weather cache status: {snapshot['weather_cache_status']}",
            f"display config: {display['driver']} {display['width']}x{display['height']} fullscreen={display['fullscreen']} fps={display['fps']}",
            f"web config: {web['host']}:{web['port']}",
            f"free RAM MB: {snapshot['free_ram_mb'] if snapshot['free_ram_mb'] is not None else 'unknown'}",
            f"CPU temperature C: {snapshot['cpu_temperature_c'] if snapshot['cpu_temperature_c'] is not None else 'unknown'}",
            f"worker: {snapshot['worker']}",
        ]
    )


def _is_writable(path: str) -> bool:
    db_path = Path(path)
    if db_path.exists():
        return db_path.is_file() and os_access_write(db_path)
    parent = db_path.parent if str(db_path.parent) != "" else Path(".")
    return parent.exists() and os_access_write(parent)


def os_access_write(path: Path) -> bool:
    import os

    return os.access(path, os.W_OK)
