from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

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


def test_database_persists_across_process_restart(tmp_path):
    db_path = tmp_path / "persistent" / "jiri.db"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["JIRI_DB_PATH"] = str(db_path)
    env["PYTHONPATH"] = str(project_root / "src")

    subprocess.run(
        [sys.executable, "-m", "jiri.cli", "todo", "add", "Survives restart"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "jiri.cli", "todo", "list"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert db_path.is_file()
    assert "Survives restart" in result.stdout
