from __future__ import annotations

from datetime import datetime, timedelta
import json
import time
from typing import Any

import requests

from . import db
from .config import AppConfig, load_config


OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WTTR_URL = "https://wttr.in/{latitude},{longitude}?format=j2"

LOCATION_SETTING_KEYS = (
    "weather.location_name",
    "weather.latitude",
    "weather.longitude",
    "weather.timezone",
    "weather.country",
    "weather.country_code",
    "weather.admin1",
    "weather.admin2",
    "weather.admin3",
    "weather.admin4",
)

RECENT_LOCATIONS_KEY = "weather.recent_locations_json"
RECENT_LOCATION_LIMIT = 8
AUTO_REFRESH_FAILURE_KEY = "weather.auto_refresh_failed_at"
AUTO_REFRESH_RETRY_MINUTES = 5

WEATHER_CODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def search_locations(query: str, country: str | None = None, timeout_seconds: int = 3) -> list[dict[str, object]]:
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Location search query cannot be empty")
    response = requests.get(
        OPEN_METEO_GEOCODING_URL,
        params={"name": clean_query, "count": 10, "language": "en", "format": "json"},
        timeout=_safe_timeout(timeout_seconds),
    )
    response.raise_for_status()
    raw = response.json()
    results = [_normalize_location_result(item) for item in raw.get("results", []) if isinstance(item, dict)]
    if country:
        preferred = country.strip().upper()
        results.sort(key=lambda item: 0 if str(item.get("country_code", "")).upper() == preferred else 1)
    return results


def save_last_location_search(results: list[dict[str, object]], db_path: str | None = None) -> None:
    db.set_setting("weather.last_location_search_json", json.dumps(results, separators=(",", ":"), sort_keys=True), db_path=db_path)


def get_last_location_search(db_path: str | None = None) -> list[dict[str, object]]:
    raw = db.get_setting("weather.last_location_search_json", db_path=db_path)
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Last location search is corrupted. Run location search again.") from exc
    if not isinstance(decoded, list):
        raise ValueError("Last location search is invalid. Run location search again.")
    return [item for item in decoded if isinstance(item, dict)]


def select_location(index: int, db_path: str | None = None) -> dict[str, object]:
    results = get_last_location_search(db_path=db_path)
    if not results:
        raise ValueError("No saved location search. Run location search first.")
    if index < 1 or index > len(results):
        raise ValueError(f"Location index must be between 1 and {len(results)}")
    selected = results[index - 1]
    save_selected_location(selected, db_path=db_path)
    return selected


def select_recent_location(index: int, db_path: str | None = None) -> dict[str, object]:
    results = get_recent_locations(db_path=db_path)
    if not results:
        raise ValueError("No recent weather locations saved yet.")
    if index < 1 or index > len(results):
        raise ValueError(f"Recent location index must be between 1 and {len(results)}")
    selected = results[index - 1]
    save_selected_location(selected, db_path=db_path)
    return selected


def save_selected_location(location: dict[str, object], db_path: str | None = None) -> None:
    lat = _required_float(location.get("latitude"), "latitude")
    lon = _required_float(location.get("longitude"), "longitude")
    _validate_coordinates(lat, lon)
    values = {
        "weather.location_name": str(location.get("name") or location.get("location_name") or "Selected location"),
        "weather.latitude": str(lat),
        "weather.longitude": str(lon),
        "weather.timezone": str(location.get("timezone") or ""),
        "weather.country": str(location.get("country") or ""),
        "weather.country_code": str(location.get("country_code") or ""),
        "weather.admin1": str(location.get("admin1") or ""),
        "weather.admin2": str(location.get("admin2") or ""),
        "weather.admin3": str(location.get("admin3") or ""),
        "weather.admin4": str(location.get("admin4") or ""),
    }
    for key, value in values.items():
        db.set_setting(key, value, db_path=db_path)
    save_recent_location(location, db_path=db_path)


def get_recent_locations(db_path: str | None = None) -> list[dict[str, object]]:
    raw = db.get_setting(RECENT_LOCATIONS_KEY, db_path=db_path)
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    locations: list[dict[str, object]] = []
    for item in decoded:
        if isinstance(item, dict) and item.get("latitude") is not None and item.get("longitude") is not None:
            locations.append(item)
    return locations[:RECENT_LOCATION_LIMIT]


def save_recent_location(location: dict[str, object], db_path: str | None = None) -> None:
    normalized = _normalize_saved_location(location)
    recent = [item for item in get_recent_locations(db_path=db_path) if _location_key(item) != _location_key(normalized)]
    db.set_setting(
        RECENT_LOCATIONS_KEY,
        json.dumps([normalized, *recent][:RECENT_LOCATION_LIMIT], separators=(",", ":"), sort_keys=True),
        db_path=db_path,
    )


