"""Benchmark JIRI's display loop headless, and estimate what a Pi 3B can do.

    PYTHONPATH=src .venv/bin/python scripts/bench_display.py [--seconds 10] [--fps 12]
        [--pi-factor 12] [--profile]

Runs the real `Stage` + `pages` for N simulated seconds per screen at a fixed
frame rate (simulated clock, so no sleeping) against a realistic scene, with
the SDL dummy driver. Every frame also goes through `output.FramebufferOutput`
writing to a temp file with a fake sysfs, to count the 16-row bands that
changed and turn them into SPI bytes.

Nothing here touches the real database, the network or /dev/fb*.

Pi 3B extrapolation is a flat multiplier (default 12x slower single-thread
than a modern desktop core). That's a rough figure, not a measurement: confirm
on the device with `--pi-factor 1` run on the Pi itself.

SPI models (which one applies depends on the panel driver; see
docs/PI_DISPLAY_CHECKLIST.md):
  bands : only the changed 16-row bands go over SPI (best case).
  span  : the driver merges damage into one rectangle from the first to the
          last changed row (fbtft deferred-io style).
  full  : any write re-sends the whole frame (old fbtft `fb_write` behaviour).
"""

from __future__ import annotations

import argparse
import cProfile
import io
import math
import os
import pstats
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

from jiri.ui import output, renderer  # noqa: E402
from jiri.ui.stage import Stage  # noqa: E402

W, H = 480, 320
SCREENS = ("face", "splash", "tasks", "weather", "water", "focus", "usage")
SPI_MHZ = (16, 24, 32)
BASE_NOW = datetime(2026, 11, 23, 21, 5)


# --- Fake data ----------------------------------------------------------------

def fake_snapshot(now: datetime, sim_t: float) -> SimpleNamespace:
    """A busy, realistic evening: late + soon tasks, rain coming, focus running."""
    remaining = max(0, 25 * 60 - 400 - int(sim_t))
    todo = lambda title, minutes: SimpleNamespace(  # noqa: E731
        title=title, due_at=(now + timedelta(minutes=minutes)).isoformat(timespec="minutes") if minutes is not None else None,
    )
    return SimpleNamespace(
        face_state="annoyed",
        face_reason="",
        headline="Ship invoice. It's been waiting since lunch.",
        subheadline="It's still there. I checked twice.",
        focus={"active": True, "status": "running", "remaining_text": f"{remaining // 60:02d}:{remaining % 60:02d}",
               "progress": 0.27 + sim_t / 1500, "title": "Write the quarterly report"},
        overdue_count=1,
        pending_count=4,
        pending_todos=[
            todo("Ship invoice to the client", -45),
            todo("Call the bank about the card", 15),
            todo("Book dentist appointment", 180),
            todo("Water the plants on the balcony", None),
        ],
        water={"goal_ml": 3000, "percent": 40, "progress_ml": 1200,
               "week": [{"label": d, "percent": p} for d, p in
                        (("Mo", 100), ("Tu", 80), ("We", 110), ("Th", 60), ("Fr", 95), ("Sa", 40), ("Su", 40))]},
        weather={"available": True, "temperature_c": 21.4, "condition": "Light rain", "rain_chance": 80,
                 "fetched_at": now.isoformat(timespec="seconds"), "location": "Springfield",
                 "feels_like_c": 23.0, "humidity": 78, "wind_kmh": 12,
                 "hourly_forecast": [{"time": f"{h}:00", "temperature_c": 21 - k * 0.6, "rain_chance": 40 + k * 8}
                                     for k, h in enumerate((22, 23, 0, 1, 2, 3))]},
        panel="todos",
    )


def fake_usage(now: datetime) -> tuple:
    ts = now.timestamp()
    return (
        SimpleNamespace(provider="claude", label="Opus 4.5", context_pct=18.0, five_hour_pct=9.0,
                        five_hour_resets_at=ts + 43 * 60, weekly_pct=4.0,
                        weekly_resets_at=ts + 2 * 86400 + 3 * 3600, updated_at=ts - 20),
        SimpleNamespace(provider="chatgpt", label="gpt-5-codex", context_pct=None, five_hour_pct=81.0,
                        five_hour_resets_at=ts + 95 * 60, weekly_pct=47.0,
                        weekly_resets_at=ts + 5 * 86400, updated_at=ts - 300),
    )


