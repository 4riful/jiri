"""A live, animated preview of the device for the browser (`/screen/live`).

The still `/screen.png` hides everything that makes JIRI alive: blinking,
gaze, spring motion, the typing effect. This runs the *real* `Stage` on a
background thread at ~10 FPS (same code path as `pygame_app.run`), keeps the
latest frame as JPEG bytes, and lets the web layer stream it as MJPEG.

Pi 3B budget: the thread only exists while someone is watching. It starts on
the first viewer and stops itself after `idle_timeout` seconds with no viewer
and no tap. Rendering shares `renderer._PNG_LOCK` with `/screen.png`, so the
two never touch pygame at the same time (one pygame per process).

Like the device loop, the frame thread never touches SQLite: a `StateReader`
reads the snapshot once a second on its own thread, and the voice closure is a
pure in-memory lookup. A failed read or a broken frame keeps the last frame.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import zlib
from datetime import datetime

from . import renderer

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 320
_SETUP_LOCK = threading.Lock()


def shared_lock() -> threading.Lock:
    """The process-wide pygame lock, shared with renderer.render_snapshot_png."""
    with _SETUP_LOCK:
        if renderer._PNG_LOCK is None:
            renderer._PNG_LOCK = threading.Lock()
        return renderer._PNG_LOCK


def _fonts(pygame):
    """Fonts are loaded once per process (caller holds the shared lock)."""
    if renderer._PNG_FONTS is None:
        pygame.font.init()
        renderer._PNG_FONTS = renderer.load_fonts(pygame)
    return renderer._PNG_FONTS


class LivePreview:
    def __init__(
        self,
        runtime=None,
        *,
        fps: float = 10.0,
        idle_timeout: float = 30.0,
        reader_factory=None,
        stage_factory=None,
    ) -> None:
        self.runtime = runtime
        self.fps = fps
        self.idle_timeout = idle_timeout
        self._reader_factory = reader_factory
        self._stage_factory = stage_factory
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._taps: list[tuple[int, int]] = []
        self._viewers = 0
        self._last_activity = time.monotonic()
        self.frame: bytes = b""
        self.mimetype = "image/jpeg"
        self.counter = 0
        self.stage = None
        self.frame_seconds = 0.0  # last frame's render+encode time (diagnostics)

    # -- viewers -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def acquire(self) -> None:
        """A viewer arrived: count it and make sure the thread runs."""
        with self._cond:
            self._viewers += 1
            self._last_activity = time.monotonic()
        self.ensure_running()

    def release(self) -> None:
        with self._cond:
            self._viewers = max(0, self._viewers - 1)
            self._last_activity = time.monotonic()

    def tap(self, x: float, y: float) -> None:
        """Queue a touch (480x320 coords) for the next frame."""
        px = int(max(0, min(WIDTH - 1, x)))
        py = int(max(0, min(HEIGHT - 1, y)))
        with self._cond:
            self._taps.append((px, py))
            del self._taps[:-8]  # never let a flood of taps pile up
            self._last_activity = time.monotonic()
        self.ensure_running()

    def ensure_running(self) -> None:
        with self._cond:
            if self.running:
                return
            self._stop = threading.Event()
            self._last_activity = time.monotonic()
            self._thread = threading.Thread(target=self._run, name="jiri-live-preview", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        with self._cond:
            self._cond.notify_all()

    def wait_frame(self, after: int, timeout: float = 1.0) -> tuple[int, bytes, str]:
        """Block until a frame newer than `after` exists (or timeout)."""
        with self._cond:
            self._cond.wait_for(lambda: self.counter > after or not self.running, timeout)
            return self.counter, self.frame, self.mimetype

    def _keep_going(self) -> bool:
        """Decide (atomically with acquire/tap) whether the thread lives on.

        On exit the thread unregisters itself under the same lock, so a viewer
        arriving at that instant starts a fresh thread instead of waiting on a
        dying one."""
        with self._cond:
            idle = self._viewers == 0 and time.monotonic() - self._last_activity > self.idle_timeout
            if self._stop.is_set() or idle:
                if self._thread is threading.current_thread():
                    self._thread = None
                self._cond.notify_all()
                return False
            return True

    # -- the thread ----------------------------------------------------------

    def _make_reader(self):
        if self._reader_factory is not None:
            return self._reader_factory(self.runtime)
        from .pygame_app import StateReader

        return StateReader(self.runtime).start()

    def _make_stage(self, reader):
        def voice(category: str, mood: str, seed):
            # Same in-memory lookup as the device: never SQLite from a frame.
            lines = reader.lines.get((category, mood))
            if not lines:
                reader.want((category, mood))
                return None
            return lines[zlib.crc32(str(seed).encode("utf-8")) % len(lines)]

        if self._stage_factory is not None:
            return self._stage_factory(voice)
        from .stage import Stage

        # No boot splash: the preview joins a device that is already running.
        return Stage(voice=voice, boot=False)

    def _run(self) -> None:
        reader = None
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame

            lock = shared_lock()
            reader = self._make_reader()
            stage = self.stage = self._make_stage(reader)
            canvas = None
            scene, scene_key = None, None
            period = 1.0 / max(1.0, self.fps)
            while self._keep_going():
                frame_start = time.monotonic()
                try:
                    state = reader.latest()
                    if state is not None:
                        snapshot, usage_reports = state
                        now = datetime.now()
                        key = (id(snapshot), id(usage_reports), now.strftime("%H:%M"))
                        if key != scene_key:
                            scene, scene_key = renderer.build_scene(snapshot, now=now, usage=usage_reports), key
                        with self._cond:
                            taps, self._taps = self._taps, []
                        with lock:
                            fonts = _fonts(pygame)
                            size = (getattr(snapshot, "width", WIDTH) or WIDTH, getattr(snapshot, "height", HEIGHT) or HEIGHT)
                            if canvas is None or canvas.get_size() != size:
                                canvas = pygame.Surface(size)
                            stage.frame(pygame, canvas, fonts, scene, frame_start, taps)
                            data, mimetype = _encode(pygame, canvas)
                        self.frame_seconds = time.monotonic() - frame_start
                        with self._cond:
                            self.frame, self.mimetype = data, mimetype
                            self.counter += 1
                            self._cond.notify_all()
                except Exception:  # noqa: BLE001 - keep the last frame, keep going
                    log.debug("live preview frame failed", exc_info=True)
                self._stop.wait(max(0.0, period - (time.monotonic() - frame_start)))
        except Exception:  # noqa: BLE001 - never raise out of the thread
            log.warning("live preview stopped", exc_info=True)
        finally:
            if reader is not None and hasattr(reader, "stop"):
                try:
                    reader.stop()
                except Exception:  # noqa: BLE001
                    pass
            with self._cond:
                self._cond.notify_all()


_JPEG_OK: bool | None = None


def _encode(pygame, surface) -> tuple[bytes, str]:
    """JPEG when SDL_image supports it (small, fast), else PNG."""
    global _JPEG_OK
    if _JPEG_OK is not False:
        try:
            buf = io.BytesIO()
            pygame.image.save(surface, buf, "jpg")
            data = buf.getvalue()
            if data[:2] == b"\xff\xd8":
                _JPEG_OK = True
                return data, "image/jpeg"
        except Exception:  # noqa: BLE001
            pass
        _JPEG_OK = False
    buf = io.BytesIO()
    pygame.image.save(surface, buf, "png")
    return buf.getvalue(), "image/png"


_INSTANCES: dict[str, LivePreview] = {}
_INSTANCES_LOCK = threading.Lock()


def get(runtime) -> LivePreview:
    """The one LivePreview for this process (per database)."""
    key = str(getattr(runtime, "db_path", ""))
    with _INSTANCES_LOCK:
        preview = _INSTANCES.get(key)
        if preview is None:
            preview = _INSTANCES[key] = LivePreview(runtime)
        return preview


def stop_all() -> None:
    with _INSTANCES_LOCK:
        previews = list(_INSTANCES.values())
        _INSTANCES.clear()
    for preview in previews:
        preview.stop()
