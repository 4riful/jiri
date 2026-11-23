from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from jiri.ui import renderer
from jiri.ui.emotion import EmotionEngine, appraise, classify


def scene(late=0, water=60, focus=None, hour=14, todos=None):
    todos = todos if todos is not None else [
        SimpleNamespace(title=f"Task {i}", due_at=f"2026-01-01T{hour - 2:02d}:00:00") for i in range(late)
    ]
    snap = SimpleNamespace(
        face_state="idle", face_reason="", headline="hi", subheadline="", focus=focus or {},
        overdue_count=late, pending_count=len(todos), pending_todos=todos,
        water={"goal_ml": 3000, "percent": water, "progress_ml": water * 30},
        weather={"available": True, "temperature_c": 22, "condition": "Clear sky", "rain_chance": 5,
                 "fetched_at": f"2026-01-01T{hour:02d}:00:00"},
        panel="todos",
    )
    return renderer.build_scene(snap, now=datetime(2026, 1, 1, hour, 0))


def run(engine, sc, seconds, start=0.0, hour=14):
    t = start
    feeling = None
    while t < start + seconds:
        feeling = engine.update(sc, t, datetime(2026, 1, 1, hour, 0))
        t += 0.5
    return feeling, t


def test_late_tasks_make_jiri_worried_or_upset_and_say_why():
    f, _ = run(EmotionEngine(), scene(late=3), 30)
    assert f.name in ("worried", "upset", "furious")
    assert "3 tasks are late" in f.cause
    assert f.valence < -0.2


def test_calm_day_is_calm_or_content():
    f, _ = run(EmotionEngine(), scene(late=0, water=70), 30)
    assert f.name in ("calm", "content", "joyful")


def test_feelings_do_not_flicker():
    engine = EmotionEngine()
    calm = scene(late=0, water=70)
    f, t = run(engine, calm, 20)
    first = f.name
    # A brief blip of bad news shorter than the confirmation window changes nothing.
    engine.update(scene(late=3), t, datetime(2026, 1, 1, 14, 0))
    f2 = engine.update(calm, t + 0.5, datetime(2026, 1, 1, 14, 0))
    assert f2.name == first


def test_finishing_a_task_brings_joy():
    engine = EmotionEngine()
    two = [SimpleNamespace(title="A", due_at=None), SimpleNamespace(title="B", due_at=None)]
    f, t = run(engine, scene(todos=two), 20)
    f, _ = run(engine, scene(todos=two[:1]), 6, start=t)
    assert f.name == "joyful" and "finished a task" in f.cause


def test_late_night_makes_jiri_sleepy():
    f, _ = run(EmotionEngine(), scene(hour=1, water=10), 40, hour=1)
    assert f.name in ("sleepy", "glum")


def test_classify_regions():
    assert classify(0.8, 0.8, False) == "joyful"
    assert classify(0.0, 0.1, False) == "sleepy"
    assert classify(-0.9, 0.9, False) == "furious"
    assert classify(0.1, 0.5, True) == "focused"
