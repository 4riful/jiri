from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pytest

from jiri.ui import live
from jiri.web import create_app

from conftest import login_client


def snap(state="idle"):
    return SimpleNamespace(
        face_state=state, face_reason="", headline="", subheadline="",
        focus={}, overdue_count=0, pending_count=0,
        water={"goal_ml": 3000, "percent": 40}, weather={"temperature_c": 21.4}, panel="todos",
        width=480, height=320,
    )


class FakeReader:
    """Stands in for pygame_app.StateReader: no thread, no SQLite."""

    def __init__(self, runtime=None):
        self.state = (snap(), ())
        self.lines = {}
        self.stopped = False

    def latest(self):
        return self.state

    def want(self, bucket):
        pass

    def stop(self):
        self.stopped = True


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def preview():
    from jiri.ui.stage import Stage

    p = live.LivePreview(
        None, fps=30, idle_timeout=30, reader_factory=FakeReader,
        stage_factory=lambda voice: Stage(voice=voice, boot=False, rotate=False),
    )
    yield p
    p.stop()


def test_live_preview_renders_animated_frames(preview):
    preview.acquire()
    counter, data, mimetype = preview.wait_frame(0, timeout=5)
    assert counter >= 1
    assert mimetype in {"image/jpeg", "image/png"}
    assert data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n"
    later, _, _ = preview.wait_frame(counter, timeout=5)
    assert later > counter  # keeps rendering: it is a live view, not a still
    preview.release()


def test_taps_reach_the_stage(preview):
    preview.acquire()
    preview.wait_frame(0, timeout=5)
    preview.tap(240, 140)
    assert wait_until(lambda: preview.stage.pet.action is not None and preview.stage.pet.action.name == "poked")
    preview.release()


def test_taps_are_clamped_to_the_panel():
    p = live.LivePreview(None, reader_factory=FakeReader)
    p.ensure_running = lambda: None  # just queue, no thread
    p.tap(-50, 9999)
    assert p._taps == [(0, 319)]


def test_idle_preview_stops_itself():
    p = live.LivePreview(None, fps=30, idle_timeout=0.3, reader_factory=FakeReader)
    p.acquire()
    p.wait_frame(0, timeout=5)
    assert p.running
    time.sleep(0.5)
    assert p.running  # a viewer is still watching
    p.release()
    assert wait_until(lambda: not p.running, timeout=3)
    # A new viewer brings it back.
    before = p.counter
    p.acquire()
    counter, _, _ = p.wait_frame(before, timeout=5)
    assert counter > before
    p.release()
    p.stop()


def test_failed_snapshot_read_keeps_the_last_frame():
    class Flaky(FakeReader):
        calls = 0

        def latest(self):
            Flaky.calls += 1
            if Flaky.calls > 2:
                raise RuntimeError("database is locked")
            return self.state

    p = live.LivePreview(None, fps=30, reader_factory=Flaky)
    p.acquire()
    counter, data, _ = p.wait_frame(0, timeout=5)
    assert data
    time.sleep(0.3)
    assert p.running and p.frame
    p.release()
    p.stop()


@pytest.fixture
def screen_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    monkeypatch.setenv("JIRI_WIDTH", "480")
    monkeypatch.setenv("JIRI_HEIGHT", "320")
    yield
    live.stop_all()


def read_stream(response, limit=200_000):
    body = b""
    for chunk in response.response:
        body += chunk
        if (b"\xff\xd8" in body or b"\x89PNG" in body) and len(body) > 2000 or len(body) > limit:
            break
    response.close()
    return body


def test_screen_live_streams_multipart_frames(screen_env):
    client = create_app(surface="screen").test_client()
    page = client.get("/screen")
    assert b'src="/screen/live"' in page.data
    response = client.get("/screen/live", buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "multipart/x-mixed-replace"
    assert "boundary=frame" in response.headers["Content-Type"]
    body = read_stream(response)
    assert body.startswith(b"--frame\r\nContent-Type: image/")
    assert b"\xff\xd8" in body or b"\x89PNG" in body


def test_screen_tap_on_screen_surface_needs_no_csrf(screen_env):
    client = create_app(surface="screen").test_client()
    assert client.post("/screen/tap", json={"x": 240, "y": 160}).status_code == 204
    assert client.post("/screen/tap", json={"x": "left"}).status_code == 400
    # Not JSON (a cross-site form post can't send JSON without a preflight).
    assert client.post("/screen/tap", data={"x": 1, "y": 2}).status_code == 400


def test_screen_tap_on_all_surface_requires_login_and_csrf(screen_env):
    client = create_app(surface="all").test_client()
    assert client.get("/screen/live").status_code == 302  # login first
    login_client(client)
    token = client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert client.post("/screen/tap", json={"x": 10, "y": 10}).status_code == 400
    ok = client.post("/screen/tap", json={"x": 10, "y": 10}, headers={"X-CSRF-Token": token})
    assert ok.status_code == 204
    page = client.get("/screen")
    assert token.encode() in page.data


def test_admin_surface_hides_live_routes(screen_env):
    client = create_app(surface="admin").test_client()
    assert client.get("/screen/live").status_code == 404
    assert client.post("/screen/tap", json={"x": 1, "y": 1}).status_code == 404
