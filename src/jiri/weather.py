from __future__ import annotations

from .config import load_config
from .models import WeatherSnapshot


def get_weather(db_path: str | None = None) -> WeatherSnapshot:
    cfg = load_config()
    return WeatherSnapshot(
        location=cfg.weather.location,
        fetched_at=None,
        temperature_c=None,
        condition="Weather unavailable until Stage 2 cache/fetch is implemented",
        stale=False,
        unavailable=True,
    )


def refresh_weather(db_path: str | None = None) -> WeatherSnapshot:
    return get_weather(db_path=db_path)