def set_coordinates(name: str, latitude: float, longitude: float, db_path: str | None = None) -> dict[str, object]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Location name cannot be empty")
    _validate_coordinates(latitude, longitude)
    location = {
        "name": clean_name,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "timezone": "",
        "country": "",
        "country_code": "",
        "admin1": "",
        "admin2": "",
        "admin3": "",
        "admin4": "",
    }
    save_selected_location(location, db_path=db_path)
    return location


def get_active_location(db_path: str | None = None, config: AppConfig | None = None) -> dict[str, object] | None:
    cfg = config or load_config()
    lat = db.get_setting("weather.latitude", db_path=db_path)
    lon = db.get_setting("weather.longitude", db_path=db_path)
    if lat is not None and lon is not None:
        location = _settings_location(db_path=db_path)
        location["source"] = "settings"
        return location
    if cfg.weather.latitude is not None and cfg.weather.longitude is not None:
        return {
            "source": "config",
            "name": cfg.weather.location,
            "latitude": cfg.weather.latitude,
            "longitude": cfg.weather.longitude,
            "timezone": "",
            "country": "",
            "country_code": "",
            "admin1": "",
            "admin2": "",
            "admin3": "",
            "admin4": "",
        }
    return None


def fetch_open_meteo_weather(location: dict[str, object], timeout_seconds: int = 3) -> dict[str, object]:
    if load_config().weather.fake:
        return _fake_open_meteo_weather(location)
    lat = _required_float(location.get("latitude"), "latitude")
    lon = _required_float(location.get("longitude"), "longitude")
    response = requests.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,rain,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,rain,relative_humidity_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,rain_sum",
            "timezone": "auto",
            "forecast_days": 7,
        },
        timeout=_safe_timeout(timeout_seconds),
    )
    response.raise_for_status()
    return _parse_open_meteo_response(location, response.json())


def fetch_wttr_weather(location: dict[str, object], timeout_seconds: int = 3) -> dict[str, object]:
    lat = _required_float(location.get("latitude"), "latitude")
    lon = _required_float(location.get("longitude"), "longitude")
    response = requests.get(WTTR_URL.format(latitude=lat, longitude=lon), timeout=_safe_timeout(timeout_seconds))
    response.raise_for_status()
    return _parse_wttr_response(location, response.json())


def get_cached_weather(location_name: str | None = None, db_path: str | None = None) -> dict[str, object] | None:
    db.init_db(db_path)
    params: tuple[object, ...] = ()
    where = ""
    if location_name:
        where = "WHERE location = ?"
        params = (location_name,)
    with db.connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT * FROM weather_cache
            {where}
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if row is None:
        return None
    data = _base_weather(str(row["location"]), "cache")
    data.update(
        {
            "available": True,
            "temperature_c": row["temperature_c"],
            "condition": row["condition"] or "Weather cached.",
            "humidity": row["humidity"],
            "rain_chance": row["rain_chance"],
            "fetched_at": row["fetched_at"],
            "raw_json": row["raw_json"],
            "message": "Using cached weather.",
        }
    )
    try:
        cached_raw = json.loads(row["raw_json"] or "{}")
    except json.JSONDecodeError:
        cached_raw = {}
    if isinstance(cached_raw, dict):
        cache_extra = cached_raw.get("_jiri_cache")
        if isinstance(cache_extra, dict):
            _apply_cached_extra(data, cache_extra)
        _apply_cached_extra(data, cached_raw)
        _hydrate_provider_cache_fields(data, cached_raw)
    return data


def save_weather_cache(location_name: str, weather_data: dict[str, object], db_path: str | None = None) -> dict[str, object]:
    clean_location = location_name.strip() or str(weather_data.get("location") or "Selected location")
    fetched_at = str(weather_data.get("fetched_at") or _now_iso())
    extra = {
        "feels_like_c": weather_data.get("feels_like_c"),
        "wind_kmh": weather_data.get("wind_kmh"),
        "location_meta": weather_data.get("location_meta"),
        "hourly_forecast": weather_data.get("hourly_forecast"),
        "daily_forecast": weather_data.get("daily_forecast"),
    }
    raw_json = _cache_raw_json(weather_data.get("raw_json"), extra)

    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO weather_cache(location, fetched_at, temperature_c, condition, humidity, rain_chance, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_location,
                fetched_at,
                _optional_float(weather_data.get("temperature_c")),
                weather_data.get("condition"),
                _optional_int(weather_data.get("humidity")),
                _optional_int(weather_data.get("rain_chance")),
                raw_json,
            ),
        )
    cached = get_cached_weather(clean_location, db_path=db_path)
    assert cached is not None
    return cached


