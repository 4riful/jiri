from __future__ import annotations

from datetime import datetime

from . import db


WATER_DATE_KEY = "water.date"
WATER_PROGRESS_KEY = "water.progress_ml"
WATER_GOAL_KEY = "water.goal_ml"
WATER_AGE_KEY = "water.age"
WATER_SEX_KEY = "water.sex"
DEFAULT_SEX = "female"
DEFAULT_GOAL_ML = 2150

# National Academies DRI adequate intakes are total water from food,
# beverages, and drinking water. Use ~80% as a practical drink/fluid target.
DRINK_TARGETS_ML = {
    "child": (
        (3, 1050),
        (8, 1350),
    ),
    "male": (
        (13, 1900),
        (18, 2650),
        (120, 3000),
    ),
    "female": (
        (13, 1700),
        (18, 1850),
        (120, 2150),
    ),
}


def water_snapshot(db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now()
    _reset_if_new_day(db_path=db_path, now=current)
    goal_ml = _goal_ml(db_path=db_path)
    progress_ml = _int_setting(WATER_PROGRESS_KEY, 0, db_path=db_path)
    percent = min(100, int((progress_ml / goal_ml) * 100)) if goal_ml > 0 else 0
    return {
        "date": _today(current),
        "goal_ml": goal_ml,
        "progress_ml": progress_ml,
        "remaining_ml": max(0, goal_ml - progress_ml),
        "percent": percent,
        "age": _optional_int_setting(WATER_AGE_KEY, db_path=db_path),
        "sex": _sex_setting(db_path=db_path),
        "complete": progress_ml >= goal_ml,
        "message": "Hydration goal complete." if progress_ml >= goal_ml else "Keep sipping water.",
    }


def add_water(amount_ml: int, db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    if amount_ml <= 0:
        raise ValueError("Water amount must be positive")
    current = now or datetime.now()
    _reset_if_new_day(db_path=db_path, now=current)
    progress = _int_setting(WATER_PROGRESS_KEY, 0, db_path=db_path) + amount_ml
    db.set_setting(WATER_PROGRESS_KEY, str(progress), db_path=db_path)
    return water_snapshot(db_path=db_path, now=current)


def set_goal(goal_ml: int, db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    if goal_ml < 250 or goal_ml > 6000:
        raise ValueError("Water goal must be between 250ml and 6000ml")
    db.set_setting(WATER_GOAL_KEY, str(goal_ml), db_path=db_path)
    return water_snapshot(db_path=db_path, now=now)


def set_goal_by_profile(age: int, sex: str, db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    if age < 1 or age > 120:
        raise ValueError("Age must be between 1 and 120")
    normalized_sex = _normalize_sex(sex)
    db.set_setting(WATER_AGE_KEY, str(age), db_path=db_path)
    db.set_setting(WATER_SEX_KEY, normalized_sex, db_path=db_path)
    db.set_setting(WATER_GOAL_KEY, str(goal_for_profile(age, normalized_sex)), db_path=db_path)
    return water_snapshot(db_path=db_path, now=now)


def reset_water(db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now()
    db.set_setting(WATER_DATE_KEY, _today(current), db_path=db_path)
    db.set_setting(WATER_PROGRESS_KEY, "0", db_path=db_path)
    return water_snapshot(db_path=db_path, now=current)


def goal_for_profile(age: int, sex: str) -> int:
    normalized_sex = _normalize_sex(sex)
    if age <= 3:
        return DRINK_TARGETS_ML["child"][0][1]
    if age <= 8:
        return DRINK_TARGETS_ML["child"][1][1]
    for max_age, goal_ml in DRINK_TARGETS_ML[normalized_sex]:
        if age <= max_age:
            return goal_ml
    return DEFAULT_GOAL_ML


def _reset_if_new_day(db_path: str | None = None, now: datetime | None = None) -> None:
    current = now or datetime.now()
    today = _today(current)
    saved = db.get_setting(WATER_DATE_KEY, db_path=db_path)
    if saved == today:
        return
    db.set_setting(WATER_DATE_KEY, today, db_path=db_path)
    db.set_setting(WATER_PROGRESS_KEY, "0", db_path=db_path)


def _goal_ml(db_path: str | None = None) -> int:
    return _int_setting(WATER_GOAL_KEY, DEFAULT_GOAL_ML, db_path=db_path)


def _sex_setting(db_path: str | None = None) -> str:
    value = db.get_setting(WATER_SEX_KEY, db_path=db_path)
    if value is None or value == "":
        return DEFAULT_SEX
    try:
        return _normalize_sex(value)
    except ValueError:
        return DEFAULT_SEX


def _normalize_sex(sex: str) -> str:
    normalized = sex.strip().lower()
    if normalized not in {"male", "female"}:
        raise ValueError("Sex must be male or female")
    return normalized


def _today(now: datetime) -> str:
    return now.date().isoformat()


def _int_setting(key: str, default: int, db_path: str | None = None) -> int:
    value = db.get_setting(key, db_path=db_path)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional_int_setting(key: str, db_path: str | None = None) -> int | None:
    value = db.get_setting(key, db_path=db_path)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
