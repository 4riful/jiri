"""The stage: the pet, touch, screen rotation and splash transitions.

`Stage.frame(...)` draws the next frame. The face is driven by `pet.Pet`
(drives -> behaviours -> spring physics); this module routes touch, rotates
screens and plays the splash between them.

Touch:
- Home: tap JIRI's face to pet it (poke, tickle, wake it); tap the top bar
  for a time check; tap the speech bubble to go to the next screen.
- Any other screen: tap to go to the next screen (with the splash wipe).
- DOUBLE tap anywhere: turn automatic rotation on / off.
- Prev / next arrows appear at the screen edges for a few seconds after a
  touch or a screen change; tapping one changes the screen.

Home screen: JIRI cycles through "thoughts" built from real data. Each has a
fact (shown in the bubble's top line), its own facial expression, and a quip
(LLM-written, cached; offline fallback in jiri.quips). JIRI thinks (eyes up,
• • •) and then the text decodes in with a scramble effect.
Pet reflexes ("hey, that's my face!") come from the LLM's pet_* buckets.
"""

from __future__ import annotations

import math
import os
import random
from datetime import datetime

from . import pages
from .emotion import EmotionEngine, Feeling
from .pet import Pet

# Offline voice for pet reflexes. The live voice comes from the hosted LLM
# (ai.pick on the pet_* buckets); these only speak when the cache is empty.
REFLEX_FALLBACK = {
    "pet_poked": ("Boop received!", "Hey, that's my face!", "Oh! Hello, finger."),
    "pet_tickled": ("Hehehe, stop it!", "No tickles, I'm ticklish!", "Ahaha, mercy!"),
    "pet_overpoked": ("Okay, okay, I'm awake!", "My face is not a button!", "Rude. Cute, but rude."),
    "pet_wake": ("Huh? Oh, it's you!", "Five more minutes...", "I was not asleep. Promise."),
    "pet_yawn": ("*yaaawn*", "So... sleepy...", "Is it nap o'clock?"),
    "pet_bored": ("Hellooo? Anyone?", "Poke me. I dare you.", "So. Very. Bored."),
    "pet_saw_water": ("Sip detected! Proud of you.", "Hydration hero!", "Glug glug, nice!"),
    "pet_saw_done": ("One down! Woo!", "Crossed off! Tiny parade!", "Task gone. Nice work!"),
    "pet_saw_new_task": ("Ooh, a new task?", "Something new on the list...", "Noted. I'm watching it."),
    "pet_saw_usage": ("Coding with your AI pal?", "Those tokens are moving!", "Busy brain day, huh?"),
    "pet_saw_change": ("Ooh, something changed!", "Wait, what was that?", "I noticed that."),
}

URGENT = {"alert", "annoyed", "angry", "rage", "system_warning"}
HOME_SECONDS = 45.0
PAGE_SECONDS = 15.0
THOUGHT_SECONDS = 11.0
DOUBLE_TAP_SECONDS = 0.45
ARROW_SECONDS = 4.0        # how long the prev/next arrows stay after a touch
ARROW_ZONE = 64            # px from each edge that counts as an arrow tap
TIME_CHECK_SECONDS = 7.0   # eyes flip to the clock digits this long
SPLASH_SECONDS = 0.9
BOOT_SECONDS = 3.4
THINK_SECONDS = 0.9
GIGGLE_SECONDS = 0.9
TOAST_SECONDS = 1.4
TYPE_CPS = 30.0
LOOK_SPOTS = ((0, 0), (-14, -4), (14, -4), (-10, 6), (10, 6), (0, -6), (0, 0))


def greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if h < 5:
        return "still up? me too."
    if h < 12:
        return "good morning!"
    if h < 17:
        return "good afternoon!"
    if h < 21:
        return "good evening!"
    return "night shift, huh?"


