"""JIRI's emotion engine: one coherent feeling, computed from real life.

Instead of switching faces per message, JIRI has a continuous emotional
state in two dimensions (the circumplex model of affect):

    valence  -1 (miserable) .. +1 (delighted)
    arousal   0 (drowsy)    ..  1 (wired)

Every input *appraises* the situation and pushes the target state:
late tasks (stress grows with count and lateness), things due soon,
water vs what you'd expect by this hour, focus, weather, AI usage near
its limits, time of day, and how you treat JIRI (taps, neglect). Events
(a task finished, a drink logged) add short-lived impulses of joy.

The state moves smoothly toward the target, and the named emotion only
changes when a new one has held for a few seconds — so the face never
flickers, and every expression can be explained: `Feeling.cause` says why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math

# Named emotions -> face state in mascot.MOODS, plus a word to show.
EMOTIONS = {
    "joyful": ("happy", "joyful"),
    "content": ("idle", "content"),
    "calm": ("idle", "calm"),
    "curious": ("curious", "curious"),
    "focused": ("focused", "focused"),
    "worried": ("alert", "worried"),
    "upset": ("angry", "upset"),
    "furious": ("rage", "fuming"),
    "glum": ("annoyed", "glum"),
    "sleepy": ("tired", "sleepy"),
}

TAU_SECONDS = 8.0        # how fast feelings follow the situation
HOLD_SECONDS = 12.0      # a feeling lasts at least this long...
CONFIRM_SECONDS = 3.0    # ...and a new one must persist this long to take over


@dataclass(frozen=True)
class Feeling:
    name: str            # key of EMOTIONS
    face: str            # mascot mood
    word: str            # shown on screen ("worried")
    cause: str           # shown on screen ("4 tasks are late")
    valence: float
    arousal: float
    intensity: float     # 0..1, distance from neutral


@dataclass
class Appraisal:
    valence: float = 0.25
    arousal: float = 0.4
    causes: list = field(default_factory=list)  # (weight, text)

    def push(self, dv: float, da: float, weight: float, cause: str) -> None:
        self.valence += dv
        self.arousal += da
        if cause:
            self.causes.append((weight, cause))


def appraise(scene, now: datetime, *, affection: float = 0.0, boredom: float = 0.0, energy: float = 0.7) -> Appraisal:
    """What the situation means to JIRI. Pure function of data + pet drives."""
    a = Appraisal()
    late = [t for t in scene.tasks if t[2] == "late"]
    soon = [t for t in scene.tasks if t[2] == "soon"]
    if late:
        worst = max(_minutes_late(t[1]) for t in late)
        stress = min(1.0, 0.3 + 0.12 * len(late) + worst / 300)
        noun = "task is" if len(late) == 1 else "tasks are"
        a.push(-1.0 * stress, 0.6 * stress, 3 + stress, f"{len(late)} {noun} late")
    if soon:
        a.push(-0.1, 0.3, 2, f"{soon[0][0]} is due {soon[0][1]}")
    if scene.focus:
        a.push(0.1, 0.15, 2.5, f"guarding your focus: {scene.focus[0]}")
    if scene.water:
        pct = scene.water[2]
        expected = max(0.0, min(100.0, (now.hour + now.minute / 60 - 8) / 14 * 100))
        if pct >= 100:
            a.push(0.3, 0.1, 1.5, "you hit your water goal")
        elif expected - pct > 30:
            a.push(-0.25, 0.05, 1.2, f"only {pct}% of your water so far")
    if scene.weather and scene.weather[0] is not None and not scene.weather[3]:
        temp, cond, rain = scene.weather[0], scene.weather[1].lower(), scene.weather[2]
        if temp >= 33:
            a.push(-0.2, 0.2, 1, f"it's {round(temp)}° out")
        elif rain >= 60 or "rain" in cond:
            a.push(-0.1, -0.05, 0.8, "it's raining")
        elif 16 <= temp <= 28 and "cloud" not in cond:
            a.push(0.12, 0.05, 0.5, "the weather is lovely")
    for row in scene.usage:
        top = max([g[1] or 0 for g in row.gauges[1:]] or [0])
        if not row.stale and top >= 80:
            a.push(-0.15, 0.25, 1.4, f"{row.title.split(' ·')[0]} is at {top:.0f}% of its limit")
    hour = now.hour
    if hour >= 23 or hour < 6:
        a.push(0.0, -0.45, 1.0, "it's late at night")
    a.push(0.0, (energy - 0.6) * 0.4, 0, "")
    if affection > 0.3:
        a.push(0.5 * affection, 0.2 * affection, 2 * affection, "you've been nice to me")
    if boredom > 0.5:
        a.push(-0.25 * boredom, -0.25 * boredom, boredom, "nobody has poked me in ages")
    a.valence = max(-1.0, min(1.0, a.valence))
    a.arousal = max(0.0, min(1.0, a.arousal))
    return a


def classify(valence: float, arousal: float, focus: bool) -> str:
    if focus and valence > -0.45:
        return "focused"
    if arousal < 0.2:
        return "sleepy" if valence > -0.35 else "glum"
    if valence >= 0.45:
        return "joyful" if arousal >= 0.5 else "content"
    if valence > -0.15:
        return "curious" if arousal >= 0.65 else "calm"
    if valence <= -0.8 and arousal >= 0.6:
        return "furious"
    if valence <= -0.5 and arousal >= 0.5:
        return "upset"
    if arousal >= 0.4:
        return "worried"
    return "glum"


class EmotionEngine:
    def __init__(self) -> None:
        self.valence = 0.25
        self.arousal = 0.4
        self.current = "calm"
        self.current_since = -1e9
        self.pending = ""
        self.pending_since = 0.0
        self.last: float | None = None
        self.impulses: list[tuple[float, float, float, str]] = []  # (start, dv, half_life, cause)
        self.fingerprint = None
        self.cause = ""

    def _events(self, scene, now: float) -> None:
        fp = (len(scene.tasks), scene.water[2] if scene.water else -1)
        if self.fingerprint is not None:
            if fp[0] < self.fingerprint[0]:
                self.impulses.append((now, 0.9, 60.0, "you finished a task!"))
            if fp[1] > self.fingerprint[1] >= 0:
                self.impulses.append((now, 0.5, 40.0, "you drank some water"))
        self.fingerprint = fp

    def update(self, scene, now: float, current: datetime | None = None, *, affection=0.0, boredom=0.0, energy=0.7) -> Feeling:
        dt = 0.0 if self.last is None else max(0.0, now - self.last)
        self.last = now
        self._events(scene, now)
        a = appraise(scene, current or datetime.now(), affection=affection, boredom=boredom, energy=energy)
        boost, boost_cause = 0.0, ""
        alive = []
        for start, dv, half, cause in self.impulses:
            k = 0.5 ** ((now - start) / half)
            if k > 0.05:
                alive.append((start, dv, half, cause))
                if dv * k > boost:
                    boost, boost_cause = dv * k, cause
        self.impulses = alive
        tv = max(-1.0, min(1.0, a.valence + boost))
        ta = max(0.0, min(1.0, a.arousal + boost * 0.5))
        k = 1.0 if self.current_since < -1e8 else 1 - math.exp(-dt / TAU_SECONDS)
        self.valence += (tv - self.valence) * k
        self.arousal += (ta - self.arousal) * k

        candidate = classify(self.valence, self.arousal, bool(scene.focus))
        if self.current_since < -1e8:
            self.current, self.current_since = candidate, now
        elif candidate != self.current:
            if candidate != self.pending:
                self.pending, self.pending_since = candidate, now
            urgent = boost > 0.4 or candidate in ("furious", "upset")
            held = now - self.current_since >= (2.0 if urgent else HOLD_SECONDS)
            confirmed = now - self.pending_since >= (0.5 if urgent else CONFIRM_SECONDS)
            if held and confirmed:
                self.current, self.current_since, self.pending = candidate, now, ""
        else:
            self.pending = ""

        # The cause: the strongest appraisal behind the current feeling.
        causes = sorted(a.causes, key=lambda c: -c[0])
        if boost_cause and boost > 0.2:
            self.cause = boost_cause
        elif causes:
            positive = self.current in ("joyful", "content", "calm", "curious", "focused")
            pick = next((c for w, c in causes if ("late" in c or "limit" in c or "only" in c) != positive), causes[0][1])
            self.cause = pick
        else:
            self.cause = "all quiet on the desk"
        face, word = EMOTIONS[self.current]
        intensity = min(1.0, math.hypot(self.valence - 0.25, self.arousal - 0.4) / 1.1)
        return Feeling(self.current, face, word, self.cause, self.valence, self.arousal, intensity)


def _minutes_late(label: str) -> int:
    try:
        n = int("".join(ch for ch in label.split()[0] if ch.isdigit()) or 0)
    except (ValueError, IndexError):
        return 0
    if "d" in label.split()[0]:
        return n * 1440
    if "h" in label.split()[0]:
        return n * 60
    return n
