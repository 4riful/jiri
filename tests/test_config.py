from __future__ import annotations

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
    assert cfg.database.path == "data/jiri_dev.db"
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


def test_llm_env_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_LLM_SERVER_BINARY", "/opt/llama.cpp/llama-server")
    monkeypatch.setenv("JIRI_LLM_MODEL_PATH", "/models/gemma.gguf")
    monkeypatch.setenv("JIRI_LLM_SERVER_PORT", "8088")
    cfg = load_config()
    assert cfg.llm.server_binary == "/opt/llama.cpp/llama-server"
    assert cfg.llm.model_path == "/models/gemma.gguf"
    assert cfg.llm.server_port == 8088


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
