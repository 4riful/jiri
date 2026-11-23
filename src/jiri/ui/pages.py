"""JIRI's screens. Each draws a full 480x320 frame from a `Scene`.

Pure drawing: the stage passes a `Life` sample (blink, gaze, breathing,
thinking, typing, giggle, wink, time) so animation stays deterministic and
testable. Only the home screen has the face; the info screens are clean
cards with icons and real numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from . import mascot

W, H = 480, 320
PAD = 16
CARD = (19, 25, 32)
LINE = (32, 40, 50)


@dataclass(frozen=True)
class Life:
    """One instant of ambient motion, sampled by the stage."""

    t: float = 0.0             # seconds since start (drives particles)
    open_amount: float = 1.0   # blink / mood pop
    gaze: tuple[int, int] = (0, 0)
    bob: int = 0               # breathing offset in px
    tick: bool = True          # once-a-second pulse
    typed: int = 10_000        # characters of speech revealed so far
    thinking: float = -1.0     # 0..1 while JIRI is "thinking", else -1
    giggle: float = -1.0       # 0..1 while giggling after a tap, else -1
    wink: float = 1.0          # left-eye openness (idle wink)
    page_index: int = 0
    page_count: int = 1
    paused: bool = False       # rotation stopped by a tap
    toast: str = ""            # brief feedback after a tap ("paused"/"spinning")
    pose: object = None        # pet.Pose from the pet brain (None = still frame)
    reveal: float = 99.0       # seconds since the current text started decoding
    fact_icon: str = ""        # icon for the current thought's fact line
    show_time: bool = True     # eyes show the clock digits (a "time check") vs pupils
    arrows: float = 0.0        # prev/next arrow visibility 0..1 (fades out)
    feeling: object = None     # emotion.Feeling: what JIRI feels and why
    thought_index: int = 0     # which thought JIRI is on (for the flow indicator)
    thought_count: int = 0
    thought_progress: float = 0.0  # 0..1 until the next thought
    say: str = ""              # a short spoken reaction (pet reflex), shown big


PAGES = ("face", "tasks", "notes", "weather", "water", "focus", "usage")
PAGE_TITLES = {
    "face": "Home", "tasks": "Tasks", "notes": "Notes", "weather": "Weather",
    "water": "Water", "focus": "Focus", "usage": "AI usage",
}
PAGE_COLORS = {
    "face": mascot.PINK, "tasks": mascot.CORAL, "notes": (240, 200, 110), "weather": mascot.SKY,
    "water": (110, 190, 255), "focus": (182, 150, 255), "usage": (217, 119, 87),
}
TONE = {"late": mascot.CORAL, "soon": mascot.AMBER, "ok": mascot.MINT}


# --- Text helpers -----------------------------------------------------------

_CONTROL = dict.fromkeys(list(range(0, 32)) + [127])


def text(surface, font, value: str, pos, color, *, anchor: str = "topleft"):
    # SDL_ttf raises on NUL; user-entered titles can contain anything.
    img = font.render(str(value).translate(_CONTROL), True, color)
    rect = img.get_rect(**{anchor: pos})
    surface.blit(img, rect)
    return rect


def fit(font, value: str, width: int) -> str:
    """Clip to `width` px with an ellipsis. Binary search: a 400-char title
    used to cost ~18 ms here (re-measured once per dropped character)."""
    value = str(value).translate(_CONTROL)[:160]
    if font.size(value)[0] <= width:
        return value
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(value[:mid] + "…")[0] <= width:
            lo = mid
        else:
            hi = mid - 1
    return value[:lo].rstrip() + "…"


def wrap(font, value: str, width: int, max_lines: int) -> list[str]:
    words, lines, line = value.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit(font, lines[-1] + " …", width)
    return lines


# --- Icons (primitives only: no icon font on the Pi) -------------------------

def icon(pygame, surface, kind: str, cx: int, cy: int, color, size: int = 8, t: float = 0.0, bg=None) -> None:
    """`bg` (optional) is the colour behind the icon, used for cut-outs."""
    s = size
    d = pygame.draw
    if kind in ("tasks", "check"):
        d.rect(surface, color, (cx - s, cy - s, 2 * s, 2 * s), 2, border_radius=max(2, s // 3))
        d.lines(surface, color, False, [(cx - s // 2, cy), (cx - s // 6, cy + s // 2), (cx + s // 2 + 1, cy - s // 2)], 2)
    elif kind in ("water", "drop"):
        d.circle(surface, color, (cx, cy + s // 3), int(s * 0.68))
        d.polygon(surface, color, [(cx - int(s * 0.62), cy + s // 6), (cx + int(s * 0.62), cy + s // 6), (cx, cy - s)])
    elif kind in ("weather", "sun"):
        d.circle(surface, color, (cx, cy), max(2, int(s * 0.5)))
        for i in range(8):
            a = t * 0.6 + i * math.pi / 4
            d.line(surface, color, (cx + int(s * 0.72 * math.cos(a)), cy + int(s * 0.72 * math.sin(a))),
                   (cx + int(s * 1.05 * math.cos(a)), cy + int(s * 1.05 * math.sin(a))), 2)
    elif kind == "cloud":
        d.circle(surface, color, (cx - s // 2, cy + s // 6), int(s * 0.5))
        d.circle(surface, color, (cx + s // 6, cy - s // 5), int(s * 0.62))
        d.circle(surface, color, (cx + int(s * 0.65), cy + s // 6), int(s * 0.45))
        d.rect(surface, color, (cx - s // 2, cy + s // 6, int(s * 1.15), int(s * 0.5)))
    elif kind == "rain":
        icon(pygame, surface, "cloud", cx, cy - s // 4, color, s)
        for k in (-1, 0, 1):
            d.line(surface, color, (cx + k * s // 2, cy + s // 2), (cx + k * s // 2 - 2, cy + s), 2)
    elif kind in ("focus", "clock"):
        d.circle(surface, color, (cx, cy), s, 2)
        d.line(surface, color, (cx, cy), (cx, cy - int(s * 0.6)), 2)
        d.line(surface, color, (cx, cy), (cx + int(s * 0.45), cy), 2)
    elif kind in ("usage", "bars"):
        for i, h in enumerate((0.5, 1.0, 0.75)):
            bh = int(2 * s * h)
            d.rect(surface, color, (cx - s + i * (2 * s // 3 + 1), cy + s - bh, max(2, s // 2), bh), border_radius=1)
    elif kind == "alert":
        d.circle(surface, color, (cx, cy), s, 2)
        d.line(surface, color, (cx, cy - s // 2), (cx, cy + s // 6), 2)
        d.circle(surface, color, (cx, cy + s // 2), 1)
    elif kind == "notes":
        d.rect(surface, color, (cx - int(s * 0.8), cy - s, int(s * 1.6), 2 * s), 2, border_radius=2)
        for k in (-1, 0, 1):
            d.line(surface, color, (cx - s // 2, cy + k * s // 2), (cx + s // 2, cy + k * s // 2), 2)
    elif kind == "list":
        for k in (-1, 0, 1):
            d.circle(surface, color, (cx - s + 1, cy + k * s * 2 // 3), 1)
            d.line(surface, color, (cx - s // 3, cy + k * s * 2 // 3), (cx + s, cy + k * s * 2 // 3), 2)
    elif kind == "thermo":
        d.rect(surface, color, (cx - s // 4, cy - s, s // 2 + 1, int(s * 1.4)), 2, border_radius=s // 4)
        d.circle(surface, color, (cx, cy + s // 2), max(2, s // 2 - 1))
    elif kind == "humidity":
        icon(pygame, surface, "drop", cx, cy, color, s)
    elif kind == "wind":
        for k, ln in ((-1, 1.0), (0, 1.3), (1, 0.8)):
            y = cy + k * s * 2 // 3
            d.line(surface, color, (cx - s, y), (cx - s + int(2 * s * ln * 0.8), y), 2)
    elif kind == "glass":
        d.polygon(surface, color, [(cx - s, cy - s), (cx + s, cy - s), (cx + int(s * 0.7), cy + s), (cx - int(s * 0.7), cy + s)], 2)
    elif kind == "glass_full":
        d.polygon(surface, color, [(cx - s, cy - s), (cx + s, cy - s), (cx + int(s * 0.7), cy + s), (cx - int(s * 0.7), cy + s)])
    elif kind == "pause":
        d.rect(surface, color, (cx - s, cy - s, int(s * 0.7), 2 * s), border_radius=2)
        d.rect(surface, color, (cx + int(s * 0.3), cy - s, int(s * 0.7), 2 * s), border_radius=2)
    elif kind == "play":
        d.polygon(surface, color, [(cx - s * 2 // 3, cy - s), (cx - s * 2 // 3, cy + s), (cx + s, cy)])
    elif kind in ("face", "home"):
        # A solid little house with a chimney and an arched door (not eyes:
        # JIRI's eyes live on the Home screen only).
        d.rect(surface, color, (cx + int(s * 0.42), cy - int(s * 0.95), int(s * 0.26), int(s * 0.6)))
        d.polygon(surface, color, [(cx - int(s * 1.15), cy - int(s * 0.02)), (cx, cy - int(s * 1.1)),
                                   (cx + int(s * 1.15), cy - int(s * 0.02))])
        d.rect(surface, color, (cx - int(s * 0.8), cy - int(s * 0.12), int(s * 1.6), int(s * 1.08)),
               border_radius=max(2, int(s * 0.14)))
        if bg is not None and s >= 8:
            r = max(2, int(s * 0.2))
            d.rect(surface, bg, (cx - int(s * 0.22), cy + int(s * 0.36), int(s * 0.44), int(s * 0.6)),
                   border_top_left_radius=r, border_top_right_radius=r)


def weather_kind(condition: str, rain: int) -> str:
    c = condition.lower()
    if any(k in c for k in ("rain", "drizzle", "shower", "thunder")) or rain >= 60:
        return "rain"
    if any(k in c for k in ("cloud", "overcast", "fog", "mist")):
        return "cloud"
    return "sun"


def chip(pygame, surface, font, kind: str, label: str, right: int, y: int, color) -> int:
    """Icon + label, right-aligned at `right`. Returns the chip's left x."""
    w = font.size(label)[0]
    x = right - w
    text(surface, font, label, (x, y), color)
    icon(pygame, surface, kind, x - 11, y + 8, color, 6)
    return x - 22


