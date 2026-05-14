from __future__ import annotations

from dataclasses import dataclass

from jiri.views import ScreenSnapshot

from .face import FaceFrame, face_frame_for_state
from .touch import TouchZone, build_touch_zones


@dataclass(frozen=True)
class DisplayViewModel:
    width: int
    height: int
    panel: str
    panel_title: str
    face: FaceFrame
    headline: str
    subheadline: str
    right_rows: tuple[tuple[str, str], ...]
    touch_zones: tuple[TouchZone, ...]


def build_display_view_model(snapshot: ScreenSnapshot) -> DisplayViewModel:
    return DisplayViewModel(
        width=snapshot.width,
        height=snapshot.height,
        panel=snapshot.panel,
        panel_title=snapshot.panel_title,
        face=face_frame_for_state(snapshot.face_state, focus_snapshot=snapshot.focus),
        headline=snapshot.headline,
        subheadline=snapshot.subheadline,
        right_rows=_right_rows(snapshot),
        touch_zones=build_touch_zones(snapshot.width, snapshot.height),
    )


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
        rows = [(f"#{todo.id}", todo.title) for todo in snapshot.pending_todos[:4]]
        return tuple(rows) or (("Todos", "None pending"),)
    if snapshot.panel == "notes":
        rows = [(note.title, note.body[:24]) for note in snapshot.recent_notes[:3]]
        return tuple(rows) or (("Notes", "None yet"),)
    return (
        ("DB", "writable" if snapshot.system.get("database_writable") else "readonly"),
        ("Todos", str(snapshot.system.get("todos_count"))),
        ("Overdue", str(snapshot.system.get("overdue_count"))),
        ("RAM", str(snapshot.system.get("free_ram_mb") or "unknown")),
    )


def _unit(value: object, suffix: str) -> str:
    if value is None:
        return "unknown"
    return f"{value}{suffix}"
