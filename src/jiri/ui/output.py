"""Where frames go, and where taps come from.

Two backends behind one tiny interface (`present(canvas)`, `taps()`):

- `SdlOutput`  — a normal pygame window. Dev on WSL, or an HDMI screen.
- `FramebufferOutput` — the 3.5" SPI panel on the GPIO header. SDL2 has no
  fbcon driver, so we render offscreen (SDL dummy driver) and write the panel's
  /dev/fbN ourselves. Only row bands that changed are written: on SPI a full
  480x320 RGB565 frame is ~2.4 Mbit, so an unchanged frame must cost nothing.
  Touch comes straight from evdev (ads7846/XPT2046), calibrated in software.

Everything about the real panel (fb number, bpp, touch axes) is a hardware
unknown — see docs/PI_DISPLAY_CHECKLIST.md.
"""

from __future__ import annotations

import fcntl
import os
import struct
import time

BAND_ROWS = 16


class SdlOutput:
    def __init__(self, pygame, size: tuple[int, int], fullscreen: bool, caption: str = "JIRI") -> None:
        self.pygame = pygame
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.window = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(caption)
        if fullscreen:
            pygame.mouse.set_visible(False)

    def present(self, canvas) -> None:
        self.window.blit(canvas, (0, 0))
        self.pygame.display.flip()

    def taps(self) -> tuple[list[tuple[int, int]], bool]:
        taps, quit_requested = [], False
        for event in self.pygame.event.get():
            if event.type == self.pygame.QUIT:
                quit_requested = True
            elif event.type == self.pygame.KEYDOWN and event.key == self.pygame.K_ESCAPE:
                quit_requested = True
            elif event.type == self.pygame.MOUSEBUTTONUP:
                taps.append(event.pos)
        return taps, quit_requested


