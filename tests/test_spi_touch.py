"""Polled XPT2046 touch (SpiTouch) against a fake SPI layer."""

from __future__ import annotations

import ctypes
import os

import pytest

from jiri.ui import output, pygame_app


def enc(value: int) -> bytes:
    """What the chip sends back for a 12-bit reading in a [cmd, 0, 0] exchange."""
    v = value << 3
    return bytes((0, (v >> 8) & 0xFF, v & 0xFF))


class FakeSpi:
    """Answers each command byte from a per-channel script (cycled)."""

    def __init__(self, x=0, y=0, z1=0, z2=0):
        self.set(x, y, z1, z2)
        self.sent: list[bytes] = []
        self.closed = False
        self.fail = False

    def set(self, x=0, y=0, z1=0, z2=0):
        self.values = {output.XPT_X: x, output.XPT_Y: y, output.XPT_Z1: z1, output.XPT_Z2: z2}
        self.idx = {k: 0 for k in self.values}

    def transfer(self, data: bytes) -> bytes:
        if self.fail:
            raise OSError(19, "No such device")
        self.sent.append(bytes(data))
        cmd = data[0]
        v = self.values[cmd]
        if isinstance(v, list):
            i = self.idx[cmd]
            self.idx[cmd] = i + 1
            v = v[i % len(v)]
        return enc(v)

    def close(self):
        self.closed = True


def make(fake, **kw):
    kw.setdefault("calibration", "")
    return output.SpiTouch("/dev/spidev0.1", (480, 320), spi_factory=lambda dev: fake, start=False, **kw)


def press(t, fake, x, y, n, z1=400, z2=900):
    fake.set(x, y, z1, z2)
    for _ in range(n):
        t.step()


def release(t, fake, n):
    fake.set(0, 0, 0, 0)
    for _ in range(n):
        t.step()


def test_ioctl_numbers_and_struct_layout():
    assert ctypes.sizeof(output._SpiIocTransfer) == 32
    assert output._SpiIocTransfer.len.offset == 16
    assert output._SpiIocTransfer.speed_hz.offset == 20
    assert output._SpiIocTransfer.delay_usecs.offset == 24
    assert output.SPI_IOC_WR_MODE == 0x40016B01
    assert output.SPI_IOC_WR_BITS_PER_WORD == 0x40016B03
    assert output.SPI_IOC_WR_MAX_SPEED_HZ == 0x40046B04
    assert output.SPI_IOC_MESSAGE_1 == 0x40206B00


def test_value_decoding():
    assert output.xpt_decode(enc(0)) == 0
    assert output.xpt_decode(enc(4095)) == 4095
    assert output.xpt_decode(enc(1234)) == 1234
    assert output.xpt_decode(bytes((0, 0xFF, 0xFF))) == 4095   # low 3 bits are padding


def test_raw_sample_takes_medians_and_sends_xpt_commands():
    fake = FakeSpi(x=[1000, 3000, 1010, 990, 1005], y=[2000, 2001, 50, 1999, 2002], z1=[300, 0, 310], z2=900)
    t = make(fake)
    assert t.raw_sample() == (1005, 2000, 300, 900)
    cmds = {s[0] for s in fake.sent}
    assert cmds == {0xD0, 0x90, 0xB0, 0xC0}
    assert all(len(s) == 3 and s[1:] == b"\0\0" for s in fake.sent)


def test_pressure_threshold_and_rail_values(monkeypatch):
    monkeypatch.setenv("JIRI_TOUCH_Z_MIN", "120")
    t = make(FakeSpi())
    assert t.z_min == 120
    assert not t.is_touched(2000, 2000, 120, 900)          # at threshold: not pressed
    assert t.is_touched(2000, 2000, 121, 900)
    assert not t.is_touched(4095, 2000, 500, 900)          # rail: open circuit
    assert not t.is_touched(2000, 30, 500, 900)
    capped = make(FakeSpi(), r_max=1.0)
    assert capped.is_touched(2048, 2000, 500, 1000)        # r = 0.5
    assert not capped.is_touched(2048, 2000, 100, 1000)    # r = 4.5: too soft


def test_untouched_poll_skips_xy_reads():
    fake = FakeSpi(z1=10)
    t = make(fake)
    t.step()
    assert {s[0] for s in fake.sent} == {output.XPT_Z1, output.XPT_Z2}


def test_debounced_press_gives_exactly_one_tap_at_mapped_median():
    fake = FakeSpi()
    t = make(fake, calibration="0,4095,0,4095")
    fake.set(x=[2047, 2047, 2047, 2047, 2047], y=[1023] * 5, z1=400, z2=900)
    t.step()
    fake.set(x=[2100] * 5, y=[1100] * 5, z1=400, z2=900)
    t.step()
    fake.set(x=[2047] * 5, y=[1023] * 5, z1=400, z2=900)
    t.step()
    release(t, fake, 1)
    assert t.poll() == []                                  # one untouched sample isn't a release
    release(t, fake, 1)
    taps = t.poll()
    assert taps == [t.map(2047, 1023)]
    assert taps == [(239, 79)]
    release(t, fake, 5)
    assert t.poll() == []                                  # no repeat tap


def test_brief_dropout_does_not_split_a_press():
    fake = FakeSpi()
    t = make(fake)
    press(t, fake, 2000, 2000, 3)
    release(t, fake, 1)
    press(t, fake, 2000, 2000, 3)
    release(t, fake, 2)
    assert len(t.poll()) == 1