class Stage:
    def __init__(self, *, seed: int = 7, boot: bool = True, rotate: bool | None = None, voice=None) -> None:
        self.pet = Pet(seed=seed)
        self.emotion = EmotionEngine()
        self.feeling: Feeling | None = None
        self.voice = voice  # callable(category, mood, seed) -> str | None (read-only cache lookup)
        self.last_tap = -1e9
        self.last_touch = -1e9
        self.pending_nav: float | None = None  # single tap waits to see if it's a double
        self.pending_dir = 1
        self.arrows_until = 0.0
        self.thought_i = 0
        self.thought_since = 0.0
        self._quips: dict = {}
        self.time_until = 0.0     # eyes show the clock until this moment
        self._minute = ""  # (category, seed) -> quip; looked up once, not per frame
        self._said: tuple[str, str] = ("", "")
        self._say_count = 0
        self.rng = random.Random(seed)
        self.start: float | None = None
        self.boot = boot
        if rotate is None:
            # Screens change on their own (with the splash wipe) by default:
            # Home holds longest. Double tap to stop/start; JIRI_ROTATE=0 turns it off.
            rotate = os.environ.get("JIRI_ROTATE", "1").lower() not in {"0", "false", "no"}
        self.spinning = rotate
        self.page = "face"
        self.page_since = 0.0
        self.splash_page: str | None = None
        self.splash_start = 0.0
        self.speech = ""
        self.speech_since = -100.0
        self.gaze_from = (0, 0)
        self.gaze_to = (0, 0)
        self.gaze_since = 0.0
        self.next_look = 2.0
        self.last_state = ""
        self.toast_text = ""
        self.toast_start = -100.0

    # -- screen choice -------------------------------------------------------

    @staticmethod
    def available(scene) -> list[str]:
        """Every screen, always, in a fixed order. Only Home has the face; a
        screen with no data shows its own empty state, never the face."""
        return list(pages.PAGES)

    def go(self, page: str, now: float) -> None:
        if page == self.page and self.splash_page is None:
            return
        self.splash_page = page
        self.splash_start = now

    def next_page(self, scene, now: float, step: int = 1) -> None:
        pages_now = self.available(scene)
        current = self.splash_page or self.page
        i = pages_now.index(current) if current in pages_now else 0
        self.go(pages_now[(i + step) % len(pages_now)], now)
        self.arrows_until = max(self.arrows_until, now + 2.5)  # brief hint after a change

    def prev_page(self, scene, now: float) -> None:
        self.next_page(scene, now, step=-1)

    def tap(self, scene, now: float, x: int, width: int, y: int = 0) -> None:
        double = now - self.last_tap <= DOUBLE_TAP_SECONDS
        self.last_tap = -1e9 if double else now
        self.last_touch = now
        arrows_visible = now < self.arrows_until
        self.arrows_until = now + ARROW_SECONDS
        if not double and arrows_visible and (x < ARROW_ZONE or x > width - ARROW_ZONE) and 60 < y < 280:
            # A visible arrow was tapped: change screen now (no double-tap wait).
            self.pending_nav = None
            if x < ARROW_ZONE:
                self.prev_page(scene, now)
            else:
                self.next_page(scene, now)
            return
        if not double:
            if self.page == "face" and self.splash_page is None and y < 44:
                self.time_check(now)  # tap the top bar: "what time is it?"
            elif self.page == "face" and self.splash_page is None and y < 205:
                self.pet.touch(now, x, y)
            else:
                self.pending_nav = now  # next screen, unless a second tap follows
            return
        self.pending_nav = None
        if self.spinning:
            self.spinning = False
            self.toast_text = "stopped"
        else:
            self.spinning = True
            self.toast_text = "spinning"
            self.next_page(scene, now)
        self.toast_start = now

    # -- life ----------------------------------------------------------------

    def _say(self, category: str) -> str:
        if not category:
            return ""
        if self._said[0] != category:
            self._say_count += 1
            text = None
            if self.voice is not None:
                try:
                    text = self.voice(category, "pet", (category, self._say_count))
                except Exception:  # noqa: BLE001 - a voice failure must not stop the face
                    text = None
            pool = REFLEX_FALLBACK.get(category, ("Hm!",))
            self._said = (category, text or pool[self._say_count % len(pool)])
        return self._said[1]

    def time_check(self, now: float) -> None:
        """Eyes flip from pupils to the clock digits for a few seconds."""
        if now >= self.time_until:
            self.pet.squash.velocity -= 3.0  # the flip reads as a little pop
        self.time_until = now + TIME_CHECK_SECONDS

    def thought_scene(self, scene, now: float):
        """The home screen's scene for the current thought (fact, mood, quip)."""
        if not scene.thoughts:
            return scene, ""
        if now - self.thought_since >= THOUGHT_SECONDS:
            self.thought_i += 1
            self.thought_since = now
            # Re-resolve quips per thought: lookups are in-memory now, and this
            # lets freshly generated AI lines replace an offline fallback.
            self._quips.clear()
        thought_state, icon_kind, fact, category = scene.thoughts[self.thought_i % len(scene.thoughts)]
        # The face shows JIRI's FEELING, not the topic. A thought only adds an
        # accessory (shades, looking up at rain/stars) when JIRI feels good.
        state = self.feeling.face if self.feeling else thought_state
        positive = self.feeling is not None and self.feeling.name in ("joyful", "content", "calm", "curious")
        if positive and thought_state.startswith("weather_"):
            state = thought_state
        # Same fact -> same quip for a 15-minute window, so it never flickers.
        seed = (category, fact, int(datetime.now().timestamp() // 900))
        key = (category, seed)
        quip = self._quips.get(key)
        if quip is None:
            lookup = (lambda c, s: self.voice(c, "thought", s)) if self.voice else None
            try:
                from jiri import quips

                quip = quips.quip(category, seed, lookup=lookup)
            except ImportError:  # quips module not installed yet
                quip = (lookup(category, seed) if lookup else None) or scene.speech
            if len(self._quips) > 64:
                self._quips.clear()
            self._quips[key] = quip
        from dataclasses import replace

        return replace(scene, state=state, reason=fact, speech=quip), icon_kind

    def life(self, scene, now: float, page_list: list[str], fact_icon: str = "") -> pages.Life:
        minute = scene.clock_text
        if minute != self._minute:
            if self._minute:
                self.time_check(now)  # every new minute, JIRI shows the time
            self._minute = minute
        pose = self.pet.update(scene, now)
        say = self._say(pose.say)
        if not pose.say:
            self._said = ("", "")
        if scene.speech != self.speech:
            self.speech, self.speech_since = scene.speech, now
        t = now - (self.start or now)
        since = now - self.speech_since
        thinking = since / THINK_SECONDS if 0 <= since < THINK_SECONDS else -1.0
        typed = int(max(0.0, since - THINK_SECONDS) * TYPE_CPS)
        reveal = since - THINK_SECONDS
        sleeping = pose.state == "sleeping"
        bob = int(round((3 if sleeping else 2) * math.sin(2 * math.pi * t / (6.0 if sleeping else 4.2))))
        current = self.splash_page if self.splash_page and (now - self.splash_start) / SPLASH_SECONDS >= 0.5 else self.page
        return pages.Life(
            t=t,
            open_amount=pose.right_open,
            gaze=pose.gaze,
            bob=bob,
            tick=(t % 1.0) < 0.5,
            typed=typed,
            thinking=thinking,
            pose=pose,
            say=say,
            reveal=reveal,
            fact_icon=fact_icon,
            feeling=self.feeling,
            thought_index=(self.thought_i % len(scene.thoughts)) if getattr(scene, "thoughts", ()) else 0,
            thought_count=len(getattr(scene, "thoughts", ()) or ()),
            thought_progress=min(1.0, (now - self.thought_since) / THOUGHT_SECONDS),
            show_time=now < self.time_until,
            page_index=page_list.index(current) if current in page_list else 0,
            page_count=len(page_list),
            paused=not self.spinning,
            arrows=max(0.0, min(1.0, (self.arrows_until - now) / 0.6)),
            toast=self.toast_text if 0 <= now - self.toast_start < TOAST_SECONDS else "",
        )

    # -- frame ---------------------------------------------------------------

    def frame(self, pygame, canvas, fonts, scene, now: float, taps=()) -> None:
        if self.start is None:
            self.start = now
            self.page_since = now
        page_list = self.available(scene)

        elapsed = now - self.start
        if self.boot and elapsed < BOOT_SECONDS:
            life = self.life(scene, now, page_list)
            pages.draw_boot(pygame, canvas, fonts, elapsed / BOOT_SECONDS, life, greeting())
            if taps:
                self.boot = False
            return
        if self.boot:
            self.boot = False
            self.speech_since = now  # think, then say the first line
            self.time_check(now)     # and open with the time

        for x, y in taps:
            self.tap(scene, now, x, canvas.get_width(), y)
        if self.pending_nav is not None and now - self.pending_nav > DOUBLE_TAP_SECONDS:
            self.pending_nav = None
            self.next_page(scene, now)
        self.feeling = self.emotion.update(
            scene, now, affection=self.pet.affection, boredom=self.pet.boredom, energy=self.pet.energy,
        )
        home_scene, fact_icon = self.thought_scene(scene, now)

        # Urgent mood change pulls JIRI back home to say it to your face.
        if scene.state != self.last_state:
            if self.last_state and scene.state in URGENT and self.page != "face":
                self.go("face", now)
            self.last_state = scene.state

        if self.splash_page is None and self.spinning:
            hold = HOME_SECONDS if self.page == "face" else PAGE_SECONDS
            if now - self.page_since >= hold and len(page_list) > 1:
                self.next_page(scene, now)
        if self.page not in page_list and self.splash_page is None:
            self.go("face", now)
        # Stopped on an info screen and left alone: wander back home to JIRI.
        if (not self.spinning and self.page != "face" and self.splash_page is None
                and now - max(self.page_since, self.last_touch) >= 60):
            self.go("face", now)

        if self.splash_page is not None:
            progress = (now - self.splash_start) / SPLASH_SECONDS
            if progress >= 0.5 and self.page != self.splash_page:
                self.page = self.splash_page
                self.page_since = now
                if self.page == "face":
                    self.speech_since = now  # back home: think, then speak
            shown = home_scene if self.page == "face" else scene
            life = self.life(shown, now, page_list, fact_icon)
            pages.draw_page(pygame, canvas, fonts, shown, self.page, life)
            if progress >= 1.0:
                self.splash_page = None
            else:
                pages.draw_splash(pygame, canvas, fonts, self.splash_page, progress, life)
            return
        shown = home_scene if self.page == "face" else scene
        pages.draw_page(pygame, canvas, fonts, shown, self.page, self.life(shown, now, page_list, fact_icon))
