from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from jiri.ui import mascot, output, renderer
from jiri.ui.face import FACE_STATES


@pytest.fixture(scope="module")
def fonts():
    pygame.display.init()
    pygame.font.init()
    return renderer.load_fonts(pygame)


def snap(state="idle", reason="", headline="", subheadline="", focus=None, overdue=0, pending=0):
    return SimpleNamespace(
        face_state=state, face_reason=reason, headline=headline, subheadline=subheadline,
        focus=focus or {}, overdue_count=overdue, pending_count=pending,
        water={"goal_ml": 3000, "percent": 40}, weather={"temperature_c": 21.4}, panel="todos",
    )


def test_every_face_state_has_a_mood_and_renders(fonts):
    surface = pygame.Surface((480, 320))
    for state in FACE_STATES:
        assert state in mascot.MOODS
        scene = renderer.build_scene(snap(state, "reason", "hello"), now=datetime(2026, 1, 1, 9, 5))
        renderer.render(pygame, surface, fonts, scene)
        renderer.render(pygame, surface, fonts, scene, open_amount=0.25, glance=12)


def test_eyes_show_hour_and_minute():
    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 21, 5), clock_24h=False)
    assert scene.digits == ("9", "05")
    assert scene.eyes_show_time
    scene24 = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 21, 5), clock_24h=True)
    assert scene24.digits == ("21", "05")


def test_focus_turns_eyes_into_countdown_and_moves_clock_to_status():
    focus = {"active": True, "status": "running", "remaining_text": "24:10"}
    scene = renderer.build_scene(snap("focused", focus=focus), now=datetime(2026, 1, 1, 21, 5))
    assert scene.digits == ("24", "10")
    assert not scene.eyes_show_time


def test_sleeping_moves_clock_to_status_line():
    scene = renderer.build_scene(snap("sleeping"), now=datetime(2026, 1, 1, 1, 5))
    assert not scene.eyes_show_time


def test_speech_never_reads_back_the_reason():
    scene = renderer.build_scene(snap(
        "annoyed",
        reason="1 overdue task · Verify JIRI persistence",
        headline="Verify JIRI persistence.",
        subheadline="It's still there. I checked twice.",
    ))
    assert scene.speech == "It's still there. I checked twice."


def test_lids_never_hide_the_clock_digits(fonts):
    # Render the angriest eye and confirm the digit area still has both
    # eye-colour and background pixels (i.e. digits are visible, not lidded).
    for state in ("angry", "rage", "focused", "happy"):
        surface = pygame.Surface((200, 160))
        surface.fill(mascot.BACKGROUND)
        mood = mascot.mood_for(state)
        mascot.draw_eye(pygame, surface, (10, 10, 138, 128), mood, digits="05", inner_on_right=True)
        top = int(10 + max(mood.lid_inner, mood.lid_outer) * 128)
        colours = {tuple(surface.get_at((x, y)))[:3] for x in range(20, 140, 3) for y in range(top, 130, 3)}
        assert mood.color in colours and mascot.BACKGROUND in colours, state


def test_animator_blinks_and_is_quiet_otherwise():
    anim = renderer.Animator(seed=1)
    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 9, 5))
    anim.observe(scene, 0.0)
    values = {anim.frame("idle", t / 20)[0] for t in range(0, 400)}
    assert 1.0 in values and min(values) < 0.5
    # Sleeping never blinks.
    sleepy = renderer.Animator(seed=1)
    assert {sleepy.frame("sleeping", t / 20)[0] for t in range(0, 400)} == {1.0}


def test_framebuffer_writes_only_changed_bands(tmp_path):
    pygame.display.init()
    sysfs = tmp_path / "sys"
    (sysfs / "fb1").mkdir(parents=True)
    (sysfs / "fb1" / "bits_per_pixel").write_text("16")
    (sysfs / "fb1" / "stride").write_text("960")
    (sysfs / "fb1" / "virtual_size").write_text("480,320")
    fb = tmp_path / "fb1"
    fb.write_bytes(bytes(480 * 320 * 2))

    out = output.FramebufferOutput(pygame, (480, 320), str(fb), sysfs_root=str(sysfs))
    canvas = pygame.Surface((480, 320))
    canvas.fill((255, 255, 255))
    assert out.present(canvas) == 320 // output.BAND_ROWS
    assert out.present(canvas) == 0
    pygame.draw.rect(canvas, (0, 0, 0), (0, 100, 10, 5))
    assert out.present(canvas) == 1
    data = fb.read_bytes()
    assert data[:2] == b"\xff\xff"  # white in RGB565
    assert data[100 * 960: 100 * 960 + 2] == b"\x00\x00"


