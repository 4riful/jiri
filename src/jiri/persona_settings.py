from __future__ import annotations

from . import db


PREFIX = "persona."

DEFAULT_QUIET_START = "23:00"
DEFAULT_QUIET_END = "07:00"

CATEGORIES = (
    "todo_rage",
    "todo_angry",
    "todo_annoyed",
    "todo_late",
    "todo_due_soon",
    "focus",
    "weather_hot",
    "weather_rain",
    "water",
    "celebrate",
    "ambient",
    "sleep",
)

DEFAULT_INTERVALS: dict[str, int] = {
    "todo_rage": 10,
    "todo_angry": 10,
    "todo_annoyed": 10,
    "todo_late": 10,
    "todo_due_soon": 45,
    "focus": 60,
    "weather_hot": 60,
    "weather_rain": 60,
    "water": 120,
    "celebrate": 60,
    "ambient": 30,
    "sleep": 360,
}

DEFAULT_ENABLED: dict[str, bool] = {c: True for c in CATEGORIES}

INTERVAL_MIN = 1
INTERVAL_MAX = 1440


def get_quiet_start(db_path: str | None = None) -> str:
    return db.get_setting(PREFIX + "quiet_start", db_path=db_path) or DEFAULT_QUIET_START


def get_quiet_end(db_path: str | None = None) -> str:
    return db.get_setting(PREFIX + "quiet_end", db_path=db_path) or DEFAULT_QUIET_END


def set_quiet_hours(start: str, end: str, db_path: str | None = None) -> None:
    _validate_time(start)
    _validate_time(end)
    db.set_setting(PREFIX + "quiet_start", start, db_path=db_path)
    db.set_setting(PREFIX + "quiet_end", end, db_path=db_path)


def get_interval(category: str, db_path: str | None = None) -> int:
    if category not in DEFAULT_INTERVALS:
        raise ValueError(f"Unknown category: {category}")
    raw = db.get_setting(PREFIX + f"interval.{category}", db_path=db_path)
    if raw is not None:
        try:
            val = int(raw)
            if INTERVAL_MIN <= val <= INTERVAL_MAX:
                return val
        except (ValueError, TypeError):
            pass
    return DEFAULT_INTERVALS[category]


def set_interval(category: str, minutes: int, db_path: str | None = None) -> None:
    if category not in DEFAULT_INTERVALS:
        raise ValueError(f"Unknown category: {category}")
    if not isinstance(minutes, int) or minutes < INTERVAL_MIN or minutes > INTERVAL_MAX:
        raise ValueError(f"Interval must be between {INTERVAL_MIN} and {INTERVAL_MAX} minutes")
    db.set_setting(PREFIX + f"interval.{category}", str(minutes), db_path=db_path)


def is_enabled(category: str, db_path: str | None = None) -> bool:
    if category not in DEFAULT_ENABLED:
        raise ValueError(f"Unknown category: {category}")
    raw = db.get_setting(PREFIX + f"enabled.{category}", db_path=db_path)
    if raw is not None:
        return raw in ("1", "true", "yes")
    return DEFAULT_ENABLED[category]


def set_enabled(category: str, enabled: bool, db_path: str | None = None) -> None:
    if category not in DEFAULT_ENABLED:
        raise ValueError(f"Unknown category: {category}")
    db.set_setting(PREFIX + f"enabled.{category}", "1" if enabled else "0", db_path=db_path)


def load_all(db_path: str | None = None) -> dict[str, object]:
    return {
        "quiet_start": get_quiet_start(db_path=db_path),
        "quiet_end": get_quiet_end(db_path=db_path),
        "categories": {
            cat: {
                "interval": get_interval(cat, db_path=db_path),
                "enabled": is_enabled(cat, db_path=db_path),
            }
            for cat in CATEGORIES
        },
    }


def _validate_time(value: str) -> None:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Time must be in HH:MM format")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError("Time must be in HH:MM format")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time must be between 00:00 and 23:59")
