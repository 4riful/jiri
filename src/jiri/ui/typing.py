from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MAX_MESSAGE_LENGTH = 160


@dataclass(frozen=True)
class TypedText:
    visible: str
    complete: bool
    total_length: int
    visible_length: int


def type_text(
    text: str,
    started_at: datetime,
    now: datetime | None = None,
    speed_cps: int = 24,
) -> TypedText:
    truncated = truncate_text(text)
    total = len(truncated)
    if total == 0:
        return TypedText("", True, 0, 0)

    current = now or datetime.now()
    elapsed = (current - started_at).total_seconds()
    visible_count = min(int(elapsed * speed_cps), total)
    visible_count = max(0, visible_count)

    return TypedText(
        visible=truncated[:visible_count],
        complete=visible_count >= total,
        total_length=total,
        visible_length=visible_count,
    )


def typing_duration_seconds(text: str, speed_cps: int = 24) -> float:
    truncated = truncate_text(text)
    if not truncated:
        return 0.0
    return len(truncated) / max(1, speed_cps)


def truncate_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    return text[:max(0, max_length)]
