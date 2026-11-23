from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Todo:
    id: int
    title: str
    description: str | None
    due_at: str | None
    status: str
    priority: int
    created_at: str
    updated_at: str
    completed_at: str | None
    angry_level: int


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str
    tags: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WeatherSnapshot:
    location: str
    fetched_at: str | None
    temperature_c: float | None
    condition: str
    humidity: int | None = None
    rain_chance: int | None = None
    stale: bool = False
    unavailable: bool = False


@dataclass(frozen=True)
class FocusSession:
    id: int
    kind: str
    status: str
    title: str
    todo_id: int | None
    duration_seconds: int
    elapsed_seconds: int
    started_at: str | None
    paused_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    created_at: str
    updated_at: str