# --- Framebuffer sink -----------------------------------------------------------

class FbSink:
    """A real FramebufferOutput pointed at a temp file + fake sysfs (16 bpp)."""

    def __init__(self, root: str) -> None:
        sysfs = os.path.join(root, "sys", "fb1")
        os.makedirs(sysfs, exist_ok=True)
        for name, value in (("bits_per_pixel", "16"), ("stride", str(W * 2)), ("virtual_size", f"{W},{H}")):
            with open(os.path.join(sysfs, name), "w") as fh:
                fh.write(value)
        self.path = os.path.join(root, "fb1")
        with open(self.path, "wb") as fh:
            fh.write(bytes(W * H * 2))
        self.out = output.FramebufferOutput(pygame, (W, H), self.path, sysfs_root=os.path.join(root, "sys"))
        self.row_bytes = W * 2

    def present(self, canvas) -> tuple[float, int, int, int]:
        """Returns (present_ms, bands, span_bytes, full_bytes) for one frame."""
        before = list(self.out.previous)
        t0 = time.perf_counter()
        bands = self.out.present(canvas)
        ms = (time.perf_counter() - t0) * 1000
        after = self.out.previous
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b] if before else list(range(len(after)))
        if not changed:
            return ms, 0, 0, 0
        rows = lambda band: min(H, (band + 1) * output.BAND_ROWS) - band * output.BAND_ROWS  # noqa: E731
        span = sum(rows(b) for b in range(changed[0], changed[-1] + 1)) * self.row_bytes
        return ms, bands, span, W * H * 2

    def close(self) -> None:
        os.close(self.out.fd)


# --- Bench ---------------------------------------------------------------------

def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))]
    return {"mean": statistics.fmean(values), "p95": p95, "max": ordered[-1]}


def bench_screen(screen: str, fonts, seconds: float, fps: float, tmp: str) -> dict:
    stage = Stage(seed=7, boot=False, rotate=False, voice=None)
    canvas = pygame.Surface((W, H))
    sink = FbSink(os.path.join(tmp, screen))
    frames = max(1, int(round(seconds * fps)))
    render_ms, scene_ms, present_ms = [], [], []
    bands, span_bytes, full_bytes = [], [], []
    splash_cycle = ("tasks", "face")
    splash_i = 0
    snapshot = None
    usage = None
    try:
        for k in range(frames):
            sim_t = k / fps
            now = BASE_NOW + timedelta(seconds=sim_t)
            if snapshot is None or k % max(1, int(fps)) == 0:  # the app re-reads once a second
                snapshot, usage = fake_snapshot(now, sim_t), fake_usage(now)
            t0 = time.perf_counter()
            scene = renderer.build_scene(snapshot, now=now, usage=usage)
            t1 = time.perf_counter()
            if screen == "splash":
                if stage.splash_page is None:
                    stage.go(splash_cycle[splash_i % 2], sim_t)
                    splash_i += 1
            elif screen != "face":
                stage.page = screen
            stage.frame(pygame, canvas, fonts, scene, sim_t)
            t2 = time.perf_counter()
            ms, n, span, full = sink.present(canvas)
            scene_ms.append((t1 - t0) * 1000)
            render_ms.append((t2 - t1) * 1000)
            if k == 0:
                continue  # the first frame is always a full write; not steady state
            present_ms.append(ms)
            bands.append(n)
            span_bytes.append(span)
            full_bytes.append(full)
    finally:
        sink.close()
    band_bytes = [n * output.BAND_ROWS * W * 2 for n in bands]
    return {
        "screen": screen,
        "frames": frames,
        "render": _stats(render_ms),
        "scene": _stats(scene_ms),
        "present": _stats(present_ms),
        "bands_mean": statistics.fmean(bands) if bands else 0.0,
        "changed_frac": (sum(1 for n in bands if n) / len(bands)) if bands else 0.0,
        "bytes": {
            "bands": statistics.fmean(band_bytes) if band_bytes else 0.0,
            "span": statistics.fmean(span_bytes) if span_bytes else 0.0,
            "full": statistics.fmean(full_bytes) if full_bytes else 0.0,
        },
    }


