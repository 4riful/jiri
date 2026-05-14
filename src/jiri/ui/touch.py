from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .face import is_critical_face_state
from .layout import Rect, build_layout


@dataclass(frozen=True)
class TouchZone:
    name: str
    action: str
    rect: Rect
    requires_confirmation: bool = False


@dataclass(frozen=True)
class PendingConfirmation:
    action: str
    created_at: datetime
    timeout_seconds: int = 5

    def expired(self, now: datetime) -> bool:
        return now - self.created_at > timedelta(seconds=self.timeout_seconds)


def build_touch_zones(width: int = 480, height: int = 320) -> tuple[TouchZone, ...]:
    layout = build_layout(width, height)
    panel_h = max(1, layout.panel.height // 3)
    return (
        TouchZone("face", "cycle_face", layout.face),
        TouchZone("panel_top", "previous_panel", Rect(layout.panel.x, layout.panel.y, layout.panel.width, panel_h)),
        TouchZone("panel_middle", "next_panel", Rect(layout.panel.x, layout.panel.y + panel_h, layout.panel.width, panel_h)),
        TouchZone("panel_bottom", "confirm_or_primary", Rect(layout.panel.x, layout.panel.y + panel_h * 2, layout.panel.width, layout.panel.height - panel_h * 2), requires_confirmation=True),
    )


def hit_test(point: tuple[int, int], zones: tuple[TouchZone, ...]) -> TouchZone | None:
    for zone in zones:
        if zone.rect.contains(point):
            return zone
    return None


def action_for_touch(
    point: tuple[int, int],
    face_state: str,
    width: int = 480,
    height: int = 320,
    pending: PendingConfirmation | None = None,
    now: datetime | None = None,
) -> tuple[str, PendingConfirmation | None]:
    current = now or datetime.now()
    zone = hit_test(point, build_touch_zones(width, height))
    if zone is None:
        return "none", pending
    if zone.action == "cycle_face" and is_critical_face_state(face_state):
        return "blocked_critical_face", pending
    if zone.requires_confirmation:
        if pending and pending.action == zone.action and not pending.expired(current):
            return zone.action, None
        return "confirmation_required", PendingConfirmation(zone.action, current)
    return zone.action, pending
