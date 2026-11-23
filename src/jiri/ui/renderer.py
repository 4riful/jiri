"""Compose one 480x320 JIRI frame: status line, face-clock, and what JIRI says.

Layout (480x320, designed for a 3.5" SPI panel read from about 1 m):

    +--------------------------------------------------+
    | JIRI  Mon 23 Nov            2 late · 40% · 21°   |  status, 30 px
    |                                                  |
    |        [  9  ]     [ 05 ]                        |  eyes = the clock
    |                 ‿                                |  tiny mouth
    | 1 OVERDUE TASK · SHIP INVOICE                    |  why the face looks like that
    | I'm not saying I'm watching. I'm watching.       |  what JIRI says
    +--------------------------------------------------+

Pure: takes a `Scene` plus animation amounts, draws onto a surface. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
import random

from . import mascot

# Fira Code first (installed by scripts/install_pi.sh as `fonts-firacode`):
# a terminal-flavoured desk companion, and it carries the block glyphs the
# usage bars are drawn with. DejaVu Sans Mono ships with Raspberry Pi OS and
# is the guaranteed fallback.
FONT_CANDIDATES = {
    "regular": (
        "/usr/share/fonts/truetype/firacode/FiraCode-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ),
    "bold": (
        "/usr/share/fonts/truetype/firacode/FiraCode-SemiBold.ttf",
        "/usr/share/fonts/truetype/firacode/FiraCode-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ),
}


@dataclass(frozen=True)
class Scene:
    state: str
    digits: tuple[str, str]
    reason: str
    speech: str
    date_text: str
    status_text: str
    clock_text: str  # shown in the status line only when the eyes can't show it
    eyes_show_time: bool = True
    # When set, the bottom area shows AI usage gauges instead of speech.
    usage: tuple = ()
    show_usage: bool = False
    # Data for the other screens (all plain tuples so a Scene stays hashable).
    tasks: tuple = ()          # ((title, due_label, tone), ...) tone: late|soon|ok
    weather: tuple = ()        # (temp, condition, rain_pct, stale, location, hours, feels, humidity, wind)
    water: tuple = ()          # (progress_ml, goal_ml, percent, ((day, pct), ...))
    focus: tuple = ()          # (title, remaining_text, progress 0..1, status)
    # What JIRI cycles through on the home screen: real facts, each with the
    # expression it deserves. ((state, icon, fact, quip_category), ...)
    thoughts: tuple = ()
    notes: tuple = ()          # ((title, snippet, age_label), ...)


@dataclass
class Animator:
    """Blinks, mood-change pops and glances. The only motion on the face.

    Motion is reserved for meaning: a blink says "alive", a pop says "my mood
    just changed", a glance says "I saw your tap" or "the hour turned".
    """

    seed: int = 7
    _rng: random.Random = field(init=False)
    _next_blink: float = 0.0
    _blink_started: float = -10.0
    _double: bool = False
    _pop_started: float = -10.0
    _glance_started: float = -10.0
    _glance_dir: int = 1
    _last_state: str = ""
    _last_hour: str = ""

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def observe(self, scene: Scene, now: float) -> None:
        if scene.state != self._last_state:
            if self._last_state:
                self._pop_started = now
            self._last_state = scene.state
        hour = scene.digits[0] if scene.eyes_show_time else ""
        if hour and self._last_hour and hour != self._last_hour:
            self.glance(now, 1)
            self._blink_started, self._double = now, True
        self._last_hour = hour or self._last_hour

    def glance(self, now: float, direction: int = 1) -> None:
        self._glance_started, self._glance_dir = now, direction

    def frame(self, state: str, now: float) -> tuple[float, int]:
        """Return (open_amount, glance_px) for this instant."""
        if self._next_blink == 0.0:
            self._next_blink = now + 2.0
        if state != "sleeping" and now >= self._next_blink:
            self._blink_started = now
            self._double = self._rng.random() < 0.2
            self._next_blink = now + self._rng.uniform(2.5, 6.5)

        open_amount = 1.0
        blink_len = 0.16
        elapsed = now - self._blink_started
        windows = [(0.0, blink_len)]
        if self._double:
            windows.append((blink_len + 0.08, 2 * blink_len + 0.08))
        for start, end in windows:
            if start <= elapsed < end:
                open_amount = abs(1 - 2 * (elapsed - start) / blink_len)

        pop = now - self._pop_started
        if 0 <= pop < 0.3:
            # Squash then settle: the eyes "react" to their own new mood.
            open_amount = min(open_amount, 0.78 + 0.22 * (pop / 0.3))

        glance = 0
        g = now - self._glance_started
        if 0 <= g < 1.2:
            reach = 1.0 if g < 0.9 else max(0.0, 1 - (g - 0.9) / 0.3)
            glance = int(16 * reach) * self._glance_dir
        # Quantise so identical frames really are identical (saves SPI writes).
        return round(open_amount * 8) / 8, glance


def load_fonts(pygame) -> dict[str, object]:
    def font(weight: str, size: int):
        for path in FONT_CANDIDATES[weight]:
            if os.path.exists(path):
                return pygame.font.Font(path, size)
        return pygame.font.Font(None, int(size * 1.3))

    return {
        "status": font("regular", 13),
        "status_bold": font("bold", 13),
        "brand": font("bold", 14),
        "reason": font("bold", 12),
        "speech": font("regular", 15),
        "zzz": font("bold", 18),
        "gauge": font("regular", 12),
        "gauge_head": font("bold", 12),
        "task": font("regular", 16),
        "small": font("regular", 11),
        "big": font("bold", 30),
        "huge": font("bold", 54),
        "gauge_big": font("regular", 14),
        "title": font("bold", 17),
        "stat": font("bold", 24),
        "clock": font("bold", 38),
    }


def build_scene(
    snapshot,
    *,
    now: datetime | None = None,
    clock_24h: bool | None = None,
    usage: tuple | None = None,
) -> Scene:
    """Map a ScreenSnapshot onto what the face should show. No I/O."""
    current = now or datetime.now()
    if clock_24h is None:
        clock_24h = os.environ.get("JIRI_CLOCK_24H", "").lower() in {"1", "true", "yes"}

    state = snapshot.face_state if snapshot.face_state != "blink" else "idle"
    hour = current.strftime("%H") if clock_24h else str(int(current.strftime("%I")))
    minute = current.strftime("%M")
    clock_text = f"{hour}:{minute}" + ("" if clock_24h else current.strftime(" %p").lower())

    focus = snapshot.focus or {}
    focus_running = bool(focus.get("active")) and str(focus.get("status", "running")) == "running"
    if focus_running and focus.get("remaining_text"):
        digits = _countdown_digits(str(focus["remaining_text"]))
        eyes_show_time = False
    else:
        digits = (hour, minute)
        eyes_show_time = state != "sleeping"

    reason = (snapshot.face_reason or "").strip()
    if not reason and snapshot.overdue_count:
        # Every expression must be explained on screen; some panels leave the
        # reason blank because their old HTML block showed it. The face can't.
        todos = getattr(snapshot, "pending_todos", ()) or ()
        title = getattr(todos[0], "title", "") if todos else ""
        noun = "task" if snapshot.overdue_count == 1 else "tasks"
        reason = f"{snapshot.overdue_count} overdue {noun}" + (f" · {title}" if title else "")
    if focus_running:
        reason = reason or f"focus · {focus.get('remaining_text')} left"
    speech = _pick_speech(snapshot, reason)

    return Scene(
        state=state,
        digits=digits,
        reason=reason,
        speech=speech,
        date_text=current.strftime("%a %d %b"),
        status_text=_status_text(snapshot),
        clock_text=clock_text,
        eyes_show_time=eyes_show_time,
        usage=_usage_rows(usage or (), current),
        show_usage=usage is not None,
        tasks=_tasks(snapshot, current),
        weather=_weather(snapshot, current),
        water=_water(snapshot),
        focus=(
            (str(focus.get("title") or "Focus"), str(focus.get("remaining_text") or "00:00"),
             float(focus.get("progress") or 0.0), str(focus.get("status") or "running"))
            if focus.get("active") else ()
        ),
        thoughts=_thoughts(snapshot, state, current, usage or ()),
        notes=_notes(snapshot, current),
    )


def _notes(snapshot, current: datetime) -> tuple:
    out = []
    for note in (getattr(snapshot, "recent_notes", ()) or ())[:3]:
        body = " ".join(str(getattr(note, "body", "") or "").split())
        stamp = getattr(note, "updated_at", None) or getattr(note, "created_at", None)
        age = ""
        try:
            mins = int((current - datetime.fromisoformat(str(stamp))).total_seconds() // 60)
            age = ("just now" if mins < 2 else f"{mins}m ago" if mins < 60
                   else f"{mins // 60}h ago" if mins < 1440 else f"{mins // 1440}d ago")
        except (TypeError, ValueError):
            pass
        out.append((str(getattr(note, "title", "") or "Note"), body, age))
    return tuple(out)


def _thoughts(snapshot, state: str, current: datetime, usage) -> tuple:
    """Real facts JIRI has an opinion about, most pressing first.

    Every entry is computed from data; the expression is chosen by the fact,
    so the face visibly changes as JIRI moves from one thought to the next.
    """
    out = []
    tasks = _tasks(snapshot, current)
    late = [t for t in tasks if t[2] == "late"]
    soon = [t for t in tasks if t[2] == "soon"]
    if late:
        mood = state if state in ("annoyed", "angry", "rage") else "annoyed"
        more = f" (+{len(late) - 1} more)" if len(late) > 1 else ""
        out.append((mood, "alert", f"{late[0][0]} · {late[0][1]}{more}", "thought_late"))
    focus = snapshot.focus or {}
    if focus.get("active"):
        out.append(("focused", "focus", f"{focus.get('title') or 'Focus'} · {focus.get('remaining_text')} left", "thought_focus"))
    if soon:
        out.append(("alert", "clock", f"{soon[0][0]} · {soon[0][1]}", "thought_soon"))
    water = _water(snapshot)
    if water:
        ml, goal, pct, _ = water
        if pct >= 100:
            out.append(("happy", "drop", f"Water goal done · {ml / 1000:.1f} L", "thought_water_done"))
        elif pct >= 50:
            out.append(("smirk", "drop", f"Water · {ml / 1000:.1f} of {goal / 1000:.1f} L", "thought_water_good"))
        else:
            out.append(("curious", "drop", f"Water · {ml / 1000:.1f} of {goal / 1000:.1f} L, {goal - ml} ml to go", "thought_water_low"))
    weather = _weather(snapshot, current)
    if weather and weather[0] is not None and not weather[3]:
        temp, condition, rain = weather[0], weather[1], weather[2]
        fact = f"{round(temp)}° · {condition or 'outside'}" + (f" · rain {rain}%" if rain >= 40 else "")
        c = condition.lower()
        night = current.hour >= 18 or current.hour < 6
        if temp >= 33:
            out.append(("weather_hot", "sun", fact, "thought_weather_hot"))
        elif rain >= 60 or any(k in c for k in ("rain", "drizzle", "shower", "thunder")):
            out.append(("weather_rain", "rain", fact, "thought_weather_rain"))
        elif temp <= 12:
            out.append(("weather_cold", "thermo", fact, "thought_weather_cold"))
        elif any(k in c for k in ("cloud", "overcast", "fog", "mist")):
            out.append(("weather_cloudy", "cloud", fact, "thought_weather_nice"))
        elif night:
            out.append(("weather_night", "sun", fact, "thought_weather_nice"))
        else:
            out.append(("weather_sunny", "sun", fact, "thought_weather_nice"))
    rows = _usage_rows(usage, current)
    live = [r for r in rows if not r.stale]
    if live:
        def pressure(row):
            return max([g[1] or 0 for g in row.gauges[1:]] or [0])

        r = max(live, key=pressure)
        # Limits first; a provider with no limit data (OpenCode) still has context.
        bits = [f"{label} {pct:.0f}%" for label, pct, _ in r.gauges[1:] if pct is not None] or [
            f"context {pct:.0f}%" for label, pct, _ in r.gauges[:1] if pct is not None
        ]
        top = pressure(r)
        name = PROVIDER_NAMES.get(r.provider, r.provider)
        if bits:
            out.append(("alert" if top >= 75 else "smirk", "bars", f"{name} · " + " · ".join(bits), "thought_usage_high" if top >= 75 else "thought_usage_ok"))
    if tasks and not late and not soon:
        out.append(("idle", "check", f"{len(tasks)} on the list, nothing late", "thought_tasks_some"))
    if not tasks:
        out.append(("happy", "check", "Task list is empty", "thought_tasks_clear"))
    hour = current.hour
    if hour >= 23 or hour < 5:
        out.append(("tired", "clock", f"It's {current.strftime('%-I:%M %p').lower()}", "thought_night"))
    elif 6 <= hour < 10:
        out.append(("happy", "sun", f"Morning · {current.strftime('%A')}", "thought_morning"))
    return tuple(out)


def _countdown_digits(remaining: str) -> tuple[str, str]:
    """'24:10' -> ('24','10'); '125:00' or '2:05:00' -> hours+minutes ('2','05')."""
    try:
        parts = [int(p) for p in remaining.split(":")]
    except ValueError:
        return ("--", "--")
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + max(0, p)
    minutes, secs = divmod(seconds, 60)
    if minutes >= 100:
        hours, mins = divmod(minutes, 60)
        return (str(hours), f"{mins:02d}")
    return (f"{minutes:02d}", f"{secs:02d}")


def _due_label(due_at: str | None, current: datetime) -> tuple[str, str]:
    if not due_at:
        return "no due date", "ok"
    try:
        due = datetime.fromisoformat(str(due_at))
    except ValueError:
        return "", "ok"
    minutes = int((due - current).total_seconds() // 60)
    if minutes < 0:
        late = -minutes
        text = f"{late}m late" if late < 60 else (f"{late // 60}h late" if late < 1440 else f"{late // 1440}d late")
        return text, "late"
    if minutes < 60:
        return f"in {minutes}m", "soon"
    if due.date() == current.date():
        return due.strftime("%-I:%M %p").lower(), "ok"
    return due.strftime("%a %-d %b"), "ok"


def _tasks(snapshot, current: datetime) -> tuple:
    rows = []
    for todo in (getattr(snapshot, "pending_todos", ()) or ())[:4]:
        label, tone = _due_label(getattr(todo, "due_at", None), current)
        rows.append((str(getattr(todo, "title", "")), label, tone))
    return tuple(rows)


def _weather(snapshot, current: datetime) -> tuple:
    w = snapshot.weather or {}
    if not w.get("available") and w.get("temperature_c") is None:
        return ()
    stale = True
    try:
        stale = (current - datetime.fromisoformat(str(w.get("fetched_at")))).total_seconds() > 3600
    except (TypeError, ValueError):
        pass
    hours = tuple(
        (str(h.get("time", "")), float(h.get("temperature_c") or 0), int(h.get("rain_chance") or 0))
        for h in (w.get("hourly_forecast") or ())[:6]
    )
    temp = w.get("temperature_c")
    return (
        None if temp is None else float(temp), str(w.get("condition") or ""), int(w.get("rain_chance") or 0),
        stale, str(w.get("location") or ""), hours,
        _num(w.get("feels_like_c")), _num(w.get("humidity")), _num(w.get("wind_kmh")),
    )


def _num(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _water(snapshot) -> tuple:
    w = snapshot.water or {}
    if not w.get("goal_ml"):
        return ()
    week = tuple((str(d.get("label", ""))[:2], int(d.get("percent") or 0)) for d in (w.get("week") or ())[-7:])
    return (int(w.get("progress_ml") or 0), int(w.get("goal_ml") or 0), int(w.get("percent") or 0), week)


def _pick_speech(snapshot, reason: str) -> str:
    """Never read back the reason line; say something instead."""
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    for candidate in (snapshot.headline, snapshot.subheadline):
        text = (candidate or "").strip()
        if text and norm(text) not in norm(reason) and norm(reason) not in norm(text):
            return text
    return (snapshot.subheadline or snapshot.headline or "").strip()


def _status_text(snapshot) -> str:
    parts = []
    if snapshot.overdue_count:
        parts.append(f"{snapshot.overdue_count} late")
    elif snapshot.pending_count:
        parts.append(f"{snapshot.pending_count} to do")
    else:
        parts.append("all clear")
    water = snapshot.water or {}
    if water.get("goal_ml"):
        parts.append(f"{int(water.get('percent') or 0)}% water")
    temp = (snapshot.weather or {}).get("temperature_c")
    if temp is not None:
        parts.append(f"{round(float(temp))}°")
    return "  ·  ".join(parts)


def _wrap(font, text: str, width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and font.size(last + "…")[0] > width:
            last = last[:-1]
        lines[-1] = last.rstrip(" ,.;:") + "…"
    return lines


def render(pygame, surface, fonts, scene: Scene, *, open_amount: float = 1.0, glance: int = 0) -> None:
    """Draw one still frame (home face, or the usage screen when requested).

    The live device goes through `stage.Stage`, which adds ambient life and
    screen transitions; this is the static path used by previews and tests.
    """
    from . import pages

    life = pages.Life(open_amount=open_amount, gaze=(glance, 0))
    pages.draw_page(pygame, surface, fonts, scene, "usage" if scene.show_usage else "face", life)


# --- AI usage gauges --------------------------------------------------------
# Mirrors the owner's Claude Code statusline:
#   ctx [██▏░░░] 18%  5h [█░░░░░] 9% 43m  wk [▍░░░░░] 4% 2d3h

BAR_CELLS = 6
PARTIALS = " ▏▎▍▌▋▊▉"
STALE_USAGE_SECONDS = 30 * 60
PROVIDER_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}
PROVIDER_COLORS = {"claude": (217, 119, 87), "chatgpt": (116, 210, 168)}
GAUGE_GREEN, GAUGE_YELLOW, GAUGE_ORANGE, GAUGE_RED = (135, 215, 135), (215, 215, 95), (255, 175, 95), (255, 95, 95)
TRACK = (84, 92, 104)


@dataclass(frozen=True)
class UsageRow:
    provider: str
    title: str
    age: str
    stale: bool
    gauges: tuple  # ((label, pct | None, countdown), ...)


def _countdown(resets_at, now_ts: float) -> str:
    if not resets_at:
        return ""
    left = int(float(resets_at) - now_ts)
    if left <= 0:
        # The window has rolled over since this was pushed: the percentage is
        # history, not a reading. Say so instead of showing it as live.
        return "reset"
    d, h, m = left // 86400, left % 86400 // 3600, left % 3600 // 60
    if d:
        return f"{d}d{h}h" if h else f"{d}d"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _usage_rows(reports, current: datetime) -> tuple:
    now_ts = current.timestamp()
    rows = []
    for report in reports:
        provider = getattr(report, "provider", "")
        age_s = max(0, int(now_ts - float(getattr(report, "updated_at", now_ts) or now_ts)))
        age = "now" if age_s < 90 else (f"{age_s // 60}m ago" if age_s < 3600 else f"{age_s // 3600}h ago")
        gauges = (
            ("ctx", getattr(report, "context_pct", None), ""),
            ("5h", getattr(report, "five_hour_pct", None), _countdown(getattr(report, "five_hour_resets_at", None), now_ts)),
            ("wk", getattr(report, "weekly_pct", None), _countdown(getattr(report, "weekly_resets_at", None), now_ts)),
        )
        label = getattr(report, "label", "") or ""
        title = PROVIDER_NAMES.get(provider, provider.title()) + (f" · {label}" if label else "")
        # `updated_at` is when the Pi received the push, not when the numbers
        # were measured. If every limit window has already reset, the reading
        # is from an older session (e.g. a months-old Codex log): say so.
        resets = [g[2] for g in gauges[1:] if g[1] is not None]
        outdated = bool(resets) and all(r == "reset" for r in resets)
        if outdated:
            age = "old data"
        rows.append(UsageRow(provider, title, age, outdated or age_s > STALE_USAGE_SECONDS, gauges))
    return tuple(rows)


def gauge_color(pct: float):
    if pct >= 90:
        return GAUGE_RED
    if pct >= 75:
        return GAUGE_ORANGE
    if pct >= 50:
        return GAUGE_YELLOW
    return GAUGE_GREEN


def bar_parts(pct: float, cells: int = BAR_CELLS) -> tuple[str, str]:
    """(filled, track) glyph runs with eighth-cell precision, e.g. ('█▍', '░░░░')."""
    amount = max(0.0, min(100.0, pct)) / 100 * cells
    full = min(int(amount), cells)
    frac = int((amount - full) * (len(PARTIALS) - 1)) if full < cells else 0
    partial = PARTIALS[frac].strip() or ("▏" if pct > 0 and not full else "")
    return "█" * full + partial, "░" * (cells - full - len(partial))


def draw_provider_icon(pygame, surface, provider: str, cx: int, cy: int, color) -> None:
    """Small generic glyphs (not the companies' logos): a burst and a ring-knot."""
    import math as _m

    if provider == "claude":
        for i in range(8):
            a = i * _m.pi / 4
            r = 6 if i % 2 else 7
            pygame.draw.line(surface, color, (cx, cy), (cx + int(r * _m.cos(a)), cy + int(r * _m.sin(a))), 2)
    else:
        pts = [(cx + int(6 * _m.cos(i * _m.pi / 3 + _m.pi / 6)), cy + int(6 * _m.sin(i * _m.pi / 3 + _m.pi / 6))) for i in range(6)]
        pygame.draw.polygon(surface, color, pts, 2)
        pygame.draw.circle(surface, color, (cx, cy), 2)


def _render_usage(pygame, surface, fonts, rows, *, top: int, spacing: int = 24) -> None:
    w = surface.get_width()
    pad = 16
    font, head = fonts["gauge"], fonts["gauge_head"]
    y = top
    for row in rows[:2]:
        accent = PROVIDER_COLORS.get(row.provider, mascot.INK)
        if row.stale:
            accent = mascot.MUTED
        surface.blit(head.render(row.title, True, accent), (pad, y))
        age = font.render(row.age, True, mascot.MUTED)
        surface.blit(age, (w - pad - age.get_width(), y))
        y += 18
        x = pad
        for label, pct, countdown in row.gauges:
            if pct is None:
                continue
            color = mascot.MUTED if row.stale or countdown == "reset" else gauge_color(float(pct))
            filled, track = bar_parts(float(pct))
            for text, col in (
                (f"{label} [", mascot.MUTED), (filled, color), (track, TRACK), ("] ", mascot.MUTED),
                (f"{float(pct):.0f}%", color), ((" " + countdown) if countdown else "", mascot.MUTED),
            ):
                if text:
                    img = font.render(text, True, col)
                    surface.blit(img, (x, y))
                    x += img.get_width()
            x += font.size("  ")[0]
        y += spacing
    if not rows:
        surface.blit(font.render("No usage pushed yet. See README: 'Show usage on JIRI'.", True, mascot.MUTED), (pad, y))


_PNG_LOCK = None
_PNG_FONTS = None


def render_snapshot_png(
    snapshot, *, now: datetime | None = None, usage: tuple | None = None, page: str | None = None,
    paused: bool = False,
    voice=None,
) -> bytes:
    """The exact frame the Pi would show, as PNG bytes (for the web preview).

    Same renderer as the device, so the laptop preview can never drift from
    the 3.5-inch panel again. Thread-safe; pygame runs headless.
    """
    global _PNG_LOCK, _PNG_FONTS
    import io
    import threading

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    if _PNG_LOCK is None:
        _PNG_LOCK = threading.Lock()
    with _PNG_LOCK:
        if _PNG_FONTS is None:
            pygame.font.init()
            _PNG_FONTS = load_fonts(pygame)
        surface = pygame.Surface((snapshot.width, snapshot.height))
        scene = build_scene(snapshot, now=now, usage=usage)
        if page:
            from . import pages

            import time as _time

            from .stage import THOUGHT_SECONDS, Stage

            page_list = Stage.available(scene)
            page = page if page in page_list else "tasks"
            fact_icon = ""
            if page == "face":
                # Same thought the device would be on right now (they rotate on a clock).
                stage = Stage(boot=False, voice=voice)
                stage.thought_i = int(_time.time() // THOUGHT_SECONDS)
                scene, fact_icon = stage.thought_scene(scene, 0.0)
            life = pages.Life(t=0.0, page_index=page_list.index(page), page_count=len(page_list),
                              paused=paused, fact_icon=fact_icon)
            pages.draw_page(pygame, surface, _PNG_FONTS, scene, page, life)
        else:
            render(pygame, surface, _PNG_FONTS, scene)
        buf = io.BytesIO()
        pygame.image.save(surface, buf, "png")
        return buf.getvalue()
