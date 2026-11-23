"""Print raw XPT2046 touch samples and suggest a JIRI_TOUCH_CAL line.

    PYTHONPATH=src .venv/bin/python scripts/touch_calibrate.py [--seconds 20]
        [--device /dev/spidev0.1] [--hz 10] [--z-min 80]

Stop the UI first (`sudo systemctl stop jiri-ui`) so only one process talks
to the chip. While it runs, press and drag a stylus along all four edges of
the screen, into each corner. Every sample prints as `x y z1 z2`, with
`TOUCH` on the ones that count as pressed. At the end it prints the min/max
of the touched X/Y and a suggested `JIRI_TOUCH_CAL=xmin,xmax,ymin,ymax`.

The suggested range maps raw X to screen X and raw Y to screen Y. If taps
then land mirrored, swap that pair (xmin<->xmax or ymin<->ymax); if they move
on the wrong axis, add `,swap` and exchange the X and Y pairs. A calibration
string disables automatic rotation handling, so it is in final screen
orientation.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from jiri.ui.output import DEFAULT_Z_MIN, SPI_TOUCH_DEVICE, SpiTouch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default=SPI_TOUCH_DEVICE, help="spidev node (an spi: prefix is accepted)")
    ap.add_argument("--seconds", type=float, default=20.0, help="how long to sample (default 20)")
    ap.add_argument("--hz", type=float, default=10.0, help="samples per second (default 10)")
    ap.add_argument("--z-min", type=int, default=None, help=f"pressure threshold (default $JIRI_TOUCH_Z_MIN or {DEFAULT_Z_MIN})")
    args = ap.parse_args(argv)

    touch = SpiTouch(args.device, calibration="", z_min=args.z_min, start=False)
    print(f"device {touch.device}  z_min {touch.z_min}  {args.seconds:g}s @ {args.hz:g} Hz")
    print("press along every edge and into each corner...")
    xs, ys = [], []
    start = time.monotonic()
    step = 1.0 / args.hz
    try:
        while (elapsed := time.monotonic() - start) < args.seconds:
            try:
                x, y, z1, z2 = touch.raw_sample()
            except OSError as exc:
                print(f"cannot read {touch.device}: {exc}", file=sys.stderr)
                return 1
            pressed = touch.is_touched(x, y, z1, z2)
            if pressed:
                xs.append(x)
                ys.append(y)
            print(f"{elapsed:6.1f}s  x={x:4d} y={y:4d} z1={z1:4d} z2={z2:4d}{'  TOUCH' if pressed else ''}", flush=True)
            time.sleep(max(0.0, start + (int(elapsed / step) + 1) * step - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        touch.stop()

    if not xs:
        print("\nno touched samples: check wiring, or lower --z-min (watch z1 while pressing)")
        return 2
    print(f"\ntouched samples: {len(xs)}")
    print(f"X min {min(xs)}  max {max(xs)}")
    print(f"Y min {min(ys)}  max {max(ys)}")
    print(f"\nJIRI_TOUCH_CAL={min(xs)},{max(xs)},{min(ys)},{max(ys)}")
    print("(mirrored taps: swap that axis' pair; wrong axis: append ,swap and exchange the X/Y pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
