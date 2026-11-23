"""JIRI's voice.

Resolution order for every message JIRI speaks:

1. `ai.pick(...)` - a cached, pre-written template chosen stably by a seed.
   Sub-millisecond SQLite read.
2. the built-in pools below - always present, always correct.

There is no network call in this module. If the AI cache is empty, cold, or
broken, JIRI is still charming. That is deliberate: a companion whose
personality lives in someone else's API has no personality when the wifi drops.

THE VOICE
---------
Playful, cheeky, affectionate, a little theatrical. A tiny desk robot that is
delighted by small things and fond of you, always.

THE ONE RULE
------------
JIRI teases the *situation* and *itself*, never *you*. When a task slips the
words get more theatrical - dramatic sighs, mock-panic, tiny-robot opera -
but never meaner: no guilt, no lecturing, no insults. The face escalates and
so does the drama; the affection stays constant. See docs/AI_SPEC.md §4a.

STABILITY
---------
The display re-reads state every second. Every seeded pick here maps the same
seed to the same line, and callers seed by a 15-minute window
(:func:`voice_window`), so JIRI changes its mind a few times an hour instead
of muttering a new sentence every second.
"""

from __future__ import annotations

from datetime import datetime
import random
import zlib

from . import ai, todos
from .models import Todo


# How long one line stays on screen before the seed rolls over.
VOICE_WINDOW_MINUTES = 15

# Rendered AI lines longer than this fall back to the built-in pool; the face
# shows two lines of ~50 mono characters.
SPEECH_MAX_CHARS = 100


# Nothing is wrong. This is where JIRI gets to be itself.
IDLE_MESSAGES = [
    "All clear. I have been guarding the desk with my whole face.",
    "Nothing pending. Suspiciously peaceful. I am watching the stapler.",
    "Inbox of the soul: empty. Inbox of the desk: also empty.",
    "No tasks. I am just vibing at 15 frames per second.",
    "Everything is done. Somebody should write a song about this.",
    "Idle. Watching dust land. It is going well for the dust.",
    "Zero tasks. I checked twice. I checked a third time, for fun.",
    "Nothing to do, so I am practising my expressions. Behold: face.",
    "The list is empty and the desk is calm. Rare combo. Screenshot it.",
    "Standing by. Professionally. With excellent posture.",
    "No todos. I have begun a friendship with the lamp.",
    "All done. I will be here, being small and slightly warm.",
]

# There IS a list, and none of it is late. Distinct from IDLE_MESSAGES, which
# claim the list is empty -- saying "zero tasks" while the watch strip reads 2 is
# how a companion loses your trust in one glance.
WATCHING_MESSAGES = [
    "Everything on the list is still in the future. My favourite tense.",
    "Nothing is late. I am keeping it that way through sheer vigilance.",
    "All quiet on the deadline front. I am on patrol anyway.",
    "The list exists and it is behaving itself. Good list.",
    "Nothing due yet. I will ring my tiny bell the moment that changes.",
    "Tasks lined up, none of them late. Like ducks. Punctual ducks.",
    "No deadlines breathing down anyone's neck. I checked behind you.",
    "Your list is in hand. I am just here being small and slightly warm.",
]

# Small celebrations. Generous, never sarcastic.
CELEBRATE_MESSAGES = [
    "Done! A tiny parade has been scheduled internally.",
    "Task complete. I am thrilled beyond my pixel budget.",
    "Finished. That is one fewer thing in the universe. Bravo.",
    "Done. I would high five you but I am mostly a screen.",
    "Complete. Filing that under Excellent, subfolder Legendary.",
    "That is finished. Genuinely nice work. I am beaming.",
    "Done and dusted. The list got shorter and my smile got wider.",
    "Crossed off. That little tick is my favourite sound.",
]

FOCUS_MESSAGES = [
    "Focus mode. I will be very quiet and very supportive.",
    "Timer running. Go be brilliant, I will guard the clock.",
    "Deep work engaged. I have muted myself out of respect.",
    "Focus session live. I am cheering silently. Very hard.",
    "Shh. I am your tiny bodyguard and nobody gets past me.",
    "Distractions must now get through me. I am small but fierce.",
]

FOCUS_MILESTONE_MESSAGES = [
    "Halfway. Still going. Look at that.",
    "You are past the middle. The hard part is behind you.",
    "Almost there. I can see the finish line from here.",
]