def run_bench(seconds: float = 10.0, fps: float = 12.0, screens=SCREENS) -> list[dict]:
    pygame.display.init()
    pygame.font.init()
    fonts = renderer.load_fonts(pygame)
    with tempfile.TemporaryDirectory(prefix="jiri-bench-") as tmp:
        return [bench_screen(s, fonts, seconds, fps, tmp) for s in screens]


# --- Report --------------------------------------------------------------------

def spi_fps(bytes_per_frame: float, mhz: float, efficiency: float) -> float:
    """Frames/s the SPI bus could carry at this average payload per frame."""
    if bytes_per_frame <= 0:
        return float("inf")
    return mhz * 1e6 / 8 * efficiency / bytes_per_frame


def report(results: list[dict], fps: float, pi_factor: float, efficiency: float) -> str:
    out = io.StringIO()
    p = lambda *a: print(*a, file=out)  # noqa: E731
    p(f"Simulated {results[0]['frames'] / fps:.0f} s per screen at {fps:g} FPS, SDL dummy driver, 480x320.")
    p(f"Pi 3B estimate = desktop x {pi_factor:g} (flat CPU factor, not measured).")
    p("")
    p(f"{'screen':<8} {'render ms mean/p95/max':>24} {'scene ms':>9} {'fb ms':>7} "
      f"{'bands/f':>8} {'chg%':>5} {'Pi ms/f':>8}  Pi CPU fps cap (at p95)")
    for r in results:
        rd, sc, pr = r["render"], r["scene"], r["present"]
        pi_ms = (rd["mean"] + sc["mean"] + pr["mean"]) * pi_factor
        pi_p95 = (rd["p95"] + sc["p95"] + pr["p95"]) * pi_factor
        p(f"{r['screen']:<8} {rd['mean']:7.2f} /{rd['p95']:6.2f} /{rd['max']:6.2f}  {sc['mean']:8.2f} {pr['mean']:7.2f} "
          f"{r['bands_mean']:8.1f} {100 * r['changed_frac']:5.0f} {pi_ms:8.1f} {min(fps, 1000 / pi_ms):5.1f}"
          f" ({min(fps, 1000 / pi_p95):4.1f})")
    p("")
    p(f"SPI (RGB565, {100 * efficiency:.0f}% bus efficiency). Bytes/frame averaged over all frames incl. unchanged ones;")
    p(f"'fps' is what the bus could carry; 'load' is the bus share needed at {fps:g} FPS.")
    header = f"{'screen':<8} {'model':<6} {'KB/frame':>9} {'KB/s @fps':>10}"
    for mhz in SPI_MHZ:
        header += f" {f'{mhz}MHz fps/load':>17}"
    p(header)
    for r in results:
        for model in ("bands", "span", "full"):
            per = r["bytes"][model]
            line = f"{r['screen']:<8} {model:<6} {per / 1024:9.1f} {per * fps / 1024:10.0f}"
            for mhz in SPI_MHZ:
                cap = spi_fps(per, mhz, efficiency)
                load = per * fps / (mhz * 1e6 / 8 * efficiency)
                cap_s = "inf" if math.isinf(cap) else f"{cap:5.1f}"
                line += f" {cap_s:>8}/{100 * load:5.0f}%  "
            p(line)
    return out.getvalue()


def profile(seconds: float, fps: float, top: int) -> str:
    pygame.display.init()
    pygame.font.init()
    fonts = renderer.load_fonts(pygame)
    prof = cProfile.Profile()
    with tempfile.TemporaryDirectory(prefix="jiri-bench-") as tmp:
        prof.enable()
        for s in SCREENS:
            bench_screen(s, fonts, seconds, fps, tmp)
        prof.disable()
    buf = io.StringIO()
    stats = pstats.Stats(prof, stream=buf)
    stats.sort_stats("tottime").print_stats(top)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=10.0, help="simulated seconds per screen")
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--pi-factor", type=float, default=12.0, help="Pi 3B slowdown vs this machine")
    ap.add_argument("--spi-efficiency", type=float, default=0.8, help="usable share of the raw SPI clock")
    ap.add_argument("--profile", action="store_true", help="also print the cProfile top functions")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)
    results = run_bench(args.seconds, args.fps)
    print(report(results, args.fps, args.pi_factor, args.spi_efficiency))
    if args.profile:
        print(profile(args.seconds, args.fps, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
