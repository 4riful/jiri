from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib


@dataclass(frozen=True)
class DisplayConfig:
    driver: str = "pygame"
    width: int = 480
    height: int = 320
    fullscreen: bool = True
    fps: int = 15
    rotate_seconds: int = 20


@dataclass(frozen=True)
class AssistantConfig:
    name: str = "JIRI"
    personality: str = "funny_sarcastic"
    rage_mode_enabled: bool = True


@dataclass(frozen=True)
class WeatherConfig:
    provider: str = "wttr"
    location: str = "Dhaka"
    refresh_minutes: int = 30
    timeout_seconds: int = 3
    fake: bool = False


@dataclass(frozen=True)
class DatabaseConfig:
    path: str = "data/jiri.db"
    backup_dir: str = "backups"


@dataclass(frozen=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 5000


@dataclass(frozen=True)
class WorkerConfig:
    enabled: bool = False
    base_url: str = "http://pi-worker.local:5050"
    timeout_seconds: int = 1


@dataclass(frozen=True)
class PerformanceConfig:
    max_ui_ram_mb: int = 250
    max_web_ram_mb: int = 150
    target_fps: int = 15
    min_acceptable_fps: int = 10


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool = False
    provider: str = "none"
    model_path: str = ""


@dataclass(frozen=True)
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    web: WebConfig = field(default_factory=WebConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)


class ConfigError(ValueError):
    """Raised when the config is invalid."""


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    data: dict[str, Any] = {}
    config_path = Path(path or os.environ.get("JIRI_CONFIG", "config.toml"))
    if config_path.exists():
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML config: {exc}") from exc

    cfg = AppConfig(
        display=_section(DisplayConfig, data.get("display", {})),
        assistant=_section(AssistantConfig, data.get("assistant", {})),
        weather=_section(WeatherConfig, data.get("weather", {})),
        database=_section(DatabaseConfig, data.get("database", {})),
        web=_section(WebConfig, data.get("web", {})),
        worker=_section(WorkerConfig, data.get("worker", {})),
        performance=_section(PerformanceConfig, data.get("performance", {})),
        llm=_section(LlmConfig, data.get("llm", {})),
    )
    cfg = _apply_env(cfg)
    _validate(cfg)
    return cfg


def _section(cls: type[Any], values: dict[str, Any]) -> Any:
    allowed = cls.__dataclass_fields__.keys()
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise ConfigError(f"Unknown config keys for {cls.__name__}: {', '.join(unknown)}")
    return cls(**values)


def _apply_env(cfg: AppConfig) -> AppConfig:
    display = cfg.display
    database = cfg.database
    weather = cfg.weather

    if "JIRI_DISPLAY_DRIVER" in os.environ:
        display = replace(display, driver=os.environ["JIRI_DISPLAY_DRIVER"])
    if "JIRI_FULLSCREEN" in os.environ:
        display = replace(display, fullscreen=_parse_bool(os.environ["JIRI_FULLSCREEN"], "JIRI_FULLSCREEN"))
    if "JIRI_WIDTH" in os.environ:
        display = replace(display, width=_parse_int(os.environ["JIRI_WIDTH"], "JIRI_WIDTH"))
    if "JIRI_HEIGHT" in os.environ:
        display = replace(display, height=_parse_int(os.environ["JIRI_HEIGHT"], "JIRI_HEIGHT"))
    if "JIRI_DB_PATH" in os.environ:
        database = replace(database, path=os.environ["JIRI_DB_PATH"])
    if "JIRI_WEATHER_FAKE" in os.environ:
        weather = replace(weather, fake=_parse_bool(os.environ["JIRI_WEATHER_FAKE"], "JIRI_WEATHER_FAKE"))

    return replace(cfg, display=display, database=database, weather=weather)


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean value")


def _parse_int(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _validate(cfg: AppConfig) -> None:
    if cfg.display.width <= 0 or cfg.display.height <= 0:
        raise ConfigError("Display width and height must be positive")
    if not 1 <= cfg.display.fps <= 30:
        raise ConfigError("Display FPS must be between 1 and 30")
    if cfg.weather.timeout_seconds > 3:
        raise ConfigError("Weather timeout must not exceed 3 seconds")
    if cfg.weather.refresh_minutes < 1:
        raise ConfigError("Weather refresh interval must be at least 1 minute")
    if cfg.worker.timeout_seconds > 1:
        raise ConfigError("Worker timeout must not exceed 1 second")
    if cfg.web.port <= 0 or cfg.web.port > 65535:
        raise ConfigError("Web port must be between 1 and 65535")