def test_framebuffer_rejects_wrong_geometry(tmp_path):
    sysfs = tmp_path / "sys"
    (sysfs / "fb1").mkdir(parents=True)
    (sysfs / "fb1" / "bits_per_pixel").write_text("16")
    (sysfs / "fb1" / "virtual_size").write_text("800,480")
    with pytest.raises(RuntimeError, match="rotate"):
        output.FramebufferOutput(pygame, (480, 320), str(tmp_path / "fb1"), sysfs_root=str(sysfs))


def test_touch_calibration_maps_and_swaps():
    t = object.__new__(output.EvdevTouch)
    t.size = (480, 320)
    t.xmin, t.xmax, t.ymin, t.ymax, t.swap = 200, 3900, 300, 3800, False
    assert t.map(200, 300) == (0, 0)
    assert t.map(3900, 3800) == (479, 319)
    t.swap = True
    assert t.map(300, 200) == (0, 0)


def test_usage_bar_parts_match_statusline_style():
    assert renderer.bar_parts(0) == ("", "░" * 6)
    assert renderer.bar_parts(100) == ("█" * 6, "")
    filled, track = renderer.bar_parts(18)
    assert filled.startswith("█") and len(filled) + len(track) == 6
    assert renderer.bar_parts(1)[0] == "▏"  # tiny usage is still visible
    assert renderer.gauge_color(95) == renderer.GAUGE_RED
    assert renderer.gauge_color(10) == renderer.GAUGE_GREEN


def test_usage_panel_renders_reports_and_empty_state(fonts):
    now = datetime(2026, 1, 1, 12, 0)
    report = SimpleNamespace(
        provider="claude", label="Opus", context_pct=18.0, five_hour_pct=9.0,
        five_hour_resets_at=now.timestamp() + 43 * 60, weekly_pct=4.0,
        weekly_resets_at=now.timestamp() + 2 * 86400, updated_at=now.timestamp() - 7200,
    )
    scene = renderer.build_scene(snap(), now=now, usage=(report,))
    assert scene.show_usage
    row = scene.usage[0]
    assert row.stale and row.age == "2h ago"
    assert row.gauges[1] == ("5h", 9.0, "43m")
    assert row.gauges[2][2] == "2d"
    surface = pygame.Surface((480, 320))
    renderer.render(pygame, surface, fonts, scene)
    empty = renderer.build_scene(snap(), now=now, usage=())
    assert empty.show_usage and empty.usage == ()
    renderer.render(pygame, surface, fonts, empty)
    assert not renderer.build_scene(snap(), now=now).show_usage


def test_single_tap_pets_double_tap_stops_then_spins(fonts):
    from jiri.ui.stage import Stage

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False, rotate=True)
    surface = pygame.Surface((480, 320))
    stage.frame(pygame, surface, fonts, scene, 0.0)
    stage.frame(pygame, surface, fonts, scene, 1.0, [(100, 100)])     # single tap
    assert stage.spinning and stage.pet.action.name == "poked"        # petted only
    stage.frame(pygame, surface, fonts, scene, 3.0, [(240, 260)])
    stage.frame(pygame, surface, fonts, scene, 3.2, [(240, 260)])     # double tap
    assert not stage.spinning
    assert stage.life(scene, 3.3, stage.available(scene)).toast == "stopped"
    stage.frame(pygame, surface, fonts, scene, 200.0)
    assert stage.page == "face"                                        # stays put
    stage.frame(pygame, surface, fonts, scene, 201.0, [(240, 100)])
    stage.frame(pygame, surface, fonts, scene, 201.3, [(240, 100)])   # double tap again
    assert stage.spinning and stage.splash_page == stage.available(scene)[1]


def test_thoughts_come_from_real_data_and_change_the_face():
    from jiri.ui.stage import THOUGHT_SECONDS, Stage

    s = snap("annoyed", overdue=1, pending=1)
    s.pending_todos = [SimpleNamespace(title="Pay bill", due_at="2026-01-01T11:30:00")]
    scene = renderer.build_scene(s, now=datetime(2026, 1, 1, 12, 0))
    cats = [t[3] for t in scene.thoughts]
    assert cats[0] == "thought_late" and "Pay bill" in scene.thoughts[0][2]
    assert "thought_water_low" in cats                     # 40% water
    stage = Stage(boot=False)
    first, _ = stage.thought_scene(scene, 0.0)
    second, _ = stage.thought_scene(scene, THOUGHT_SECONDS + 0.1)
    assert first.reason != second.reason and first.state != second.state
    assert first.speech and second.speech


