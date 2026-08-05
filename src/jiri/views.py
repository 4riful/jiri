from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import focus, health, messages, mood, notes, persona, telegram, todos, weather, water
from .config import AppConfig, load_config
from .models import Note, Todo


SCREEN_PANELS = ("weather", "focus", "todos", "notes", "water", "system")

PANEL_TITLES = {
    "weather": "Weather",
    "focus": "Focus",
    "todos": "Todos",
    "notes": "Notes",
    "water": "Water",
    "system": "System",
}


@dataclass(frozen=True)
class ScreenSnapshot:
    generated_at: str
    clock: str
    app_name: str
    panel: str
    panel_title: str
    face_state: str
    face_reason: str
    headline: str
    subheadline: str
    weather: dict[str, object]
    focus: dict[str, object]
    active_location: dict[str, object] | None
    pending_todos: tuple[Todo, ...]
    recent_notes: tuple[Note, ...]
    system: dict[str, object]
    water: dict[str, object]
    telegram: dict[str, object]
    panel_order: tuple[str, ...] = SCREEN_PANELS
    refresh_seconds: int = 20
    width: int = 480
    height: int = 320
    pending_count: int = 0
    overdue_count: int = 0
    note_count: int = 0
    typing_speed_cps: int = 24


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: str
    screen: ScreenSnapshot
    health: dict[str, object]
    todos: tuple[Todo, ...]
    notes: tuple[Note, ...]
    active_location: dict[str, object] | None
    recent_locations: tuple[dict[str, object], ...]
    weather: dict[str, object]
    focus: dict[str, object]
    ai: dict[str, object]
    water: dict[str, object]
    search_results: tuple[dict[str, object], ...] = ()
    provider_results: tuple[dict[str, object], ...] = ()
    notice: str = ""
    error: str = ""


def build_screen_snapshot(
    db_path: str | None = None,
    config: AppConfig | None = None,
    panel: str | None = None,
    now: datetime | None = None,
) -> ScreenSnapshot:
    cfg = config or load_config()
    current = now or datetime.now()
    active_location = weather.get_active_location(db_path=db_path, config=cfg)
    weather_state = weather.auto_update_weather(db_path=db_path, config=cfg)
    focus_state = focus.active_snapshot(db_path=db_path, now=current)
    pending_todos = tuple(todos.list_todos(include_done=False, db_path=db_path))
    all_notes = tuple(notes.list_notes(db_path=db_path))
    recent_notes = all_notes[:3]
    overdue_todos = todos.get_overdue_todos(current, db_path=db_path)
    face_state = mood.calculate_mood(current, db_path=db_path)
    water_state = water.water_snapshot(db_path=db_path, now=current)
    selected_panel = _resolve_panel(panel, current, cfg.display.rotate_seconds)
    headline = _headline_for(
        face_state, selected_panel, pending_todos, weather_state, focus_state, recent_notes, water_state,
        # Seeded by the situation, not left to random.choice: an unseeded pick
        # hands you a different sentence on every 20s repaint, which reads as JIRI
        # muttering to itself. Same mood, same day, same line.
        seed=f"{face_state}:{selected_panel}:{current.date().isoformat()}",
    )
    subheadline = _subheadline_for(selected_panel, pending_todos, weather_state, focus_state, recent_notes, overdue_todos, water_state)
    persona_moment = persona.screen_moment(
        now=current,
        db_path=db_path,
        base_face_state=face_state,
        base_headline=headline,
        base_subheadline=subheadline,
        focus_snapshot=focus_state,
        weather_snapshot=weather_state,
    )
    system_snapshot = health.health_snapshot(db_path=db_path, config=cfg)
    try:
        telegram_state = telegram.binding_status(config=cfg, db_path=db_path)
    except Exception:  # a misconfigured bot must never blank the display
        telegram_state = {"enabled": False, "status": "unavailable"}

    return ScreenSnapshot(
        generated_at=current.replace(microsecond=0).isoformat(),
        # Full date and time. The browser retimes this every second; this is the
        # value that has to be right on the very first paint and without JS.
        clock=current.strftime("%a %d %b %Y · %H:%M:%S"),
        app_name=cfg.assistant.name,
        panel=selected_panel,
        panel_title=PANEL_TITLES.get(selected_panel, "System"),
        face_state=persona_moment.face_state,
        face_reason="" if persona_moment.reason_kind == selected_panel else persona_moment.reason,
        headline=_speech_for(persona_moment, selected_panel, headline),
        subheadline=persona_moment.subheadline,
        weather=weather_state,
        focus=focus_state,
        active_location=active_location,
        pending_todos=pending_todos,
        recent_notes=recent_notes,
        system=system_snapshot,
        water=water_state,
        telegram=telegram_state,
        refresh_seconds=max(5, cfg.display.rotate_seconds),
        width=cfg.display.width,
        height=cfg.display.height,
        pending_count=len(pending_todos),
        overdue_count=len(overdue_todos),
        note_count=len(all_notes),
        typing_speed_cps=cfg.display.typing_speed_cps,
    )