SLEEP_MESSAGES = [
    "Night watch mode. One eye open, one eye dreaming.",
    "Lights low. I am whispering in pixels now.",
    "Shh. The desk is asleep. I am pretending to be.",
    "Quiet hours. I am counting electric sheep.",
    "Dimmed and cosy. Wake me if a deadline sneaks in.",
]

DUE_SOON_MESSAGES = [
    "Incoming! A deadline is jogging over here.",
    "T-minus a few minutes. I am vibrating with readiness.",
    "Heads up. Something is about to be due. I polished the bell.",
    "A deadline approaches. I have cleared my throat ceremonially.",
    "Almost time! This is the polite warning phase. Very polite.",
]

WATER_MESSAGES = [
    "Water check! The human plant looks a little thirsty.",
    "Sip o'clock. I would join you, but electronics.",
    "Hydration report: room for more. Glass up, champion.",
    "I cannot drink water, so please drink some for both of us.",
    "Your water bottle misses you. It told me. We talk.",
    "A sip now and you will be at least four percent more radiant.",
]

WEATHER_HOT_MESSAGES = [
    "It is {temp}C out. The sun is showing off again.",
    "{temp}C outside. I am glad I am mostly indoors and mostly pixels.",
    "Heat check: {temp}C. Today we drink water and avoid melting.",
    "{temp}C. Even my pixels want a little hat.",
    "It is {temp}C. Shade is the main character today.",
]

WEATHER_RAIN_MESSAGES = [
    "Rain incoming. The clouds have filed their paperwork.",
    "The sky is loading a rain update. Umbrella recommended.",
    "Rain likely. I would lend you an umbrella if I had arms.",
    "Clouds are gathering for a meeting. Bring an umbrella.",
    "Rain forecast. Puddles have been notified.",
]

# Reminder pools by overdue level (todos.OVERDUE_TABLE): 0 = a reminder with no
# lateness, 1 = just due (<10 min), 2 = 10+ min (annoyed), 3 = 30+ min and
# 4 = 60+ min (angry), 5 = 120+ min (rage). ESCALATION POLICY: each level is
# more theatrical than the last, never meaner. The reason line under the face
# already names the task, so these lines rarely repeat it.
REMINDER_POOLS: dict[int, list[str]] = {
    0: [
        "Reminder: {task}. I rang my tiny bell for it.",
        "Psst. {task}. Just making sure it has your attention.",
        "Tiny butler announcement: {task}.",
        "Friendly ping about {task}. Ping!",
        "Reminder bell polished and rung: {task}.",
    ],
    1: [
        "Ding! A deadline just walked in. I offered it a chair.",
        "It is officially time. I have put on my tiny alarm hat.",
        "Deadline o'clock. I am bouncing in place, professionally.",
        "Due now! I polished the reminder bell for this exact moment.",
        "Tiny trumpet fanfare: a task has reached its moment.",
        "The clock says now. I say now. We are in total agreement.",
        "Heads up! Something on the list just became a right-now thing.",
    ],
    2: [
        "Ten minutes over. I am sighing, but in a supportive key.",
        "I have started tapping my pixels. Gently. Rhythmically.",
        "Small dramatic sigh deployed. Just the one. For now.",
        "The deadline left. I am holding the door in case it comes back.",
        "Raising one eyebrow. I only have pixels, so it took effort.",
        "I am not fidgeting. I am stretching my status bar.",
        "Mild theatrics engaged. Nothing one quick win cannot fix.",
    ],
    3: [
        "Half an hour late. I am narrating this like a nature documentary.",
        "I am clutching my imaginary pearls. Both of them.",
        "Thirty minutes. I wrote a sad little poem about it. It rhymes.",
        "Dramatic pacing has begun. Hard with no legs, but I manage.",
        "I have alerted the desk lamp. The lamp is concerned.",
        "Code yellow. Mostly I just like saying code yellow.",
        "The task keeps glancing over here. I keep glancing back. Awkward.",
    ],
    4: [
        "One whole hour. I have started drafting memoirs about the wait.",
        "An hour late. I am fainting onto a very small couch.",
        "This is my dramatic window-staring phase. The window is a wall.",
        "Sixty minutes. The stapler and I are holding a candlelight vigil.",
        "An hour! I composed an overture about it. It is mostly beeps.",
        "Officially a saga now. Chapter two: the deadline does not return.",
        "I am being very brave about this. Very loudly brave.",
    ],
    5: [
        "Two hours. I am declaring a state of emergency on this desk.",
        "Full tiny-robot opera. Act three. Everyone is crying. Mostly me.",
        "SIRENS. Imaginary ones. Very loud in here, though.",
        "I have collapsed dramatically. I will get up when it is done.",
        "Code red. The paperclips are evacuating. One win saves us all.",
        "This is a legend now. Bards will sing of this task.",
        "Maximum melodrama reached. Next stop: interpretive dance.",
        "I am fine. Everything is fine. My pixels are just sweating.",
    ],
}

