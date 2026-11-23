"""Deterministic fallback quips for JIRI's home-screen thoughts.

A "thought" on the home screen is (mood, FACT line, QUIP). The fact line is
computed from real data and drawn separately; the quip only *reacts* to it.
Normally the quip comes from the AI cache (`ai.pick(category, "thought", seed)`,
read-only, never touches the network). These hand-written lines are the
outage/cold-start fallback required by docs/AI_SPEC.md.

Rules for every line here (enforced by tests/test_quips.py):
- at most 60 characters, plain ASCII, no digits, no placeholders;
- never restates the fact (no task names, times, amounts);
- witty or sincere, never mean, never guilt.

Pure module: no I/O, safe to call from the draw loop.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable

MAX_CHARS = 60

FALLBACK: dict[str, tuple[str, ...]] = {
    "thought_late": (
        "It's not late, it's fashionably delayed.",
        "One small push and it's done. I believe in you.",
        "I've composed a tiny opera about this. Act two: you win.",
        "The deadline sighed. I sighed. We're both fine.",
        "Quick win waiting right there. I'll hold the door.",
        "My pixels are clutching imaginary pearls.",
        "No stress. Future you will send a thank-you note.",
    ),
    "thought_soon": (
        "Heads up! Something's coming round the corner.",
        "Tiny drumroll starting now.",
        "I'm warming up the confetti, just in case.",
        "Almost time. Stretch, sip, conquer.",
        "Friendly nudge from your desk lookout.",
        "Getting ready is half the fun. Okay, a third.",
        "I'll keep an eye on the clock for you.",
    ),
    "thought_tasks_clear": (
        "Nothing on the list. Suspiciously peaceful.",
        "A clean slate. I'm doing a tiny happy dance.",
        "All clear. The desk is breathing a sigh of relief.",
        "No tasks? I'll guard this calm with my life.",
        "Free time unlocked. Use it wisely, or don't.",
        "Empty list, full heart.",
        "Even the pens look relaxed today.",
    ),
    "thought_tasks_some": (
        "A few things on the list. Nothing scary.",
        "I'm keeping watch. You keep being great.",
        "Steady pace. We've got this.",
        "The list is behaving itself today.",
        "One at a time is still a parade.",
        "I counted them twice. Still friendly.",
        "Small list, big potential.",
    ),
    "thought_water_low": (
        "Your plant has had more water than you. Rematch?",
        "A sip would make my pixels very happy.",
        "Robots can't drink, so please sip for both of us.",
        "Hydration break? The mug is looking lonely.",
        "Water: still undefeated as a beverage.",
        "Psst. The glass misses you.",
        "Tiny sip now, big thank-you from your brain later.",
    ),
    "thought_water_good": (
        "Look at you, hydrating like a pro.",
        "Your cells are sending a thank-you card.",
        "Steady sipping. I'm quietly impressed.",
        "Halfway to legendary hydration status.",
        "The plant is getting competitive now.",
        "Good rhythm. Keep the cup company.",
        "Proud of you. Also a little jealous.",
    ),
    "thought_water_done": (
        "Water goal crushed. Tiny trophy for you.",
        "Fully hydrated. Glowing, honestly.",
        "Mission complete. The plant salutes you.",
        "I'd raise a glass, but I'm a screen.",
        "Hydration champion of this desk. Officially.",
        "Every cell in you is doing a happy wiggle.",
        "You did it. I'm proud of you.",
    ),
    "thought_weather_hot": (
        "It's toasty out. Shade is your best friend.",
        "My pixels are sweating. Stay cool out there.",
        "Hot one today. Water bottle, don't leave home without it.",
        "Sun's showing off. Hat recommended.",
        "Ice cubes are today's MVP.",
        "Melting is for ice cream, not for you.",
        "Keep cool. I'll keep the desk chill.",
    ),
    "thought_weather_rain": (
        "Rain on the way. Umbrella, you're up.",
        "Perfect weather for tea and a cosy task.",
        "Listen for the pitter-patter. Very soothing.",
        "Stay dry out there. I'll stay dry in here.",
        "Puddles ahead. Choose your shoes wisely.",
        "Rainy days are good for focus. Just saying.",
        "The sky is watering the plants for you.",
    ),
    "thought_weather_nice": (
        "Lovely out there. A short walk might be magic.",
        "Fresh air is calling. I'll take a message.",
        "Nice day. Open a window and let it in.",
        "The sky is in a great mood. So am I.",
        "Perfect stretch weather.",
        "If I had legs, I'd go outside.",
        "Good weather, good vibes, good you.",
    ),
    "thought_weather_cold": (
        "Chilly out. Layers are your friend.",
        "I'd wear a tiny scarf if I could.",
        "Warm drink weather. Highly recommended.",
        "Cold outside, cosy desk inside.",
        "Bundle up. Your toes will thank you.",
        "My pixels are shivering in solidarity.",
        "Perfect excuse for a hot cup of something.",
    ),
    "thought_focus": (
        "Focus mode. I'm guarding the door.",
        "Shh. Genius at work.",
        "Distractions have been politely turned away.",
        "You're in the zone. I won't make a peep.",
        "Steady and calm. You're doing great.",
        "Tiny bodyguard on duty.",
        "Deep breath. One thing at a time.",
    ),
    "thought_usage_high": (
        "You and your AI are on a roll today.",
        "Busy building! Maybe stretch those fingers?",
        "That's some serious coding energy.",
        "Your AI buddy is working overtime. So are you.",
        "Impressive hustle. A water break is allowed.",
        "Big brain day. Don't forget to blink.",
        "I'm nosy. What are you two building?",
    ),
    "thought_usage_ok": (
        "Nice steady pace with the AI today.",
        "Easy does it. Good rhythm.",
        "Building something cool? I'm curious.",
        "Balanced and calm. Very zen.",
        "You and the AI make a tidy team.",
        "Quiet productivity. My favourite kind.",
        "Plenty of room to tinker today.",
    ),
    "thought_night": (
        "It's getting late. Rest is productive too.",
        "Sleepy hours. I'm dimming my thoughts.",
        "The desk is yawning. Maybe you should too.",
        "Tomorrow will still be there. Promise.",
        "Night mode. Soft voices only.",
        "Even robots need beauty sleep.",
        "Good work today. Time to wind down.",
    ),
    "thought_morning": (
        "Good morning! Fresh day, fresh start.",
        "Rise and shine. I've been waiting.",
        "Morning! Coffee first, greatness second.",
        "New day, new possibilities.",
        "Hello, sunshine. Ready when you are.",
        "Hope you slept well. I dreamed in pixels.",
        "Let's make today a good one.",
    ),
}

GENERIC: tuple[str, ...] = (
    "Just here, keeping you company.",
    "Hi. I'm glad you're here.",
    "All's well on this little desk.",
)

Lookup = Callable[[str, object], "str | None"]


def _index(seed: object, size: int) -> int:
    return zlib.crc32(str(seed).encode("utf-8")) % size


def quip(category: str, seed: object, lookup: Lookup | None = None) -> str:
    """One quip for a thought category, stable for a given seed.

    `lookup(category, seed)` is tried first (normally a wrapper around
    `ai.pick(category, "thought", seed, db_path=...)`); a falsy result or any
    exception falls back to the hand-written lines. Never raises.
    """
    if lookup is not None:
        try:
            text = lookup(category, seed)
        except Exception:
            text = None
        if text:
            return str(text)
    lines = FALLBACK.get(category) or GENERIC
    return lines[_index(seed, len(lines))]