def build_dashboard_snapshot(
    db_path: str | None = None,
    config: AppConfig | None = None,
    panel: str | None = None,
    now: datetime | None = None,
    search_results: list[dict[str, object]] | None = None,
    provider_results: list[dict[str, object]] | None = None,
    notice: str = "",
    error: str = "",
) -> DashboardSnapshot:
    cfg = config or load_config()
    current = now or datetime.now()
    screen = build_screen_snapshot(db_path=db_path, config=cfg, panel=panel, now=current)
    health_snapshot = screen.system
    all_todos = tuple(todos.list_todos(include_done=True, db_path=db_path))
    all_notes = tuple(notes.list_notes(db_path=db_path))
    active_location = screen.active_location
    recent_locations = tuple(weather.get_recent_locations(db_path=db_path))
    weather_state = screen.weather
    focus_state = screen.focus
    water_state = screen.water
    stored_results = tuple(search_results or [])
    provider_rows = tuple(provider_results or [])

    if not stored_results:
        try:
            stored_results = tuple(weather.get_last_location_search(db_path=db_path))
        except ValueError:
            stored_results = ()

    return DashboardSnapshot(
        generated_at=current.replace(microsecond=0).isoformat(),
        screen=screen,
        health=health_snapshot,
        todos=all_todos,
        notes=all_notes,
        active_location=active_location,
        recent_locations=recent_locations,
        weather=weather_state,
        focus=focus_state,
        ai=health_snapshot.get("ai", {"enabled": False}),
        water=water_state,
        search_results=stored_results,
        provider_results=provider_rows,
        notice=notice,
        error=error,
    )


def _speech_for(moment: persona.PersonaMoment, panel: str, panel_headline: str) -> str:
    """Never make the voice line repeat the block right above it.

    When you are already looking at the thing JIRI is reacting to, the numbers are
    on screen — so it comments instead. When the cause is on another panel, it
    says the cause outright. Otherwise the panel speaks for itself.
    """
    if moment.reason_kind and moment.reason_kind == panel:
        return moment.subheadline
    if moment.priority >= 70:
        return moment.headline
    return panel_headline


def _resolve_panel(panel: str | None, now: datetime, rotate_seconds: int) -> str:
    clean = (panel or "auto").strip().lower()
    if clean and clean != "auto":
        return clean if clean in SCREEN_PANELS else "system"
    if rotate_seconds <= 0:
        return "system"
    index = int(now.timestamp() // rotate_seconds) % len(SCREEN_PANELS)
    return SCREEN_PANELS[index]


def _headline_for(
    face_state: str,
    panel: str,
    pending_todos: tuple[Todo, ...],
    weather_state: dict[str, object],
    focus_state: dict[str, object],
    recent_notes: tuple[Note, ...],
    water_state: dict[str, object],
    seed: object = None,
) -> str:
    """What JIRI says out loud.

    Every line here has to add something the panel does not already print. A voice
    that reads back the number above it is furniture, not a companion — which is
    why todos and notes deliberately fall through to the mood line instead of
    echoing the task title or the note heading sitting right above.
    """
    if panel == "water":
        return str(water_state.get("message") or "Keep sipping water.")
    if panel == "focus":
        if focus_state.get("active"):
            return f"{focus_state.get('title')} · {focus_state.get('remaining_text')}"
        return "No timer running. I can guard a session whenever you start one."
    if panel == "weather":
        message = str(weather_state.get("message") or "Weather ready.")
        return message
    # "Idle" here means nothing is *late*, which is not the same as nothing being
    # on the list. Only the empty list gets the empty-list lines.
    if face_state == "idle" and pending_todos:
        return messages.watching_message(seed)
    return messages.message_for_mood(face_state, seed=seed)


def _subheadline_for(
    panel: str,
    pending_todos: tuple[Todo, ...],
    weather_state: dict[str, object],
    focus_state: dict[str, object],
    recent_notes: tuple[Note, ...],
    overdue_todos: list[Todo],
    water_state: dict[str, object],
) -> str:
    if panel == "water":
        return f"{water_state.get('progress_ml')}ml of {water_state.get('goal_ml')}ml today"
    if panel == "weather":
        location = str(weather_state.get("location") or "No location selected")
        condition = str(weather_state.get("condition") or "Unknown")
        return f"{location} · {condition}"
    if panel == "focus":
        if focus_state.get("active"):
            return f"{focus_state.get('kind')} · {focus_state.get('status')} · {int(float(focus_state.get('progress') or 0) * 100)}%"
        return "Start a focus session from the web dashboard or CLI."
    if panel == "todos":
        if overdue_todos:
            return f"{len(overdue_todos)} overdue task(s) need attention."
        if pending_todos:
            return f"Next up: {pending_todos[0].title}"
        return "No pending todos."
    if panel == "notes":
        if recent_notes:
            return f"Latest note: {recent_notes[0].title}"
        return "No notes yet."
    return str(weather_state.get("message") or "System stable.")
