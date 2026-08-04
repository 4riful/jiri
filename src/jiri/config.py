from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    personality: str = "playful_joyful"
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
class AiProviderConfig:
    """One OpenAI-compatible chat-completions endpoint.

    `name` selects a preset in `jiri.ai.PROVIDER_PRESETS` (groq, gemini, xai,
    ollama); `base_url` and `api_key_env` override the preset when set.
    """

    name: str = ""
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class AiConfig:
    """Hosted-LLM wording layer. Never on the render path — see `jiri.ai`."""

    timeout_seconds: float = 8.0
    daily_request_cap: int = 200
    max_output_chars: int = 160
    max_tokens: int = 400
    # High temperature is deliberate: this layer wants variety, not accuracy.
    # Groq requires 0 < temperature <= 2 and rewrites 0 to 1e-8.
    temperature: float = 1.1
    min_lines_per_bucket: int = 12
    max_lines_per_bucket: int = 60
    providers: tuple[AiProviderConfig, ...] = (
        AiProviderConfig(name="gemini"),
        AiProviderConfig(name="groq"),
    )


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
    ai: AiConfig = field(default_factory=AiConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


class ConfigError(ValueError):
    """Raised when the config is invalid."""


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    data: dict[str, Any] = {}
    configured_path = Path(path or os.environ.get("JIRI_CONFIG", PROJECT_ROOT / "config.toml")).expanduser()
    config_path = configured_path if configured_path.is_absolute() else PROJECT_ROOT / configured_path
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
        ai=_ai_section(data.get("ai", {})),
        telegram=_section(TelegramConfig, data.get("telegram", {})),
    )
    cfg = _apply_env(cfg)
    cfg = _resolve_storage_paths(cfg, config_path.parent)
    _validate(cfg)
    return cfg


def _resolve_storage_paths(cfg: AppConfig, config_dir: Path) -> AppConfig:
    def resolve(value: str) -> str:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = config_dir / candidate
        return str(candidate.resolve())

    database = replace(
        cfg.database,
        path=resolve(cfg.database.path),
        backup_dir=resolve(cfg.database.backup_dir),
    )
    return replace(cfg, database=database)


def _section(cls: type[Any], values: dict[str, Any]) -> Any:
    allowed = cls.__dataclass_fields__.keys()
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise ConfigError(f"Unknown config keys for {cls.__name__}: {', '.join(unknown)}")
    return cls(**values)


def _ai_section(values: dict[str, Any]) -> AiConfig:
    """Parse `[ai]` plus its `[[ai.providers]]` array of tables."""
    scalars = {k: v for k, v in values.items() if k != "providers"}
    raw_providers = values.get("providers")
    base = _section(AiConfig, scalars)
    if raw_providers is None:
        return base
    if not isinstance(raw_providers, list):
        raise ConfigError("[ai].providers must be an array of tables")
    providers = []
    for index, entry in enumerate(raw_providers):
        if not isinstance(entry, dict):
            raise ConfigError(f"[[ai.providers]] entry {index + 1} must be a table")
        provider = _section(AiProviderConfig, entry)
        if not provider.name.strip():
            raise ConfigError(f"[[ai.providers]] entry {index + 1} needs a name")
        providers.append(provider)
    return replace(base, providers=tuple(providers))


def _apply_env(cfg: AppConfig) -> AppConfig:
    display = cfg.display
    database = cfg.database
    weather = cfg.weather
    web = cfg.web
    ai = cfg.ai
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
    if "JIRI_AI_DAILY_CAP" in os.environ:
        ai = replace(ai, daily_request_cap=_parse_int(os.environ["JIRI_AI_DAILY_CAP"], "JIRI_AI_DAILY_CAP"))
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

    return replace(cfg, display=display, database=database, weather=weather, web=web, ai=ai, telegram=telegram)


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
    if not 18 <= cfg.display.typing_speed_cps <= 30:
        raise ConfigError("Display typing speed must be between 18 and 30 characters per second")
    if not cfg.ai.providers:
        raise ConfigError("AI requires at least one [[ai.providers]] entry")
    if cfg.ai.daily_request_cap < 0:
        raise ConfigError("AI daily request cap cannot be negative")
    if cfg.ai.timeout_seconds <= 0:
        raise ConfigError("AI timeout must be positive")
    if cfg.ai.max_output_chars < 20 or cfg.ai.max_output_chars > 500:
        raise ConfigError("AI max output chars must be between 20 and 500")
    if not 0 < cfg.ai.temperature <= 2:
        raise ConfigError("AI temperature must be greater than 0 and at most 2")
    if cfg.ai.min_lines_per_bucket < 1:
        raise ConfigError("AI min lines per bucket must be at least 1")
    if cfg.ai.max_lines_per_bucket < cfg.ai.min_lines_per_bucket:
        raise ConfigError("AI max lines per bucket must be >= min lines per bucket")
    names = [p.name for p in cfg.ai.providers]
    if len(names) != len(set(names)):
        raise ConfigError("[[ai.providers]] names must be unique")
