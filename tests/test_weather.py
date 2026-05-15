from __future__ import annotations

from datetime import datetime

import pytest
import requests

from jiri import db, weather
from jiri.config import WeatherConfig, AppConfig


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


@pytest.fixture(autouse=True)
def disable_fake_weather(monkeypatch):
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "false")


def test_open_meteo_geocoding_parse(monkeypatch):
    def fake_get(url, params, timeout):
        assert url == weather.OPEN_METEO_GEOCODING_URL
        assert params["name"] == "panchagarh"
        assert params["count"] == 10
        assert timeout == 3
        return FakeResponse({"results": [geo_result("Panchagarh", country_code="BD")]})

    monkeypatch.setattr(weather.requests, "get", fake_get)
    results = weather.search_locations("panchagarh")
    assert results[0]["name"] == "Panchagarh"
    assert results[0]["admin1"] == "Rangpur Division"
    assert results[0]["admin2"] == "Panchagarh District"
    assert results[0]["admin3"] == "Panchagarh Sadar"


def test_duplicate_location_results_displayed_separately(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "results": [
                    geo_result("Panchagarh", latitude=26.1, longitude=88.8),
                    geo_result("Panchagarh", latitude=26.2, longitude=88.9, admin3="Tetulia"),
                ]
            }
        )

    monkeypatch.setattr(weather.requests, "get", fake_get)
    results = weather.search_locations("panchagarh")
    assert len(results) == 2
    assert results[0]["latitude"] != results[1]["latitude"]


def test_bangladesh_labels_include_division_district_upazila():
    item = weather._normalize_location_result(geo_result("Panchagarh", country_code="BD"))
    text = weather.format_location_result(1, item)
    assert "Division: Rangpur Division" in text
    assert "District: Panchagarh District" in text
    assert "Upazila/Subdistrict: Panchagarh Sadar" in text


def test_country_bd_sorts_bangladesh_first(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "results": [
                    geo_result("Panchagarh", country="India", country_code="IN"),
                    geo_result("Panchagarh", country="Bangladesh", country_code="BD"),
                ]
            }
        )

    monkeypatch.setattr(weather.requests, "get", fake_get)
    results = weather.search_locations("panchagarh", country="BD")
    assert results[0]["country_code"] == "BD"
    assert results[1]["country_code"] == "IN"