def test_single_glitch_sample_is_not_a_tap():
    fake = FakeSpi()
    t = make(fake)
    press(t, fake, 2000, 2000, 1)
    release(t, fake, 3)
    assert t.poll() == []


def test_calibration_and_rotation_are_shared_with_evdev():
    t = make(FakeSpi(), calibration="200,3900,300,3800")
    assert t.calibrated and t.map(200, 300) == (0, 0) and t.map(3900, 3800) == (479, 319)
    t.rotate_for(90)                                       # calibrated: rotation is a no-op
    assert not t.swap
    r = make(FakeSpi())
    r.rotate_for(270)
    assert r.swap and (r.xmin, r.xmax) == (4095, 0)
    assert issubclass(output.EvdevTouch, output._TouchMapping)


def test_device_gone_never_raises_and_retries(monkeypatch):
    fake = FakeSpi()
    opens = []

    def factory(dev):
        opens.append(dev)
        if len(opens) == 2:
            raise OSError(2, "No such file")
        return fake

    clock = [100.0]
    monkeypatch.setattr(output.time, "monotonic", lambda: clock[0])
    t = output.SpiTouch("spi:/dev/spidev0.1", (480, 320), spi_factory=factory, start=False)
    assert t.device == "/dev/spidev0.1"
    press(t, fake, 2000, 2000, 2)
    fake.fail = True
    t.step()                                               # ioctl fails mid-press
    assert t._spi is None and fake.closed and t.poll() == []
    t.step()
    assert len(opens) == 1                                 # waits before retrying
    clock[0] += 5.1
    t.step()                                               # retry: open fails quietly
    assert len(opens) == 2 and t._spi is None
    clock[0] += 5.1
    fake.fail = False
    press(t, fake, 2000, 2000, 2)
    release(t, fake, 2)
    assert len(opens) == 3 and len(t.poll()) == 1


def test_thread_starts_and_stops(tmp_path):
    t = output.SpiTouch(str(tmp_path / "missing"), (480, 320), hz=200)
    assert t._thread is not None and t._thread.daemon and t._thread.is_alive()
    assert t.poll() == []
    t.stop()
    assert t._thread is None


def test_real_spidev_open_failure_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        output.SpiDev(str(tmp_path / "nope"))


# --- backend selection ------------------------------------------------------

@pytest.fixture
def fake_backends(monkeypatch):
    made = []

    class Spi:
        def __init__(self, device, size, cal):
            made.append(("spi", device, cal))

    class Ev:
        def __init__(self, device, size, cal):
            made.append(("evdev", device, cal))

    monkeypatch.setattr(output, "SpiTouch", Spi)
    monkeypatch.setattr(output, "EvdevTouch", Ev)
    monkeypatch.delenv("JIRI_TOUCH_DEVICE", raising=False)
    monkeypatch.setenv("JIRI_TOUCH_CAL", "1,2,3,4")
    return made


def test_select_explicit_spi(monkeypatch, fake_backends):
    monkeypatch.setenv("JIRI_TOUCH_DEVICE", "spi:/dev/spidev0.1")
    monkeypatch.setattr(output, "find_touch_device", lambda: "/dev/input/event0")
    assert pygame_app._make_touch(output, (480, 320)) is not None
    assert fake_backends == [("spi", "/dev/spidev0.1", "1,2,3,4")]


def test_select_explicit_evdev(monkeypatch, fake_backends):
    monkeypatch.setenv("JIRI_TOUCH_DEVICE", "/dev/input/event3")
    pygame_app._make_touch(output, (480, 320))
    assert fake_backends == [("evdev", "/dev/input/event3", "1,2,3,4")]


def test_select_auto_prefers_evdev(monkeypatch, fake_backends):
    monkeypatch.setattr(output, "find_touch_device", lambda: "/dev/input/event1")
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    pygame_app._make_touch(output, (480, 320))
    assert fake_backends == [("evdev", "/dev/input/event1", "1,2,3,4")]


def test_select_auto_falls_back_to_spidev(monkeypatch, fake_backends):
    monkeypatch.setattr(output, "find_touch_device", lambda: None)
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/dev/spidev0.1")
    pygame_app._make_touch(output, (480, 320))
    assert fake_backends == [("spi", "/dev/spidev0.1", "1,2,3,4")]


def test_select_auto_none(monkeypatch, fake_backends):
    monkeypatch.setattr(output, "find_touch_device", lambda: None)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    assert pygame_app._make_touch(output, (480, 320)) is None
    assert fake_backends == []


def test_select_evdev_open_failure_degrades_to_no_touch(monkeypatch):
    monkeypatch.setenv("JIRI_TOUCH_DEVICE", "/nonexistent/event9")
    assert pygame_app._make_touch(output, (480, 320)) is None


def test_make_output_wires_touch_and_rotation(monkeypatch):
    rotated = []

    class Touch:
        def rotate_for(self, r):
            rotated.append(r)

    class Fb:
        def __init__(self, pygame, size, device, touch):
            self.touch, self.rotation = touch, 90

    monkeypatch.setenv("JIRI_FB_DEVICE", "/dev/fb1")
    monkeypatch.setattr(pygame_app, "_make_touch", lambda out, size: Touch())
    monkeypatch.setattr(output, "FramebufferOutput", Fb)
    fb = pygame_app._make_output(None, "fb", (480, 320), None)
    assert isinstance(fb.touch, Touch) and rotated == [90]
