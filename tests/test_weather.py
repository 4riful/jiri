from __future__ import annotations

from jiri.weather import get_weather


def test_stage_one_weather_is_unavailable_without_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    snapshot = get_weather(db_path=str(tmp_path / "jiri.db"))
    assert snapshot.unavailable is True
    assert "Stage 2" in snapshot.condition
