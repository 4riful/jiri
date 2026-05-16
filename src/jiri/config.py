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
    typing_speed_cps: int = 24


@dataclass(frozen=True)
class AssistantConfig:
    name: str = "JIRI"
    personality: str = "funny_sarcastic"
    rage_mode_enabled: bool = True


@dataclass(frozen=True)
class WeatherConfig:
    provider: str = "open_meteo"
    location: str = "auto"
    latitude: float | None = None
    longitude: float | None = None
    refresh_minutes: int = 30
    timeout_seconds: int = 3
    fake: bool = False


@dataclass(frozen=True)
class FocusConfig:
    enabled: bool = True
    default_minutes: int = 25
    break_minutes: int = 5
    checkpoint_seconds: int = 60


@dataclass(frozen=True)
class DatabaseConfig:
    path: str = "data/jiri.db"
    backup_dir: str = "backups"


@dataclass(frozen=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 5000


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
    server_binary: str = "llama-server"
    server_port: int = 8080
    server_context: int = 512
    server_threads: int = 2


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    allowed_chat_ids: tuple[int, ...] = ()
    polling_timeout_seconds: int = 25
    command_chat_id: int | None = None
    enabled: bool = False


@dataclass(frozen=True)
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    focus: FocusConfig = field(default_factory=FocusConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    web: WebConfig = field(default_factory=WebConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


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
        focus=_section(FocusConfig, data.get("focus", {})),
        database=_section(DatabaseConfig, data.get("database", {})),
        web=_section(WebConfig, data.get("web", {})),
        performance=_section(PerformanceConfig, data.get("performance", {})),
        llm=_section(LlmConfig, data.get("llm", {})),
        telegram=_section(TelegramConfig, data.get("telegram", {})),
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
    web = cfg.web
    llm = cfg.llm
    telegram = cfg.telegram

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
    if "JIRI_WEATHER_LOCATION" in os.environ:
        weather = replace(weather, location=os.environ["JIRI_WEATHER_LOCATION"])
    if "JIRI_WEATHER_FAKE" in os.environ:
        weather = replace(weather, fake=_parse_bool(os.environ["JIRI_WEATHER_FAKE"], "JIRI_WEATHER_FAKE"))
    if "JIRI_WEB_HOST" in os.environ:
        web = replace(web, host=os.environ["JIRI_WEB_HOST"])
    if "JIRI_WEB_PORT" in os.environ:
        web = replace(web, port=_parse_int(os.environ["JIRI_WEB_PORT"], "JIRI_WEB_PORT"))
    if "JIRI_LLM_SERVER_BINARY" in os.environ:
        llm = replace(llm, server_binary=os.environ["JIRI_LLM_SERVER_BINARY"].strip())
    if "JIRI_LLM_MODEL_PATH" in os.environ:
        llm = replace(llm, model_path=os.environ["JIRI_LLM_MODEL_PATH"].strip())
    if "JIRI_LLM_SERVER_PORT" in os.environ:
        llm = replace(llm, server_port=_parse_int(os.environ["JIRI_LLM_SERVER_PORT"], "JIRI_LLM_SERVER_PORT"))
    if "JIRI_TELEGRAM_BOT_TOKEN" in os.environ:
        telegram = replace(telegram, bot_token=os.environ["JIRI_TELEGRAM_BOT_TOKEN"].strip())
    if "JIRI_TELEGRAM_ALLOWED_CHAT_IDS" in os.environ:
        telegram = replace(
            telegram,
            allowed_chat_ids=_parse_int_list(os.environ["JIRI_TELEGRAM_ALLOWED_CHAT_IDS"], "JIRI_TELEGRAM_ALLOWED_CHAT_IDS"),
        )
    if "JIRI_TELEGRAM_COMMAND_CHAT_ID" in os.environ:
        telegram = replace(telegram, command_chat_id=_parse_optional_int(os.environ["JIRI_TELEGRAM_COMMAND_CHAT_ID"], "JIRI_TELEGRAM_COMMAND_CHAT_ID"))
    if "JIRI_TELEGRAM_ENABLED" in os.environ:
        telegram = replace(telegram, enabled=_parse_bool(os.environ["JIRI_TELEGRAM_ENABLED"], "JIRI_TELEGRAM_ENABLED"))

    return replace(cfg, display=display, database=database, weather=weather, web=web, llm=llm, telegram=telegram)


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


def _parse_optional_int(value: str, name: str) -> int | None:
    clean = value.strip()
    if not clean:
        return None
    return _parse_int(clean, name)


def _parse_int_list(value: str, name: str) -> tuple[int, ...]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a comma-separated list of integers") from exc


def _validate(cfg: AppConfig) -> None:
    if cfg.display.width <= 0 or cfg.display.height <= 0:
        raise ConfigError("Display width and height must be positive")
    if not 1 <= cfg.display.fps <= 30:
        raise ConfigError("Display FPS must be between 1 and 30")
    if cfg.weather.timeout_seconds > 3:
        raise ConfigError("Weather timeout must not exceed 3 seconds")
    if cfg.weather.refresh_minutes < 1:
        raise ConfigError("Weather refresh interval must be at least 1 minute")
    if not cfg.weather.location.strip():
        raise ConfigError("Weather location cannot be empty")
    if (cfg.weather.latitude is None) != (cfg.weather.longitude is None):
        raise ConfigError("Weather latitude and longitude must be configured together")
    if cfg.weather.latitude is not None and not -90 <= cfg.weather.latitude <= 90:
        raise ConfigError("Weather latitude must be between -90 and 90")
    if cfg.weather.longitude is not None and not -180 <= cfg.weather.longitude <= 180:
        raise ConfigError("Weather longitude must be between -180 and 180")
    if cfg.focus.default_minutes < 1:
        raise ConfigError("Focus default minutes must be at least 1")
    if cfg.focus.break_minutes < 1:
        raise ConfigError("Focus break minutes must be at least 1")
    if cfg.focus.checkpoint_seconds < 10:
        raise ConfigError("Focus checkpoint seconds must be at least 10")
    if cfg.web.port <= 0 or cfg.web.port > 65535:
        raise ConfigError("Web port must be between 1 and 65535")
    if cfg.telegram.polling_timeout_seconds < 1 or cfg.telegram.polling_timeout_seconds > 50:
        raise ConfigError("Telegram polling timeout must be between 1 and 50 seconds")
    if not 10 <= cfg.display.typing_speed_cps <= 40:
        raise ConfigError("Display typing speed must be between 10 and 40 characters per second")
