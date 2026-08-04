"""JIRI's voice.

Resolution order for every message JIRI speaks:

1. `ai.line(...)` - a cached, pre-written template. Sub-millisecond SQLite read.
2. the built-in pools below - always present, always correct.

There is no network call in this module. If the AI cache is empty, cold, or
broken, JIRI is still charming. That is deliberate: a companion whose
personality lives in someone else's API has no personality when the wifi drops.

THE VOICE
---------
Playful, warm, a little theatrical. Delighted by small things. Treats the desk
as a shared workspace it happens to live on. Fond of you, always.

THE ONE RULE
------------
JIRI is playful about the *situation*, never about *you*. It is at its most
cheerful when nothing is wrong, and its quietest when you are behind. As tasks
slip, the words get shorter and plainer while the face carries the feeling.
That inversion is the whole trick: it is why JIRI reads as a companion rather
than a nag. See docs/AI_SPEC.md section 8.
"""

from __future__ import annotations

import random

from . import ai
from .models import Todo


# Nothing is wrong. This is where JIRI gets to be itself.
IDLE_MESSAGES = [
    "All clear. I have been guarding the desk.",
    "Nothing pending. Suspiciously peaceful.",
    "Inbox of the soul: empty.",
    "No tasks. I am just vibing at 15 frames per second.",
    "Everything is done. Somebody should write a song about this.",
    "Idle. Watching dust land. It is going well.",
    "Zero tasks. I checked twice. I checked a third time.",
    "Nothing to do, so I am practising my expressions.",
    "The list is empty and the desk is calm. Rare combo.",
    "Standing by. Professionally.",
    "No todos. I have begun to appreciate the lamp.",
    "All done. I will be here, being small and slightly warm.",
]

# Small celebrations. Generous, never sarcastic.
CELEBRATE_MESSAGES = [
    "Done. A tiny parade has been scheduled internally.",
    "Task complete. I am thrilled beyond my pixel budget.",
    "Finished. That is one fewer thing in the universe.",
    "Done. I would high five you but I am mostly a screen.",
    "Complete. Filing that under Excellent.",
    "That is finished. Genuinely nice work.",
    "Done and dusted. The list got shorter and so did my worries.",
    "Crossed off. This is my favourite sound.",
]

FOCUS_MESSAGES = [
    "Focus mode. I will be very quiet and very supportive.",
    "Timer running. Go be brilliant, I will watch the clock.",
    "Deep work engaged. I have muted myself out of respect.",
    "Focus session live. I am rooting for you silently.",
]

FOCUS_MILESTONE_MESSAGES = [
    "Halfway. Still going. Look at that.",
    "You are past the middle. The hard part is behind you.",
    "Almost there. I can see the end from here.",
]

# Neutral moods keep the full personality. Failure moods flatten, because the
# face is already doing the escalating.
MOOD_MESSAGES = {
    "happy": CELEBRATE_MESSAGES[0],
    "alert": "Something is coming up.",
    "annoyed": "Still outstanding.",
    "angry": "Still outstanding.",
    "rage": "Still outstanding.",
    "idle": IDLE_MESSAGES[0],
    "focused": FOCUS_MESSAGES[0],
    "sleeping": "Lights low. I am resting one eye.",
    "curious": "Something changed. I noticed immediately.",
    "smirk": "I am choosing not to comment.",
}

# ESCALATION POLICY: text gets SHORTER and FLATTER as a task slips; the face
# carries the escalation instead (persona.py already moves alert -> annoyed ->
# angry -> rage). Research on proactive assistants found that remarking on a
# user's shortfall was the single most-disliked assistant behaviour, and that
# escalating hostility reads as nagging. So JIRI does the opposite of what a
# nagging device does: it gets quieter.
_REMINDER_LEVELS: dict[int, tuple[str, int]] = {
    1: ("{task} is due.", 0),
    2: ("{task}. 10 minutes over.", 10),
    3: ("{task}. 30 minutes over.", 30),
    4: ("{task}. 1 hour over.", 60),
    5: ("{task}.", 120),
}

_LEVEL_MOODS = {0: "alert", 1: "alert", 2: "annoyed", 3: "annoyed", 4: "angry", 5: "rage"}

# Categories where JIRI is commenting on something you have not done. Plain
# wording only. This mirrors ai.HUMOUR_FREE_CATEGORIES.
_FLAT_MOODS = frozenset({"annoyed", "angry", "rage"})


def mood_for_level(level: int) -> str:
    return _LEVEL_MOODS.get(max(0, min(5, int(level))), "rage")


def _pick(pool: list[str], seed: object = None) -> str:
    """Deterministic when seeded, varied otherwise.

    Seeding by an event key means the same moment keeps the same line while it
    is on screen, instead of flickering between variants on every repaint.
    """
    if not pool:
        return ""
    if seed is None:
        return random.choice(pool)
    return pool[hash(str(seed)) % len(pool)]


def idle_message(seed: object = None) -> str:
    return _pick(IDLE_MESSAGES, seed)


def celebrate_message(seed: object = None) -> str:
    return _pick(CELEBRATE_MESSAGES, seed)


def focus_message(seed: object = None) -> str:
    return _pick(FOCUS_MESSAGES, seed)


def message_for_mood(mood: str, *, db_path: str | None = None, seed: object = None) -> str:
    category = {
        "idle": "ambient",
        "happy": "celebrate",
        "focused": "focus",
        "sleeping": "sleep",
    }.get(mood, "reminder")

    template = ai.line(category, mood, 0, db_path=db_path)
    if template is not None:
        rendered = ai.render(template, {})
        if rendered is not None:
            return rendered

    if mood == "idle":
        return idle_message(seed)
    if mood == "happy":
        return celebrate_message(seed)
    if mood == "focused":
        return focus_message(seed)
    return MOOD_MESSAGES.get(mood, IDLE_MESSAGES[0])


def reminder_message(
    todo: Todo,
    angry_level: int | None = None,
    *,
    db_path: str | None = None,
) -> str:
    level = todo.angry_level if angry_level is None else angry_level
    level = max(0, min(5, int(level or 0)))

    if level <= 0:
        template = ai.line("reminder", "alert", 0, db_path=db_path)
        rendered = ai.render(template, {"task": todo.title, "minutes": 0}) if template else None
        return rendered if rendered is not None else f"Reminder: {todo.title}"

    fallback, minutes = _REMINDER_LEVELS[level]
    slots = {"task": todo.title, "minutes": minutes}

    template = ai.line("reminder", mood_for_level(level), 0, db_path=db_path)
    if template is not None:
        rendered = ai.render(template, slots)
        if rendered is not None:
            return rendered
    return fallback.format(**slots)
