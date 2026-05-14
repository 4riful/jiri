from __future__ import annotations

from datetime import datetime

from . import todos


MOODS = {"idle", "alert", "annoyed", "angry", "rage", "happy"}


def calculate_mood(now: datetime | None = None, db_path: str | None = None) -> str:
    current = now or datetime.now()
    pending = todos.list_todos(include_done=False, db_path=db_path)
    if not pending:
        if todos.recently_completed(current, db_path=db_path):
            return "happy"
        return "idle"

    highest = max((todos.calculate_angry_level(todo, current) for todo in pending), default=0)
    if highest >= 3:
        return "rage"
    if highest == 2:
        return "angry"
    if highest == 1:
        return "annoyed"
    if todos.due_soon(current, db_path=db_path):
        return "alert"
    if todos.recently_completed(current, db_path=db_path):
        return "happy"
    return "idle"