def test_location_set_validates_invalid_index(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.save_last_location_search([weather._normalize_location_result(geo_result("Panchagarh"))], db_path=db_path)
    with pytest.raises(ValueError, match="between 1 and 1"):
        weather.select_location(2, db_path=db_path)


def test_selected_location_saved_with_admin_fields(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    result = weather._normalize_location_result(geo_result("Panchagarh"))
    weather.save_last_location_search([result], db_path=db_path)
    selected = weather.select_location(1, db_path=db_path)
    assert selected["admin1"] == "Rangpur Division"
    assert db.get_setting("weather.admin2", db_path=db_path) == "Panchagarh District"
    assert db.get_setting("weather.latitude", db_path=db_path) == "26.1167"
    assert weather.get_recent_locations(db_path=db_path)[0]["name"] == "Panchagarh"


def test_recent_locations_are_saved_deduped_and_selectable(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    weather.set_coordinates("Office", 26.2, 88.9, db_path=db_path)
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)

    recent = weather.get_recent_locations(db_path=db_path)

    assert [item["name"] for item in recent] == ["Home", "Office"]
    selected = weather.select_recent_location(2, db_path=db_path)
    assert selected["name"] == "Office"
    assert weather.get_active_location(db_path=db_path)["name"] == "Office"


def test_location_current_prefers_sqlite_settings_over_config(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    cfg = AppConfig(weather=WeatherConfig(latitude=1.0, longitude=2.0, location="Config"))
    active = weather.get_active_location(db_path=db_path, config=cfg)
    assert active is not None
    assert active["source"] == "settings"
    assert active["name"] == "Home"
    assert active["latitude"] == 26.1167


def test_set_coords_validates_latitude_longitude(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    with pytest.raises(ValueError, match="Latitude"):
        weather.set_coordinates("Bad", 91, 88.85, db_path=db_path)
    with pytest.raises(ValueError, match="Longitude"):
        weather.set_coordinates("Bad", 26.1167, 181, db_path=db_path)


def test_weather_refresh_uses_coordinates_and_does_not_geocode(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    calls = []

    def fake_open(location, timeout_seconds=3):
        calls.append(location)
        return stable_weather("Home", source="open_meteo")

    def fail_geocode(*args, **kwargs):
        raise AssertionError("weather refresh must not geocode")

    monkeypatch.setattr(weather, "fetch_open_meteo_weather", fake_open)
    monkeypatch.setattr(weather, "search_locations", fail_geocode)
    result = weather.refresh_weather(db_path=db_path)
    assert result["source"] == "open_meteo"
    assert calls[0]["latitude"] == 26.1167


def test_open_meteo_weather_success_parse(monkeypatch):
    def fake_get(url, params, timeout):
        assert url == weather.OPEN_METEO_FORECAST_URL
        assert params["latitude"] == 26.1167
        assert "weather_code" in params["current"]
        assert "weather_code" in params["daily"]
        assert params["forecast_days"] == 7
        return FakeResponse(open_meteo_payload())

    monkeypatch.setattr(weather.requests, "get", fake_get)
    result = weather.fetch_open_meteo_weather(location())
    assert result["source"] == "open_meteo"
    assert result["temperature_c"] == 31.0
    assert result["feels_like_c"] == 35.0
    assert result["condition"] == "Partly cloudy"
    assert result["humidity"] == 70
    assert result["rain_chance"] == 80
    assert result["wind_kmh"] == 12.0
    assert result["hourly_forecast"][0]["time"] == "3:00 am"
    assert result["hourly_forecast"][0]["temperature_c"] == 31.0
    assert result["hourly_forecast"][0]["icon"] == "cloud"
    assert result["daily_forecast"][0]["day"] == "Today"
    assert result["daily_forecast"][0]["high_c"] == 34.0
    assert result["location_meta"]["latitude"] == 26.1167
    assert result["location_meta"]["country"] == "Bangladesh"


def test_cached_open_meteo_weather_preserves_secondary_fields(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    live = weather._parse_open_meteo_response(location(), open_meteo_payload())
    weather.save_weather_cache("Home", live, db_path=db_path)

    cached = weather.get_cached_weather("Home", db_path=db_path)

    assert cached is not None
    assert cached["feels_like_c"] == 35.0
    assert cached["wind_kmh"] == 12.0
    assert cached["hourly_forecast"][0]["rain_chance"] == 35
    assert cached["hourly_forecast"][0]["time"] == "3:00 am"
    assert cached["daily_forecast"][0]["low_c"] == 26.0
    assert cached["location_meta"]["latitude"] == 26.1167


def test_fake_weather_mode_does_not_require_network(monkeypatch):
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")

    def fail_get(*args, **kwargs):
        raise AssertionError("fake weather must not call network")

    monkeypatch.setattr(weather.requests, "get", fail_get)
    result = weather.fetch_open_meteo_weather(location())
    assert result["source"] == "open_meteo"
    assert result["condition"] == "Fake partly cloudy"


def test_open_meteo_timeout_then_wttr_success(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    loc = weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)

    def fail_open(location, timeout_seconds=3):
        raise requests.Timeout("open meteo slow")

    def good_wttr(location, timeout_seconds=3):
        return stable_weather("Home", source="wttr", condition="Wttr clear")

    monkeypatch.setattr(weather, "fetch_open_meteo_weather", fail_open)
    monkeypatch.setattr(weather, "fetch_wttr_weather", good_wttr)
    result = weather.refresh_weather_for_location({**loc, "source": "settings"}, db_path=db_path)
    assert result["source"] == "wttr"
    assert result["condition"] == "Wttr clear"


def test_both_providers_fail_then_cache_fallback(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    loc = weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    weather.save_weather_cache("Home", stable_weather("Home", condition="Cached clouds"), db_path=db_path)

    def fail_provider(location, timeout_seconds=3):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(weather, "fetch_open_meteo_weather", fail_provider)
    monkeypatch.setattr(weather, "fetch_wttr_weather", fail_provider)
    result = weather.refresh_weather_for_location({**loc, "source": "settings"}, db_path=db_path)
    assert result["source"] == "cache"
    assert result["condition"] == "Cached clouds"


def test_auto_update_uses_fresh_cache_without_network(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    loc = weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    weather.save_weather_cache("Home", stable_weather("Home", condition="Fresh cache"), db_path=db_path)

    def fail_refresh(*args, **kwargs):
        raise AssertionError("fresh cache must not refresh")

    monkeypatch.setattr(weather, "refresh_weather_for_location", fail_refresh)
    result = weather.auto_update_weather(db_path=db_path, config=AppConfig(weather=WeatherConfig(refresh_minutes=30)))

    assert loc["name"] == "Home"
    assert result["condition"] == "Fresh cache"


def test_auto_update_refreshes_stale_cache(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    stale = stable_weather("Home", condition="Old cache")
    stale["fetched_at"] = "2026-01-01T00:00:00"
    weather.save_weather_cache("Home", stale, db_path=db_path)

    def fake_refresh(location, timeout_seconds=3, db_path=None):
        return stable_weather("Home", condition="Fresh live")

    monkeypatch.setattr(weather, "refresh_weather_for_location", fake_refresh)
    result = weather.auto_update_weather(db_path=db_path, config=AppConfig(weather=WeatherConfig(refresh_minutes=1)))

    assert result["condition"] == "Fresh live"


def test_auto_update_failure_cooldown_uses_cache(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)
    stale = stable_weather("Home", condition="Old cache")
    stale["fetched_at"] = "2026-01-01T00:00:00"
    weather.save_weather_cache("Home", stale, db_path=db_path)
    db.set_setting(weather.AUTO_REFRESH_FAILURE_KEY, weather._now_iso(), db_path=db_path)

    def fail_refresh(*args, **kwargs):
        raise AssertionError("cooldown must prevent refresh")

    monkeypatch.setattr(weather, "refresh_weather_for_location", fail_refresh)
    result = weather.auto_update_weather(db_path=db_path, config=AppConfig(weather=WeatherConfig(refresh_minutes=1)))

    assert result["condition"] == "Old cache"
    assert result["message"] == "Weather refresh recently failed. Using cached weather."


def test_all_providers_fail_and_no_cache_returns_unavailable(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jiri.db")
    loc = weather.set_coordinates("Home", 26.1167, 88.85, db_path=db_path)

    def fail_provider(location, timeout_seconds=3):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(weather, "fetch_open_meteo_weather", fail_provider)
    monkeypatch.setattr(weather, "fetch_wttr_weather", fail_provider)
    result = weather.refresh_weather_for_location({**loc, "source": "settings"}, db_path=db_path)
    assert result["available"] is False
    assert result["source"] == "unavailable"
    assert result["message"] == "Weather unavailable. I will try again later."


def geo_result(name, latitude=26.1167, longitude=88.85, country="Bangladesh", country_code="BD", admin3="Panchagarh Sadar"):
    return {
        "id": 1,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "Asia/Dhaka",
        "country": country,
        "country_code": country_code,
        "admin1": "Rangpur Division",
        "admin2": "Panchagarh District",
        "admin3": admin3,
        "admin4": "Local Area",
        "population": 50000,
    }


def location():
    return {
        "name": "Home",
        "latitude": 26.1167,
        "longitude": 88.85,
        "country": "Bangladesh",
        "country_code": "BD",
        "admin1": "Rangpur Division",
        "admin2": "Panchagarh District",
    }


def open_meteo_payload():
    return {
        "current": {
            "time": "2026-05-15T03:00",
            "temperature_2m": 31.0,
            "relative_humidity_2m": 70,
            "apparent_temperature": 35.0,
            "precipitation": 0.0,
            "rain": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 12.0,
        },
        "hourly": {
            "time": ["2026-05-15T03:00", "2026-05-15T04:00"],
            "temperature_2m": [31.0, 31.5],
            "precipitation_probability": [35, 40],
            "rain": [0.0, 0.2],
            "relative_humidity_2m": [70, 71],
            "weather_code": [2, 3],
        },
        "daily": {
            "time": ["2026-05-15", "2026-05-16"],
            "weather_code": [95, 61],
            "temperature_2m_max": [34.0, 32.0],
            "temperature_2m_min": [26.0, 25.0],
            "precipitation_probability_max": [80, 55],
            "rain_sum": [8.0, 4.0],
        },
    }


def stable_weather(location_name="Home", source="open_meteo", condition="Partly cloudy"):
    return {
        "available": True,
        "source": source,
        "location": location_name,
        "temperature_c": 31.0,
        "feels_like_c": 35.0,
        "condition": condition,
        "humidity": 70,
        "rain_chance": 40,
        "wind_kmh": 12.0,
        "fetched_at": datetime.now().replace(microsecond=0).isoformat(),
        "raw_json": '{"ok":true}',
        "message": "Weather online.",
    }
