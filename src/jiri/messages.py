from __future__ import annotations

from .models import Todo


IDLE_MESSAGES = [
    "Systems calm. Suspiciously calm.",
    "No pending tasks. I will allow it.",
    "Desk assistant idle. Try not to break anything.",
]

MOOD_MESSAGES = {
    "happy": "Task complete. Tiny victory parade scheduled internally.",
    "alert": "A task is coming up. Pretend this was your idea.",
    "annoyed": "This task is late. I am still being polite, somehow.",
    "angry": "The task is properly late now. Bold strategy.",
    "rage": "RAGE MODE: The todo has escaped containment.",
    "idle": IDLE_MESSAGES[0],
}


def message_for_mood(mood: str) -> str:
    return MOOD_MESSAGES.get(mood, IDLE_MESSAGES[0])


def reminder_message(todo: Todo, angry_level: int | None = None) -> str:
    level = todo.angry_level if angry_level is None else angry_level
    if level <= 0:
        return f"Reminder: {todo.title}"
    if level == 1:
        return f"{todo.title} is due. I am watching the clock for both of us."
    if level == 2:
        return f"{todo.title} is 10+ minutes late. Excellent procrastination specimen."
    if level == 3:
        return f"{todo.title} is 30+ minutes late. The desk goblin is concerned."
    if level == 4:
        return f"{todo.title} is 60+ minutes late. I have upgraded concern to judgment."
    return f"{todo.title} is 120+ minutes late. RAGE MODE has entered the chat."