def test_scramble_settles_left_to_right():
    from jiri.ui.pages import scramble

    text = "Hello there"
    early = scramble(text, 0.0, 1.0)
    assert early != text and early[5] == " " and len(early) == len(text)
    mid = scramble(text, 0.18 + 5 * 0.016, 1.0)
    assert mid[:5] == "Hello" and mid[6:] != "there"
    assert scramble(text, 5.0, 1.0) == text


def test_pet_reacts_to_touch_like_a_pet():
    from jiri.ui.pet import Pet

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    pet = Pet()
    pet.update(scene, 0.0, hour=12)
    pet.touch(1.0, 400, 60)
    pose = pet.update(scene, 1.3, hour=12)
    assert pose.action == "poked" and pose.gaze[0] > 0   # looks toward the finger
    for k in range(3):
        pet.touch(2.0 + k * 0.3, 240, 100)
    assert pet.update(scene, 2.8, hour=12).action == "tickled"
    for k in range(5):
        pet.touch(3.0 + k * 0.2, 240, 100)
    assert pet.update(scene, 4.1, hour=12).action == "grumpy"


def test_pet_falls_asleep_when_tired_and_ignored_then_wakes_on_touch():
    from jiri.ui.pet import Pet

    scene = renderer.build_scene(snap(overdue=0), now=datetime(2026, 1, 1, 2, 0))
    pet = Pet()
    pet.energy = 0.2
    t = 0.0
    while t < 400 and not pet.asleep:
        pet.update(scene, t, hour=2)
        t += 0.5
    assert pet.asleep and pet.update(scene, t, hour=2).state == "sleeping"
    pet.touch(t + 1, 240, 100)
    assert pet.update(scene, t + 1.2, hour=2).action == "wake"


def test_pet_notices_real_data_changes():
    from jiri.ui.pet import Pet

    before = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    after_snap = snap()
    after_snap.water = {"goal_ml": 3000, "percent": 55, "progress_ml": 1650}
    after = renderer.build_scene(after_snap, now=datetime(2026, 1, 1, 12, 0))
    pet = Pet()
    pet.update(before, 0.0, hour=12)
    pose = pet.update(after, 0.5, hour=12)
    assert pose.action == "notice" and pose.say == "pet_saw_water"


def test_jiri_thinks_before_it_types(fonts):
    from jiri.ui.stage import THINK_SECONDS, Stage

    scene = renderer.build_scene(snap(headline="Hello there, human."), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False)
    first = stage.life(scene, 0.0, ["face"])
    assert first.thinking >= 0 and first.typed == 0
    later = stage.life(scene, THINK_SECONDS + 0.5, ["face"])
    assert later.thinking < 0 and later.typed > 0


def test_eyes_show_pupils_and_flip_to_the_clock_on_time_checks(fonts):
    from jiri.ui.stage import TIME_CHECK_SECONDS, Stage

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False)
    surface = pygame.Surface((480, 320))
    stage.frame(pygame, surface, fonts, scene, 0.0)
    assert not stage.life(scene, 0.1, ["face"]).show_time          # pupils by default
    stage.frame(pygame, surface, fonts, scene, 1.0, [(240, 20)])   # tap the top bar
    assert stage.life(scene, 1.5, ["face"]).show_time               # time check
    assert not stage.life(scene, 1.0 + TIME_CHECK_SECONDS + 0.1, ["face"]).show_time
    later = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 1))
    assert stage.life(later, 20.0, ["face"]).show_time              # new minute -> time check


def test_screens_change_on_their_own_with_the_splash_by_default(fonts):
    from jiri.ui.stage import HOME_SECONDS, PAGE_SECONDS, Stage

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False, rotate=None)
    surface = pygame.Surface((480, 320))
    assert stage.spinning                                       # auto-rotation is on
    seen_splash = set()
    t = 0.0
    while t < HOME_SECONDS + 2 * PAGE_SECONDS + 5:
        stage.frame(pygame, surface, fonts, scene, t)
        if stage.splash_page:
            seen_splash.add(stage.splash_page)
        t += 0.5
    assert {"tasks", "notes"} <= seen_splash                    # each change used the splash
    stage.frame(pygame, surface, fonts, scene, t, [(240, 260)])
    stage.frame(pygame, surface, fonts, scene, t + 0.2, [(240, 260)])   # double tap: stop
    assert not stage.spinning
    for k in range(0, 80, 5):
        stage.frame(pygame, surface, fonts, scene, t + 1 + k)
    assert stage.page == "face"                                 # stopped elsewhere -> back home