def _cache_raw_json(raw_json: object, extra: dict[str, object]) -> str:
    if raw_json is None:
        return json.dumps(extra, separators=(",", ":"), sort_keys=True)
    if isinstance(raw_json, str):
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return raw_json
    else:
        payload = raw_json
    if isinstance(payload, dict):
        enriched = dict(payload)
        enriched["_jiri_cache"] = extra
        return json.dumps(enriched, separators=(",", ":"), sort_keys=True)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _apply_cached_extra(data: dict[str, object], cached_raw: dict[str, object]) -> None:
    for key in ("feels_like_c", "wind_kmh"):
        if key in cached_raw and cached_raw[key] is not None:
            data[key] = cached_raw[key]
    location_meta = cached_raw.get("location_meta")
    if isinstance(location_meta, dict):
        data["location_meta"] = location_meta
    hourly = cached_raw.get("hourly_forecast")
    if isinstance(hourly, list):
        data["hourly_forecast"] = _normalize_hourly_rows(hourly[:24])
    daily = cached_raw.get("daily_forecast")
    if isinstance(daily, list):
        data["daily_forecast"] = daily[:7]


def _hydrate_provider_cache_fields(data: dict[str, object], cached_raw: dict[str, object]) -> None:
    current = cached_raw.get("current")
    if isinstance(current, dict):
        if data.get("feels_like_c") is None:
            data["feels_like_c"] = _optional_float(current.get("apparent_temperature"))
        if data.get("wind_kmh") is None:
            data["wind_kmh"] = _optional_float(current.get("wind_speed_10m"))
        if not data.get("hourly_forecast"):
            data["hourly_forecast"] = _open_meteo_hourly_forecast(cached_raw)
        if not data.get("daily_forecast"):
            data["daily_forecast"] = _open_meteo_daily_forecast(cached_raw)

    wttr_current = _first(cached_raw.get("current_condition"))
    if isinstance(wttr_current, dict):
        if data.get("feels_like_c") is None:
            data["feels_like_c"] = _optional_float(wttr_current.get("FeelsLikeC"))
        if data.get("wind_kmh") is None:
            data["wind_kmh"] = _optional_float(wttr_current.get("windspeedKmph"))
        if not data.get("hourly_forecast"):
            data["hourly_forecast"] = _wttr_hourly_forecast(cached_raw)
        if not data.get("daily_forecast"):
            data["daily_forecast"] = _wttr_daily_forecast(cached_raw)


def refresh_weather(db_path: str | None = None) -> dict[str, object]:
    cfg = load_config()
    location = get_active_location(db_path=db_path, config=cfg)
    if location is None:
        return unavailable_weather(
            "No weather location selected",
            "No weather coordinates selected. Run: python -m jiri.cli location search \"your place\" --country BD; python -m jiri.cli location set 1",
        )
    return refresh_weather_for_location(location, timeout_seconds=cfg.weather.timeout_seconds, db_path=db_path)


def get_weather(db_path: str | None = None) -> dict[str, object]:
    cfg = load_config()
    location = get_active_location(db_path=db_path, config=cfg)
    if location is None:
        return unavailable_weather("No weather location selected", "No weather coordinates selected.")
    cached = get_cached_weather(_location_label(location), db_path=db_path)
    if cached is not None and not _is_stale(str(cached["fetched_at"]), cfg.weather.refresh_minutes):
        return cached
    return refresh_weather_for_location(location, timeout_seconds=cfg.weather.timeout_seconds, db_path=db_path)


def peek_weather(db_path: str | None = None, config: AppConfig | None = None) -> dict[str, object]:
    cfg = config or load_config()
    location = get_active_location(db_path=db_path, config=cfg)
    if location is None:
        return unavailable_weather("No weather location selected", "No weather coordinates selected.")
    label = _location_label(location)
    cached = get_cached_weather(label, db_path=db_path)
    if cached is not None:
        return cached
    return unavailable_weather(label, "Weather not cached yet.")


