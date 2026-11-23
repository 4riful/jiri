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
    # Plain fact that produced face_state, for the display to show underneath the
    # face. An expression nobody can explain reads as a glitch, not a reaction.
    reason: str = ""

    @property
    def reason_kind(self) -> str:
        """Which panel this mood is about, so the display can avoid saying it twice."""
        if self.category.startswith("todo"):
            return "todos"
        if self.category.startswith("weather"):
            return "weather"
        if self.category in {"focus", "water"}:
            return self.category
        return ""


def screen_moment(
    *,
    now: datetime | None = None,
    db_path: str | None = None,
    base_face_state: str = "idle",
    base_headline: str = "System stable.",
    base_subheadline: str = "Nothing urgent.",
    focus_snapshot: dict[str, object] | None = None,
    weather_snapshot: dict[str, object] | None = None,
    emit_events: bool = True,
) -> PersonaMoment:
    """Pick what JIRI is reacting to right now.

    With ``emit_events=False`` this is read-only (no SQLite writes from this
    module), which is what the display path uses; event recording then happens
    in :func:`emit_moment_events` from a background tick.
    """
    current = now or datetime.now()
    focus_snapshot = focus_snapshot or {}
    weather_snapshot = weather_snapshot or {}

    if emit_events:
        emit_moment_events(now=current, db_path=db_path, focus_snapshot=focus_snapshot)

    pending = todos.list_todos(include_done=False, db_path=db_path)
    top = pending[0] if pending else None
    top_level = todos.calculate_angry_level(top, current) if top else 0
    top_mood = todos.mood_for_level(top_level) if top_level > 0 else None

    overdue = todos.get_overdue_todos(current, db_path=db_path)
    # One seed per 15-minute window: the display re-reads every second, and the
    # same moment must keep the same words until the window rolls over.
    window = messages.voice_window(current)

    def speak(category: str, mood: str, pool: list[str], slots: dict[str, object] | None = None) -> str:
        return messages.say(category, mood, pool, seed=f"{category}:{window}", slots=slots, db_path=db_path)

    def aside(kind: str, slots: dict[str, object] | None = None) -> str:
        return messages.subheadline(kind, seed=window, slots=slots)

    def remind() -> str:
        return messages.reminder_message(top, angry_level=top_level, db_path=db_path, now=current)

    if top is not None and top_mood == "rage":
        return PersonaMoment(
            "todo_rage",
            "rage",
            remind(),
            aside("todo_rage"),
            priority=90,
            telegram=True,
            interval_minutes=persona_settings.get_interval("todo_rage", db_path=db_path),
            cooldown_key=f"todo_rage.{top.id}",
            reason=_overdue_reason(overdue, top),
        )

    if focus_snapshot.get("active"):
        status = str(focus_snapshot.get("status") or "running")
        return PersonaMoment(
            "focus",
            base_face_state if status == "paused" else "focused",
            speak("focus", "focused", messages.FOCUS_MESSAGES),
            aside("focus_paused" if status == "paused" else "focus"),
            priority=80,
            telegram=False,
            interval_minutes=persona_settings.get_interval("focus", db_path=db_path),
            reason=f"focus {status} · {focus_snapshot.get('remaining_text') or '--:--'} left",
        )

    if top is not None:
        if top_mood == "angry":
            return PersonaMoment(
                "todo_angry",
                "angry",
                remind(),
                aside("todo_angry"),
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_angry", db_path=db_path),
                cooldown_key=f"todo_angry.{top.id}",
                reason=_overdue_reason(overdue, top),
            )
        if top_mood == "annoyed":
            return PersonaMoment(
                "todo_annoyed",
                "annoyed",
                remind(),
                aside("todo_annoyed"),
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_annoyed", db_path=db_path),
                cooldown_key=f"todo_annoyed.{top.id}",
                reason=_overdue_reason(overdue, top),
            )
        if top_mood == "alert":
            # Under 10 minutes late: still the polite "it's due" phase.
            return PersonaMoment(
                "todo_late",
                "alert",
                remind(),
                aside("todo_late"),
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_late", db_path=db_path),
                cooldown_key=f"todo_late.{top.id}",
                reason=_overdue_reason(overdue, top),
            )
        if todos.due_soon(current, db_path=db_path):
            return PersonaMoment(
                "todo_due_soon",
                "alert",
                speak(
                    "todo_due_soon", "alert", messages.DUE_SOON_MESSAGES,
                    {"task": top.title, "minutes": _minutes_until(top, current)},
                ),
                aside("todo_due_soon"),
                priority=70,
                telegram=True,
                interval_minutes=persona_settings.get_interval("todo_due_soon", db_path=db_path),
                cooldown_key=f"todo_due_soon.{top.id}",
                reason=f"due soon · {top.title}",
            )

    if weather_snapshot.get("available") and weather_snapshot.get("rain_chance") is not None:
        rain = int(weather_snapshot.get("rain_chance") or 0)
        temp = weather_snapshot.get("temperature_c")
        if temp is not None and float(temp) >= 34 and 7 <= current.hour <= 20:
            return PersonaMoment(
                "weather_hot",
                "weather_hot",
                speak(
                    "weather_hot", "weather_hot", messages.WEATHER_HOT_MESSAGES,
                    {"temp": round(float(temp)), "condition": weather_snapshot.get("condition") or "sunny"},
                ),
                aside("weather_hot"),
                priority=50,
                telegram=True,
                interval_minutes=persona_settings.get_interval("weather_hot", db_path=db_path),
                reason=f"{round(float(temp))}°C outside",
            )
        if rain >= 70 and 7 <= current.hour <= 20:
            return PersonaMoment(
                "weather_rain",
                "weather_rain",
                speak(
                    "weather_rain", "weather_rain", messages.WEATHER_RAIN_MESSAGES,
                    {
                        "temp": round(float(temp)) if temp is not None else "?",
                        "condition": weather_snapshot.get("condition") or "rain",
                    },
                ),
                aside("weather_rain"),
                priority=50,
                telegram=True,
                interval_minutes=persona_settings.get_interval("weather_rain", db_path=db_path),
                reason=f"{rain}% rain today",
            )

    if _quiet_hours(current, db_path=db_path):
        return PersonaMoment(
            "sleep",
            "sleeping",
            speak("sleep", "sleeping", messages.SLEEP_MESSAGES),
            aside("sleep"),
            priority=10,
            telegram=False,
            interval_minutes=persona_settings.get_interval("sleep", db_path=db_path),
            reason=f"quiet hours until {persona_settings.get_quiet_end(db_path=db_path)}",
        )

    hydration = water.water_snapshot(db_path=db_path, now=current, reset_daily=False)
    if not hydration.get("complete") and int(hydration.get("remaining_ml") or 0) >= 500 and 9 <= current.hour <= 21:
        return PersonaMoment(
            "water",
            base_face_state,
            speak(
                "water", "idle", messages.WATER_MESSAGES,
                {"amount": hydration.get("progress_ml"), "goal": hydration.get("goal_ml")},
            ),
            aside("water", {"remaining": hydration.get("remaining_ml")}),
            priority=30,
            telegram=True,
            interval_minutes=persona_settings.get_interval("water", db_path=db_path),
            reason=f"{hydration.get('remaining_ml')}ml of water left today",
        )

    if todos.recently_completed(current, db_path=db_path):
        return PersonaMoment(
            "celebrate",
            "happy",
            speak("celebrate", "happy", messages.CELEBRATE_MESSAGES),
            aside("celebrate"),
            priority=40,
            telegram=False,
            interval_minutes=persona_settings.get_interval("celebrate", db_path=db_path),
            reason="task completed just now",
        )

    return PersonaMoment(
        "ambient",
        base_face_state,
        base_headline,
        base_subheadline,
        priority=10,
        telegram=False,
        interval_minutes=persona_settings.get_interval("ambient", db_path=db_path),
        reason=_ambient_reason(pending),
    )