def test_every_mood_is_pink():
    from jiri.ui import mascot

    for name, mood in mascot.MOODS.items():
        assert mood.color in (mascot.PINK, mascot.PINK_DEEP, mascot.PINK_DIM, mascot.SLATE), name


def test_single_tap_on_bubble_or_info_screen_goes_to_next_screen(fonts):
    from jiri.ui.stage import Stage

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False, rotate=False)
    surface = pygame.Surface((480, 320))
    stage.frame(pygame, surface, fonts, scene, 0.0)
    stage.frame(pygame, surface, fonts, scene, 1.0, [(240, 260)])   # tap the bubble
    assert stage.splash_page is None                               # waits: maybe a double tap
    stage.frame(pygame, surface, fonts, scene, 1.6)
    assert stage.splash_page == "tasks" and not stage.spinning     # next screen, with splash
    for t in (2.0, 2.5, 3.0):
        stage.frame(pygame, surface, fonts, scene, t)
    stage.frame(pygame, surface, fonts, scene, 4.0, [(240, 100)])   # tap anywhere on Tasks
    stage.frame(pygame, surface, fonts, scene, 4.6)
    assert stage.splash_page == "notes"


def test_framebuffer_rotates_landscape_frames_onto_a_portrait_panel(tmp_path):
    pygame.display.init()
    sysfs = tmp_path / "sys"
    (sysfs / "fb1").mkdir(parents=True)
    (sysfs / "fb1" / "bits_per_pixel").write_text("16")
    (sysfs / "fb1" / "virtual_size").write_text("320,480")
    fb = tmp_path / "fb1"
    fb.write_bytes(bytes(320 * 480 * 2))
    out = output.FramebufferOutput(pygame, (480, 320), str(fb), sysfs_root=str(sysfs))
    assert out.rotation == 90 and out.fb_size == (320, 480)
    canvas = pygame.Surface((480, 320))
    canvas.fill((0, 0, 0))
    pygame.draw.rect(canvas, (255, 255, 255), (0, 0, 10, 10))  # top-left marker
    assert out.present(canvas) > 0
    data = fb.read_bytes()
    assert len(data) == 320 * 480 * 2 and b"\xff\xff" in data


def test_prev_next_arrows_appear_after_a_touch_and_change_screens(fonts):
    from jiri.ui.stage import Stage

    scene = renderer.build_scene(snap(), now=datetime(2026, 1, 1, 12, 0))
    stage = Stage(boot=False, rotate=False)
    surface = pygame.Surface((480, 320))
    stage.frame(pygame, surface, fonts, scene, 0.0)
    assert stage.life(scene, 0.1, stage.available(scene)).arrows == 0     # hidden at rest
    stage.frame(pygame, surface, fonts, scene, 1.0, [(240, 100)])         # any touch...
    assert stage.life(scene, 1.5, stage.available(scene)).arrows > 0.9    # ...shows them
    stage.frame(pygame, surface, fonts, scene, 2.0, [(470, 160)])         # right arrow
    assert stage.splash_page == "tasks"
    for t in (2.5, 3.0, 3.5):
        stage.frame(pygame, surface, fonts, scene, t)
    stage.frame(pygame, surface, fonts, scene, 4.0, [(10, 160)])          # left arrow
    assert stage.splash_page == "face"


def test_touch_device_vanishing_does_not_crash_the_display(tmp_path, monkeypatch):
    t = object.__new__(output.EvdevTouch)
    t.size, t.device, t._retry_at = (480, 320), str(tmp_path / "event0"), 0.0
    t.x = t.y = 0
    t.down = False
    t.fd = 99

    def gone(fd, n):
        raise OSError(19, "No such device")

    monkeypatch.setattr(output.os, "read", gone)
    monkeypatch.setattr(output.os, "close", lambda fd: None)
    assert t.poll() == [] and t.fd is None          # survives, drops the device
    assert t.poll() == []                           # retry later, no crash
