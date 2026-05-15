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
