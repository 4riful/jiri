from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from jiri.views import ScreenSnapshot

from .face import FaceFrame, face_frame_for_state
from .touch import TouchZone, build_touch_zones
from .typing import TypedText, truncate_text, type_text


@dataclass(frozen=True)
class ScreenHero:
    """The single most important thing on the display right now."""

    kind: str
    label: str
    value: str
    detail: str
    progress: float = 0.0
    compact: bool = False
    extras: tuple[str, ...] = ()
    tone: str = "normal"


@dataclass(frozen=True)
class DisplayViewModel:
    width: int
    height: int
    panel: str
    panel_title: str
    face: FaceFrame
    headline: str
    subheadline: str
    typed_headline: str
    typed_complete: bool
    typing_speed_cps: int
    right_rows: tuple[tuple[str, str], ...]
    touch_zones: tuple[TouchZone, ...]
    hero: ScreenHero


def build_display_view_model(
    snapshot: ScreenSnapshot,
    message_started_at: datetime | None = None,
    now: datetime | None = None,
) -> DisplayViewModel:
    headline = truncate_text(snapshot.headline)
    subheadline = truncate_text(snapshot.subheadline)
    typed = _typed_headline(snapshot, headline, message_started_at=message_started_at, now=now)
    return DisplayViewModel(
        width=snapshot.width,
        height=snapshot.height,
        panel=snapshot.panel,
        panel_title=snapshot.panel_title,
        face=face_frame_for_state(snapshot.face_state, focus_snapshot=snapshot.focus),
        headline=headline,
        subheadline=subheadline,
        typed_headline=typed.visible,
        typed_complete=typed.complete,
        typing_speed_cps=snapshot.typing_speed_cps,
        right_rows=_right_rows(snapshot),
        touch_zones=build_touch_zones(snapshot.width, snapshot.height),
        hero=_hero(snapshot),
    )


def _hero(snapshot: ScreenSnapshot) -> ScreenHero:
    """The big block: a running focus session always wins, otherwise the current panel."""
    if _focus_is_running(snapshot.focus):
        return _fit(_focus_hero(snapshot))
    builders = {
        "focus": _focus_hero,
        "weather": _weather_hero,
        "todos": _todos_hero,
        "notes": _notes_hero,
        "water": _water_hero,
        "system": _system_hero,
    }
    return _fit(builders.get(snapshot.panel, _system_hero)(snapshot))


def _fit(hero: ScreenHero) -> ScreenHero:
    """Clip to what the 480px display can actually hold, on word-safe boundaries."""
    return replace(
        hero,
        label=_clip(hero.label, 24),
        value=_clip(hero.value, 46 if hero.compact else 12),
        detail=_clip(hero.detail, 48),
        extras=tuple(_clip(extra, 20) for extra in hero.extras[:2]),
    )


def _focus_is_running(focus_state: dict[str, object]) -> bool:
    """A session that has burned down to 00:00 is over; it should stop owning the screen."""
    if not focus_state.get("active"):
        return False
    return float(focus_state.get("progress") or 0.0) < 1.0


def _focus_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    focus_state = snapshot.focus
    if not _focus_is_running(focus_state):
        finished = bool(focus_state.get("active"))
        return ScreenHero(
            kind="focus-idle",
            label="SESSION DONE" if finished else "NO FOCUS SESSION",
            value="00:00" if finished else "--:--",
            detail=str(focus_state.get("title") or "Focus session") if finished else "Start one from the dashboard or CLI",
            extras=(f"{snapshot.pending_count} todos waiting",),
        )
    progress = float(focus_state.get("progress") or 0.0)
    return ScreenHero(
        kind="focus",
        label=f"{str(focus_state.get('kind') or 'focus').upper()} · {str(focus_state.get('status') or 'running').upper()}",
        value=str(focus_state.get("remaining_text") or "--:--"),
        detail=str(focus_state.get("title") or "Focus session"),
        progress=progress,
        extras=(f"{int(progress * 100)}% done",),
    )


def _weather_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    temperature = snapshot.weather.get("temperature_c")
    rain = snapshot.weather.get("rain_chance")
    humidity = snapshot.weather.get("humidity")
    extras = []
    if rain is not None:
        extras.append(f"{rain}% rain")
    if humidity is not None:
        extras.append(f"{humidity}% humidity")
    if snapshot.weather.get("stale"):
        extras.append("cached")
    return ScreenHero(
        kind="weather",
        label=str(snapshot.weather.get("condition") or "weather").upper(),
        value="--°" if temperature is None else f"{round(float(temperature))}°",
        detail=str(snapshot.weather.get("location") or "No location set"),
        extras=tuple(extras[:2]),
    )


def _todos_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    if snapshot.overdue_count:
        plural = "" if snapshot.overdue_count == 1 else "S"
        return ScreenHero(
            kind="overdue",
            label=f"{snapshot.overdue_count} OVERDUE TASK{plural}",
            value=str(snapshot.pending_count),
            detail=snapshot.pending_todos[0].title if snapshot.pending_todos else "Check the todo list",
            extras=tuple(todo.title for todo in snapshot.pending_todos[1:3]),
            tone="alert",
        )
    if not snapshot.pending_todos:
        return ScreenHero(kind="todos", label="TODO LIST", value="0", detail="Nothing pending. Enjoy it.")
    return ScreenHero(
        kind="todos",
        label="PENDING TASKS",
        value=str(snapshot.pending_count),
        detail=f"Next: {snapshot.pending_todos[0].title}",
        extras=tuple(todo.title for todo in snapshot.pending_todos[1:3]),
    )