def auto_update_weather(db_path: str | None = None, config: AppConfig | None = None) -> dict[str, object]:
    cfg = config or load_config()
    location = get_active_location(db_path=db_path, config=cfg)
    if location is None:
        return unavailable_weather("No weather location selected", "No weather coordinates selected.")

    label = _location_label(location)
    cached = get_cached_weather(label, db_path=db_path)
    if cached is not None and not _is_stale(str(cached["fetched_at"]), cfg.weather.refresh_minutes):
        return cached

    failed_at = db.get_setting(AUTO_REFRESH_FAILURE_KEY, db_path=db_path)
    if failed_at and not _is_stale(failed_at, AUTO_REFRESH_RETRY_MINUTES):
        if cached is not None:
            fallback = dict(cached)
            fallback["message"] = "Weather refresh recently failed. Using cached weather."
            return fallback
        return unavailable_weather(label, "Weather refresh recently failed. I will retry later.")

    result = refresh_weather_for_location(location, timeout_seconds=cfg.weather.timeout_seconds, db_path=db_path)
    if result.get("available") is False:
        db.set_setting(AUTO_REFRESH_FAILURE_KEY, _now_iso(), db_path=db_path)
    else:
        db.set_setting(AUTO_REFRESH_FAILURE_KEY, "", db_path=db_path)
    return result


def refresh_weather_for_location(location: dict[str, object], timeout_seconds: int = 3, db_path: str | None = None) -> dict[str, object]:
    label = _location_label(location)
    cached = get_cached_weather(label, db_path=db_path)
    try:
        live = fetch_open_meteo_weather(location, timeout_seconds=timeout_seconds)
    except (requests.RequestException, ValueError, json.JSONDecodeError, KeyError, TypeError):
        try:
            live = fetch_wttr_weather(location, timeout_seconds=timeout_seconds)
        except (requests.RequestException, ValueError, json.JSONDecodeError, KeyError, TypeError):
            if cached is not None:
                fallback = dict(cached)
                fallback["source"] = "cache"
                fallback["message"] = "Weather offline. Using cached weather."
                return fallback
            return unavailable_weather(label, "Weather unavailable. I will try again later.")
    save_weather_cache(label, live, db_path=db_path)
    return live


def test_providers(db_path: str | None = None) -> list[dict[str, object]]:
    location = get_active_location(db_path=db_path)
    if location is None:
        raise ValueError("No weather coordinates selected. Run location search/set first.")
    providers = (("Open-Meteo", fetch_open_meteo_weather), ("wttr.in", fetch_wttr_weather))
    results = []
    for name, func in providers:
        start = time.perf_counter()
        try:
            weather = func(location, timeout_seconds=3)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            results.append(
                {
                    "provider": name,
                    "ok": True,
                    "response_ms": elapsed_ms,
                    "temperature_c": weather.get("temperature_c"),
                    "condition": weather.get("condition"),
                    "error": "",
                }
            )
        except Exception as exc:  # diagnostic command must report provider errors, not crash
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            results.append(
                {
                    "provider": name,
                    "ok": False,
                    "response_ms": elapsed_ms,
                    "temperature_c": None,
                    "condition": None,
                    "error": str(exc),
                }
            )
    return results


def unavailable_weather(location: str, message: str = "Weather unavailable.") -> dict[str, object]:
    data = _base_weather(location, "unavailable")
    data.update({"available": False, "message": message})
    return data


def format_location_result(index: int, item: dict[str, object]) -> str:
    country_code = str(item.get("country_code") or "")
    bd = country_code.upper() == "BD"
    labels = (
        ("Division" if bd else "Region/Admin1", item.get("admin1")),
        ("District" if bd else "District/Admin2", item.get("admin2")),
        ("Upazila/Subdistrict" if bd else "Admin3", item.get("admin3")),
        ("Local area" if bd else "Admin4", item.get("admin4")),
    )
    parts = [f"{index}. {item.get('name')}"]
    for label, value in labels:
        if value:
            parts.append(f"{label}: {value}")
    parts.extend(
        [
            f"Country: {item.get('country') or 'unknown'} ({country_code or 'unknown'})",
            f"Lat/Lon: {item.get('latitude')}, {item.get('longitude')}",
            f"Timezone: {item.get('timezone') or 'unknown'}",
        ]
    )
    if item.get("population") is not None:
        parts.append(f"Population: {item.get('population')}")
    return " | ".join(parts)


def format_active_location(location: dict[str, object] | None) -> str:
    if location is None:
        return "No active weather location. Run: python -m jiri.cli location search \"your place\" --country BD"
    lines = [
        f"source: {location.get('source')}",
        f"name: {location.get('name')}",
        f"country: {location.get('country') or 'unknown'} ({location.get('country_code') or 'unknown'})",
        f"division/region: {location.get('admin1') or 'unknown'}",
        f"district: {location.get('admin2') or 'unknown'}",
        f"coordinates: {location.get('latitude')}, {location.get('longitude')}",
        f"timezone: {location.get('timezone') or 'unknown'}",
    ]
    return "\n".join(lines)


