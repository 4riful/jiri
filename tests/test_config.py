from __future__ import annotations

import pytest

from jiri.config import ConfigError, load_config


def test_load_defaults_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.display.width == 480
    assert cfg.display.height == 320
    assert cfg.weather.timeout_seconds == 3
    assert cfg.worker.timeout_seconds == 1


def test_env_overrides_for_wsl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    monkeypatch.setenv("JIRI_DB_PATH", "data/jiri_dev.db")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    cfg = load_config()
    assert cfg.display.driver == "mock"
    assert cfg.display.fullscreen is False
    assert cfg.database.path == "data/jiri_dev.db"
    assert cfg.weather.fake is True


def test_invalid_weather_timeout_rejected(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[weather]\ntimeout_seconds = 5\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Weather timeout"):
        load_config(cfg_path)
