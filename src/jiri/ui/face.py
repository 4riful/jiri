"""The closed set of face states the persona layer may produce.

``persona.py`` and ``todos.OVERDUE_TABLE`` pick one of these; ``ui/mascot.py``
must have a drawing for every one of them (enforced by tests).
"""

from __future__ import annotations

FACE_STATES = frozenset(
    {
        "idle",
        "happy",
        "alert",
        "annoyed",
        "angry",
        "rage",
        "sleeping",
        "blink",
        "curious",
        "smirk",
        "focused",
        "weather_hot",
        "weather_rain",
        "ai_offline",
        "system_warning",
    }
)