def emit_moment_events(
    *,
    now: datetime | None = None,
    db_path: str | None = None,
    focus_snapshot: dict[str, object] | None = None,
) -> int:
    """Record one-time persona events (overdue, focus milestones).

    Background-only: this writes to SQLite. events.emit is idempotent and
    memoised, so repeated ticks for an unchanged state do not write. Returns the
    number of new events recorded.
    """
    current = now or datetime.now()
    focus_snapshot = focus_snapshot or {}
    written = 0

    pending = todos.list_todos(include_done=False, db_path=db_path)
    top = pending[0] if pending else None
    top_level = todos.calculate_angry_level(top, current) if top else 0
    if top is not None and top_level >= 1:
        written += events.emit(
            events.TODO_OVERDUE, f"todo_{top.id}",
            f"Todo '{top.title}' is overdue (level {top_level}).",
            db_path=db_path,
        )
        if todos.mood_for_level(top_level) == "rage":
            written += events.emit(
                events.TODO_CRITICAL_OVERDUE, f"todo_{top.id}",
                f"Todo '{top.title}' is critically overdue.",
                db_path=db_path,
            )

    session_id = focus_snapshot.get("id")
    if focus_snapshot.get("active") and session_id is not None:
        progress = float(focus_snapshot.get("progress") or 0)
        if 0.5 <= progress < 0.9:
            written += events.emit(
                events.FOCUS_HALFWAY, f"session_{session_id}",
                f"Focus '{focus_snapshot.get('title')}' is halfway done. {focus_snapshot.get('remaining_text')} left.",
                db_path=db_path,
            )
        if progress >= 0.9:
            written += events.emit(
                events.FOCUS_ALMOST_DONE, f"session_{session_id}",
                f"Focus '{focus_snapshot.get('title')}' is almost done. {focus_snapshot.get('remaining_text')} left.",
                db_path=db_path,
            )
    return written


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


def _minutes_until(todo, now: datetime) -> int:
    try:
        due = todos._parse_datetime(str(todo.due_at))
    except (AttributeError, TypeError, ValueError):
        return 0
    return max(0, round((due - now).total_seconds() / 60))


def _overdue_reason(overdue: list, top) -> str:
    """What the angry face is angry about — count first, then the worst offender."""
    count = len(overdue) or 1
    plural = "" if count == 1 else "s"
    return f"{count} overdue task{plural} · {top.title}"


def _ambient_reason(pending: list) -> str:
    if not pending:
        return "nothing pending"
    plural = "" if len(pending) == 1 else "s"
    return f"{len(pending)} task{plural} pending · nothing due"