# --- Shared chrome ----------------------------------------------------------

def header(pygame, surface, fonts, scene, page: str, life: Life) -> None:
    color = PAGE_COLORS[page]
    icon(pygame, surface, page, PAD + 9, 22, color, 9, life.t)
    text(surface, fonts["title"], PAGE_TITLES[page], (PAD + 26, 11), mascot.INK)
    text(surface, fonts["status"], scene.clock_text, (W - PAD, 14), mascot.MUTED, anchor="topright")


def page_dots(pygame, surface, life: Life, color) -> None:
    n = life.page_count
    if n <= 1 or life.page_index == 0:
        return  # Home shows JIRI's thought dots instead; no navigation chrome
    gap = 12
    x0 = W // 2 - (n - 1) * gap // 2 - 6
    for i in range(n):
        if i == life.page_index:
            pygame.draw.rect(surface, color, (x0 + i * gap - 2, H - 9, 14, 4), border_radius=2)
        else:
            pygame.draw.circle(surface, LINE, (x0 + i * gap + 5, H - 7), 2)


def toast(pygame, surface, fonts, life: Life) -> None:
    if not life.toast:
        return
    label = life.toast
    w = fonts["status"].size(label)[0] + 40
    r = pygame.Rect(W // 2 - w // 2, 10, w, 26)
    pygame.draw.rect(surface, (34, 42, 52), r, border_radius=13)
    icon(pygame, surface, "pause" if "stop" in label else "play", r.x + 16, r.centery, mascot.INK, 5)
    text(surface, fonts["status"], label, (r.x + 28, r.y + 5), mascot.INK)


def card(pygame, surface, rect, color=CARD, radius: int = 12) -> None:
    pygame.draw.rect(surface, color, rect, border_radius=radius)


# --- Home: the face ---------------------------------------------------------

def status_bar(pygame, surface, fonts, scene, life: Life) -> None:
    """Date left, the time ALWAYS on the right, status chips between."""
    font = fonts["status_bold"]
    text(surface, font, scene.date_text, (PAD, 9), mascot.INK)
    clock = text(surface, font, scene.clock_text, (W - PAD, 9), mascot.INK, anchor="topright")
    x = clock.left - 14
    if scene.weather and scene.weather[0] is not None:
        kind = weather_kind(scene.weather[1], scene.weather[2])
        x = chip(pygame, surface, font, kind, f"{round(scene.weather[0])}°", x, 9,
                 mascot.AMBER if kind == "sun" else mascot.SKY)
    if scene.water:
        x = chip(pygame, surface, font, "drop", f"{scene.water[2]}%", x, 9, PAGE_COLORS["water"])
    late = sum(1 for t in scene.tasks if t[2] == "late")
    label = f"{late} late" if late else (f"{len(scene.tasks)}" if scene.tasks else "0")
    chip(pygame, surface, font, "check", label, x, 9, mascot.CORAL if late else mascot.MINT)


def page_face(pygame, surface, fonts, scene, life: Life) -> None:
    status_bar(pygame, surface, fonts, scene, life)
    pose = life.pose
    state = pose.state if pose else scene.state
    hop = pose.hop if pose else 0
    lift = 8 if life.thinking >= 0 and not life.say else 0
    cy = 110 + life.bob - hop
    geometry = mascot.face_geometry(W // 2, cy, eye_w=132, eye_h=118, gap=28)
    gx, gy = pose.gaze if pose else life.gaze
    if lift:
        gx, gy = gx + 14, gy - 12  # thinking: look up and away
    # The pupils carry the gaze; the whole eye only drifts a little with it.
    gaze_x = int(gx * 0.35)
    pupils = None if life.show_time else (gx / 22, gy / 14)
    owns = pose is not None and pose.owns_face
    # One expression at a time: while a reflex plays, the thought's blush and
    # particles step aside instead of stacking into a mixed face.
    happy = (state == "happy" and not owns) or (pose is not None and pose.particles in ("hearts", "sparkle"))
    face_mood = mascot.draw_face(
        pygame, surface, geometry, state, digits=scene.digits if life.show_time else ("", ""),
        pupils=pupils, blush=happy,
        open_amount=(pose.right_open if pose else life.open_amount),
        left_open=(pose.left_open if pose else life.wink),
        squash=(pose.squash if pose else 1.0), mouth=(pose.mouth if pose else ""),
        glance=gaze_x, gaze_y=gy // 4, lift=lift, small_font=fonts["zzz"],
        droop=(pose.droop if pose else 0.0), t=life.t,
    )
    if pose and (pose.particles or owns):
        from dataclasses import replace

        face_mood = replace(face_mood, extra=pose.particles)
    # The clock colon: two dots between the eyes, ticking every second.
    particles(pygame, surface, face_mood, geometry, life, fonts)
    home_text(pygame, surface, fonts, scene, life, face_mood)
    page_dots(pygame, surface, life, face_mood.color)
    toast(pygame, surface, fonts, life)


def home_text(pygame, surface, fonts, scene, life: Life, mood) -> None:
    """Unboxed text under the face: the thought (fact + JIRI's line).

    JIRI's emotion is never written on screen as a label; the face carries it.
    A reflex ("hey, that's my face!") takes the top line while it plays.
    """
    y = 214
    if life.say:
        text(surface, fonts["task"], fit(fonts["task"], life.say, W - 2 * PAD), (W // 2, y - 4), mood.color, anchor="center")
        y += 14
    if scene.reason:
        fact = fit(fonts["reason"], scene.reason, W - 2 * PAD - 24)
        fw = fonts["reason"].size(fact)[0]
        icon(pygame, surface, life.fact_icon or "check", W // 2 - fw // 2 - 12, y + 7, mascot.MUTED, 6, life.t)
        text(surface, fonts["reason"], scramble(fact, life.reveal + 0.6, life.t), (W // 2 + 6, y), (150, 160, 172), anchor="midtop")
        y += 22
    if life.thinking >= 0:
        for i in range(3):
            phase = (life.t * 2.2 - i * 0.25) % 1.0
            lift = int(4 * math.sin(phase * math.pi)) if phase < 0.5 else 0
            pygame.draw.circle(surface, mascot.MUTED, (W // 2 - 16 + i * 16, y + 12 - lift), 4)
    else:
        offset = 0
        for line in wrap(fonts["speech"], scene.speech, W - 2 * PAD, 2):
            text(surface, fonts["speech"], scramble(line, life.reveal, life.t, offset), (W // 2, y), mascot.INK, anchor="midtop")
            offset += len(line) + 1
            y += 21
    if life.thought_count > 1:
        n = life.thought_count
        x0 = W // 2 - (n - 1) * 5
        for i in range(n):
            r = 3 if i == life.thought_index else 2
            col = mood.color if i == life.thought_index else LINE
            pygame.draw.circle(surface, col, (x0 + i * 10, H - 7), r)


def reflex_tag(pygame, surface, fonts, say: str, color) -> None:
    """A pet reflex ('hey, that's my face!') as its own little tag, so it never
    gets confused with the thought in the bubble below."""
    font = fonts["status_bold"]
    label = fit(font, say, 200)
    w = font.size(label)[0] + 24
    r = pygame.Rect(W - PAD - w, 182, w, 26)
    pygame.draw.rect(surface, color, r, border_radius=13)
    pygame.draw.polygon(surface, color, [(r.x + 14, r.centery), (r.x - 6, r.y + 4), (r.x + 14, r.y + 6)])
    text(surface, font, label, (r.centerx, r.centery), mascot.BACKGROUND, anchor="center")


def bubble(pygame, surface, fonts, scene, life: Life, mood, mouth) -> None:
    """Speech bubble from JIRI's mouth. While thinking it holds '• • •'."""
    rect = pygame.Rect(PAD, 214, W - 2 * PAD, 88)
    card(pygame, surface, rect, CARD, 14)
    tail_x = max(rect.x + 30, min(rect.right - 30, mouth[0]))
    pygame.draw.polygon(surface, CARD, [(tail_x - 10, rect.y + 1), (tail_x + 10, rect.y + 1), (tail_x, rect.y - 10)])
    y = rect.y + 10
    if life.pose is not None and getattr(life.pose, "action", "") == "sleep":
        text(surface, fonts["task"], "z z z ...", (rect.x + 16, y + 8), mascot.MUTED)
        return
    if scene.reason:
        kind = life.fact_icon or ("alert" if scene.state in ("alert", "annoyed", "angry", "rage") else "check")
        icon(pygame, surface, kind, rect.x + 20, y + 7, mood.color, 6, life.t)
        fact = fit(fonts["reason"], scene.reason, rect.w - 50 - (11 * life.thought_count if life.thought_count > 1 else 0))
        text(surface, fonts["reason"], scramble(fact, life.reveal + 0.6, life.t), (rect.x + 32, y), mood.color)
        y += 22
    if life.thought_count > 1:
        # The flow: which thought this is, and a bar running down to the next.
        n = life.thought_count
        for i in range(n):
            cx = rect.right - 16 - (n - 1 - i) * 11
            if i == life.thought_index:
                pygame.draw.circle(surface, mood.color, (cx, rect.y + 16), 4)
            else:
                pygame.draw.circle(surface, LINE, (cx, rect.y + 16), 3)
        bar = int((rect.w - 28) * max(0.0, min(1.0, 1 - life.thought_progress)))
        pygame.draw.rect(surface, LINE, (rect.x + 14, rect.bottom - 7, rect.w - 28, 2), border_radius=1)
        pygame.draw.rect(surface, mood.color, (rect.x + 14, rect.bottom - 7, bar, 2), border_radius=1)
    if life.thinking >= 0:
        for i in range(3):
            phase = (life.t * 2.2 - i * 0.25) % 1.0
            lift = int(4 * math.sin(phase * math.pi)) if phase < 0.5 else 0
            pygame.draw.circle(surface, mascot.MUTED, (rect.x + 28 + i * 16, y + 12 - lift), 4)
        return
    offset = 0
    for line in wrap(fonts["speech"], scene.speech, rect.w - 32, 2 if scene.reason else 3):
        text(surface, fonts["speech"], scramble(line, life.reveal, life.t, offset), (rect.x + 16, y), mascot.INK)
        offset += len(line) + 1
        y += 21


SCRAMBLE_GLYPHS = "!<>-_/[]{}=+*^?#%&@$~"
SCRAMBLE_STEP = 0.016   # seconds between successive characters settling
SCRAMBLE_LEAD = 0.18    # every character scrambles at least this long


def scramble(value: str, elapsed: float, t: float, offset: int = 0) -> str:
    """Decode effect: characters churn through glyphs, then settle left to right.

    `elapsed` is seconds since the text changed; `offset` is this line's
    position in the whole message so multi-line text settles as one stream.
    Spaces never scramble, so word shapes stay readable while it resolves.
    """
    if elapsed >= SCRAMBLE_LEAD + (offset + len(value)) * SCRAMBLE_STEP:
        return value
    tick = int(t * 30)
    out = []
    for i, ch in enumerate(value):
        settle = SCRAMBLE_LEAD + (offset + i) * SCRAMBLE_STEP
        if ch == " " or elapsed >= settle:
            out.append(ch)
        else:
            # 5 and 3 are coprime with the glyph count, so every glyph shows up.
            out.append(SCRAMBLE_GLYPHS[(tick * 3 + (offset + i) * 5) % len(SCRAMBLE_GLYPHS)])
    return "".join(out)


# --- Info screens -----------------------------------------------------------

def page_tasks(pygame, surface, fonts, scene, life: Life) -> None:
    header(pygame, surface, fonts, scene, "tasks", life)
    late = sum(1 for t in scene.tasks if t[2] == "late")
    soon = sum(1 for t in scene.tasks if t[2] == "soon")
    later = len(scene.tasks) - late - soon
    stats = (("alert", late, "late", mascot.CORAL), ("clock", soon, "soon", mascot.AMBER), ("list", later, "later", mascot.MINT))
    cw = (W - 2 * PAD - 16) // 3
    for i, (kind, n, label, color) in enumerate(stats):
        r = pygame.Rect(PAD + i * (cw + 8), 46, cw, 44)
        card(pygame, surface, r)
        icon(pygame, surface, kind, r.x + 18, r.centery, color if n else mascot.MUTED, 7)
        text(surface, fonts["stat"], str(n), (r.x + 34, r.y + 6), mascot.INK if n else mascot.MUTED)
        text(surface, fonts["small"], label, (r.right - 10, r.y + 16), mascot.MUTED, anchor="topright")
    if not scene.tasks:
        icon(pygame, surface, "check", W // 2, 180, mascot.MINT, 18)
        text(surface, fonts["task"], "Nothing on the list", (W // 2, 214), mascot.MUTED, anchor="midtop")
        page_dots(pygame, surface, life, PAGE_COLORS["tasks"])
        return
    y = 100
    for title, due, tone in scene.tasks[:4]:
        color = TONE.get(tone, mascot.MINT)
        r = pygame.Rect(PAD, y, W - 2 * PAD, 46)
        card(pygame, surface, r)
        pulse = 2 if tone == "late" and life.tick else 0
        pygame.draw.rect(surface, color, (r.x, r.y + 8, 4 + pulse, r.h - 16), border_radius=2)
        text(surface, fonts["task"], fit(fonts["task"], title, r.w - 150), (r.x + 18, r.y + 13), mascot.INK)
        icon(pygame, surface, "clock", r.right - 18 - fonts["small"].size(due)[0] - 12, r.centery, color, 5)
        text(surface, fonts["small"], due, (r.right - 14, r.centery), color, anchor="midright")
        y += 52
    page_dots(pygame, surface, life, PAGE_COLORS["tasks"])


def page_weather(pygame, surface, fonts, scene, life: Life) -> None:
    header(pygame, surface, fonts, scene, "weather", life)
    if not scene.weather:
        text(surface, fonts["task"], "No weather yet", (W // 2, 160), mascot.MUTED, anchor="center")
        page_dots(pygame, surface, life, PAGE_COLORS["weather"])
        return
    temp, condition, rain, stale, location, hours, feels, humidity, wind = scene.weather
    kind = weather_kind(condition, rain)
    tint = mascot.MUTED if stale else (mascot.AMBER if kind == "sun" else mascot.SKY)
    cx, cy = 82, 98
    if kind == "sun":
        pygame.draw.circle(surface, tint, (cx, cy), 24)
        for i in range(10):
            a = life.t * 0.5 + i * math.pi / 5
            pygame.draw.line(surface, tint, (cx + int(32 * math.cos(a)), cy + int(32 * math.sin(a))),
                             (cx + int(40 * math.cos(a)), cy + int(40 * math.sin(a))), 3)
    else:
        icon(pygame, surface, "cloud", cx, cy - 4, (170, 186, 200) if not stale else mascot.MUTED, 30)
        if kind == "rain":
            for i in range(5):
                phase = (life.t * 1.6 + i * 0.37) % 1.0
                dx, dy = cx - 24 + i * 12, cy + 16 + int(phase * 26)
                pygame.draw.line(surface, mascot.SKY, (dx, dy), (dx - 3, dy + 7), 3)
    if temp is not None:
        text(surface, fonts["huge"], f"{round(temp)}°", (148, 52), mascot.INK)
    text(surface, fonts["task"], fit(fonts["task"], condition or "-", W - 300 - PAD), (300, 62), tint)
    place = location.split(",")[0] if location else ""
    text(surface, fonts["small"], fit(fonts["small"], place + ("  · old reading" if stale else ""), W - 300 - PAD),
         (300, 86), mascot.AMBER if stale else mascot.MUTED)
    chips = (("thermo", "feels", f"{round(feels)}°" if feels is not None else "-"),
             ("humidity", "humid", f"{round(humidity)}%" if humidity is not None else "-"),
             ("wind", "wind", f"{round(wind)} km/h" if wind is not None else "-"),
             ("rain", "rain", f"{rain}%"))
    cw = (W - 2 * PAD - 24) // 4
    for i, (k, label, value) in enumerate(chips):
        r = pygame.Rect(PAD + i * (cw + 8), 150, cw, 48)
        card(pygame, surface, r)
        icon(pygame, surface, k, r.x + 15, r.y + 15, mascot.SKY, 6)
        text(surface, fonts["small"], label, (r.x + 28, r.y + 8), mascot.MUTED)
        text(surface, fonts["task"], value, (r.x + 10, r.y + 24), mascot.INK)
    if hours:
        temps = [h[1] for h in hours]
        lo, hi = min(temps), max(temps)
        bw = (W - 2 * PAD) // len(hours)
        for i, (label, ht, hr) in enumerate(hours):
            x = PAD + i * bw
            frac = 0.5 if hi == lo else (ht - lo) / (hi - lo)
            bh = 6 + int(frac * 22)
            pygame.draw.rect(surface, mascot.SKY if hr >= 50 else mascot.AMBER, (x + bw // 2 - 12, 266 - bh, 24, bh), border_radius=4)
            text(surface, fonts["small"], f"{round(ht)}°", (x + bw // 2, 222), mascot.INK, anchor="midtop")
            text(surface, fonts["small"], label.replace(":00", ""), (x + bw // 2, 272), mascot.MUTED, anchor="midtop")
    page_dots(pygame, surface, life, PAGE_COLORS["weather"])


def page_water(pygame, surface, fonts, scene, life: Life) -> None:
    header(pygame, surface, fonts, scene, "water", life)
    color = PAGE_COLORS["water"]
    if not scene.water:
        text(surface, fonts["task"], "Set a water goal in the dashboard", (W // 2, 160), mascot.MUTED, anchor="center")
        page_dots(pygame, surface, life, color)
        return
    ml, goal, pct, week = scene.water
    gx, gy, gw, gh = PAD + 8, 52, 96, 196
    level = max(0.0, min(1.0, ml / goal if goal else 0))
    top = gy + gh - int(gh * level)
    if level > 0:
        pts = [(x, top + int(math.sin(life.t * 2.4 + x * 0.1) * 3)) for x in range(gx, gx + gw + 1, 4)]
        pygame.draw.polygon(surface, color, pts + [(gx + gw, gy + gh), (gx, gy + gh)])
        for i in range(3):
            phase = (life.t * 0.5 + i * 0.33) % 1.0
            pygame.draw.circle(surface, (200, 235, 255), (gx + 22 + i * 26, gy + gh - int(phase * (gy + gh - top))), 3, 1)
    pygame.draw.rect(surface, mascot.INK, (gx - 4, gy - 4, gw + 8, gh + 8), 3, border_radius=12)
    x0 = 150
    text(surface, fonts["huge"], f"{pct}%", (x0, 46), mascot.INK)
    text(surface, fonts["task"], f"{ml / 1000:.1f} of {goal / 1000:.1f} L", (x0 + 2, 112), color)
    left = max(0, goal - ml)
    total = min(12, max(1, round(goal / 250)))
    full = min(total, int(ml // 250))
    for i in range(total):
        cx = x0 + 10 + (i % 6) * 26
        cy = 150 + (i // 6) * 26
        icon(pygame, surface, "glass_full" if i < full else "glass", cx, cy, color if i < full else LINE, 8)
    text(surface, fonts["small"], "goal reached!" if left == 0 else f"{left} ml to go", (x0 + 2, 196), mascot.MUTED)
    if week:
        bw = (W - x0 - PAD) // len(week)
        for i, (day, p) in enumerate(week):
            x = x0 + i * bw
            bh = max(3, int(min(100, p) / 100 * 34))
            pygame.draw.rect(surface, LINE, (x + 4, 226, bw - 10, 34), border_radius=4)
            pygame.draw.rect(surface, color if p >= 100 else (70, 120, 170), (x + 4, 260 - bh, bw - 10, bh), border_radius=4)
            text(surface, fonts["small"], day, (x + bw // 2 - 3, 266), mascot.MUTED, anchor="midtop")
    page_dots(pygame, surface, life, color)


def page_focus(pygame, surface, fonts, scene, life: Life) -> None:
    header(pygame, surface, fonts, scene, "focus", life)
    color = PAGE_COLORS["focus"]
    if not scene.focus:
        icon(pygame, surface, "clock", W // 2, 140, mascot.MUTED, 22)
        text(surface, fonts["task"], "No focus session running", (W // 2, 184), mascot.MUTED, anchor="midtop")
        page_dots(pygame, surface, life, color)
        return
    title, remaining, progress, status = scene.focus
    cx, cy, r = W // 2, 140, 74
    pygame.draw.circle(surface, (34, 30, 52), (cx, cy), r + 6, 12)
    steps = max(1, int(120 * progress))
    for k in range(steps + 1):
        a = math.pi / 2 - 2 * math.pi * progress * k / steps
        pygame.draw.circle(surface, color, (cx + int(r * math.cos(a)), cy - int(r * math.sin(a))), 6)
    a = -life.t * (2 * math.pi / 60) + math.pi / 2
    pygame.draw.circle(surface, mascot.INK, (cx + int((r + 18) * math.cos(a)), cy - int((r + 18) * math.sin(a))), 3)
    text(surface, fonts["clock"], remaining, (cx, cy - 6), mascot.INK, anchor="center")
    text(surface, fonts["small"], "left" if status == "running" else status, (cx, cy + 30),
         mascot.AMBER if status != "running" else mascot.MUTED, anchor="center")
    text(surface, fonts["task"], fit(fonts["task"], title, W - 2 * PAD), (cx, 256), color, anchor="center")
    text(surface, fonts["small"], f"{round(progress * 100)}% done", (cx, 280), mascot.MUTED, anchor="center")
    page_dots(pygame, surface, life, color)


def page_usage(pygame, surface, fonts, scene, life: Life) -> None:
    from .renderer import PROVIDER_COLORS, TRACK, bar_parts, gauge_color

    header(pygame, surface, fonts, scene, "usage", life)
    if not scene.usage:
        text(surface, fonts["task"], "No usage pushed yet", (W // 2, 150), mascot.MUTED, anchor="center")
        page_dots(pygame, surface, life, PAGE_COLORS["usage"])
        return
    font = fonts["gauge_big"]
    y = 46
    for row in scene.usage[:2]:
        accent = mascot.MUTED if row.stale else PROVIDER_COLORS.get(row.provider, mascot.INK)
        r = pygame.Rect(PAD, y, W - 2 * PAD, 124)
        card(pygame, surface, r)
        text(surface, fonts["gauge_head"], row.title, (r.x + 14, r.y + 9), accent)
        text(surface, fonts["small"], row.age, (r.right - 12, r.y + 10), mascot.MUTED, anchor="topright")
        gy = r.y + 36
        for label, pct, countdown in row.gauges:
            if pct is None:
                continue
            col = mascot.MUTED if row.stale or countdown == "reset" else gauge_color(float(pct))
            filled, track = bar_parts(float(pct), cells=14)
            x = r.x + 14
            for chunk, c in ((f"{label:<3} ", mascot.MUTED), (filled, col), (track, TRACK),
                             (f" {float(pct):>3.0f}%", col), (f"  {countdown}" if countdown else "", mascot.MUTED)):
                if chunk:
                    x = text(surface, font, chunk, (x, gy), c).right
            gy += 26
        y += 132
    page_dots(pygame, surface, life, PAGE_COLORS["usage"])


def page_notes(pygame, surface, fonts, scene, life: Life) -> None:
    header(pygame, surface, fonts, scene, "notes", life)
    color = PAGE_COLORS["notes"]
    if not scene.notes:
        icon(pygame, surface, "notes", W // 2, 140, mascot.MUTED, 20)
        text(surface, fonts["task"], "No notes yet", (W // 2, 182), mascot.MUTED, anchor="midtop")
        page_dots(pygame, surface, life, color)
        return
    y = 48
    h = (H - y - 18) // len(scene.notes) - 8
    for title, body, age in scene.notes:
        r = pygame.Rect(PAD, y, W - 2 * PAD, h)
        card(pygame, surface, r)
        pygame.draw.rect(surface, color, (r.x, r.y + 8, 4, r.h - 16), border_radius=2)
        text(surface, fonts["task"], fit(fonts["task"], title, r.w - 110), (r.x + 16, r.y + 8), mascot.INK)
        text(surface, fonts["small"], age, (r.right - 12, r.y + 11), mascot.MUTED, anchor="topright")
        ly = r.y + 32
        for line in wrap(fonts["small"], body, r.w - 32, max(1, (h - 38) // 18)):
            text(surface, fonts["small"], line, (r.x + 16, ly), (170, 180, 190))
            ly += 18
        y += h + 8
    page_dots(pygame, surface, life, color)


DRAW = {
    "face": page_face, "tasks": page_tasks, "notes": page_notes, "weather": page_weather,
    "water": page_water, "focus": page_focus, "usage": page_usage,
}


def nav_arrows(pygame, surface, life: Life, color) -> None:
    """Prev / next buttons at the screen edges; they fade in after a touch."""
    if life.arrows <= 0.01:
        return
    layer = pygame.Surface((W, H), pygame.SRCALPHA)
    alpha = int(220 * life.arrows)
    for cx, d in ((30, -1), (W - 30, 1)):
        pygame.draw.circle(layer, (28, 34, 44, alpha), (cx, H // 2), 22)
        pygame.draw.circle(layer, (*color, alpha), (cx, H // 2), 22, 2)
        pts = [(cx - 4 * d, H // 2 - 9), (cx + 5 * d, H // 2), (cx - 4 * d, H // 2 + 9)]
        pygame.draw.lines(layer, (*mascot.INK, alpha), False, pts, 4)
    surface.blit(layer, (0, 0))


def draw_page(pygame, surface, fonts, scene, page: str, life: Life) -> None:
    surface.fill(mascot.BACKGROUND)
    DRAW.get(page, page_face)(pygame, surface, fonts, scene, life)
    nav_arrows(pygame, surface, life, PAGE_COLORS.get(page, mascot.PINK))
    if page != "face":
        toast(pygame, surface, fonts, life)


# --- Ambient particles (pure functions of time) -----------------------------

def particles(pygame, surface, mood, geometry, life: Life, fonts) -> None:
    x, y, w, h = geometry.bounds
    t = life.t
    if mood.extra == "hearts":
        for i in range(3):
            phase = (t * 0.45 + i / 3) % 1.0
            hx = x + w + 6 + int(8 * math.sin(phase * 6 + i))
            hy = y + h // 2 - int(phase * 90)
            r = 5
            col = (255, 120, 160)
            pygame.draw.circle(surface, col, (hx - r // 2 - 1, hy), r // 2 + 2)
            pygame.draw.circle(surface, col, (hx + r // 2 + 1, hy), r // 2 + 2)
            pygame.draw.polygon(surface, col, [(hx - r - 1, hy + 1), (hx + r + 1, hy + 1), (hx, hy + r + 4)])
    elif mood.extra == "sparkle" or life.giggle >= 0:
        for i, (ox, oy) in enumerate(((-22, 4), (w + 16, -6), (w + 4, h - 2), (-12, h - 18), (w // 2, -16))):
            phase = (t * 0.8 + i * 0.23) % 1.0
            r = int(2 + 5 * math.sin(phase * math.pi))
            if r > 2:
                px, py = x + ox, y + oy
                pygame.draw.line(surface, mood.color, (px - r, py), (px + r, py), 2)
                pygame.draw.line(surface, mood.color, (px, py - r), (px, py + r), 2)
    elif mood.extra == "stars":
        for i, (ox, oy) in enumerate(((-30, -24), (w // 3, -34), (w + 20, -18), (w - 30, -40), (-10, 30))):
            phase = (t * 0.6 + i * 0.29) % 1.0
            r = 1 + int(3 * math.sin(phase * math.pi))
            px, py = x + ox, y + oy
            pygame.draw.line(surface, (255, 236, 170), (px - r, py), (px + r, py), 2)
            pygame.draw.line(surface, (255, 236, 170), (px, py - r), (px, py + r), 2)
    elif mood.extra == "rain":
        for i in range(7):
            phase = (t * 0.9 + i * 0.143) % 1.0
            px = x - 30 + i * (w + 60) // 6
            py = y - 30 + int(phase * (h + 60))
            pygame.draw.line(surface, mascot.SKY, (px, py), (px - 2, py + 7), 2)
    elif mood.extra == "zzz":
        for i in range(3):
            phase = (t * 0.25 + i / 3) % 1.0
            img = fonts["zzz"].render("z", True, mood.color)
            img.set_alpha(int(255 * (1 - phase)))
            surface.blit(img, (x + w - 10 + int(phase * 30), y + 10 - int(phase * 60)))
    elif mood.extra == "sweat":
        phase = (t * 0.5) % 1.0
        dx, dy = x + w + 4, y + 6 + int(phase * 50)
        pygame.draw.circle(surface, mascot.SKY, (dx, dy + 8), 5)
        pygame.draw.polygon(surface, mascot.SKY, [(dx - 4, dy + 6), (dx + 4, dy + 6), (dx, dy - 3)])


# --- Splash / boot ----------------------------------------------------------

def draw_splash(pygame, surface, fonts, page: str, progress: float, life: Life) -> None:
    """A coloured card wipes across with the next screen's icon and name."""
    color = PAGE_COLORS.get(page, mascot.MINT)
    ease = lambda v: 1 - (1 - v) ** 3  # noqa: E731
    left = int(W * (1 - ease(progress / 0.5))) if progress < 0.5 else -int(W * ease((progress - 0.5) / 0.5))
    pygame.draw.rect(surface, color, (left, 0, W, H))
    cx = left + W // 2
    icon(pygame, surface, page, cx, 130, mascot.BACKGROUND, 24, life.t, bg=color)
    text(surface, fonts["big"], PAGE_TITLES.get(page, page), (cx, 192), mascot.BACKGROUND, anchor="center")


def draw_boot(pygame, surface, fonts, progress: float, life: Life, greeting: str = "") -> None:
    """JIRI wakes up: closed eyes, eyes open, a happy squint, a greeting."""
    surface.fill(mascot.BACKGROUND)
    geometry = mascot.face_geometry(W // 2, 130)
    if progress < 0.35:
        state, open_amount = "sleeping", 1.0
    elif progress < 0.55:
        state, open_amount = "idle", (progress - 0.35) / 0.2
    else:
        state, open_amount = "happy", 1.0
    mascot.draw_face(pygame, surface, geometry, state, open_amount=open_amount, small_font=fonts["zzz"])
    if progress > 0.6 and greeting:
        shown = greeting[: int((progress - 0.6) / 0.3 * len(greeting)) + 1]
        text(surface, fonts["task"], shown, (W // 2, 262), mascot.MINT, anchor="center")