class FramebufferOutput:
    def __init__(
        self,
        pygame,
        size: tuple[int, int],
        device: str,
        touch: "EvdevTouch | None" = None,
        sysfs_root: str = "/sys/class/graphics",
    ) -> None:
        self.pygame = pygame
        self.size = size
        self.device = device
        sysfs = os.path.join(sysfs_root, os.path.basename(device))
        self.bpp = int(_read(f"{sysfs}/bits_per_pixel", "16"))
        fb_w, fb_h = (int(v) for v in _read(f"{sysfs}/virtual_size", f"{size[0]},{size[1]}").split(","))
        self.rotation = 0
        if (fb_w, fb_h) == (size[1], size[0]):
            # DRM panels (e.g. ili9486 via the piscreen overlay) expose their
            # native portrait framebuffer even when the overlay says rotate=:
            # turn each landscape frame ourselves. JIRI_FB_ROTATE picks 90/270.
            self.rotation = 270 if os.environ.get("JIRI_FB_ROTATE", "90").strip() == "270" else 90
        elif (fb_w, fb_h) != size:
            raise RuntimeError(f"{device} is {fb_w}x{fb_h}, expected {size[0]}x{size[1]} (check rotate= in the overlay)")
        self.fb_size = (fb_w, fb_h)
        self.stride = int(_read(f"{sysfs}/stride", str(fb_w * self.bpp // 8)))
        if self.bpp not in (16, 32):
            raise RuntimeError(f"{device} uses {self.bpp} bpp; only 16 and 32 are supported")
        self.fd = os.open(device, os.O_RDWR)
        if self.bpp == 16:
            self.scratch = pygame.Surface(self.fb_size, 0, 16, (0xF800, 0x07E0, 0x001F, 0))
        self.previous: list[bytes] = []
        self.touch = touch

    def _rows(self, canvas) -> tuple[bytes, int]:
        if self.rotation:
            canvas = self.pygame.transform.rotate(canvas, self.rotation)
        if self.bpp == 16:
            self.scratch.blit(canvas, (0, 0))
            return self.scratch.get_buffer().raw, self.scratch.get_pitch()
        return self.pygame.image.tobytes(canvas, "BGRA"), self.fb_size[0] * 4

    def present(self, canvas) -> int:
        """Write changed bands. Returns the number of bands written."""
        raw, pitch = self._rows(canvas)
        row_bytes = self.fb_size[0] * self.bpp // 8
        height = self.fb_size[1]
        written = 0
        bands = []
        for b, top in enumerate(range(0, height, BAND_ROWS)):
            bottom = min(height, top + BAND_ROWS)
            chunk = raw[top * pitch: bottom * pitch]
            bands.append(chunk)
            if self.previous and self.previous[b] == chunk:
                continue
            if pitch == self.stride == row_bytes:
                os.pwrite(self.fd, chunk, top * self.stride)
            else:
                for row in range(top, bottom):
                    start = row * pitch
                    os.pwrite(self.fd, raw[start:start + row_bytes], row * self.stride)
            written += 1
        self.previous = bands
        return written

    def taps(self) -> tuple[list[tuple[int, int]], bool]:
        return (self.touch.poll() if self.touch else []), False


# --- evdev touch ------------------------------------------------------------

EV_KEY, EV_ABS = 0x01, 0x03
ABS_X, ABS_Y = 0x00, 0x01
BTN_TOUCH = 0x14A
_EVENT = struct.Struct("llHHi")
_ABSINFO = struct.Struct("iiiiii")


def _eviocgabs(axis: int) -> int:
    # _IOR('E', 0x40 + axis, struct input_absinfo)
    return (2 << 30) | (_ABSINFO.size << 16) | (ord("E") << 8) | (0x40 + axis)


class EvdevTouch:
    """Single-touch resistive panel -> screen taps.

    Calibration env `JIRI_TOUCH_CAL="xmin,xmax,ymin,ymax[,swap]"` overrides the
    kernel's reported ranges; ads7846 ranges are rarely right out of the box.
    """

    def __init__(self, device: str, size: tuple[int, int], calibration: str = "") -> None:
        self.size = size
        self.device = device
        self._retry_at = 0.0
        self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        self.x = self.y = 0
        self.down = False
        parts = [p.strip() for p in calibration.split(",") if p.strip()]
        if len(parts) >= 4:
            self.xmin, self.xmax, self.ymin, self.ymax = (int(p) for p in parts[:4])
            self.swap = len(parts) > 4 and parts[4].lower() in {"1", "swap", "true"}
            self.calibrated = True
        else:
            self.xmin, self.xmax = self._range(ABS_X, size[0])
            self.ymin, self.ymax = self._range(ABS_Y, size[1])
            self.swap = False
            self.calibrated = False

    def _range(self, axis: int, fallback: int) -> tuple[int, int]:
        try:
            buf = fcntl.ioctl(self.fd, _eviocgabs(axis), bytes(_ABSINFO.size))
            _, lo, hi, *_ = _ABSINFO.unpack(buf)
            return (lo, hi) if hi > lo else (0, fallback)
        except OSError:
            return 0, fallback

    def rotate_for(self, rotation: int) -> None:
        """Match a rotated panel: swap axes (and their ranges); 270 also flips.
        Fine-tune with JIRI_TOUCH_CAL if taps land mirrored."""
        if rotation in (90, 270) and not self.calibrated:
            self.swap = True
            self.xmin, self.xmax, self.ymin, self.ymax = self.ymin, self.ymax, self.xmin, self.xmax
            if rotation == 90:
                self.ymin, self.ymax = self.ymax, self.ymin
            else:
                self.xmin, self.xmax = self.xmax, self.xmin

    def map(self, rx: int, ry: int) -> tuple[int, int]:
        if self.swap:
            rx, ry = ry, rx
        w, h = self.size
        # A reversed range (xmin > xmax) inverts that axis, which resistive
        # panels often need. Python's // floors toward -inf, so map via float.
        sx = int((rx - self.xmin) * (w - 1) / ((self.xmax - self.xmin) or 1))
        sy = int((ry - self.ymin) * (h - 1) / ((self.ymax - self.ymin) or 1))
        return max(0, min(w - 1, sx)), max(0, min(h - 1, sy))

    def poll(self) -> list[tuple[int, int]]:
        """Taps since the last call. Never raises: if the touch device goes
        away (driver reloaded, cable/board issue), JIRI keeps running without
        touch and quietly retries opening it every few seconds."""
        if self.fd is None:
            return self._reopen()
        taps = []
        while True:
            try:
                data = os.read(self.fd, _EVENT.size * 32)
            except BlockingIOError:
                break
            except OSError:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None
                self._retry_at = time.monotonic() + 5.0
                return taps
            if not data:
                break
            for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                _, _, etype, code, value = _EVENT.unpack_from(data, off)
                if etype == EV_ABS and code == ABS_X:
                    self.x = value
                elif etype == EV_ABS and code == ABS_Y:
                    self.y = value
                elif etype == EV_KEY and code == BTN_TOUCH:
                    if self.down and value == 0:
                        taps.append(self.map(self.x, self.y))
                    self.down = value == 1
        return taps


def _evdev_reopen(self) -> list:
    if time.monotonic() < self._retry_at:
        return []
    self._retry_at = time.monotonic() + 5.0
    try:
        self.fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        self.fd = None
    return []


EvdevTouch._reopen = _evdev_reopen


def find_touch_device() -> str | None:
    """First input device that looks like a resistive touchscreen."""
    try:
        text = open("/proc/bus/input/devices").read()
    except OSError:
        return None
    for block in text.split("\n\n"):
        if any(k in block for k in ("ADS7846", "XPT2046", "Touchscreen", "touchscreen")):
            for token in block.split():
                if token.startswith("event"):
                    return f"/dev/input/{token}"
    return None


def find_panel_framebuffer() -> str:
    """Prefer a non-HDMI framebuffer (the SPI panel is usually fb1)."""
    for n in range(4):
        name = _read(f"/sys/class/graphics/fb{n}/name", "")
        if name and not any(k in name.lower() for k in ("vc4", "bcm2708", "simple")):
            return f"/dev/fb{n}"
    return "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0"


def _read(path: str, default: str) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return default