def _parse_open_meteo_response(location: dict[str, object], raw: dict[str, Any]) -> dict[str, object]:
    current = raw.get("current")
    if not isinstance(current, dict):
        raise ValueError("Open-Meteo response missing current weather")
    daily = raw.get("daily") if isinstance(raw.get("daily"), dict) else {}
    rain_chance = _first_number(daily.get("precipitation_probability_max"))
    if rain_chance is None and isinstance(raw.get("hourly"), dict):
        rain_chance = _first_number(raw["hourly"].get("precipitation_probability"))
    hourly = _open_meteo_hourly_forecast(raw)
    data = _base_weather(_location_label(location), "open_meteo")
    data.update(
        {
            "available": True,
            "temperature_c": _optional_float(current.get("temperature_2m")),
            "feels_like_c": _optional_float(current.get("apparent_temperature")),
            "condition": WEATHER_CODE_MAP.get(_optional_int(current.get("weather_code")), "Unknown"),
            "humidity": _optional_int(current.get("relative_humidity_2m")),
            "rain_chance": _optional_int(rain_chance),
            "wind_kmh": _optional_float(current.get("wind_speed_10m")),
            "hourly_forecast": _slice_from_now(hourly, current.get("time")),
            "daily_forecast": _open_meteo_daily_forecast(raw),
            "fetched_at": _now_iso(),
            "raw_json": json.dumps(raw, separators=(",", ":"), sort_keys=True),
            "location_meta": _location_meta(location),
            "message": "Weather online.",
        }
    )
    return data


def _parse_wttr_response(location: dict[str, object], raw: dict[str, Any]) -> dict[str, object]:
    current = _first(raw.get("current_condition"))
    if not isinstance(current, dict):
        raise ValueError("wttr response missing current_condition")
    desc = _first(current.get("weatherDesc"))
    condition = str(desc.get("value")) if isinstance(desc, dict) and desc.get("value") else "Unknown"
    data = _base_weather(_location_label(location), "wttr")
    data.update(
        {
            "available": True,
            "temperature_c": _optional_float(current.get("temp_C")),
            "feels_like_c": _optional_float(current.get("FeelsLikeC")),
            "condition": condition,
            "humidity": _optional_int(current.get("humidity")),
            "rain_chance": _optional_int(_wttr_rain_chance(raw)),
            "wind_kmh": _optional_float(current.get("windspeedKmph")),
            "hourly_forecast": _wttr_hourly_forecast(raw),
            "daily_forecast": _wttr_daily_forecast(raw),
            "fetched_at": _now_iso(),
            "raw_json": json.dumps(raw, separators=(",", ":"), sort_keys=True),
            "location_meta": _location_meta(location),
            "message": "Weather online.",
        }
    )
    return data


def _fake_open_meteo_weather(location: dict[str, object]) -> dict[str, object]:
    data = _base_weather(_location_label(location), "open_meteo")
    data.update(
        {
            "available": True,
            "temperature_c": 31.0,
            "feels_like_c": 35.0,
            "condition": "Fake partly cloudy",
            "humidity": 70,
            "rain_chance": 20,
            "wind_kmh": 12.0,
            "hourly_forecast": _fake_hourly_forecast(),
            "daily_forecast": _fake_daily_forecast(),
            "fetched_at": _now_iso(),
            "raw_json": json.dumps({"fake": True}, separators=(",", ":"), sort_keys=True),
            "location_meta": _location_meta(location),
            "message": "Weather online.",
        }
    )
    return data


def _normalize_location_result(item: dict[str, Any]) -> dict[str, object]:
    return {
        "id": item.get("id"),
        "name": str(item.get("name") or "Unknown"),
        "latitude": _required_float(item.get("latitude"), "latitude"),
        "longitude": _required_float(item.get("longitude"), "longitude"),
        "timezone": str(item.get("timezone") or ""),
        "country": str(item.get("country") or ""),
        "country_code": str(item.get("country_code") or ""),
        "admin1": str(item.get("admin1") or ""),
        "admin2": str(item.get("admin2") or ""),
        "admin3": str(item.get("admin3") or ""),
        "admin4": str(item.get("admin4") or ""),
        "population": item.get("population"),
    }


