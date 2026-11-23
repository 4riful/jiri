"""JIRI's pet brain: drives -> behaviours -> a physically-moving face.

Nothing here is a fixed animation loop. JIRI has internal drives that change
with time, data and touch; behaviours are chosen from those drives; the face
pose is driven by springs so every motion overshoots and settles like a living
thing.

Drives (0..1):
- energy    : time of day + how long it has been awake; sleep restores it.
- boredom   : grows while nobody touches it and nothing changes.
- affection : jumps when you tap it, fades over a couple of minutes.
- alarm     : from real data (late tasks, AI usage near its limit).
- curiosity : spikes when the data changes (new task, water logged, usage moved).

Touch: eyes look at your finger, squish on a poke, giggle when tickled
(fast taps), get grumpy when over-poked, show hearts after gentle taps,
and wake up (startled, then pleased) if it was asleep.

All state is in memory. No SQLite writes, no network: safe for the frame loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import random

W, H = 480, 320


class Spring:
    """Damped spring. Under-damped by default so motion overshoots a little."""

    def __init__(self, value: float = 0.0, stiffness: float = 140.0, damping: float = 14.0) -> None:
        self.value = value
        self.velocity = 0.0
        self.target = value
        self.k = stiffness
        self.c = damping

    def step(self, dt: float) -> float:
        # Sub-step so motion runs in real time at 10-15 FPS (one 0.08 s step
        # would be unstable; clamping it made blinks too slow to ever close).
        dt = min(dt, 0.5)  # after a stall, don't simulate a long catch-up
        while dt > 1e-6:
            h = min(dt, 0.02)
            accel = self.k * (self.target - self.value) - self.c * self.velocity
            self.velocity += accel * h
            self.value += self.velocity * h
            dt -= h
        return self.value


@dataclass(frozen=True)
class Pose:
    state: str                     # mood name for mascot.MOODS
    gaze: tuple[int, int]          # eye offset in px
    squash: float = 1.0            # >1 tall/thin, <1 short/wide
    left_open: float = 1.0
    right_open: float = 1.0
    hop: int = 0                   # px upward
    mouth: str = ""                # override mascot mouth ("" = mood default)
    particles: str = ""            # override particles ("hearts", "sparkle", "zzz", ...)
    say: str = ""                  # short reaction category for the bubble ("" = none)
    action: str = "idle"           # for tests / debugging
    droop: float = 0.0             # upper lid lowered over the pupil (tired, yawn)
    owns_face: bool = False        # a reflex is playing: it sets the whole expression


@dataclass
class Action:
    name: str
    start: float
    duration: float

    def progress(self, now: float) -> float:
        return (now - self.start) / self.duration if self.duration else 1.0


@dataclass
class Pet:
    seed: int = 11
    rng: random.Random = field(init=False)
    energy: float = 0.8
    boredom: float = 0.0
    affection: float = 0.3
    curiosity: float = 0.0
    alarm: float = 0.0
    asleep: bool = False

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.gx = Spring(0, 160, 13)
        self.gy = Spring(0, 160, 13)
        self.lids = Spring(1.0, 260, 24)
        self.squash = Spring(1.0, 220, 9)
        self.hop = Spring(0.0, 180, 10)
        self.droop = Spring(0.0, 90, 14)
        self.last = None
        self.action: Action | None = None
        self.next_saccade = 0.0
        self.next_blink = 1.5
        self.blink_until = -1.0
        self.taps: list[float] = []
        self.last_touch = -1e9
        self.fingerprint = None
        self.notice_kind = ""
        self.say = ""
        self.say_until = -1.0

    # -- inputs --------------------------------------------------------------

    def touch(self, now: float, x: int, y: int) -> None:
        self.taps = [t for t in self.taps if now - t < 5.0] + [now]
        self.last_touch = now
        self.boredom = 0.0
        # Look at the finger (offset from screen centre, scaled down).
        self.gx.target = max(-22, min(22, (x - W / 2) / 8))
        self.gy.target = max(-14, min(14, (y - 120) / 8))
        self.next_saccade = now + 1.2
        if self.asleep:
            self.asleep = False
            self.energy = max(self.energy, 0.45)
            self._start("wake", now, 1.6, say="pet_wake")
            return
        recent = [t for t in self.taps if now - t < 2.0]
        if len(self.taps) >= 7:
            self.affection = max(0.0, self.affection - 0.2)
            self._start("grumpy", now, 1.6, say="pet_overpoked")
        elif len(recent) >= 3:
            self.affection = min(1.0, self.affection + 0.25)
            self._start("tickled", now, 1.4, say="pet_tickled")
        else:
            self.affection = min(1.0, self.affection + 0.15)
            self.squash.velocity -= 3.5  # the poke squish
            self._start("poked", now, 0.9, say="pet_poked" if self.rng.random() < 0.5 else "")

    def observe(self, scene, now: float) -> None:
        """Feed real data in. Changes make JIRI curious; trouble makes it alert."""
        late = sum(1 for t in scene.tasks if t[2] == "late")
        water = scene.water[2] if scene.water else -1
        usage = tuple(round(g[1] or 0) for row in scene.usage for g in row.gauges[1:2])
        fp = (len(scene.tasks), late, water, usage, bool(scene.focus))
        if self.fingerprint is not None and fp != self.fingerprint:
            old = self.fingerprint
            self.curiosity = 1.0
            self.boredom = 0.0
            if fp[2] > old[2] >= 0:
                self.notice_kind = "pet_saw_water"
            elif fp[0] < old[0]:
                self.notice_kind = "pet_saw_done"
            elif fp[0] > old[0]:
                self.notice_kind = "pet_saw_new_task"
            elif fp[3] != old[3]:
                self.notice_kind = "pet_saw_usage"
            else:
                self.notice_kind = "pet_saw_change"
        self.fingerprint = fp
        near_limit = any((g[1] or 0) >= 85 for row in scene.usage for g in row.gauges[1:])
        target = min(1.0, 0.35 * late + (0.4 if near_limit else 0.0))
        self.alarm += (target - self.alarm) * 0.1

    # -- brain ---------------------------------------------------------------

    def _start(self, name: str, now: float, duration: float, say: str = "") -> None:
        self.action = Action(name, now, duration)
        if say:
            self.say, self.say_until = say, now + max(2.5, duration + 1.0)

    def _drives(self, now: float, dt: float, hour: float) -> None:
        # Circadian baseline: bright mid-day, dim late at night.
        circadian = 0.5 + 0.5 * math.cos((hour - 14) / 24 * 2 * math.pi)
        if self.asleep:
            self.energy = min(1.0, self.energy + dt / 600)
        else:
            self.energy += ((0.25 + 0.75 * circadian) - self.energy) * dt / 120
        idle = now - self.last_touch
        if not self.asleep:
            self.boredom = min(1.0, self.boredom + dt / (480 if self.alarm < 0.3 else 1200))
        self.affection = max(0.0, self.affection - dt / 150)
        self.curiosity = max(0.0, self.curiosity - dt / 20)
        # Fall asleep when tired and left alone (never while something is late).
        if not self.asleep and self.alarm < 0.3 and self.energy < 0.3 and idle > 300:
            self.asleep = True
            self._start("doze", now, 2.5)

    def _choose(self, now: float) -> None:
        """Pick the next behaviour from the drives. Weighted, not scripted."""
        if self.action and now < self.action.start + self.action.duration:
            return
        self.action = None
        if self.asleep:
            return
        if self.notice_kind:
            kind, self.notice_kind = self.notice_kind, ""
            self._start("notice", now, 2.0, say=kind)
            return
        r = self.rng.random()
        options = [
            ("yawn", 0.006 * (1.2 - self.energy) ** 2, 2.2, "pet_yawn"),
            ("stretch", 0.002 * self.boredom, 1.6, ""),
            ("sigh", 0.004 * self.boredom, 1.8, "pet_bored" if self.boredom > 0.6 else ""),
            ("hop", 0.006 * self.affection, 1.0, ""),
            ("peek", 0.012 * self.alarm, 1.6, ""),
            ("wink", 0.0015 * (0.5 + self.affection), 0.5, ""),
        ]
        acc = 0.0
        for name, weight, duration, say in options:
            acc += weight
            if r < acc:
                self._start(name, now, duration, say=say)
                return

    # -- output --------------------------------------------------------------

    def update(self, scene, now: float, hour: float | None = None) -> Pose:
        dt = 0.0 if self.last is None else now - self.last
        self.last = now
        if hour is None:
            current = datetime.now()
            hour = current.hour + current.minute / 60
        self.observe(scene, now)
        self._drives(now, dt, hour)
        self._choose(now)

        state = scene.state
        mouth, particles, lid_target, squash_target, hop_target = "", "", 1.0, 1.0, 0.0
        droop_target = 0.0
        a = self.action
        p = a.progress(now) if a else 0.0
        name = a.name if a else ("sleep" if self.asleep else "idle")

        # Saccades: quick glances with micro-jitter; frequency follows mood.
        if now >= self.next_saccade and name not in ("peek", "notice"):
            spread = 18 if self.curiosity > 0.3 or self.boredom > 0.5 else 12
            self.gx.target = self.rng.uniform(-spread, spread)
            self.gy.target = self.rng.uniform(-spread / 2, spread / 2)
            busy = 0.6 if self.curiosity > 0.3 else 1.0
            self.next_saccade = now + self.rng.uniform(0.8, 4.0) * busy * (1.6 if self.energy < 0.35 else 1.0)

        if self.asleep:
            state, mouth, particles = "sleeping", "none", "zzz"
        elif name == "wake":
            state = "alert" if p < 0.35 else "happy"
            squash_target = 1.15 if p < 0.35 else 1.0
        elif name == "poked":
            state = "happy" if p > 0.3 and scene.state in ("idle", "happy", "smirk", "curious") else state
            mouth = "o" if p < 0.4 else ""
        elif name == "tickled":
            state, mouth, particles = "happy", "grin", "sparkle"
            hop_target = 6 * abs(math.sin(p * math.pi * 4))
        elif name == "grumpy":
            state, mouth = "annoyed", "flat"
            self.gx.target = 16 * math.sin(p * math.pi * 2)  # eye roll
            self.gy.target = -12 * math.sin(p * math.pi)
        elif name == "yawn":
            state = "idle"
            droop_target = 0.7 if 0.2 < p < 0.8 else 0.25
            mouth = "yawn"
            self.gy.target = -6
        elif name == "stretch":
            squash_target = 1.2 if p < 0.5 else 0.88
            hop_target = 4 if p < 0.5 else 0
        elif name == "sigh":
            state = "idle"
            droop_target = 0.4
            hop_target = -3 * math.sin(p * math.pi)
            self.gy.target = 8
        elif name == "hop":
            state = "happy" if scene.state in ("idle", "smirk") else state
            hop_target = 10 * abs(math.sin(p * math.pi * 2))
        elif name == "peek":
            self.gx.target, self.gy.target = 22, -12  # toward the "late" chip
        elif name == "notice":
            state = "curious" if scene.state in ("idle", "happy", "smirk") else state
            squash_target = 1.1 if p < 0.3 else 1.0
            self.gx.target, self.gy.target = 18, -10
        elif name == "doze":
            droop_target = min(1.0, 0.4 + p)

        if self.affection > 0.75 and name in ("idle", "poked", "hop"):
            particles = particles or "hearts"
        if not self.asleep and self.energy < 0.35 and name == "idle":
            droop_target = 0.3  # heavy-lidded when tired

        # Blinks: tired eyes blink more often and more slowly.
        if not self.asleep and now >= self.next_blink:
            length = 0.13 if self.energy > 0.4 else 0.22
            self.blink_until = now + length
            gap = self.rng.uniform(1.8, 6.0) * (0.6 if self.energy < 0.4 else 1.0)
            self.next_blink = now + gap + (0.25 if self.rng.random() < 0.15 else 0)
        blinking = now < self.blink_until

        self.lids.target = 0.0 if blinking else lid_target
        self.squash.target = squash_target
        self.hop.target = hop_target
        self.droop.target = droop_target
        for spring in (self.gx, self.gy, self.lids, self.squash, self.hop, self.droop):
            spring.step(dt)

        lids = max(0.0, min(1.0, self.lids.value))
        left = lids
        if name == "wink" and 0.15 < p < 0.85:
            left = 0.0
        say = self.say if now < self.say_until else ""
        return Pose(
            state=state,
            gaze=(int(round(self.gx.value)), int(round(self.gy.value))),
            squash=max(0.75, min(1.3, self.squash.value)),
            left_open=left,
            right_open=lids,
            hop=int(round(self.hop.value)),
            mouth=mouth,
            particles=particles,
            say=say,
            action=name,
            droop=max(0.0, min(1.0, self.droop.value)),
            owns_face=name in ("poked", "tickled", "grumpy", "yawn", "sigh", "wake", "stretch", "hop", "doze"),
        )
