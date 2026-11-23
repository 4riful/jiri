"""Where frames go, and where taps come from.

Two backends behind one tiny interface (`present(canvas)`, `taps()`):

- `SdlOutput`  — a normal pygame window. Dev on WSL, or an HDMI screen.
- `FramebufferOutput` — the 3.5" SPI panel on the GPIO header. SDL2 has no
  fbcon driver, so we render offscreen (SDL dummy driver) and write the panel's
  /dev/fbN ourselves. Only row bands that changed are written: on SPI a full
  480x320 RGB565 frame is ~2.4 Mbit, so an unchanged frame must cost nothing.
  Touch comes from evdev (ads7846/XPT2046), or — when the panel's PENIRQ line
  is dead — from `SpiTouch` polling the XPT2046 over /dev/spidev0.1. Both are
  calibrated in software.

Everything about the real panel (fb number, bpp, touch axes) is a hardware
unknown — see docs/PI_DISPLAY_CHECKLIST.md.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
import queue
import struct
import threading
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
        touch: "EvdevTouch | SpiTouch | None" = None,
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


class _TouchMapping:
    """Raw resistive-panel coordinates -> screen pixels, shared by every touch
    backend.

    Calibration `JIRI_TOUCH_CAL="xmin,xmax,ymin,ymax[,swap]"` (in the panel's
    final, rotated orientation) overrides the default ranges. A reversed range
    (xmin > xmax) inverts that axis; `swap` exchanges raw X and Y first.
    """

    size: tuple[int, int]
    xmin = xmax = ymin = ymax = 0
    swap = False
    calibrated = False

    def _init_mapping(self, size, calibration: str, default_x, default_y) -> None:
        """`default_x`/`default_y` are (lo, hi) or a zero-arg callable giving it,
        only consulted when no calibration string is supplied."""
        self.size = size
        parts = [p.strip() for p in (calibration or "").split(",") if p.strip()]
        if len(parts) >= 4:
            self.xmin, self.xmax, self.ymin, self.ymax = (int(p) for p in parts[:4])
            self.swap = len(parts) > 4 and parts[4].lower() in {"1", "swap", "true"}
            self.calibrated = True
        else:
            self.xmin, self.xmax = default_x() if callable(default_x) else default_x
            self.ymin, self.ymax = default_y() if callable(default_y) else default_y
            self.swap = False
            self.calibrated = False

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


class EvdevTouch(_TouchMapping):
    """Single-touch resistive panel -> screen taps, via the kernel's evdev node.

    Calibration env `JIRI_TOUCH_CAL="xmin,xmax,ymin,ymax[,swap]"` overrides the
    kernel's reported ranges; ads7846 ranges are rarely right out of the box.
    """

    def __init__(self, device: str, size: tuple[int, int], calibration: str = "") -> None:
        self.device = device
        self._retry_at = 0.0
        self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        self.x = self.y = 0
        self.down = False
        self._init_mapping(
            size, calibration, lambda: self._range(ABS_X, size[0]), lambda: self._range(ABS_Y, size[1])
        )

    def _range(self, axis: int, fallback: int) -> tuple[int, int]:
        try:
            buf = fcntl.ioctl(self.fd, _eviocgabs(axis), bytes(_ABSINFO.size))
            _, lo, hi, *_ = _ABSINFO.unpack(buf)
            return (lo, hi) if hi > lo else (0, fallback)
        except OSError:
            return 0, fallback

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


# --- polled SPI touch (XPT2046 / ADS7846 without a working PENIRQ) -----------
#
# On some boards the controller answers over SPI but its PENIRQ line is stuck,
# so the kernel ads7846 driver never sees an interrupt. Then the driver is not
# bound, /dev/spidev0.1 exists, and we poll the chip ourselves from a small
# daemon thread. The frame loop only ever drains a queue.

SPI_TOUCH_DEVICE = "/dev/spidev0.1"
SPI_SPEED_HZ = 1_000_000

# XPT2046 control bytes: start bit, channel, 12-bit, differential, PD=00.
XPT_X, XPT_Y, XPT_Z1, XPT_Z2 = 0xD0, 0x90, 0xB0, 0xC0
XPT_MIN, XPT_MAX = 50, 4045          # outside this the reading is an open/rail value
DEFAULT_Z_MIN = 80
AXIS_SAMPLES = 5
Z_SAMPLES = 3
TOUCH_MIN_SAMPLES = 2                # touched samples needed to count as a tap
RELEASE_SAMPLES = 2                  # untouched samples needed to count as release
MAX_HELD_SAMPLES = 64                # bound memory during a long press
RETRY_S = 5.0


def _ioc_write(nr: int, size: int) -> int:
    # _IOW('k', nr, size) with the generic Linux layout: dir(2)|size(14)|type(8)|nr(8)
    return (1 << 30) | (size << 16) | (ord("k") << 8) | nr


class _SpiIocTransfer(ctypes.Structure):
    """`struct spi_ioc_transfer` from <linux/spi/spidev.h> (32 bytes on every ABI)."""

    _fields_ = [
        ("tx_buf", ctypes.c_uint64),
        ("rx_buf", ctypes.c_uint64),
        ("len", ctypes.c_uint32),
        ("speed_hz", ctypes.c_uint32),
        ("delay_usecs", ctypes.c_uint16),
        ("bits_per_word", ctypes.c_uint8),
        ("cs_change", ctypes.c_uint8),
        ("tx_nbits", ctypes.c_uint8),
        ("rx_nbits", ctypes.c_uint8),
        ("word_delay_usecs", ctypes.c_uint8),
        ("pad", ctypes.c_uint8),
    ]


SPI_IOC_WR_MODE = _ioc_write(1, 1)
SPI_IOC_WR_BITS_PER_WORD = _ioc_write(3, 1)
SPI_IOC_WR_MAX_SPEED_HZ = _ioc_write(4, 4)
SPI_IOC_MESSAGE_1 = _ioc_write(0, ctypes.sizeof(_SpiIocTransfer))


class SpiDev:
    """Minimal stdlib spidev: mode 0, 8-bit words, full-duplex transfers."""

    def __init__(self, device: str, speed_hz: int = SPI_SPEED_HZ) -> None:
        self.speed_hz = speed_hz
        self.fd = os.open(device, os.O_RDWR)
        try:
            fcntl.ioctl(self.fd, SPI_IOC_WR_MODE, struct.pack("B", 0))
            fcntl.ioctl(self.fd, SPI_IOC_WR_BITS_PER_WORD, struct.pack("B", 8))
            fcntl.ioctl(self.fd, SPI_IOC_WR_MAX_SPEED_HZ, struct.pack("I", speed_hz))
        except OSError:
            os.close(self.fd)
            raise

    def transfer(self, data: bytes) -> bytes:
        n = len(data)
        tx = ctypes.create_string_buffer(bytes(data), n)
        rx = ctypes.create_string_buffer(n)
        xfer = _SpiIocTransfer(
            tx_buf=ctypes.addressof(tx), rx_buf=ctypes.addressof(rx), len=n,
            speed_hz=self.speed_hz, bits_per_word=8,
        )
        fcntl.ioctl(self.fd, SPI_IOC_MESSAGE_1, xfer)
        return rx.raw

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def xpt_decode(rx: bytes) -> int:
    """12-bit result from a 3-byte [cmd, 0, 0] exchange."""
    return ((rx[1] << 8) | rx[2]) >> 3 & 0xFFF


def _median(values) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


class SpiTouch(_TouchMapping):
    """Polled XPT2046 over spidev -> screen taps. Same interface as EvdevTouch.

    A tap is emitted on release after >= 2 touched samples (release = 2
    untouched samples in a row), at the median of the touched positions.
    Env: `JIRI_TOUCH_CAL` (as evdev), `JIRI_TOUCH_Z_MIN` (pressure threshold,
    default 80), `JIRI_TOUCH_R_MAX` (optional cap on the computed touch
    resistance, unitless X/4096*(Z2/Z1-1); unset = no cap).
    """

    def __init__(
        self,
        device: str = SPI_TOUCH_DEVICE,
        size: tuple[int, int] = (480, 320),
        calibration: str = "",
        *,
        z_min: int | None = None,
        r_max: float | None = None,
        hz: float = 60.0,
        spi_factory=None,
        start: bool = True,
    ) -> None:
        self.device = device[4:] if device.startswith("spi:") else device
        self._init_mapping(size, calibration, (0, 4095), (0, 4095))
        self.z_min = z_min if z_min is not None else _env_int("JIRI_TOUCH_Z_MIN", DEFAULT_Z_MIN)
        self.r_max = r_max if r_max is not None else _env_float("JIRI_TOUCH_R_MAX")
        self.period = 1.0 / hz
        self._spi_factory = spi_factory or SpiDev
        self._spi = None
        self._retry_at = 0.0
        self._lock = threading.Lock()
        self._taps: queue.SimpleQueue = queue.SimpleQueue()
        self._held: list[tuple[int, int]] = []
        self._released = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if start:
            self.start()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jiri-spi-touch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        with self._lock:
            self._close()

    close = stop

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:  # noqa: BLE001 - the sampler must never die loudly
                pass
            self._stop.wait(self.period)

    # -- SPI ---------------------------------------------------------------
    def _close(self) -> None:
        if self._spi is not None:
            try:
                self._spi.close()
            except Exception:  # noqa: BLE001
                pass
        self._spi = None

    def _ensure_open(self):
        if self._spi is None:
            self._spi = self._spi_factory(self.device)
        return self._spi

    def _read(self, cmd: int, n: int) -> int:
        spi = self._spi
        return _median([xpt_decode(spi.transfer(bytes((cmd, 0, 0)))) for _ in range(n)])

    def _sample(self, full: bool) -> tuple[int, int, int, int]:
        self._ensure_open()
        z1 = self._read(XPT_Z1, Z_SAMPLES)
        z2 = self._read(XPT_Z2, Z_SAMPLES)
        if not full and z1 <= self.z_min:
            return 0, 0, z1, z2          # not pressed: skip the X/Y reads
        return self._read(XPT_X, AXIS_SAMPLES), self._read(XPT_Y, AXIS_SAMPLES), z1, z2

    def raw_sample(self) -> tuple[int, int, int, int]:
        """One (x, y, z1, z2) reading for calibration/debug. Raises OSError if
        the device can't be opened or read."""
        with self._lock:
            try:
                return self._sample(full=True)
            except OSError:
                self._close()
                raise

    def is_touched(self, x: int, y: int, z1: int, z2: int) -> bool:
        if z1 <= self.z_min or not (XPT_MIN < x < XPT_MAX and XPT_MIN < y < XPT_MAX):
            return False
        if self.r_max is not None and z2 > z1:
            if x / 4096 * (z2 / z1 - 1) > self.r_max:
                return False
        return True

    # -- sampling state machine (one call per tick) --------------------------
    def step(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._spi is None:
                if now < self._retry_at:
                    return
                self._retry_at = now + RETRY_S
            try:
                sample = self._sample(full=False)
            except Exception:  # noqa: BLE001 - device gone / ioctl failed
                self._close()
                self._retry_at = now + RETRY_S
                self._held.clear()
                self._released = 0
                return
        if self.is_touched(*sample):
            self._released = 0
            self._held.append((sample[0], sample[1]))
            if len(self._held) > MAX_HELD_SAMPLES:
                del self._held[0]
        elif self._held:
            self._released += 1
            if self._released >= RELEASE_SAMPLES:
                if len(self._held) >= TOUCH_MIN_SAMPLES:
                    self._taps.put((_median(p[0] for p in self._held), _median(p[1] for p in self._held)))
                self._held = []
                self._released = 0

    def poll(self) -> list[tuple[int, int]]:
        """Taps since the last call, mapped to screen pixels. Never raises."""
        taps = []
        while True:
            try:
                rx, ry = self._taps.get_nowait()
            except queue.Empty:
                return taps
            taps.append(self.map(rx, ry))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str) -> float | None:
    try:
        raw = os.environ.get(name, "")
        return float(raw) if raw else None
    except ValueError:
        return None


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
