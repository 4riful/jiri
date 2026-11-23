"""JIRI's on-device display loop (Pygame, 480x320, 10-15 FPS).

Reads a snapshot once a second (read-only: no network, no SQLite writes),
turns it into a `Scene`, and draws only when something visible changed.

Output is chosen by `JIRI_DISPLAY_OUTPUT`:
  sdl (default) — a window; WSL dev or HDMI.
  fb            — the 3.5" SPI panel via /dev/fbN (see ui/output.py).
"""

from __future__ import annotations

import os
import time
import zlib
from datetime import datetime

from jiri.runtime import JiriRuntime

from . import renderer
from .stage import Stage

def run() -> int:
    if os.environ.get("JIRI_DISPLAY_DRIVER") == "mock":
        runtime = JiriRuntime.load()
        renderer.build_scene(runtime.screen_snapshot(panel="system"))
        return 0

    output_kind = os.environ.get("JIRI_DISPLAY_OUTPUT", "sdl").lower()
    if output_kind == "fb":
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    # SDL turns SIGTERM into a QUIT event, which the framebuffer output never
    # reads — so `systemctl stop` hung until SIGKILL. Handle it ourselves.
    os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")
    import signal

    stop_requested = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_requested.append(True))

    import pygame

    runtime = JiriRuntime.load()
    cfg = runtime.config
    size = (cfg.display.width, cfg.display.height)
    pygame.display.init()
    pygame.font.init()
    output = _make_output(pygame, output_kind, size, cfg)
    canvas = pygame.Surface(size)
    fonts = renderer.load_fonts(pygame)
    fps = max(10, min(cfg.display.fps, 15))
    from jiri import ai

    reader = StateReader(runtime).start()

    def voice(category: str, mood: str, seed):
        # Pure in-memory lookup: the reader thread pre-loads JIRI's cached
        # lines, so the frame loop never touches SQLite (a locked db used to
        # freeze a frame for 5 s here).
        lines = reader.lines.get((category, mood))
        if not lines:
            reader.want((category, mood))
            return None
        return lines[zlib.crc32(str(seed).encode("utf-8")) % len(lines)]

    stage = Stage(voice=voice)
    snapshot, usage_reports = reader.wait_first()
    scene, scene_key = None, None
    running = True

    while running:
        frame_start = time.monotonic()
        snapshot, usage_reports = reader.latest()

        taps, quit_requested = output.taps()
        running = not quit_requested and not stop_requested
        now = datetime.now()
        # The scene only changes when the data or the minute does: rebuilding
        # it every frame was pure waste on a Pi.
        key = (id(snapshot), id(usage_reports), now.strftime("%H:%M"))
        if key != scene_key:
            scene, scene_key = renderer.build_scene(snapshot, now=now, usage=usage_reports), key
        stage.frame(pygame, canvas, fonts, scene, frame_start, taps)
        # The framebuffer output only pushes bands that changed, so a still
        # frame costs nothing on SPI even though we redraw every tick.
        output.present(canvas)
        time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - frame_start)))

    reader.stop()
    pygame.quit()
    return 0


class StateReader:
    """Reads the snapshot on its own thread, once a second.

    The frame loop never waits on SQLite: a slow or locked database (up to
    sqlite's 5 s busy timeout) only delays the *next* snapshot, and a failed
    read keeps showing the last good one instead of killing the display.
    """

    def __init__(self, runtime, interval: float = 1.0) -> None:
        import threading

        self.runtime = runtime
        self.interval = interval
        self._lock = threading.Lock()
        self._state = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="jiri-state-reader", daemon=True)
        self.lines: dict[tuple[str, str], tuple[str, ...]] = {}
        self._wanted: set[tuple[str, str]] = set()
        self._lines_at = 0.0

    def want(self, bucket: tuple[str, str]) -> None:
        """Called from the frame loop on a miss: just remember it (no I/O)."""
        self._wanted.add(bucket)

    def _refresh_lines(self) -> None:
        from jiri import ai

        buckets = set(self.lines) | set(self._wanted)
        fresh = {}
        for category, mood in buckets:
            rows = ai.cached_lines(category, mood, db_path=self.runtime.db_path)
            if not rows:
                # Log demand (throttled in ai) so the worker writes some lines.
                ai.pick(category, mood, "demand", db_path=self.runtime.db_path)
            fresh[(category, mood)] = rows
        self.lines = fresh
        self._wanted -= set(fresh)

    def start(self) -> "StateReader":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                state = _read_state(self.runtime)
                with self._lock:
                    self._state = state
                self._ready.set()
                if self._wanted or time.monotonic() - self._lines_at > 60:
                    self._refresh_lines()
                    self._lines_at = time.monotonic()
            except Exception:  # noqa: BLE001 - keep the last good snapshot
                pass
            self._stop.wait(self.interval)

    def wait_first(self, timeout: float = 30.0):
        self._ready.wait(timeout)
        state = self.latest()
        if state is None:
            raise RuntimeError("JIRI could not read its database at startup")
        return state

    def latest(self):
        with self._lock:
            return self._state


def _read_state(runtime, panel: str | None = None):
    """One read-only snapshot plus the latest AI usage reports."""
    snapshot = runtime.screen_snapshot() if panel in (None, "usage") else runtime.screen_snapshot(panel=panel)
    try:
        from jiri import usage

        reports = usage.visible_latest(runtime.db_path)
    except Exception:  # noqa: BLE001 - a broken usage table must not kill the face
        reports = {}
    order = {"claude": 0, "chatgpt": 1}
    return snapshot, tuple(sorted(reports.values(), key=lambda r: order.get(r.provider, 9)))


def _make_output(pygame, kind: str, size, cfg):
    from . import output

    if kind == "fb":
        device = os.environ.get("JIRI_FB_DEVICE") or output.find_panel_framebuffer()
        touch = _make_touch(output, size)
        fb = output.FramebufferOutput(pygame, size, device, touch)
        if touch is not None and fb.rotation:
            touch.rotate_for(fb.rotation)
        return fb
    return output.SdlOutput(pygame, size, cfg.display.fullscreen, cfg.assistant.name)


def _make_touch(output, size):
    """Pick the touch backend.

    `JIRI_TOUCH_DEVICE=spi:/dev/spidev0.1` polls the XPT2046 directly (dead
    PENIRQ line); any other value is an evdev node. Unset: an evdev touchscreen
    if the kernel exposes one, else the SPI chip if spidev0.1 exists, else none.
    """
    cal = os.environ.get("JIRI_TOUCH_CAL", "")
    dev = os.environ.get("JIRI_TOUCH_DEVICE", "").strip()
    if not dev:
        dev = output.find_touch_device() or ""
        if not dev and os.path.exists(output.SPI_TOUCH_DEVICE):
            dev = "spi:" + output.SPI_TOUCH_DEVICE
    if not dev:
        return None
    try:
        if dev.startswith("spi:"):
            return output.SpiTouch(dev[4:] or output.SPI_TOUCH_DEVICE, size, cal)
        return output.EvdevTouch(dev, size, cal)
    except OSError:  # no touch beats no face
        return None


if __name__ == "__main__":
    raise SystemExit(run())
