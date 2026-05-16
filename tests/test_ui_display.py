from __future__ import annotations

from datetime import datetime, timedelta

from jiri.config import AppConfig, DisplayConfig
from jiri.ui.face import face_frame_for_state, focus_eyes, is_critical_face_state
from jiri.ui.layout import build_layout
from jiri.ui.pygame_app import run
from jiri.ui.touch import PendingConfirmation, action_for_touch, build_touch_zones, hit_test
from jiri.ui.view_model import build_display_view_model
from jiri.views import build_screen_snapshot


def test_face_frames_and_focus_eyes():
    assert face_frame_for_state("idle").eye_left == "o"
    assert face_frame_for_state("rage").mouth == "###"
    assert face_frame_for_state("curious").eye_right == "O"
    assert face_frame_for_state("smirk").mouth == "__/"
    assert face_frame_for_state("weather_rain").mouth == "~~~"
    assert face_frame_for_state("weather_hot").eye_left == "~"
    assert focus_eyes("24:59") == ("24", "59")
    assert is_critical_face_state("rage") is True
    assert is_critical_face_state("idle") is False


def test_touch_zone_hit_testing_and_confirmation():
    zones = build_touch_zones(480, 320)
    face_zone = hit_test((20, 80), zones)
    assert face_zone is not None
    assert face_zone.action == "cycle_face"

    action, pending = action_for_touch((20, 80), "rage", width=480, height=320)
    assert action == "blocked_critical_face"
    assert pending is None

    first_action, pending = action_for_touch((430, 240), "idle", width=480, height=320, now=datetime(2026, 5, 15, 9, 0, 0))
    assert first_action == "confirmation_required"
    assert pending is not None

    second_action, pending = action_for_touch((430, 240), "idle", width=480, height=320, pending=pending, now=datetime(2026, 5, 15, 9, 0, 3))
    assert second_action == "confirm_or_primary"
    assert pending is None


def test_display_view_model_from_screen_snapshot(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    cfg = AppConfig(display=DisplayConfig(driver="mock", fullscreen=False, width=480, height=320))
    snapshot = build_screen_snapshot(db_path=db_path, config=cfg, panel="system", now=datetime(2026, 5, 15, 9, 0, 0))
    model = build_display_view_model(snapshot)
    assert model.width == 480
    assert model.height == 320
    assert model.panel == "system"
    assert model.headline == model.headline[:160]
    assert model.typed_headline == model.headline
    assert model.typed_complete is True
    assert model.typing_speed_cps == 24
    assert model.right_rows
    assert model.touch_zones


def test_display_view_model_types_and_truncates_headline(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    cfg = AppConfig(display=DisplayConfig(driver="mock", fullscreen=False, width=480, height=320, typing_speed_cps=20))
    started = datetime(2026, 5, 15, 9, 0, 0)
    snapshot = build_screen_snapshot(db_path=db_path, config=cfg, panel="system", now=started)
    long_headline_snapshot = snapshot.__class__(**{**snapshot.__dict__, "headline": "A" * 300})

    model = build_display_view_model(
        long_headline_snapshot,
        message_started_at=started,
        now=started + timedelta(seconds=2),
    )

    assert len(model.headline) == 160
    assert model.typed_headline == "A" * 40
    assert model.typed_complete is False


def test_layout_respects_minimum_geometry():
    layout = build_layout(120, 100)
    assert layout.width >= 240
    assert layout.height >= 160
    assert layout.face.width > layout.panel.width


def test_pygame_mock_mode_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_FULLSCREEN", "false")
    assert run() == 0
