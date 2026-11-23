#!/usr/bin/env python3
"""Seed realistic demo data into JIRI's SQLite DB for testing the 480x320 screens.

Usage (from the repo root):
    PYTHONPATH=src .venv/bin/python scripts/seed_demo.py            # seed the configured DB
    PYTHONPATH=src .venv/bin/python scripts/seed_demo.py --no-focus
    PYTHONPATH=src .venv/bin/python scripts/seed_demo.py --reset-demo  # remove demo rows only

Everything is written through JIRI's own APIs (runtime / todos / notes /
water / focus). Demo rows are marked so they can be removed again without
touching the owner's data:
    todos  -> description starts with "[demo]"
    notes  -> tags == "demo"
    water / focus -> ids recorded in the settings key "demo.seed_manifest"
An existing DB is backed up with scripts/backup_db.sh before any write.
Seeding is idempotent: earlier demo rows are removed first.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jiri import db, focus, water  # noqa: E402
from jiri.runtime import JiriRuntime  # noqa: E402

DEMO_MARKER = "[demo]"
DEMO_TAG = "demo"
MANIFEST_KEY = "demo.seed_manifest"
DEMO_WATER_GOAL_ML = 3000
FOCUS_TITLE = "Write JIRI release notes"


def is_demo_todo(todo) -> bool:
    return (todo.description or "").startswith(DEMO_MARKER)


def is_demo_note(note) -> bool:
    return (note.tags or "").strip().lower() == DEMO_TAG


# ---------------------------------------------------------------- backup

def backup_db(db_path: str, backup_dir: str | None = None) -> str | None:
    """Back up an existing DB with scripts/backup_db.sh. Returns the backup path."""
    if not Path(db_path).is_file():
        return None
    env = dict(os.environ, JIRI_DB_PATH=str(Path(db_path).resolve()))
    if backup_dir:
        env["JIRI_BACKUP_DIR"] = str(Path(backup_dir).resolve())
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "backup_db.sh")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit(f"Backup failed, nothing was changed:\n{result.stderr.strip()}")
    path = result.stdout.strip().splitlines()[-1]
    return str((ROOT / path).resolve()) if not os.path.isabs(path) else path


# ---------------------------------------------------------------- manifest

def _load_manifest(db_path: str) -> dict:
    raw = db.get_setting(MANIFEST_KEY, db_path=db_path)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _save_manifest(manifest: dict, db_path: str) -> None:
    db.set_setting(MANIFEST_KEY, json.dumps(manifest, sort_keys=True), db_path=db_path)


# ---------------------------------------------------------------- reset

def reset_demo(rt: JiriRuntime, now: datetime | None = None) -> dict[str, int]:
    """Remove previously seeded demo rows only. Owner data is never touched."""
    current = now or datetime.now()
    path = rt.db_path
    removed = {"todos": 0, "notes": 0, "water_logs": 0, "focus_sessions": 0}

    for todo in rt.list_todos(include_done=True):
        if is_demo_todo(todo):
            rt.delete_todo(todo.id)
            removed["todos"] += 1
    for note in rt.list_notes():
        if is_demo_note(note):
            rt.delete_note(note.id)
            removed["notes"] += 1

    manifest = _load_manifest(path)
    focus_id = manifest.get("focus_session_id")
    if focus_id:
        active = focus.get_active_session(db_path=path)
        if active is not None and active.id == focus_id:
            focus.cancel_session(focus_id, db_path=path, now=current)
        # No delete API exists for focus sessions or water logs; remove by recorded id.
        with db.connect(path) as conn:
            removed["focus_sessions"] += conn.execute(
                "DELETE FROM focus_sessions WHERE id = ?", (focus_id,)
            ).rowcount

    water_ids = [int(i) for i in manifest.get("water_log_ids", [])]
    if water_ids:
        today_demo_ml = int(manifest.get("water_today_ml", 0))
        with db.connect(path) as conn:
            marks = ",".join("?" for _ in water_ids)
            removed["water_logs"] = conn.execute(
                f"DELETE FROM water_log WHERE id IN ({marks})", water_ids
            ).rowcount
        # Take the demo millilitres back off today's counter (only if still the same day).
        if manifest.get("water_day") == db.get_setting(water.WATER_DATE_KEY, db_path=path):
            progress = int(db.get_setting(water.WATER_PROGRESS_KEY, db_path=path) or 0)
            db.set_setting(water.WATER_PROGRESS_KEY, str(max(0, progress - today_demo_ml)), db_path=path)

    if manifest.get("water_goal_set"):
        previous = manifest.get("water_goal_previous")
        if previous is None:
            db.delete_setting(water.WATER_GOAL_KEY, db_path=path)
        else:
            db.set_setting(water.WATER_GOAL_KEY, str(previous), db_path=path)

    if manifest:
        db.delete_setting(MANIFEST_KEY, db_path=path)
    return removed


# ---------------------------------------------------------------- seed

def _later_today(now: datetime) -> datetime:
    """A due time later today that is clearly past the 'soon' window."""
    end_of_day = now.replace(hour=23, minute=30, second=0, microsecond=0)
    candidate = now + timedelta(hours=3)
    if candidate <= end_of_day:
        return candidate
    if end_of_day - now >= timedelta(minutes=60):
        return end_of_day
    return now + timedelta(hours=2)  # too late in the evening; best effort


def seed(rt: JiriRuntime, now: datetime | None = None, with_focus: bool = True) -> dict:
    current = (now or datetime.now()).replace(second=0, microsecond=0)
    path = rt.db_path
    removed = reset_demo(rt, now=current)  # idempotent: never stack two demo sets
    manifest: dict = {"seeded_at": current.isoformat()}
    created: dict = {"removed": removed, "todos": [], "notes": [], "water": {}, "focus": None, "skipped": []}

    tomorrow_morning = (current + timedelta(days=1)).replace(hour=10, minute=0)
    todo_specs = [
        ("Reply to Nadia about the deck", current - timedelta(minutes=15), 1, "15 min overdue -> annoyed"),
        ("Pay electricity bill", current - timedelta(minutes=45), 1, "45 min overdue -> angry"),
        ("Push JIRI to the Pi", current + timedelta(minutes=20), 2, "due in 20 min -> soon"),
        ("Buy coffee beans", _later_today(current), 3, "later today"),
        ("Call Ammu", tomorrow_morning, 2, "tomorrow"),
        ("Read 20 pages", None, 3, "no due date"),
    ]
    for title, due, priority, label in todo_specs:
        todo = rt.add_todo(title, due_at=due, description=f"{DEMO_MARKER} {label}", priority=priority)
        created["todos"].append((todo.id, title, todo.due_at, priority, label))

    note_specs = [
        ("Pi display checklist", "Check backlight, touch rotation and FPS on the 3.5-inch panel after the push."),
        ("Coffee order", "Ethiopian Yirgacheffe, 250 g, medium roast. Ask for whole beans."),
        ("Release notes ideas", "Guardian face, tap to acknowledge, honest blinking, water ring on the glance panel."),
    ]
    for title, body in note_specs:
        note = rt.add_note(title, body, tags=DEMO_TAG)
        created["notes"].append((note.id, title))

    # Water goal: only set it on a DB that has none, and remember to undo it.
    previous_goal = db.get_setting(water.WATER_GOAL_KEY, db_path=path)
    if previous_goal is None:
        rt.set_water_goal(DEMO_WATER_GOAL_ML)
        manifest["water_goal_set"] = True
        manifest["water_goal_previous"] = None

    water_ids: list[int] = []

    def _last_water_id() -> int:
        with db.connect(path) as conn:
            return int(conn.execute("SELECT MAX(id) FROM water_log").fetchone()[0])

    # History (past 6 days): water._record_water logs a back-dated drink
    # without touching today's progress counter.
    history_ml = [2400, 3100, 1800, 2750, 3000, 2200]  # 6 days ago .. yesterday
    for offset, total in zip(range(6, 0, -1), history_ml):
        day = current - timedelta(days=offset)
        for hour, share in ((9, 0.3), (13, 0.4), (18, 0.3)):
            water._record_water(int(total * share), db_path=path, now=day.replace(hour=hour, minute=15))
            water_ids.append(_last_water_id())

    # Today: ~1.4 L, logged through the normal add path so progress updates.
    today_ml = 0
    for amount, minutes_ago in ((350, 300), (500, 180), (300, 90), (250, 25)):
        at = current - timedelta(minutes=minutes_ago)
        if at.date() != current.date():
            at = current  # early morning: keep every drink on today
        water.add_water(amount, db_path=path, now=at)
        water_ids.append(_last_water_id())
        today_ml += amount
    manifest.update(water_log_ids=water_ids, water_today_ml=today_ml, water_day=water._today(current))
    created["water"] = {"today_ml": today_ml, "history_days": len(history_ml), "log_rows": len(water_ids)}

    if with_focus:
        active = focus.get_active_session(db_path=path)
        if active is not None:
            created["skipped"].append(f"focus: session {active.id} '{active.title}' is already active (left alone)")
        else:
            session = focus.start_focus(25, title=FOCUS_TITLE, db_path=path, now=current - timedelta(minutes=7))
            manifest["focus_session_id"] = session.id
            created["focus"] = (session.id, FOCUS_TITLE)

    _save_manifest(manifest, path)
    return created


def owner_rows(rt: JiriRuntime) -> dict[str, list]:
    return {
        "todos": [t for t in rt.list_todos(include_done=False) if not is_demo_todo(t)],
        "notes": [n for n in rt.list_notes() if not is_demo_note(n)],
    }


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="SQLite path (default: the configured DB, data/jiri.db)")
    parser.add_argument("--reset-demo", action="store_true", help="only remove previously seeded demo rows")
    focus_group = parser.add_mutually_exclusive_group()
    focus_group.add_argument("--focus", dest="focus", action="store_true", default=True,
                             help="start a running 25-min focus session ~7 min in (default)")
    focus_group.add_argument("--no-focus", dest="focus", action="store_false", help="do not start a focus session")
    parser.add_argument("--backup-dir", help="where backups go (default: backups/)")
    args = parser.parse_args(argv)

    # Resolve the path first: JiriRuntime.load() creates/migrates the file, and
    # an existing DB must be backed up before that happens.
    if args.db:
        db_path = args.db
    else:
        from jiri.config import load_config

        db_path = load_config().database.path
    backup = backup_db(db_path, args.backup_dir)
    rt = JiriRuntime.load(db_path=db_path)

    print(f"DB:     {rt.db_path}")
    print(f"Backup: {backup or '(new DB, nothing to back up)'}")

    if args.reset_demo:
        removed = reset_demo(rt)
        print("Removed demo rows: " + ", ".join(f"{k}={v}" for k, v in removed.items()))
    else:
        created = seed(rt, with_focus=args.focus)
        if any(created["removed"].values()):
            print("Replaced previous demo rows: " + ", ".join(f"{k}={v}" for k, v in created["removed"].items()))
        print("\nSeeded todos:")
        for todo_id, title, due, prio, label in created["todos"]:
            print(f"  #{todo_id:<4} p{prio}  {due or '-':<19}  {title}  ({label})")
        print("Seeded notes:")
        for note_id, title in created["notes"]:
            print(f"  #{note_id:<4} {title}")
        w = created["water"]
        snap = rt.water_snapshot()
        print(f"Water:  +{w['today_ml']} ml today -> {snap['progress_ml']}/{snap['goal_ml']} ml "
              f"({snap['percent']}%), {w['history_days']} days of history, {w['log_rows']} log rows")
        if created["focus"]:
            print(f"Focus:  #{created['focus'][0]} '{created['focus'][1]}' 25 min, started 7 min ago")
        for line in created["skipped"]:
            print(f"Skipped {line}")

    owner = owner_rows(rt)
    if owner["todos"] or owner["notes"]:
        print("\nOwner data left untouched:")
        for t in owner["todos"]:
            print(f"  todo #{t.id} '{t.title}' due {t.due_at or '-'} ({t.status})")
        for n in owner["notes"]:
            print(f"  note #{n.id} '{n.title}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
