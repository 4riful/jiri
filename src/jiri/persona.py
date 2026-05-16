from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from . import db, events, messages, persona_settings, todos, water


LAST_SENT_PREFIX = "persona.last_sent."


@dataclass(frozen=True)
class PersonaMoment:
    category: str
    face_state: str
    headline: str
    subheadline: str
    priority: int
    telegram: bool = False
    interval_minutes: int = 240
    cooldown_key: str = ""


def screen_moment(
    *,
    now: datetime | None = None,
    db_path: str | None = None,
    base_face_state: str = "idle",
    base_headline: str = "System stable.",
    base_subheadline: str = "Nothing urgent.",
    focus_snapshot: dict[str, object] | None = None,
    weather_snapshot: dict[str, object] | None = None,
) -> PersonaMoment:
    current = now or datetime.now()
    focus_snapshot = focus_snapshot or {}
    weather_snapshot = weather_snapshot or {}

    pending = todos.list_todos(include_done=False, db_path=db_path)
    top = pending[0] if pending else None
    top_level = todos.calculate_angry_level(top, current) if top else 0

    if top is not None:
        if top_level >= 1:
            events.emit(
                events.TODO_OVERDUE, f"todo_{top.id}",
                f"Todo '{top.title}' is overdue (level {top_level}).",
                db_path=db_path,
            )
        if top_level >= 5:
            events.emit(
                events.TODO_CRITICAL_OVERDUE, f"todo_{top.id}",
                f"Todo '{top.title}' is critically overdue.",
                db_path=db_path,
            )

    if top is not None and top_level >= 5:
        return PersonaMoment(
            "todo_rage",
            "rage",
            messages.reminder_message(top, angry_level=top_level),
            "Critical overdue state. I am not lowering this emotion.",
            priority=90,
            telegram=True,
            interval_minutes=persona_settings.get_interval("todo_rage", db_path=db_path),
            cooldown_key=f"todo_rage.{top.id}",
        )

    if focus_snapshot.get("active"):
        status = str(focus_snapshot.get("status") or "running")
        progress = float(focus_snapshot.get("progress") or 0)
        session_id = focus_snapshot.get("id")
        if session_id is not None:
            if 0.5 <= progress < 0.9:
                events.emit(
                    events.FOCUS_HALFWAY, f"session_{session_id}",
                    f"Focus '{focus_snapshot.get('title')}' is halfway done. {focus_snapshot.get('remaining_text')} left.",
                    db_path=db_path,
                )
            if progress >= 0.9:
                events.emit(
                    events.FOCUS_ALMOST_DONE, f"session_{session_id}",
                    f"Focus '{focus_snapshot.get('title')}' is almost done. {focus_snapshot.get('remaining_text')} left.",
                    db_path=db_path,
                )
        return PersonaMoment(
            "focus",
            base_face_state if status == "paused" else "focused",
            f"{focus_snapshot.get('title')} · {focus_snapshot.get('remaining_text')}",
            f"Focus {status}. I am guarding the perimeter.",
            priority=80,
            telegram=False,
            interval_minutes=persona_settings.get_interval("focus", db_path=db_path),
        )

    if top is not None:
        if top_level >= 3:
            return PersonaMoment(
                "todo_angry",
                "angry",
                messages.reminder_message(top, angry_level=top_level),
                "Escalation protocol: dramatic eye contact.",
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_angry", db_path=db_path),
                cooldown_key=f"todo_angry.{top.id}",
            )
        if top_level == 2:
            return PersonaMoment(
                "todo_annoyed",
                "annoyed",
                messages.reminder_message(top, angry_level=top_level),
                "Still reversible. Mostly.",
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_annoyed", db_path=db_path),
                cooldown_key=f"todo_annoyed.{top.id}",
            )
        if top_level == 1:
            return PersonaMoment(
                "todo_late",
                "annoyed",
                messages.reminder_message(top, angry_level=top_level),
                "A small nudge, not a court summons.",
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_late", db_path=db_path),
                cooldown_key=f"todo_late.{top.id}",
            )
        if todos.due_soon(current, db_path=db_path):
            return PersonaMoment(
                "todo_due_soon",
                "alert",
                f"Upcoming: {top.title}",
                "This is the polite warning phase.",
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_due_soon", db_path=db_path),
                cooldown_key=f"todo_due_soon.{top.id}",
            )

    if weather_snapshot.get("available") and weather_snapshot.get("rain_chance") is not None:
        rain = int(weather_snapshot.get("rain_chance") or 0)
        temp = weather_snapshot.get("temperature_c")
        if temp is not None and float(temp) >= 34 and 7 <= current.hour <= 20:
            return PersonaMoment(
                "weather_hot",
                "weather_hot",
                f"Heat check: {temp}C.",
                "Hydrate and avoid pretending you are solar-powered.",
                priority=50,
                telegram=True,
                interval_minutes=persona_settings.get_interval("weather_hot", db_path=db_path),
            )
        if rain >= 70 and 7 <= current.hour <= 20:
            return PersonaMoment(
                "weather_rain",
                "weather_rain",
                f"Rain chance is {rain}%.",
                "Umbrella diplomacy recommended.",
                priority=50,
                telegram=True,
                interval_minutes=persona_settings.get_interval("weather_rain", db_path=db_path),
            )

    if _quiet_hours(current, db_path=db_path):
        return PersonaMoment(
            "sleep",
            "sleeping",
            "Night watch mode.",
            "Quiet hours are active. I will keep the pixels calm.",
            priority=10,
            telegram=False,
            interval_minutes=persona_settings.get_interval("sleep", db_path=db_path),
        )

    hydration = water.water_snapshot(db_path=db_path, now=current, reset_daily=False)
    if not hydration.get("complete") and int(hydration.get("remaining_ml") or 0) >= 500 and 9 <= current.hour <= 21:
        return PersonaMoment(
            "water",
            _ambient_face(current, base_face_state),
            f"Water check: {hydration.get('progress_ml')}ml / {hydration.get('goal_ml')}ml.",
            f"{hydration.get('remaining_ml')}ml left. The human plant needs fluid.",
            priority=30,
            telegram=True,
            interval_minutes=persona_settings.get_interval("water", db_path=db_path),
        )

    if todos.recently_completed(current, db_path=db_path):
        return PersonaMoment(
            "celebrate",
            "happy",
            "Task complete. Tiny victory parade scheduled internally.",
            "Momentum detected. Try not to scare it away.",
            priority=40,
            telegram=False,
            interval_minutes=persona_settings.get_interval("celebrate", db_path=db_path),
        )

    return PersonaMoment(
        "ambient",
        _ambient_face(current, base_face_state),
        _ambient_headline(current, base_headline),
        base_subheadline,
        priority=10,
        telegram=False,
        interval_minutes=persona_settings.get_interval("ambient", db_path=db_path),
    )


