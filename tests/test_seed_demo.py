from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from jiri import db, focus, water
from jiri.runtime import JiriRuntime

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "scripts" / "seed_demo.py")
seed_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_demo)

NOW = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)  # today: water's daily reset reads the real clock


def _rt(tmp_path) -> JiriRuntime:
    return JiriRuntime.load(db_path=str(tmp_path / "jiri.db"))


def test_seed_creates_expected_rows(tmp_path):
    rt = _rt(tmp_path)
    created = seed_demo.seed(rt, now=NOW)

    todos = rt.list_todos()
    assert len(todos) == 6 and all(seed_demo.is_demo_todo(t) for t in todos)
    assert sum(1 for t in todos if t.due_at is None) == 1
    assert len(rt.list_notes()) == 3
    assert created["water"]["today_ml"] == 1400
    assert db.count_rows("water_log", db_path=rt.db_path) == 4 + 6 * 3
    snap = water.water_snapshot(db_path=rt.db_path, now=NOW, reset_daily=False)
    assert snap["progress_ml"] == 1400 and snap["goal_ml"] == 3000
    assert created["focus"] is not None
    active = focus.active_snapshot(db_path=rt.db_path, now=NOW)
    assert active["active"] and active["title"] == seed_demo.FOCUS_TITLE


def test_reset_demo_removes_only_demo_rows(tmp_path):
    rt = _rt(tmp_path)
    owner_todo = rt.add_todo("Owner task", description="real")
    owner_note = rt.add_note("Owner note", "keep me", tags="personal")
    water.add_water(200, db_path=rt.db_path, now=NOW)

    seed_demo.seed(rt, now=NOW)
    seed_demo.seed(rt, now=NOW)  # idempotent re-seed via reset
    assert len(rt.list_todos()) == 6 + 1

    seed_demo.reset_demo(rt, now=NOW)
    seed_demo.seed(rt, now=NOW)
    removed = seed_demo.reset_demo(rt, now=NOW)

    assert removed == {"todos": 6, "notes": 3, "water_logs": 22, "focus_sessions": 1}
    assert [t.id for t in rt.list_todos(include_done=True)] == [owner_todo.id]
    assert [n.id for n in rt.list_notes()] == [owner_note.id]
    assert db.count_rows("water_log", db_path=rt.db_path) == 1
    assert db.count_rows("focus_sessions", db_path=rt.db_path) == 0
    assert db.get_setting(water.WATER_PROGRESS_KEY, db_path=rt.db_path) == "200"
    assert db.get_setting(seed_demo.MANIFEST_KEY, db_path=rt.db_path) is None


def test_seed_leaves_owner_focus_session_alone(tmp_path):
    rt = _rt(tmp_path)
    owner = rt.start_focus(30, title="Owner focus")
    created = seed_demo.seed(rt, now=NOW)
    assert created["focus"] is None and created["skipped"]
    seed_demo.reset_demo(rt, now=NOW)
    assert rt.focus_snapshot()["active"]
    assert db.count_rows("focus_sessions", db_path=rt.db_path) == 1
    assert owner.id == rt.list_focus_sessions()[0].id
