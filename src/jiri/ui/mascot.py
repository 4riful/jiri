"""JIRI's face: two rounded eyes that double as the clock.

Pure drawing. Nothing here reads the database, the network, or the wall clock;
the caller passes in everything (mood, digits, animation amounts). That keeps
the face testable headless and cheap enough for a Pi 3B at 10-15 FPS.

Visual language (deliberately minimal, our own palette):
- Two big rounded-rectangle eyes, no pupils.
- Moods are made by *cutting* the eye with background-coloured eyelids
  (upper lid slope, lower "cheek" curve), never by redrawing the eye.
- The left eye shows the hour and the right eye the minutes, as cut-out
  segment digits. During focus they show the countdown instead.
- A tiny mouth carries the joke; one mood colour carries the urgency.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

BACKGROUND = (11, 15, 20)
INK = (232, 238, 242)
MUTED = (120, 134, 146)

MINT = (127, 245, 200)
SKY = (124, 200, 255)
AMBER = (255, 181, 71)
ORANGE = (255, 146, 84)
CORAL = (255, 92, 108)
SLATE = (90, 100, 112)
# JIRI's eyes are pink in every mood: the shape (lids, pupils, squint, mouth)
# carries the feeling, not a colour swap. Only rage deepens and sleep dims.
PINK = (255, 104, 140)
PINK_DEEP = (255, 72, 108)
PINK_DIM = (150, 66, 88)


@dataclass(frozen=True)
class Mood:
    color: tuple[int, int, int]
    # Fraction of eye height the upper lid covers at the inner / outer corner.
    lid_inner: float = 0.0
    lid_outer: float = 0.0
    # Fraction of eye height the lower "cheek" curve pushes up (happy squint).
    cheek: float = 0.0
    height: float = 1.0
    mouth: str = "smile"  # smile | grin | flat | o | wave | frown | none
    extra: str = ""       # sweat | rain | zzz | sparkle | bang | ""
    closed: bool = False
    outline: bool = False
    shades: bool = False                      # sunglasses (sunny weather)
    look: tuple[float, float] | None = None   # where the pupils want to look
    shiver: bool = False                      # cold: eyes tremble


# Keyed by the face states persona.py produces (see ui/face.py FACE_STATES).
MOODS: dict[str, Mood] = {
    "idle": Mood(PINK, mouth="smile"),
    "blink": Mood(PINK, mouth="smile"),
    "happy": Mood(PINK, cheek=0.30, mouth="grin", extra="sparkle"),
    # Plain eyes glancing sideways (e.g. at your laptop's AI usage). The old
    # slanted-lid "smirk" read as sad, so it's gone.
    "smirk": Mood(PINK, look=(0.85, 0.15), mouth="smile"),
    "curious": Mood(PINK, height=1.06, mouth="o"),
    "focused": Mood(PINK, lid_inner=0.24, lid_outer=0.24, mouth="flat"),
    "alert": Mood(PINK, height=1.06, mouth="o", extra="bang"),
    "annoyed": Mood(PINK, lid_inner=0.30, lid_outer=0.08, mouth="flat"),
    "angry": Mood(PINK, lid_inner=0.40, lid_outer=0.04, mouth="frown"),
    "rage": Mood(PINK_DEEP, lid_inner=0.46, lid_outer=0.0, height=0.96, mouth="frown", extra="bang"),
    "tired": Mood(PINK_DIM, lid_inner=0.38, lid_outer=0.42, mouth="flat"),
    "sleeping": Mood(PINK_DIM, closed=True, mouth="none", extra="zzz"),
    # Weather has its own looks, not a recoloured "happy".
    "weather_sunny": Mood(PINK, shades=True, mouth="grin"),
    "weather_hot": Mood(PINK, shades=True, mouth="wave", extra="sweat"),
    "weather_rain": Mood(PINK, look=(0.2, -1.0), mouth="o", extra="rain"),
    "weather_night": Mood(PINK, look=(-0.3, -1.0), mouth="smile", extra="stars"),
    "weather_cloudy": Mood(PINK, look=(0.6, -0.9), mouth="flat"),
    "weather_cold": Mood(PINK, lid_inner=0.22, lid_outer=0.22, mouth="wave", shiver=True),
    "ai_offline": Mood(SLATE, lid_inner=0.32, lid_outer=0.32, mouth="flat", outline=True),
    "system_warning": Mood(PINK, lid_inner=0.10, lid_outer=0.28, mouth="wave", extra="bang"),
}


def mood_for(state: str) -> Mood:
    return MOODS.get(state, MOODS["idle"])


# --- Segment digits ---------------------------------------------------------

#   a
# f   b
#   g
# e   c
#   d
_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g", " ": "",
}


def draw_digit(pygame, surface, ch: str, x: int, y: int, w: int, h: int, t: int, color) -> None:
    """Rounded seven-segment digit. Pills read friendlier than a font at 1 m."""
    segs = _SEGMENTS.get(ch, "")
    half = h // 2
    r = t // 2
    spans = {
        "a": (x + r, y, w - t, t),
        "g": (x + r, y + half - r, w - t, t),
        "d": (x + r, y + h - t, w - t, t),
        "f": (x, y + r, t, half),
        "b": (x + w - t, y + r, t, half),
        "e": (x, y + half - r + r, t, half - r),
        "c": (x + w - t, y + half, t, half - r),
    }
    for s in segs:
        pygame.draw.rect(surface, color, spans[s], border_radius=r)


def draw_digits(pygame, surface, text: str, cx: int, cy: int, dh: int, color) -> None:
    dw = int(dh * 0.56)
    t = max(4, int(dh * 0.17))
    gap = max(4, int(dh * 0.16))
    total = len(text) * dw + (len(text) - 1) * gap
    x = cx - total // 2
    for ch in text:
        draw_digit(pygame, surface, ch, x, cy - dh // 2, dw, dh, t, color)
        x += dw + gap


# --- Eyes -------------------------------------------------------------------

def draw_eye(
    pygame,
    surface,
    rect: tuple[int, int, int, int],
    mood: Mood,
    *,
    digits: str = "",
    inner_on_right: bool,
    open_amount: float = 1.0,
    pupil: tuple[float, float] | None = None,
    droop: float = 0.0,
) -> None:
    """Draw one eye into `rect` (x, y, w, h) on `surface`.

    `open_amount` < 1 squashes the eye vertically around its centre (blinks,
    mood-change pops). Lids are applied in eye-local space before squashing,
    so a squashed angry eye is still an angry eye.
    """
    x, y, w, h = rect
    h = max(4, int(h * mood.height))
    y = rect[1] + (rect[3] - h) // 2
    radius = max(6, int(min(w, h) * 0.26))

    if mood.closed:
        _closed_eye(pygame, surface, x, y, w, h, mood.color)
        return
    if droop > 0.01:
        # Heavy lids (tired, yawning): a real upper lid coming down over the
        # pupil, never a squash of the whole eye.
        from dataclasses import replace as _replace

        mood = _replace(mood, lid_inner=max(mood.lid_inner, droop * 0.6), lid_outer=max(mood.lid_outer, droop * 0.6))

    eye = pygame.Surface((w, h))
    eye.fill(BACKGROUND)
    if mood.outline:
        pygame.draw.rect(eye, mood.color, (0, 0, w, h), width=5, border_radius=radius)
    else:
        pygame.draw.rect(eye, mood.color, (0, 0, w, h), border_radius=radius)
    if mood.shades and not digits:
        _draw_shades(pygame, eye, w, h, mood.color)
    elif digits:
        # The clock must survive every mood: fit the digits into the part of
        # the eye the lids leave open, instead of letting a lid eat "05" -> "U5".
        top = max(mood.lid_inner, mood.lid_outer) * h
        bottom = h - mood.cheek * h * 0.75
        room = bottom - top
        dh = int(min(h * 0.50, room * 0.70))
        cy = int(top + room / 2)
        ink = mood.color if mood.outline else BACKGROUND
        draw_digits(pygame, eye, digits, w // 2, cy, dh, ink)
    elif pupil is not None and not mood.outline:
        _draw_pupil(pygame, eye, w, h, mood, pupil)

    inner = mood.lid_inner * h
    outer = mood.lid_outer * h
    if inner or outer:
        left_drop, right_drop = (outer, inner) if inner_on_right else (inner, outer)
        pygame.draw.polygon(eye, BACKGROUND, [(-2, -2), (w + 2, -2), (w + 2, right_drop), (-2, left_drop)])
    if mood.cheek:
        top = int(h * (1 - mood.cheek))
        pygame.draw.ellipse(eye, BACKGROUND, (-int(w * 0.2), top, int(w * 1.4), h))

    open_amount = max(0.0, min(1.0, open_amount))
    if open_amount < 0.98:
        sh = max(3, int(h * open_amount))
        if sh <= 8:
            # Fully shut reads better as a soft line than a squashed sliver.
            pygame.draw.rect(surface, mood.color, (x + 6, y + h // 2 - 3, w - 12, 6), border_radius=3)
            return
        eye = pygame.transform.smoothscale(eye, (w, sh))
        surface.blit(eye, (x, y + (h - sh) // 2))
        return
    surface.blit(eye, (x, y))


def _draw_shades(pygame, eye, w: int, h: int, frame) -> None:
    """Sunglasses: a dark lens inside a pink frame, with a diagonal glint."""
    radius = max(6, int(min(w, h) * 0.26))
    lens = pygame.Rect(7, 7, w - 14, h - 14)
    pygame.draw.rect(eye, (22, 24, 34), lens, border_radius=max(4, radius - 6))
    pygame.draw.rect(eye, (40, 44, 60), (lens.x, lens.y, lens.w, lens.h // 2), border_top_left_radius=max(4, radius - 6),
                     border_top_right_radius=max(4, radius - 6))
    for k, width in ((0, 10), (22, 5)):
        x0 = lens.x + lens.w * 0.25 + k
        pygame.draw.line(eye, (230, 236, 245), (x0, lens.y + 10), (x0 - 22, lens.bottom - 12), width)


def _draw_pupil(pygame, eye, w: int, h: int, mood: Mood, look: tuple[float, float]) -> None:
    """A big dark pupil with a light glint: where JIRI is looking, visibly.

    `look` is -1..1 on each axis. The pupil stays inside the part of the eye
    the lids leave open, so an angry squint still shows where it's glaring.
    """
    pw, ph = int(w * 0.40), int(h * 0.50)
    top = max(mood.lid_inner, mood.lid_outer) * h
    bottom = h - mood.cheek * h * 0.8
    lx = max(-1.0, min(1.0, look[0]))
    ly = max(-1.0, min(1.0, look[1]))
    cx = w / 2 + lx * (w / 2 - pw / 2 - 10)
    cy = (top + bottom) / 2 + ly * max(0.0, (bottom - top) / 2 - ph / 2 - 6)
    cy = max(top + ph / 2 + 2, min(bottom - ph / 2 + 6, cy))
    rect = pygame.Rect(0, 0, pw, ph)
    rect.center = (int(cx), int(cy))
    pygame.draw.rect(eye, BACKGROUND, rect, border_radius=int(pw * 0.42))
    # Glint: a big and a small highlight, upper-left — the "alive" sparkle.
    pygame.draw.ellipse(eye, (245, 250, 252), (rect.x + pw * 0.16, rect.y + ph * 0.14, pw * 0.30, ph * 0.24))
    pygame.draw.circle(eye, (245, 250, 252), (int(rect.x + pw * 0.70), int(rect.y + ph * 0.72)), max(2, int(pw * 0.07)))


def _closed_eye(pygame, surface, x, y, w, h, color) -> None:
    # A content "u" curve: the classic sleeping-cartoon eye.
    cy = y + h // 2
    pygame.draw.arc(surface, color, (x + 10, cy - h // 4, w - 20, h // 2), math.pi, 2 * math.pi, 7)


def draw_mouth(pygame, surface, kind: str, cx: int, cy: int, color) -> None:
    if kind == "smile":
        pygame.draw.arc(surface, color, (cx - 20, cy - 16, 40, 26), math.pi * 1.12, math.pi * 1.88, 5)
    elif kind == "grin":
        pygame.draw.ellipse(surface, color, (cx - 18, cy - 8, 36, 22))
        pygame.draw.rect(surface, BACKGROUND, (cx - 20, cy - 10, 40, 11))
    elif kind == "flat":
        pygame.draw.rect(surface, color, (cx - 12, cy - 2, 24, 4), border_radius=2)
    elif kind == "o":
        pygame.draw.circle(surface, color, (cx, cy), 8, 4)
    elif kind == "wave":
        pts = [(cx - 18 + i * 3, cy + int(3 * math.sin(i * 1.05))) for i in range(13)]
        pygame.draw.lines(surface, color, False, pts, 4)
    elif kind == "yawn":
        pygame.draw.ellipse(surface, color, (cx - 11, cy - 6, 22, 26), 4)
    elif kind == "frown":
        pygame.draw.arc(surface, color, (cx - 16, cy - 2, 32, 20), math.pi * 0.1, math.pi * 0.9, 4)


def draw_extra(pygame, surface, kind: str, face: tuple[int, int, int, int], color, font=None) -> None:
    x, y, w, h = face
    if kind == "sweat":
        dx, dy = x + w - 6, y + 4
        pygame.draw.circle(surface, SKY, (dx, dy + 14), 7)
        pygame.draw.polygon(surface, SKY, [(dx - 6, dy + 11), (dx + 6, dy + 11), (dx, dy - 2)])
    elif kind == "rain":
        for ox, oy in ((14, 6), (26, 30), (10, 50)):
            dx, dy = x + w + ox, y + oy
            pygame.draw.circle(surface, SKY, (dx, dy + 8), 5)
            pygame.draw.polygon(surface, SKY, [(dx - 4, dy + 6), (dx + 4, dy + 6), (dx, dy - 3)])
    elif kind == "sparkle":
        for ox, oy, r in ((-14, 8, 5), (w + 12, 2, 6), (w + 2, h - 6, 4)):
            px, py = x + ox, y + oy
            pygame.draw.line(surface, color, (px - r, py), (px + r, py), 2)
            pygame.draw.line(surface, color, (px, py - r), (px, py + r), 2)
    elif kind == "bang":
        px, py = x + w + 8, y + 2
        pygame.draw.rect(surface, color, (px, py, 6, 20), border_radius=3)
        pygame.draw.circle(surface, color, (px + 3, py + 28), 3)
    elif kind == "zzz" and font is not None:
        for i, size in enumerate((0, 1, 2)):
            label = font.render("z", True, color)
            surface.blit(label, (x + w - 10 + i * 14, y - 4 - i * 14))


@dataclass(frozen=True)
class FaceGeometry:
    left: tuple[int, int, int, int]
    right: tuple[int, int, int, int]
    mouth: tuple[int, int]
    bounds: tuple[int, int, int, int]


def face_geometry(cx: int, cy: int, eye_w: int = 138, eye_h: int = 128, gap: int = 26) -> FaceGeometry:
    lx = cx - gap // 2 - eye_w
    rx = cx + gap // 2
    ey = cy - eye_h // 2
    return FaceGeometry(
        left=(lx, ey, eye_w, eye_h),
        right=(rx, ey, eye_w, eye_h),
        mouth=(cx, ey + eye_h + 18),
        bounds=(lx, ey, eye_w * 2 + gap, eye_h),
    )


def draw_face(
    pygame,
    surface,
    geometry: FaceGeometry,
    state: str,
    *,
    digits: tuple[str, str] = ("", ""),
    open_amount: float = 1.0,
    glance: int = 0,
    small_font=None,
    left_open: float = 1.0,
    lift: int = 0,
    squash: float = 1.0,
    mouth: str = "",
    gaze_y: int = 0,
    pupils: tuple[float, float] | None = None,
    blush: bool = False,
    droop: float = 0.0,
    t: float = 0.0,
) -> Mood:
    """`left_open` < 1 winks the left eye; `lift` raises the eyes (thinking);
    `squash` > 1 stretches the eyes tall and thin, < 1 squashes them wide;
    `mouth` overrides the mood's mouth."""
    mood = mood_for(state)
    if mood.look is not None and pupils is not None:
        # The mood has somewhere to look (up at the rain, the stars): blend it
        # with JIRI's own gaze so it still glances around a little.
        pupils = (mood.look[0] * 0.7 + pupils[0] * 0.3, mood.look[1] * 0.7 + pupils[1] * 0.3)
    if mood.shiver:
        glance += 2 if int(t * 18) % 2 else -2
    lx, ly, lw, lh = geometry.left
    rx, ry, rw, rh = geometry.right
    # Squash & stretch keeps volume: taller eyes get thinner, and vice versa.
    sw, sh = int(lw / math.sqrt(squash)), int(lh * squash)
    dy = gaze_y - lift
    left_rect = (lx + glance + (lw - sw) // 2, ly + dy + (lh - sh) // 2, sw, sh)
    right_rect = (rx + glance + (rw - sw) // 2, ry + dy + (rh - sh) // 2, sw, sh)
    draw_eye(pygame, surface, left_rect, mood, digits=digits[0], inner_on_right=True,
             open_amount=min(open_amount, left_open), pupil=pupils, droop=droop)
    draw_eye(pygame, surface, right_rect, mood, digits=digits[1], inner_on_right=False,
             open_amount=open_amount, pupil=pupils, droop=droop)
    if mood.shades and not digits[0]:
        # The bridge between the lenses.
        pygame.draw.line(surface, mood.color, (left_rect[0] + left_rect[2] - 4, left_rect[1] + 28),
                         (right_rect[0] + 4, right_rect[1] + 28), 6)
    if blush and not mood.closed:
        for r in (left_rect, right_rect):
            pygame.draw.ellipse(surface, (255, 170, 192), (r[0] + r[2] // 2 - 22, r[1] + r[3] + 4, 44, 12))
    mx, my = geometry.mouth
    draw_mouth(pygame, surface, mouth or mood.mouth, mx + glance // 2, my + dy // 2, mood.color)
    if mood.extra:
        draw_extra(pygame, surface, mood.extra, geometry.bounds, mood.color, small_font)
    return mood