def _notes_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    if not snapshot.recent_notes:
        return ScreenHero(kind="notes", label="NOTES", value="0", detail="Nothing captured yet.")
    latest = snapshot.recent_notes[0]
    return ScreenHero(
        kind="notes",
        label="LATEST NOTE",
        value=latest.title,
        detail=_snippet(latest.body, limit=52),
        extras=tuple(note.title for note in snapshot.recent_notes[1:3]),
        compact=True,
    )


def _water_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    water = snapshot.water
    percent = int(water.get("percent") or 0)
    goal = int(water.get("goal_ml") or 0)
    progress = int(water.get("progress_ml") or 0)
    remaining = int(water.get("remaining_ml") or 0)
    return ScreenHero(
        kind="water",
        label="HYDRATION" if not water.get("complete") else "HYDRATION DONE",
        value=f"{percent}%",
        detail=f"{progress}ml of {goal}ml today",
        progress=min(1.0, percent / 100),
        extras=(f"{remaining}ml to go",) if remaining else ("goal reached",),
    )


def _system_hero(snapshot: ScreenSnapshot) -> ScreenHero:
    system = snapshot.system
    ai_state = system.get("ai")
    ai_enabled = bool(ai_state.get("enabled")) if isinstance(ai_state, dict) else False
    writable = bool(system.get("database_writable"))
    temperature = system.get("cpu_temperature_c")
    extras = [
        "db ok" if writable else "db read-only",
        f"ai {'on' if ai_enabled else 'off'} · tg {'on' if snapshot.telegram.get('enabled') else 'off'}",
    ]
    if temperature is not None:
        extras.append(f"{round(float(temperature))}°C cpu")
    return ScreenHero(
        kind="system",
        label="SYSTEM",
        value=_ram(system.get("free_ram_mb")),
        detail=f"free memory · v{system.get('app_version') or '0'}",
        extras=tuple(extras[:2]),
        tone="normal" if writable else "alert",
    )


def _typed_headline(
    snapshot: ScreenSnapshot,
    headline: str,
    message_started_at: datetime | None = None,
    now: datetime | None = None,
) -> TypedText:
    if message_started_at is None:
        return TypedText(headline, True, len(headline), len(headline))
    current = now or datetime.now()
    return type_text(headline, started_at=message_started_at, now=current, speed_cps=snapshot.typing_speed_cps)


def _right_rows(snapshot: ScreenSnapshot) -> tuple[tuple[str, str], ...]:
    if snapshot.panel == "weather":
        return (
            ("Location", str(snapshot.weather.get("location") or "unknown")),
            ("Condition", str(snapshot.weather.get("condition") or "unknown")),
            ("Temp", _unit(snapshot.weather.get("temperature_c"), "C")),
            ("Rain", _unit(snapshot.weather.get("rain_chance"), "%")),
        )
    if snapshot.panel == "focus":
        return (
            ("Title", str(snapshot.focus.get("title") or "No focus")),
            ("Status", str(snapshot.focus.get("status") or "idle")),
            ("Left", str(snapshot.focus.get("remaining_text") or "--:--")),
            ("Progress", f"{int(float(snapshot.focus.get('progress') or 0) * 100)}%"),
        )
    if snapshot.panel == "todos":
        rows = [("Pending", str(snapshot.pending_count)), ("Overdue", str(snapshot.overdue_count))]
        rows.extend((f"#{todo.id}", todo.title) for todo in snapshot.pending_todos[:2])
        return tuple(rows)
    if snapshot.panel == "notes":
        rows = [("Notes", str(snapshot.note_count))]
        rows.extend((note.title, _snippet(note.body)) for note in snapshot.recent_notes[:3])
        return tuple(rows)
    if snapshot.panel == "water":
        return (
            ("Today", f"{snapshot.water.get('progress_ml')}ml"),
            ("Goal", f"{snapshot.water.get('goal_ml')}ml"),
            ("Left", f"{snapshot.water.get('remaining_ml')}ml"),
            ("Percent", f"{snapshot.water.get('percent')}%"),
        )
    return (
        ("DB", "writable" if snapshot.system.get("database_writable") else "readonly"),
        ("Todos", str(snapshot.system.get("todos_count"))),
        ("Overdue", str(snapshot.system.get("overdue_count"))),
        ("RAM", str(snapshot.system.get("free_ram_mb") or "unknown")),
    )


def _ram(free_mb: object) -> str:
    """Free memory reads better as 21.2G than as 21716M."""
    try:
        megabytes = float(free_mb)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "--"
    if megabytes <= 0:
        return "--"
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f}G"
    return f"{int(megabytes)}M"


def _clip(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _snippet(body: str, limit: int = 34) -> str:
    return _clip(body, limit) or "(empty)"


def _unit(value: object, suffix: str) -> str:
    if value is None:
        return "unknown"
    return f"{value}{suffix}"