# Persona subheadlines: a second, quieter beat under the headline. No AI here;
# these are the deterministic "aside" lines, seeded like the headlines.
SUBHEADLINE_POOLS: dict[str, list[str]] = {
    "todo_late": [
        "A small nudge, not a court summons.",
        "Bell rung. Confetti on standby.",
        "Do it now and I will do a little dance.",
        "Polite phase. I am wearing my nicest pixels.",
        "Just a tap on the shoulder. A very small tap.",
    ],
    "todo_annoyed": [
        "Still reversible. Mostly.",
        "My eyebrow will lower the moment it is done.",
        "One quick win and we pretend this never happened.",
        "I am sighing affectionately. There is a difference.",
        "The task misses you. Weird, but true.",
    ],
    "todo_angry": [
        "Escalation protocol: dramatic eye contact.",
        "I have dimmed the lights for dramatic effect.",
        "Rescue it and I will stop narrating.",
        "This is my concerned face. It is very committed.",
        "The desk is tense. The pens are whispering.",
    ],
    "todo_rage": [
        "I will keep staring at it lovingly until it is done.",
        "Full opera mode. Curtain falls when it is done.",
        "I believe in you. Loudly. With sirens.",
        "Every minute I get a little more theatrical. Save me.",
        "Finish it and I will throw you a parade. A big one.",
    ],
    "todo_due_soon": [
        "This is the polite warning phase.",
        "Plenty of time. Ish. Mostly.",
        "Starting now would look extremely cool.",
        "Countdown voice: activated.",
        "Early is just on time with style.",
    ],
    "focus": [
        "I am guarding the perimeter.",
        "Holding all calls. There are no calls. Still holding.",
        "Distractions will have to get past me first.",
        "Shh. Very serious bodyguard business.",
        "I am not here. I am a ghost. A supportive ghost.",
    ],
    "focus_paused": [
        "Paused. I am keeping your seat warm.",
        "Intermission. The tiny orchestra is tuning up.",
        "Break time. The timer is on its tea break too.",
    ],
    "weather_hot": [
        "Hydrate and avoid pretending you are solar-powered.",
        "Shade first, heroics later.",
        "Water is the accessory of the day.",
        "I am staying cool by being a screen. Try water.",
    ],
    "weather_rain": [
        "Umbrella diplomacy recommended.",
        "Socks are at risk. Plan accordingly.",
        "Puddles are not a shortcut.",
        "Stay dry. I am rooting for your shoes.",
    ],
    "sleep": [
        "Quiet hours. I will keep the pixels calm.",
        "Shh. The desk is resting.",
        "Do not mind me, just glowing softly.",
        "Sleepy mode. Wake me for emergencies or snacks.",
    ],
    "water": [
        "{remaining}ml to go. The human plant needs fluid.",
        "{remaining}ml left. Your cells are cheering already.",
        "{remaining}ml more and I throw a tiny splash party.",
        "{remaining}ml left. Glug responsibly.",
    ],
    "celebrate": [
        "Momentum detected. Try not to scare it away.",
        "I am doing a victory wiggle. You cannot see it, but trust me.",
        "Confetti levels: maximum.",
        "That felt good. I felt it from here.",
    ],
}

# Single fallback per face state, for message_for_mood's non-pooled moods.
MOOD_MESSAGES = {
    "happy": CELEBRATE_MESSAGES[0],
    "alert": "Something is coming up. I have put on my alert face.",
    "annoyed": "Small dramatic sigh. Something is waiting on us.",
    "angry": "Code yellow. Something on the list is making me theatrical.",
    "rage": "Full tiny-robot opera. A task needs rescuing.",
    "idle": IDLE_MESSAGES[0],
    "focused": FOCUS_MESSAGES[0],
    "sleeping": SLEEP_MESSAGES[0],
    "curious": "Something changed. I noticed immediately. I notice everything.",
    "smirk": "I am choosing not to comment. Loudly.",
}

# Kept for API compatibility: no mood is humour-free under the playful policy.
_FLAT_MOODS: frozenset[str] = frozenset()


