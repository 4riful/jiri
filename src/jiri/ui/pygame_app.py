from __future__ import annotations

import os
import time
from datetime import datetime

from jiri.runtime import JiriRuntime

from . import theme
from .layout import build_layout
from .touch import PendingConfirmation, action_for_touch
from .view_model import DisplayViewModel, build_display_view_model


def run() -> int:
    if os.environ.get("JIRI_DISPLAY_DRIVER") == "mock":
        runtime = JiriRuntime.load()
        snapshot = runtime.screen_snapshot(panel="system")
        build_display_view_model(snapshot)
        return 0

    import pygame

    runtime = JiriRuntime.load()
    cfg = runtime.config
    pygame.init()
    flags = pygame.FULLSCREEN if cfg.display.fullscreen else 0
    surface = pygame.display.set_mode((cfg.display.width, cfg.display.height), flags)
    pygame.display.set_caption(cfg.assistant.name)
    clock = pygame.time.Clock()
    fps = max(10, min(cfg.display.fps, 15))
    fonts = _load_fonts(pygame)
    snapshot = runtime.screen_snapshot()
    message_key = _message_key(snapshot)
    message_started_at = datetime.now()
    model = build_display_view_model(snapshot, message_started_at=message_started_at, now=message_started_at)
    last_snapshot = 0.0
    pending: PendingConfirmation | None = None
    running = True

    while running:
        now = time.monotonic()
        if now - last_snapshot >= 1.0:
            snapshot = runtime.screen_snapshot()
            new_message_key = _message_key(snapshot)
            if new_message_key != message_key:
                message_key = new_message_key
                message_started_at = datetime.now()
            last_snapshot = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONUP:
                action, pending = action_for_touch(event.pos, snapshot.face_state, snapshot.width, snapshot.height, pending=pending)
                if action == "next_panel":
                    snapshot = runtime.screen_snapshot(panel=_next_panel(snapshot.panel))
                    message_key = _message_key(snapshot)
                    message_started_at = datetime.now()

        model = build_display_view_model(snapshot, message_started_at=message_started_at, now=datetime.now())
        _draw(pygame, surface, fonts, model)
        pygame.display.flip()
        clock.tick(fps)

    pygame.quit()
    return 0


def _load_fonts(pygame):
    return {
        "title": pygame.font.Font(None, 30),
        "face": pygame.font.Font(None, 86),
        "body": pygame.font.Font(None, 22),
        "small": pygame.font.Font(None, 18),
    }


def _draw(pygame, surface, fonts, model: DisplayViewModel) -> None:
    layout = build_layout(model.width, model.height)
    surface.fill(theme.BACKGROUND)
    pygame.draw.rect(surface, theme.ACCENT, _rect(layout.top_bar), width=1)
    pygame.draw.rect(surface, theme.TEXT, _rect(layout.face), width=1, border_radius=10)
    pygame.draw.rect(surface, theme.ACCENT, _rect(layout.panel), width=1, border_radius=10)
    _text(surface, fonts["title"], model.panel_title, (10, 8), theme.TEXT)
    _text(surface, fonts["small"], model.typed_headline[:42], (10, model.height - 26), theme.TEXT)
    face_text = f"{model.face.eye_left}   {model.face.eye_right}\n  {model.face.mouth}"
    _multiline(surface, fonts["face"], face_text, (layout.face.x + 38, layout.face.y + 42), theme.ACCENT)
    _text(surface, fonts["body"], model.subheadline[:30], (layout.face.x + 18, layout.face.y + layout.face.height - 34), theme.TEXT)
    y = layout.panel.y + 18
    for label, value in model.right_rows[:5]:
        _text(surface, fonts["small"], label.upper(), (layout.panel.x + 12, y), theme.WARNING)
        _text(surface, fonts["body"], str(value)[:20], (layout.panel.x + 12, y + 16), theme.TEXT)
        y += 48


def _rect(rect):
    return (rect.x, rect.y, rect.width, rect.height)


def _text(surface, font, text: str, pos: tuple[int, int], color) -> None:
    surface.blit(font.render(text, True, color), pos)


def _multiline(surface, font, text: str, pos: tuple[int, int], color) -> None:
    x, y = pos
    for line in text.splitlines():
        _text(surface, font, line, (x, y), color)
        y += font.get_height()


def _next_panel(panel: str) -> str:
    panels = ("weather", "focus", "todos", "notes", "system")
    try:
        index = panels.index(panel)
    except ValueError:
        return panels[0]
    return panels[(index + 1) % len(panels)]


def _message_key(snapshot) -> str:
    return f"{snapshot.face_state}|{snapshot.panel}|{snapshot.headline}|{snapshot.subheadline}"


if __name__ == "__main__":
    raise SystemExit(run())
