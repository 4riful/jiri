from __future__ import annotations

from pathlib import Path

import pytest

from jiri.config import ConfigError, load_config


def test_load_defaults_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.display.width == 480
    assert cfg.display.height == 320
    assert cfg.weather.provider == "open_meteo"
    assert cfg.weather.location == "auto"
    assert cfg.weather.timeout_seconds == 3


def test_env_overrides_for_wsl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_DB_PATH", "data/jiri_dev.db")
    monkeypatch.setenv("JIRI_WEATHER_LOCATION", "Narayanganj")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    monkeypatch.setenv("JIRI_WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("JIRI_WEB_PORT", "5001")
    cfg = load_config()
    assert cfg.display.driver == "mock"
    assert cfg.display.fullscreen is False
    assert Path(cfg.database.path).is_absolute()
    assert Path(cfg.database.path).name == "jiri_dev.db"
    assert cfg.weather.location == "Narayanganj"
    assert cfg.weather.fake is True
    assert cfg.web.host == "127.0.0.1"
    assert cfg.web.port == 5001


def test_telegram_env_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_TELEGRAM_BOT_TOKEN", "123456:abc")
    monkeypatch.setenv("JIRI_TELEGRAM_ALLOWED_CHAT_IDS", "123456789, -1001234567890")
    cfg = load_config()
    assert cfg.telegram.bot_token == "123456:abc"
    assert cfg.telegram.allowed_chat_ids == (123456789, -1001234567890)


def test_storage_paths_are_stable_across_working_directories(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "jiri.toml"
    config_path.write_text(
        '[database]\npath = "state/jiri.db"\nbackup_dir = "state/backups"\n',
        encoding="utf-8",
    )

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    first_cfg = load_config(config_path)
    monkeypatch.chdir(second)
    second_cfg = load_config(config_path)

    expected = config_dir / "state" / "jiri.db"
    assert first_cfg.database.path == str(expected)
    assert second_cfg.database.path == str(expected)
    assert first_cfg.database.backup_dir == str(config_dir / "state" / "backups")


def test_ai_providers_parse_and_env_overrides(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[ai]
daily_request_cap = 50

[[ai.providers]]
name = "gemini"
model = "gemini-3.5-flash"

[[ai.providers]]
name = "groq"
model = "qwen/qwen3.6-27b"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert [p.name for p in cfg.ai.providers] == ["gemini", "groq"]

    monkeypatch.setenv("JIRI_AI_DAILY_CAP", "7")
    cfg = load_config(cfg_path)
    assert cfg.ai.daily_request_cap == 7


def test_ai_provider_chain_is_required_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert [provider.name for provider in cfg.ai.providers] == ["gemini", "groq"]

    config_path = tmp_path / "config.toml"
    config_path.write_text("[ai]\nproviders = []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="requires at least one"):
        load_config(config_path)



def test_telegram_config_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.telegram.enabled is False
    assert cfg.telegram.command_chat_id is None
    assert cfg.telegram.polling_timeout_seconds == 25


def test_invalid_weather_timeout_rejected(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[weather]\ntimeout_seconds = 5\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Weather timeout"):
        load_config(cfg_path)


def test_invalid_weather_coordinates_rejected(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[weather]\nlatitude = 91\nlongitude = 88.85\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="latitude"):
        load_config(cfg_path)


def test_typing_speed_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.display.typing_speed_cps == 24


def test_typing_speed_from_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[display]\ntyping_speed_cps = 30\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.display.typing_speed_cps == 30


def test_invalid_typing_speed_rejected(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[display]\ntyping_speed_cps = 17\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="typing speed"):
        load_config(cfg_path)