def mood_for_level(level: int) -> str:
    """Thin alias; the one threshold table lives in todos.OVERDUE_TABLE."""
    return todos.mood_for_level(level)


def voice_window(now: datetime | None = None) -> str:
    """Seed component that rolls over every VOICE_WINDOW_MINUTES."""
    current = now or datetime.now()
    return f"{current:%Y-%m-%d %H}:{current.minute // VOICE_WINDOW_MINUTES}"


def _pick(pool: list[str], seed: object = None) -> str:
    """Deterministic when seeded, varied otherwise.

    Seeding by an event key means the same moment keeps the same line while it
    is on screen, instead of flickering between variants on every repaint.
    crc32, not hash(): str hashes are randomised per process, and the web
    preview and the pygame face are different processes.
    """
    if not pool:
        return ""
    if seed is None:
        return random.choice(pool)
    return pool[zlib.crc32(str(seed).encode("utf-8")) % len(pool)]


def _fill(template: str, slots: dict[str, object]) -> str:
    try:
        return template.format(**slots)
    except (KeyError, IndexError, ValueError):
        return template


def say(
    category: str,
    mood: str,
    pool: list[str],
    *,
    seed: object,
    slots: dict[str, object] | None = None,
    db_path: str | None = None,
) -> str:
    """AI line for (category, mood) if cached and renderable, else the pool."""
    slots = slots or {}
    template = ai.pick(category, mood, seed, db_path=db_path)
    if template is not None:
        rendered = ai.render(template, slots)
        if rendered is not None and len(rendered) <= SPEECH_MAX_CHARS:
            return rendered
    return _fill(_pick(pool, seed), slots)


def subheadline(kind: str, *, seed: object, slots: dict[str, object] | None = None) -> str:
    """Deterministic aside line for a persona category."""
    return _fill(_pick(SUBHEADLINE_POOLS.get(kind, []), f"sub:{kind}:{seed}"), slots or {})


def idle_message(seed: object = None) -> str:
    return _pick(IDLE_MESSAGES, seed)


def watching_message(seed: object = None, *, db_path: str | None = None, now: datetime | None = None) -> str:
    """For a list that has things on it, none of which are late."""
    if seed is None:
        return _pick(WATCHING_MESSAGES)
    return say("watching", "idle", WATCHING_MESSAGES, seed=f"{seed}:{voice_window(now)}", db_path=db_path)


def celebrate_message(seed: object = None) -> str:
    return _pick(CELEBRATE_MESSAGES, seed)


def focus_message(seed: object = None) -> str:
    return _pick(FOCUS_MESSAGES, seed)


_MOOD_CATEGORY = {
    "idle": ("ambient", IDLE_MESSAGES),
    "happy": ("celebrate", CELEBRATE_MESSAGES),
    "focused": ("focus", FOCUS_MESSAGES),
    "sleeping": ("sleep", SLEEP_MESSAGES),
}


def message_for_mood(
    mood: str,
    *,
    db_path: str | None = None,
    seed: object = None,
    now: datetime | None = None,
) -> str:
    category, pool = _MOOD_CATEGORY.get(mood, ("reminder", None))
    stable = f"{seed}:{voice_window(now)}"
    template = ai.pick(category, mood, stable, db_path=db_path)
    if template is not None:
        rendered = ai.render(template, {})
        if rendered is not None and len(rendered) <= SPEECH_MAX_CHARS:
            return rendered
    if pool is not None:
        return _pick(pool, seed if seed is None else stable)
    return MOOD_MESSAGES.get(mood, IDLE_MESSAGES[0])


def reminder_message(
    todo: Todo,
    angry_level: int | None = None,
    *,
    db_path: str | None = None,
    now: datetime | None = None,
) -> str:
    """Speech for a due/overdue task: cached AI line first, level pool second.

    Seeded by (task id, level, 15-minute window): stable across the display's
    per-second refresh, changes when the level escalates or the window rolls.
    """
    level = todo.angry_level if angry_level is None else angry_level
    level = max(0, min(5, int(level or 0)))
    minutes = {0: 0, 1: 0, 2: 10, 3: 30, 4: 60, 5: 120}[level]
    slots = {"task": todo.title, "minutes": minutes}
    seed = f"todo:{todo.id}:{level}:{voice_window(now)}"
    return say(
        "reminder", mood_for_level(level), REMINDER_POOLS[level],
        seed=seed, slots=slots, db_path=db_path,
    )