def _normalize_saved_location(location: dict[str, object]) -> dict[str, object]:
    lat = _required_float(location.get("latitude"), "latitude")
    lon = _required_float(location.get("longitude"), "longitude")
    _validate_coordinates(lat, lon)
    return {
        "name": str(location.get("name") or location.get("location_name") or "Selected location"),
        "latitude": lat,
        "longitude": lon,
        "timezone": str(location.get("timezone") or ""),
        "country": str(location.get("country") or ""),
        "country_code": str(location.get("country_code") or ""),
        "admin1": str(location.get("admin1") or ""),
        "admin2": str(location.get("admin2") or ""),
        "admin3": str(location.get("admin3") or ""),
        "admin4": str(location.get("admin4") or ""),
    }


def _location_key(location: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(location.get("name") or "").strip().lower(),
        f"{_required_float(location.get('latitude'), 'latitude'):.5f}",
        f"{_required_float(location.get('longitude'), 'longitude'):.5f}",
    )


def _settings_location(db_path: str | None = None) -> dict[str, object]:
    return {
        "name": db.get_setting("weather.location_name", db_path=db_path) or "Selected location",
        "latitude": _required_float(db.get_setting("weather.latitude", db_path=db_path), "latitude"),
        "longitude": _required_float(db.get_setting("weather.longitude", db_path=db_path), "longitude"),
        "timezone": db.get_setting("weather.timezone", db_path=db_path) or "",
        "country": db.get_setting("weather.country", db_path=db_path) or "",
        "country_code": db.get_setting("weather.country_code", db_path=db_path) or "",
        "admin1": db.get_setting("weather.admin1", db_path=db_path) or "",
        "admin2": db.get_setting("weather.admin2", db_path=db_path) or "",
        "admin3": db.get_setting("weather.admin3", db_path=db_path) or "",
        "admin4": db.get_setting("weather.admin4", db_path=db_path) or "",
    }


def _base_weather(location: str, source: str) -> dict[str, object]:
    return {
        "available": True,
        "source": source,
        "location": location,
        "temperature_c": None,
        "feels_like_c": None,
        "condition": "Unavailable",
        "humidity": None,
        "rain_chance": None,
        "wind_kmh": None,
        "hourly_forecast": [],
        "daily_forecast": [],
        "fetched_at": None,
        "raw_json": None,
        "location_meta": None,
        "message": "Weather online.",
    }


def _open_meteo_hourly_forecast(raw: dict[str, Any], limit: int = 24) -> list[dict[str, object]]:
    hourly = raw.get("hourly")
    if not isinstance(hourly, dict):
        return []
    times = hourly.get("time")
    if not isinstance(times, list):
        return []
    rows: list[dict[str, object]] = []
    temperatures = hourly.get("temperature_2m") if isinstance(hourly.get("temperature_2m"), list) else []
    rain_prob = hourly.get("precipitation_probability") if isinstance(hourly.get("precipitation_probability"), list) else []
    rain = hourly.get("rain") if isinstance(hourly.get("rain"), list) else []
    humidity = hourly.get("relative_humidity_2m") if isinstance(hourly.get("relative_humidity_2m"), list) else []
    codes = hourly.get("weather_code") if isinstance(hourly.get("weather_code"), list) else []
    for index, timestamp in enumerate(times[:limit]):
        code = _at_int(codes, index)
        condition = WEATHER_CODE_MAP.get(code, "")
        rows.append(
            {
                "time": _format_hour_12(timestamp),
                "timestamp": str(timestamp),
                "temperature_c": _at_float(temperatures, index),
                "rain_chance": _at_int(rain_prob, index),
                "rain_mm": _at_float(rain, index),
                "humidity": _at_int(humidity, index),
                "condition": condition,
                "icon": _weather_icon_from_code(code),
            }
        )
    return rows


def _open_meteo_daily_forecast(raw: dict[str, Any], limit: int = 7) -> list[dict[str, object]]:
    daily = raw.get("daily")
    if not isinstance(daily, dict):
        return []
    dates = daily.get("time") if isinstance(daily.get("time"), list) else []
    highs = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
    lows = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
    rain_prob = daily.get("precipitation_probability_max") if isinstance(daily.get("precipitation_probability_max"), list) else []
    rain = daily.get("rain_sum") if isinstance(daily.get("rain_sum"), list) else []
    codes = daily.get("weather_code") if isinstance(daily.get("weather_code"), list) else []
    rows: list[dict[str, object]] = []
    for index in range(min(limit, len(dates) or max(len(highs), len(lows), len(rain_prob), len(rain), len(codes)))):
        date = str(dates[index]) if index < len(dates) else ""
        rows.append(
            {
                "day": "Today" if index == 0 else _short_weekday(date),
                "date": date,
                "high_c": _at_float(highs, index),
                "low_c": _at_float(lows, index),
                "rain_chance": _at_int(rain_prob, index),
                "rain_mm": _at_float(rain, index),
                "condition": WEATHER_CODE_MAP.get(_at_int(codes, index), ""),
            }
        )
    return rows


