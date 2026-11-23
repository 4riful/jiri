"""Render JIRI's display headless to PNGs — no Pi, no window needed.

    PYTHONPATH=src .venv/bin/python scripts/render_preview.py OUT_DIR [--live]

Without --live it renders every mood from canned snapshots plus a contact
sheet; with --live it renders the current real snapshot from the database.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from jiri.ui import renderer  # noqa: E402

CASES = [
    ("idle", "", "Desk secured. Nothing needs you. Suspicious, honestly.", {}),
    ("happy", "Task done · Ship invoice", "A tiny parade is happening in my circuits.", {}),
    ("alert", "Due in 15 min · Call bank", "Fifteen minutes. I'm not panicking. You panic.", {}),
    ("annoyed", "1 overdue task · Call bank", "It's still there. I checked twice.", {}),
    ("angry", "45 min late · Ship invoice", "Ship invoice. That's the whole message.", {}),
    ("rage", "3 overdue tasks · Ship invoice", "Ship invoice. Now, please.", {}),
    ("focused", "focus · 24:10 left", "Shh. Brain at work. I'm guarding the door.", {"active": True, "status": "running", "remaining_text": "24:10"}),
    ("sleeping", "Quiet hours", "zz... I'll keep one eye on the to-do list. Figuratively.", {}),
    ("weather_hot", "34° outside · Clear sky", "It's 34 out. I am a small robot and I am sweating.", {}),
    ("weather_rain", "80% rain after 5 pm", "Umbrella. Trust me, I've seen the forecast.", {}),
    ("ai_offline", "AI offline · using cached lines", "My witty brain is offline. This is the backup brain.", {}),
    ("smirk", "Water goal 100%", "Fully hydrated. I'd high-five you but I'm a screen.", {}),
]


def snapshot(state, reason, speech, focus, overdue=1, pending=3):
    return SimpleNamespace(
        face_state=state, face_reason=reason, headline=speech, subheadline=speech,
        focus=focus, overdue_count=overdue, pending_count=pending,
        water={"goal_ml": 3000, "percent": 40}, weather={"temperature_c": 21.4}, panel="todos",
    )


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else "preview"
    os.makedirs(out, exist_ok=True)
    pygame.display.init()
    pygame.font.init()
    fonts = renderer.load_fonts(pygame)
    now = datetime(2026, 11, 23, 21, 5)
    usage = (
        SimpleNamespace(provider="claude", label="Opus 4.5", context_pct=18.0, five_hour_pct=9.0,
                        five_hour_resets_at=now.timestamp() + 43 * 60, weekly_pct=4.0,
                        weekly_resets_at=now.timestamp() + 2 * 86400 + 3 * 3600, updated_at=now.timestamp() - 20),
        SimpleNamespace(provider="chatgpt", label="gpt-5-codex", context_pct=None, five_hour_pct=81.0,
                        five_hour_resets_at=now.timestamp() + 95 * 60, weekly_pct=47.0,
                        weekly_resets_at=now.timestamp() + 5 * 86400, updated_at=now.timestamp() - 300),
    )
    if "--live" in argv:
        from jiri.runtime import JiriRuntime
        cases = [("live", JiriRuntime.load().screen_snapshot())]
        now = datetime.now()
    else:
        cases = [(c[0], snapshot(*c)) for c in CASES]
        cases.append(("usage", snapshot("idle", "", "", {})))

    shots = []
    for name, snap in cases:
        surf = pygame.Surface((480, 320))
        scene = renderer.build_scene(snap, now=now, usage=usage if name == "usage" else None)
        renderer.render(pygame, surf, fonts, scene)
        path = os.path.join(out, f"{name}.png")
        pygame.image.save(surf, path)
        shots.append(surf)
        print(path)

    if len(shots) > 1:
        cols = 3
        rows = (len(shots) + cols - 1) // cols
        sheet = pygame.Surface((cols * 488, rows * 328))
        sheet.fill((40, 44, 52))
        for i, s in enumerate(shots):
            sheet.blit(s, ((i % cols) * 488 + 4, (i // cols) * 328 + 4))
        pygame.image.save(sheet, os.path.join(out, "sheet.png"))
        print(os.path.join(out, "sheet.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