def due_telegram_moment(now: datetime | None = None, db_path: str | None = None) -> PersonaMoment | None:
    current = now or datetime.now()
    moment = screen_moment(now=current, db_path=db_path)
    if not moment.telegram:
        return None
    if _quiet_hours(current, db_path=db_path) and moment.priority < 70:
        return None
    category = moment.category
    if not persona_settings.is_enabled(category, db_path=db_path):
        return None
    key = moment.cooldown_key or category
    interval = persona_settings.get_interval(category, db_path=db_path)
    if not _interval_elapsed(key, interval, current, db_path=db_path):
        return None
    return moment


def mark_telegram_sent(category: str, now: datetime | None = None, db_path: str | None = None) -> None:
    current = now or datetime.now()
    db.set_setting(_last_sent_key(category), current.replace(microsecond=0).isoformat(), db_path=db_path)


def _interval_elapsed(category: str, minutes: int, now: datetime, db_path: str | None = None) -> bool:
    raw = db.get_setting(_last_sent_key(category), db_path=db_path)
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(raw)
    except ValueError:
        return True
    return now - previous >= timedelta(minutes=minutes)


def _last_sent_key(category: str) -> str:
    return f"{LAST_SENT_PREFIX}{category}"


def _quiet_hours(now: datetime, db_path: str | None = None) -> bool:
    current = now.time()
    raw_start = persona_settings.get_quiet_start(db_path=db_path)
    raw_end = persona_settings.get_quiet_end(db_path=db_path)
    try:
        start_parts = raw_start.split(":")
        end_parts = raw_end.split(":")
        quiet_start = time(int(start_parts[0]), int(start_parts[1]))
        quiet_end = time(int(end_parts[0]), int(end_parts[1]))
    except (ValueError, IndexError):
        quiet_start = time(23, 0)
        quiet_end = time(7, 0)
    return current >= quiet_start or current < quiet_end


def _ambient_face(now: datetime, fallback: str) -> str:
    if now.minute % 17 == 0:
        return "blink"
    if now.minute % 23 == 0:
        return "curious"
    if now.minute % 29 == 0:
        return "smirk"
    return fallback


def _ambient_headline(now: datetime, fallback: str) -> str:
    if now.minute % 29 == 0:
        return "I am not bored. I am conserving sarcasm."
    if now.minute % 23 == 0:
        return "Scanning desk orbit for chaos."
    return fallback