def _wttr_hourly_forecast(raw: dict[str, Any], limit: int = 24) -> list[dict[str, object]]:
    days = raw.get("weather")
    if not isinstance(days, list):
        return []
    rows: list[dict[str, object]] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        date = str(day.get("date") or "")
        hourly = day.get("hourly")
        if not isinstance(hourly, list):
            continue
        for item in hourly:
            if not isinstance(item, dict):
                continue
            desc = _first(item.get("weatherDesc"))
            condition = str(desc.get("value")) if isinstance(desc, dict) and desc.get("value") else ""
            rows.append(
                {
                    "time": _wttr_hour(date, item.get("time")),
                    "temperature_c": _optional_float(item.get("tempC")),
                    "rain_chance": _optional_int(item.get("chanceofrain")),
                    "rain_mm": _optional_float(item.get("precipMM")),
                    "humidity": _optional_int(item.get("humidity")),
                    "condition": condition,
                    "icon": _weather_icon_from_condition(condition),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def _wttr_daily_forecast(raw: dict[str, Any], limit: int = 7) -> list[dict[str, object]]:
    days = raw.get("weather")
    if not isinstance(days, list):
        return []
    rows: list[dict[str, object]] = []
    for index, day in enumerate(days[:limit]):
        if not isinstance(day, dict):
            continue
        hourly = day.get("hourly") if isinstance(day.get("hourly"), list) else []
        first_hour = _first(hourly)
        desc = _first(first_hour.get("weatherDesc")) if isinstance(first_hour, dict) else None
        date = str(day.get("date") or "")
        rows.append(
            {
                "day": "Today" if index == 0 else _short_weekday(date),
                "date": date,
                "high_c": _optional_float(day.get("maxtempC")),
                "low_c": _optional_float(day.get("mintempC")),
                "rain_chance": _optional_int(_wttr_day_rain_chance(day)),
                "rain_mm": _wttr_day_rain_mm(day),
                "condition": str(desc.get("value")) if isinstance(desc, dict) and desc.get("value") else "",
            }
        )
    return rows


def _slice_from_now(hourly: list[dict[str, object]], current_time: object | None = None) -> list[dict[str, object]]:
    if current_time is not None:
        try:
            current = datetime.fromisoformat(str(current_time)).replace(minute=0, second=0, microsecond=0)
        except ValueError:
            current = None
        if current is not None:
            for index, row in enumerate(hourly):
                try:
                    timestamp = datetime.fromisoformat(str(row.get("timestamp"))).replace(minute=0, second=0, microsecond=0)
                except ValueError:
                    continue
                if timestamp >= current:
                    return hourly[index:]
    now_hour = datetime.now().hour
    if 0 <= now_hour < len(hourly):
        return hourly[now_hour:]
    return hourly


def _normalize_hourly_rows(rows: list[object]) -> list[dict[str, object]]:
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["time"] = _format_hour_12(item.get("time"))
        if not item.get("icon"):
            item["icon"] = _weather_icon_from_condition(str(item.get("condition") or ""))
        normalized.append(item)
    return normalized


def _fake_hourly_forecast() -> list[dict[str, object]]:
    temps = [31.0, 32.0, 33.0, 33.0, 32.0, 31.0, 30.0, 29.0, 28.0, 28.0, 27.0, 27.0]
    rain = [10, 15, 30, 65, 80, 55, 35, 25, 20, 15, 10, 10]
    rows = []
    for index, temp in enumerate(temps):
        timestamp = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=index)
        condition = "Fake rain" if rain[index] >= 60 else "Fake partly cloudy"
        rows.append(
            {
                "time": _format_hour_12(timestamp.isoformat()),
                "temperature_c": temp,
                "rain_chance": rain[index],
                "rain_mm": 0.0,
                "humidity": 70,
                "condition": condition,
                "icon": _weather_icon_from_condition(condition),
            }
        )
    return rows


def _fake_daily_forecast() -> list[dict[str, object]]:
    rows = [
        ("Today", "Fake rain", 26.0, 34.0, 80),
        ("Sat", "Fake showers", 25.0, 32.0, 55),
        ("Sun", "Fake cloudy", 26.0, 33.0, 35),
        ("Mon", "Fake partly cloudy", 27.0, 35.0, 20),
        ("Tue", "Fake rain", 25.0, 31.0, 65),
        ("Wed", "Fake showers", 24.0, 30.0, 45),
        ("Thu", "Fake cloudy", 25.0, 32.0, 30),
    ]
    return [
        {"day": day, "date": "", "condition": condition, "low_c": low, "high_c": high, "rain_chance": rain, "rain_mm": 0.0}
        for day, condition, low, high, rain in rows
    ]


def _format_hour_12(value: object) -> str:
    text = str(value)
    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        pass
    if parsed is None:
        time_text = text.split(" ", 1)[-1]
        if "T" in time_text:
            time_text = time_text.split("T", 1)[1]
        try:
            parsed = datetime.strptime(time_text[:5], "%H:%M")
        except ValueError:
            return text
    return parsed.strftime("%I:%M %p").lstrip("0").lower()


def _weather_icon_from_code(code: int | None) -> str:
    if code is None:
        return "cloud"
    if code in {0, 1}:
        return "sun"
    if code in {2, 3}:
        return "cloud"
    if code in {45, 48}:
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77:
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


def _weather_icon_from_condition(condition: str) -> str:
    text = condition.lower()
    if any(word in text for word in ("thunder", "storm")):
        return "storm"
    if "snow" in text:
        return "snow"
    if any(word in text for word in ("rain", "drizzle", "shower")):
        return "rain"
    if any(word in text for word in ("fog", "mist", "haze")):
        return "fog"
    if any(word in text for word in ("clear", "sunny")):
        return "sun"
    return "cloud"


def _short_weekday(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%a")
    except ValueError:
        return str(value)[:3] or "Day"


def _wttr_hour(date: str, value: object) -> str:
    digits = str(value or "0").zfill(4)
    text = f"{date}T{digits[:-2]}:{digits[-2:]}" if date else f"{digits[:-2]}:{digits[-2:]}"
    return _format_hour_12(text)


def _at_float(values: object, index: int) -> float | None:
    if isinstance(values, list) and index < len(values):
        return _optional_float(values[index])
    return None


def _at_int(values: object, index: int) -> int | None:
    if isinstance(values, list) and index < len(values):
        return _optional_int(values[index])
    return None


def _location_meta(location: dict[str, object]) -> dict[str, object]:
    return {
        "name": location.get("name") or location.get("location_name") or "Selected location",
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "timezone": location.get("timezone") or "",
        "country": location.get("country") or "",
        "country_code": location.get("country_code") or "",
        "admin1": location.get("admin1") or "",
        "admin2": location.get("admin2") or "",
        "admin3": location.get("admin3") or "",
        "admin4": location.get("admin4") or "",
    }


def _location_label(location: dict[str, object]) -> str:
    name = str(location.get("name") or location.get("location_name") or "Selected location")
    country = str(location.get("country") or "")
    if country and country.lower() not in name.lower():
        return f"{name}, {country}"
    return name


def location_label(location: dict[str, object]) -> str:
    return _location_label(location)


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180")


def _safe_timeout(timeout_seconds: int) -> int:
    if timeout_seconds > 3:
        return 3
    if timeout_seconds <= 0:
        return 1
    return timeout_seconds


def _is_stale(fetched_at: str, max_age_minutes: int) -> bool:
    if max_age_minutes <= 0:
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    return datetime.now() - fetched >= timedelta(minutes=max_age_minutes)


def _wttr_rain_chance(raw: dict[str, Any]) -> object | None:
    weather = _first(raw.get("weather"))
    if not isinstance(weather, dict):
        return None
    hourly = _first(weather.get("hourly"))
    if not isinstance(hourly, dict):
        return None
    return hourly.get("chanceofrain")


def _wttr_day_rain_chance(day: dict[str, Any]) -> object | None:
    hourly = day.get("hourly")
    if not isinstance(hourly, list):
        return None
    chances = [_optional_int(item.get("chanceofrain")) for item in hourly if isinstance(item, dict)]
    real = [value for value in chances if value is not None]
    return max(real) if real else None


def _wttr_day_rain_mm(day: dict[str, Any]) -> float | None:
    hourly = day.get("hourly")
    if not isinstance(hourly, list):
        return None
    values = [_optional_float(item.get("precipMM")) for item in hourly if isinstance(item, dict)]
    real = [value for value in values if value is not None]
    return round(sum(real), 2) if real else None


def _first(value: object) -> object | None:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _first_number(value: object) -> object | None:
    first = _first(value)
    return first if first is not None else value


def _required_float(value: object, name: str) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"Weather {name} is required")
    return parsed


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
