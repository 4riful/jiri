from __future__ import annotations

from datetime import datetime

from jiri import db, water


def test_database_persists_water_log_and_settings(tmp_path):
    db_path = str(tmp_path / "jiri.db")

    db.set_setting("logical.flag", "1", db_path=db_path)
    water.add_water(250, db_path=db_path, now=datetime(2026, 5, 15, 9, 0, 0))

    with db.connect(db_path) as conn:
        setting = conn.execute("SELECT value FROM settings WHERE key = ?", ("logical.flag",)).fetchone()
        water_row = conn.execute("SELECT day, amount_ml FROM water_log ORDER BY id DESC LIMIT 1").fetchone()

    assert setting["value"] == "1"
    assert water_row["day"] == "2026-05-15"
    assert water_row["amount_ml"] == 250
