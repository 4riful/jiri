from __future__ import annotations

from datetime import datetime

import pytest

from jiri import water


def test_water_add_goal_and_progress(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    water.set_goal(2500, db_path=db_path, now=datetime(2026, 5, 15, 9, 0, 0))
    snapshot = water.add_water(500, db_path=db_path, now=datetime(2026, 5, 15, 10, 0, 0))

    assert snapshot["goal_ml"] == 2500
    assert snapshot["progress_ml"] == 500
    assert snapshot["remaining_ml"] == 2000
    assert snapshot["percent"] == 20


def test_water_resets_on_new_day(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    water.add_water(500, db_path=db_path, now=datetime(2026, 5, 15, 10, 0, 0))
    snapshot = water.water_snapshot(db_path=db_path, now=datetime(2026, 5, 16, 0, 1, 0))

    assert snapshot["date"] == "2026-05-16"
    assert snapshot["progress_ml"] == 0


def test_water_goal_by_profile(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    child = water.set_goal_by_profile(8, "female", db_path=db_path)
    female_adult = water.set_goal_by_profile(30, "female", db_path=db_path)
    male_adult = water.set_goal_by_profile(30, "male", db_path=db_path)

    assert child["goal_ml"] == 1350
    assert female_adult["goal_ml"] == 2150
    assert male_adult["goal_ml"] == 3000
    assert male_adult["sex"] == "male"


def test_water_validates_inputs(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    with pytest.raises(ValueError):
        water.add_water(0, db_path=db_path)
    with pytest.raises(ValueError):
        water.set_goal(100, db_path=db_path)
    with pytest.raises(ValueError):
        water.set_goal_by_profile(0, "female", db_path=db_path)
    with pytest.raises(ValueError):
        water.set_goal_by_profile(30, "unknown", db_path=db_path)


def test_water_records_weekly_history(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    water.add_water(300, db_path=db_path, now=datetime(2026, 5, 10, 9, 0, 0))
    water.add_water(500, db_path=db_path, now=datetime(2026, 5, 12, 9, 0, 0))
    water.add_water(700, db_path=db_path, now=datetime(2026, 5, 15, 9, 0, 0))

    week = water.weekly_history(db_path=db_path, now=datetime(2026, 5, 15, 12, 0, 0))

    assert len(week) == 7
    assert week[-1]["amount_ml"] == 700
    assert week[-1]["date"] == "2026-05-15"
    assert any(day["amount_ml"] == 500 for day in week)


def test_water_records_monthly_history(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    water.add_water(300, db_path=db_path, now=datetime(2026, 4, 20, 9, 0, 0))
    water.add_water(500, db_path=db_path, now=datetime(2026, 5, 1, 9, 0, 0))
    water.add_water(700, db_path=db_path, now=datetime(2026, 5, 15, 9, 0, 0))

    month = water.monthly_history(db_path=db_path, now=datetime(2026, 5, 15, 12, 0, 0))

    assert len(month) == 30
    assert month[-1]["amount_ml"] == 700
    assert month[-1]["date"] == "2026-05-15"
    assert any(day["amount_ml"] == 500 for day in month)
    assert any(day["amount_ml"] == 300 for day in month)


def test_water_records_yearly_history(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    water.add_water(400, db_path=db_path, now=datetime(2025, 10, 5, 9, 0, 0))
    water.add_water(600, db_path=db_path, now=datetime(2026, 1, 15, 9, 0, 0))
    water.add_water(800, db_path=db_path, now=datetime(2026, 5, 10, 9, 0, 0))
    water.add_water(200, db_path=db_path, now=datetime(2026, 5, 15, 9, 0, 0))

    year = water.yearly_history(db_path=db_path, now=datetime(2026, 5, 15, 12, 0, 0))

    assert len(year) == 12
    may_2026 = [m for m in year if m["month_key"] == "2026-05"][0]
    assert may_2026["amount_ml"] == 1000
    assert may_2026["days_active"] == 2
    assert may_2026["avg_daily_ml"] == 500
    assert may_2026["days_in_month"] == 31

    jan_2026 = [m for m in year if m["month_key"] == "2026-01"][0]
    assert jan_2026["amount_ml"] == 600
    assert jan_2026["days_active"] == 1

    oct_2025 = [m for m in year if m["month_key"] == "2025-10"][0]
    assert oct_2025["amount_ml"] == 400
