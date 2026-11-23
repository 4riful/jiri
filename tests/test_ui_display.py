from __future__ import annotations

from jiri import todos
from jiri.ui.face import FACE_STATES
from jiri.ui.pygame_app import run
from jiri.views import build_screen_snapshot


def test_pygame_mock_mode_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    assert run() == 0


def test_snapshot_face_state_is_a_known_face(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    todos.add_todo("Water the plants", db_path=db_path)
    for panel in ("auto", "todos", "weather", "focus", "notes", "system"):
        assert build_screen_snapshot(db_path=db_path, panel=panel).face_state in FACE_STATES


def test_display_is_stable_while_the_state_behind_it_is(tmp_path):
    """Two consecutive snapshots of an unchanged world must be identical.

    Everything that moves on this display is supposed to mean something. A mood,
    a sentence or a reason that differs between two renders of the same state is
    the display talking to itself.
    """
    db_path = str(tmp_path / "jiri.db")
    todos.add_todo("Water the plants", db_path=db_path)
    first = build_screen_snapshot(db_path=db_path)
    second = build_screen_snapshot(db_path=db_path)

    assert first.face_state == second.face_state
    assert first.headline == second.headline
    assert first.face_reason == second.face_reason
